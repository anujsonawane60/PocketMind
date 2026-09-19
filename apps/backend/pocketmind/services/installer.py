"""The installation job.

Everything the user agreed to happens here, in one background thread, with a
checkpoint written after every step. If the drive is unplugged, the network
drops, or the application is closed mid-download, resuming picks up at the
first step that did not finish rather than starting again (PRD section 54).
"""

from __future__ import annotations

import json
import shutil
import threading
from datetime import UTC, datetime
from pathlib import Path

from pocketmind import config
from pocketmind.logs import get_logger
from pocketmind.providers.base import RuntimeError_
from pocketmind.providers.llamacpp import LlamaCppProvider
from pocketmind.schemas import (
    Drive,
    HardwareProfile,
    InstallRequest,
    InstallStatus,
    InstallStep,
    JobState,
    Settings,
    StepStatus,
)
from pocketmind.services import catalog, downloads, portable_python
from pocketmind.services.data import PocketDatabase
from pocketmind.services.vault import Vault, VaultExists

log = get_logger("installer")

#: (key, title, relative weight). Weights are rough wall-clock shares so the
#: progress bar does not sit at 90% for the whole model download.
_STEPS: tuple[tuple[str, str, float], ...] = (
    ("layout", "Preparing the drive", 1.0),
    ("app", "Copying PocketMind onto the drive", 2.0),
    ("python", "Bundling a portable Python", 8.0),
    ("runtime", "Installing the AI engine", 8.0),
    ("model", "Downloading your AI model", 60.0),
    ("database", "Creating your local database", 2.0),
    ("vault", "Creating your encrypted vault", 2.0),
    ("config", "Saving your settings", 1.0),
    ("launcher", "Creating the drive launcher", 1.0),
    ("verify", "Testing your assistant", 14.0),
)


class InstallCancelled(RuntimeError):
    pass


class InstallJob:
    """One installation, driven from a worker thread and polled by the UI."""

    def __init__(self, request: InstallRequest, drive: Drive, hardware: HardwareProfile) -> None:
        self.request = request
        self.drive = drive
        self.hardware = hardware
        self.paths = config.InstallPaths.for_mount(drive.mount_point)

        self._lock = threading.RLock()
        self._cancel = threading.Event()
        self._thread: threading.Thread | None = None
        self._steps = {key: InstallStep(key=key, title=title) for key, title, _ in _STEPS}
        self._weights = {key: weight for key, _, weight in _STEPS}
        self._state = JobState.IDLE
        self._message = ""
        self._error: str | None = None
        self._hint: str | None = None
        self._current: str | None = None
        self._started: datetime | None = None
        self._finished: datetime | None = None
        self._backend = "cpu"
        self._bundled_python = False

        if not request.bundle_portable_python:
            self._steps["python"].status = StepStatus.SKIPPED
            self._steps["python"].detail = "Not requested — the drive will use Python on the host computer."

    # -- public surface ----------------------------------------------------

    def start(self) -> None:
        with self._lock:
            if self._state == JobState.RUNNING:
                return
            self._state = JobState.RUNNING
            self._error = None
            self._hint = None
            self._cancel.clear()
            self._started = datetime.now(UTC)
            self._finished = None
        self._thread = threading.Thread(target=self._run, name="pocketmind-install", daemon=True)
        self._thread.start()

    def cancel(self) -> None:
        self._cancel.set()

    def status(self) -> InstallStatus:
        with self._lock:
            done = sum(
                self._weights[key] * (1.0 if step.status in (StepStatus.COMPLETED, StepStatus.SKIPPED) else step.progress)
                for key, step in self._steps.items()
            )
            total = sum(self._weights.values())
            resumable = self._state in (JobState.FAILED, JobState.CANCELLED)
            return InstallStatus(
                state=self._state,
                steps=[step.model_copy(deep=True) for step in self._steps.values()],
                current_step=self._current,
                overall_progress=round(min(done / total, 1.0), 4),
                message=self._message,
                error=self._error,
                recovery_hint=self._hint,
                install_path=str(self.paths.root) if self._state == JobState.COMPLETED else None,
                launcher_path=str(self.paths.launcher) if self._state == JobState.COMPLETED else None,
                can_resume=resumable,
                started_at=self._started,
                finished_at=self._finished,
            )

    # -- step plumbing -----------------------------------------------------

    def _checkpoint(self) -> None:
        """Persist which steps are done so a later run can skip them."""
        try:
            self.paths.config.mkdir(parents=True, exist_ok=True)
            payload = {
                "app_version": config.APP_VERSION,
                "model_id": self.request.model_id,
                "updated_at": datetime.now(UTC).isoformat(timespec="seconds"),
                "completed": [
                    key for key, step in self._steps.items()
                    if step.status in (StepStatus.COMPLETED, StepStatus.SKIPPED)
                ],
            }
            temporary = self.paths.install_state_file.with_suffix(".tmp")
            temporary.write_text(json.dumps(payload, indent=2), encoding="utf-8")
            temporary.replace(self.paths.install_state_file)
        except OSError as exc:
            log.warning("Could not write the installation checkpoint: %s", exc.__class__.__name__)

    def _load_checkpoint(self) -> set[str]:
        try:
            payload = json.loads(self.paths.install_state_file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return set()
        if payload.get("model_id") != self.request.model_id:
            return set()
        return set(payload.get("completed", []))

    def _begin(self, key: str, detail: str = "") -> None:
        with self._lock:
            step = self._steps[key]
            step.status = StepStatus.RUNNING
            step.detail = detail
            step.progress = 0.0
            self._current = step.title
            self._message = step.title

    def _finish(self, key: str, detail: str = "") -> None:
        with self._lock:
            step = self._steps[key]
            step.status = StepStatus.COMPLETED
            step.progress = 1.0
            if detail:
                step.detail = detail
        self._checkpoint()

    def _skip(self, key: str, detail: str) -> None:
        with self._lock:
            step = self._steps[key]
            step.status = StepStatus.SKIPPED
            step.progress = 1.0
            step.detail = detail
        self._checkpoint()

    def _progress(self, key: str):
        def report(title: str, fraction: float, detail: str) -> None:
            with self._lock:
                step = self._steps[key]
                step.progress = max(0.0, min(fraction, 1.0))
                step.detail = detail
                self._message = title
                self._current = title
        return report

    def _guard(self) -> None:
        if self._cancel.is_set():
            raise InstallCancelled("Installation cancelled.")

    # -- the actual work ---------------------------------------------------

    def _run(self) -> None:
        completed = self._load_checkpoint()
        for key in completed:
            if key in self._steps and self._steps[key].status == StepStatus.PENDING:
                self._steps[key].status = StepStatus.COMPLETED
                self._steps[key].progress = 1.0
                self._steps[key].detail = "Already done — resumed."

        try:
            self._step_layout()
            self._step_app()
            self._step_python()
            self._step_runtime()
            self._step_model()
            self._step_database()
            self._step_vault()
            self._step_config()
            self._step_launcher()
            self._step_verify()
        except InstallCancelled:
            with self._lock:
                self._state = JobState.CANCELLED
                self._message = "Installation stopped. Your progress is saved."
                self._hint = "Choose Resume to continue from where it stopped."
                if self._current:
                    for step in self._steps.values():
                        if step.status == StepStatus.RUNNING:
                            step.status = StepStatus.PENDING
                self._finished = datetime.now(UTC)
            return
        except Exception as exc:
            hint = getattr(exc, "hint", "") or "Choose Resume to try again from this step."
            log.exception("Installation failed at %s", self._current)
            with self._lock:
                for step in self._steps.values():
                    if step.status == StepStatus.RUNNING:
                        step.status = StepStatus.FAILED
                        step.detail = str(exc)
                self._state = JobState.FAILED
                self._error = str(exc)
                self._hint = hint
                self._message = "Installation could not finish."
                self._finished = datetime.now(UTC)
            return

        with self._lock:
            self._state = JobState.COMPLETED
            self._message = "PocketMind is ready."
            self._current = None
            self._finished = datetime.now(UTC)

    def _done(self, key: str) -> bool:
        return self._steps[key].status in (StepStatus.COMPLETED, StepStatus.SKIPPED)

    def _step_layout(self) -> None:
        self._guard()
        if self._done("layout"):
            return
        self._begin("layout", f"Creating the PocketMind folder on {self.drive.id}")
        self.paths.create_folders()
        self._finish("layout", f"{self.paths.root} is ready")

    def _step_app(self) -> None:
        self._guard()
        # Deliberately not skipped on resume. The copy is small, and a drive
        # carrying an older build than the one that just ran would be a
        # confusing thing to leave behind.
        self._begin("app", "Copying the application so the drive can run on its own")
        version, copied = copy_application(self.paths)
        self._finish(
            "app",
            f"PocketMind {version} copied to the drive" if copied
            else f"Already running PocketMind {version} from this drive",
        )

    def _step_python(self) -> None:
        self._guard()
        if self._done("python"):
            self._bundled_python = portable_python.python_executable(self.paths) is not None
            return
        self._begin("python", "This lets the drive run on computers without Python")
        try:
            portable_python.install(self.paths, on_progress=self._progress("python"), cancel=self._cancel)
            self._bundled_python = True
            self._finish("python", "The drive can now run on its own")
        except downloads.DownloadCancelled as exc:
            raise InstallCancelled(str(exc)) from exc
        except portable_python.PortablePythonError as exc:
            # Not fatal: the launcher will use the host's Python instead.
            log.warning("Portable Python bundling failed: %s", exc)
            self._bundled_python = False
            self._skip("python", f"{exc} PocketMind will use Python installed on the computer instead.")

    def _step_runtime(self) -> None:
        self._guard()
        if self._done("runtime"):
            return
        self._begin("runtime", "Downloading the engine that runs your model")
        provider = LlamaCppProvider(self.paths, self.hardware)
        try:
            self._backend = provider.install_runtime(
                self.hardware, on_progress=self._progress("runtime"), cancel=self._cancel
            )
        except downloads.DownloadCancelled as exc:
            raise InstallCancelled(str(exc)) from exc

        # Prove the engine runs here before spending gigabytes on a model. On a
        # computer that refuses to load it, the user has already chosen to
        # prepare the drive for use somewhere else.
        if not self.hardware.app_control_blocks_engine:
            provider.verify_engine()
        self._finish("runtime", f"{self._backend.upper()} engine installed")

    def _step_model(self) -> None:
        self._guard()
        if self._done("model"):
            return
        entry = catalog.get_entry(self.request.model_id)
        name = entry.name if entry else self.request.model_id
        self._begin("model", f"Downloading {name}. You can leave this running.")
        provider = LlamaCppProvider(self.paths, self.hardware)
        try:
            model = provider.install_model(
                self.request.model_id, on_progress=self._progress("model"), cancel=self._cancel
            )
        except downloads.DownloadCancelled as exc:
            raise InstallCancelled(str(exc)) from exc
        self._finish("model", f"{model.name} installed and verified")

    def _step_database(self) -> None:
        self._guard()
        if self._done("database"):
            return
        self._begin("database", "Creating the local database on the drive")
        database = PocketDatabase(self.paths.database)
        try:
            settings = Settings(
                network_allowed=self.request.profile.network_allowed,
                system_prompt=_system_prompt(self.request),
            )
            database.save_settings(settings)
            for content, category, importance in _seed_memories(self.request):
                database.add_memory(content, category, importance)
        finally:
            database.close()
        self._finish("database", "Database created")

    def _step_vault(self) -> None:
        self._guard()
        if self._done("vault"):
            return
        self._begin("vault", "Encrypting your private vault with your master password")
        vault = Vault(self.paths.vault_file)
        try:
            vault.create(self.request.vault_password)
        except VaultExists:
            log.info("Vault already exists on this drive; keeping it")
        finally:
            vault.lock()
        self._finish("vault", "Vault created and locked")

    def _step_config(self) -> None:
        self._guard()
        if self._done("config"):
            return
        self._begin("config", "Saving your choices to the drive")
        profile = self.request.profile
        _write_json(
            self.paths.profile_file,
            {
                "schema_version": config.CONFIG_SCHEMA_VERSION,
                "display_name": profile.display_name,
                "use_cases": [case.value for case in profile.use_cases],
                "experience": profile.experience,
                "tone": profile.tone,
                "network_allowed": profile.network_allowed,
                "created_at": datetime.now(UTC).isoformat(timespec="seconds"),
            },
        )
        _write_json(
            self.paths.config_file,
            {
                "schema_version": config.CONFIG_SCHEMA_VERSION,
                "app_version": config.APP_VERSION,
                "created_at": datetime.now(UTC).isoformat(timespec="seconds"),
                "drive_id": self.drive.id,
                "volume_serial": self.drive.volume_serial,
                "default_model_id": self.request.model_id,
                "backend": self._backend,
                "portable_python": self._bundled_python,
            },
        )
        self._finish("config", "Settings saved")

    def _step_launcher(self) -> None:
        self._guard()
        if self._done("launcher"):
            return
        self._begin("launcher", "Creating START_POCKETMIND on the drive")
        self.paths.launcher.write_text(_LAUNCHER_CMD, encoding="utf-8", newline="\r\n")
        self.paths.start_here.write_text(
            _START_HERE_HTML.format(name=self.request.profile.display_name), encoding="utf-8"
        )
        self._finish("launcher", f"{self.paths.launcher.name} created at the drive root")

    def _step_verify(self) -> None:
        self._guard()
        if self._done("verify"):
            return
        if self.hardware.app_control_blocks_engine:
            self._skip(
                "verify",
                "Skipped: this computer will not run the AI engine, so the model cannot be tested here. "
                "The drive is complete and will work on a computer without Smart App Control.",
            )
            return
        self._begin("verify", "Loading the model and asking it one question")
        provider = LlamaCppProvider(self.paths, self.hardware)
        try:
            provider.start_runtime(self.request.model_id)
            self._progress("verify")("Testing your assistant", 0.6, "Model loaded, sending a test question")
            answer = provider.chat(
                [{"role": "user", "content": "Reply with the single word: ready"}], max_tokens=16, temperature=0.0
            )
        except RuntimeError_ as exc:
            raise RuntimeError_(
                f"The model was installed but did not answer a test question. {exc}",
                hint=getattr(exc, "hint", "") or "Try a smaller model, or resume to test again.",
            ) from exc
        finally:
            provider.stop_runtime()
        self._finish("verify", f"The model answered: {answer.strip()[:60] or '(empty)'}")


# --------------------------------------------------------------------------
# Content written to the drive
# --------------------------------------------------------------------------


#: The onboarding checkboxes become sentences, so they have to read like sentences.
_USE_CASE_PHRASES = {
    "assistant": "personal organisation and planning",
    "learning": "learning and studying",
    "coding": "programming",
    "documents": "searching my private documents",
    "journaling": "journaling",
    "finance": "finances and records",
}


def _phrase(case) -> str:
    return _USE_CASE_PHRASES.get(case.value, case.value.replace("_", " "))


def running_from(paths: config.InstallPaths) -> bool:
    """Is the code executing right now the copy that lives on this drive?"""
    try:
        source = config.PACKAGE_DIR.resolve()
        app = paths.app.resolve()
    except OSError:
        return False
    return source == app or source.is_relative_to(app)


def copy_application(paths: config.InstallPaths) -> tuple[str, bool]:
    """Put the running build of PocketMind onto the drive.

    Returns ``(version, copied)``. Used by installation and by the Settings
    action that refreshes a drive after the repository has been updated, so a
    drive never keeps running an older build than the one just installed.
    """
    destination = paths.app / "pocketmind"

    # Refusing this is not a nicety. The source and the destination would be
    # the same folder, so clearing the destination first deletes the very code
    # being copied and leaves the drive unbootable.
    if running_from(paths):
        log.info("PocketMind is running from this drive; its copy is already current")
        return config.APP_VERSION, False

    if destination.exists():
        shutil.rmtree(destination, ignore_errors=True)
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(
        config.PACKAGE_DIR,
        destination,
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo"),
    )

    # Found at the repo root normally, or beside the package when PocketMind is
    # itself running from a drive it prepared earlier.
    requirements = next(
        (
            candidate / "requirements.txt"
            for candidate in config.PACKAGE_DIR.parents[:3]
            if (candidate / "requirements.txt").exists()
        ),
        None,
    )
    if requirements is not None:
        shutil.copy2(requirements, paths.app / "requirements.txt")

    # The launcher is regenerated too, in case its contents changed.
    paths.launcher.write_text(_LAUNCHER_CMD, encoding="utf-8", newline="\r\n")
    log.info("Copied PocketMind %s to %s", config.APP_VERSION, paths.app)
    return config.APP_VERSION, True


def _system_prompt(request: InstallRequest) -> str:
    profile = request.profile
    interests = ", ".join(_phrase(case) for case in profile.use_cases)
    return (
        f"You are PocketMind, {profile.display_name}'s private assistant. You run entirely on their computer "
        f"from their own USB drive, and nothing they tell you leaves it.\n"
        f"They mainly want help with: {interests}.\n"
        "Use the memories and document passages you are given when they are relevant, and say so when they are "
        "not enough to answer. Never invent details about their life. You have no access to their secret vault, "
        "so if they ask for a stored password or key, tell them to open the Vault section themselves."
    )


def _seed_memories(request: InstallRequest) -> list[tuple[str, str, int]]:
    profile = request.profile
    seeds = [(f"My name is {profile.display_name}.", "personal", 5)]
    for case in profile.use_cases:
        seeds.append((f"I want PocketMind to help me with {_phrase(case)}.", "goals", 4))
    if profile.experience:
        seeds.append((f"I am {profile.experience} with local AI models.", "personal", 2))
    return seeds


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    temporary.replace(path)


_LAUNCHER_CMD = r"""@echo off
title PocketMind
setlocal

set "HERE=%~dp0"
set "APPDIR=%HERE%PocketMind\app"
set "EMBEDDED=%HERE%PocketMind\runtime\python\python.exe"

if exist "%EMBEDDED%" (
    set "RUNNER=%EMBEDDED%"
    goto :launch
)

where python >nul 2>nul
if not errorlevel 1 (
    set "RUNNER=python"
    goto :launch
)

echo.
echo  PocketMind could not start.
echo.
echo  This drive was prepared without a bundled Python, and no Python was
echo  found on this computer. Install Python 3.12 or newer from python.org,
echo  then run this file again.
echo.
pause
exit /b 1

:launch
echo.
echo   PocketMind is starting. Your browser will open in a few seconds.
echo   Keep this window open while you use PocketMind.
echo.
start "" cmd /c "timeout /t 6 >nul & start "" http://127.0.0.1:8000"
"%RUNNER%" -m uvicorn pocketmind.main:app --app-dir "%APPDIR%" --host 127.0.0.1 --port 8000
echo.
echo   PocketMind has stopped. You can close this window and eject the drive.
pause
"""


_START_HERE_HTML = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>PocketMind — start here</title>
<style>
  body {{ font-family: "Segoe UI", system-ui, sans-serif; background: #0c121b; color: #edf4f1;
         margin: 0; display: grid; place-items: center; min-height: 100vh; }}
  main {{ max-width: 620px; padding: 40px 28px; }}
  h1 {{ font-size: 28px; margin: 0 0 6px; }}
  p.sub {{ color: #9fb4ad; margin: 0 0 28px; }}
  ol {{ line-height: 1.9; padding-left: 20px; }}
  code {{ background: #16202c; padding: 2px 7px; border-radius: 6px; }}
  .note {{ margin-top: 28px; padding: 16px 18px; border-radius: 12px; background: #16202c;
           border: 1px solid #22303f; color: #b9cac3; font-size: 14px; }}
</style>
</head>
<body>
<main>
  <h1>PocketMind</h1>
  <p class="sub">Your AI. Your memories. Your drive. Prepared for {name}.</p>
  <ol>
    <li>Plug this drive into any Windows computer.</li>
    <li>Open the drive and double-click <code>START_POCKETMIND.cmd</code>.</li>
    <li>Your browser opens PocketMind. Unlock your vault when you need your secrets.</li>
    <li>Chat, search your documents, and manage your memories — all offline.</li>
  </ol>
  <div class="note">
    Everything personal lives in the <code>PocketMind</code> folder on this drive. Your vault is encrypted
    with your master password, which is not stored anywhere. If you lose that password, the vault cannot
    be recovered. PocketMind cannot protect your data on a computer that is already compromised.
  </div>
</main>
</body>
</html>
"""
