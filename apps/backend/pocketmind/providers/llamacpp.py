"""llama.cpp provider: a self-contained inference engine that lives on the drive.

Nothing is installed on the host computer. The engine binaries, the model
weights, and the server process all come from ``<drive>/PocketMind/runtime``
and ``<drive>/PocketMind/models``, which is what makes the drive portable.
"""

from __future__ import annotations

import atexit
import contextlib
import ctypes
import json
import os
import socket
import subprocess
import threading
import time
import zipfile
from collections.abc import Callable, Iterator, Sequence
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from pocketmind import config
from pocketmind.logs import get_logger
from pocketmind.providers.base import InstalledModel, RuntimeError_
from pocketmind.schemas import HardwareProfile, ModelInfo, RuntimeStatus
from pocketmind.services import catalog, downloads

log = get_logger("llamacpp")

# Not /releases/latest: llama.cpp marks a nightly pointer tag as "latest", and
# that release carries no binaries. The build tags (b#####) are what ship the
# Windows packages, so the list is scanned for the newest usable one.
_RELEASE_API = "https://api.github.com/repos/ggml-org/llama.cpp/releases?per_page=20"
_USER_AGENT = f"PocketMind/{config.APP_VERSION}"
_SERVER_NAME = "llama-server.exe" if os.name == "nt" else "llama-server"
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

#: The CPU package carries the shared libraries every other backend needs, so
#: it is always installed. A GPU package is layered on top when one applies.
#: Windows returns this when a code-integrity policy refuses to load a binary.
#: Smart App Control ships enabled on many new machines and blocks the engine,
#: which is published unsigned.
_APP_CONTROL_EXIT_CODE = 0xC0E90002

# SetErrorMode flags. Without these the loader shows a modal "Bad Image" dialog
# that sits on top of the user's browser and waits for a click, which is a
# terrible way to learn that a background process failed to start.
_SEM_FAILCRITICALERRORS = 0x0001
_SEM_NOGPFAULTERRORBOX = 0x0002
_SEM_NOOPENFILEERRORBOX = 0x8000


@contextlib.contextmanager
def _no_error_dialogs():
    """Stop Windows popping a modal error box when a child fails to load.

    A child process inherits the parent's error mode at creation time, so the
    mode is set around the spawn and restored immediately afterwards.
    """
    if os.name != "nt":
        yield
        return
    kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
    previous = kernel32.SetErrorMode(
        _SEM_FAILCRITICALERRORS | _SEM_NOGPFAULTERRORBOX | _SEM_NOOPENFILEERRORBOX
    )
    try:
        yield
    finally:
        kernel32.SetErrorMode(previous)

_CPU_ASSET = "bin-win-cpu-x64"
_GPU_ASSETS = {
    "nvidia": "bin-win-vulkan-x64",
    "amd": "bin-win-vulkan-x64",
    "intel": "bin-win-vulkan-x64",
}

ProgressCallback = Callable[[str, float, str], None]


class LlamaCppProvider:
    name = "llama.cpp"

    def __init__(self, paths: config.InstallPaths, hardware: HardwareProfile | None = None) -> None:
        self.paths = paths
        self.hardware = hardware
        self._process: subprocess.Popen[bytes] | None = None
        self._engine_log: object | None = None
        self._lock = threading.RLock()
        # Restored from the drive: without this a provider created after setup
        # would default to the CPU backend and never offload to the GPU again.
        self._backend = self._stored_backend()
        self._active: InstalledModel | None = None
        self._gpu_layers = 0
        self._context_length = 4096
        atexit.register(self.stop_runtime)

    # -- discovery ---------------------------------------------------------

    def discover_models(self, *, online: bool) -> Sequence[ModelInfo]:
        models, _, _ = catalog.resolve_catalog(online=online)
        installed = {model.id for model in self.installed_models()}
        for model in models:
            model.installed = model.id in installed
        return models

    def installed_models(self) -> list[InstalledModel]:
        if not self.paths.models.exists():
            return []
        default = self._default_model_id()
        found: list[InstalledModel] = []
        for entry in catalog.CATALOG:
            path = self.paths.models / entry.filename
            if path.exists() and path.stat().st_size > 1024**2:
                found.append(
                    InstalledModel(
                        id=entry.id,
                        name=entry.name,
                        path=path,
                        byte_size=path.stat().st_size,
                        is_default=entry.id == default,
                    )
                )
        return found

    def _stored_backend(self) -> str:
        """Which engine package was installed on this drive."""
        try:
            data = json.loads(self.paths.config_file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return "cpu"
        backend = str(data.get("backend") or "cpu")
        # Only trust it if the matching package is actually present.
        if backend != "cpu" and not (self.paths.runtime / f".{backend}-installed").exists():
            return "cpu"
        return backend

    def _default_model_id(self) -> str | None:
        try:
            data = json.loads(self.paths.config_file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        value = data.get("default_model_id")
        return str(value) if value else None

    def set_default_model(self, model_id: str) -> None:
        if not any(model.id == model_id for model in self.installed_models()):
            raise RuntimeError_("That model is not installed on this drive.")
        try:
            data = json.loads(self.paths.config_file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data = {}
        data["default_model_id"] = model_id
        _atomic_write_json(self.paths.config_file, data)

    # -- installation ------------------------------------------------------

    def install_runtime(
        self,
        hardware: HardwareProfile,
        *,
        on_progress: ProgressCallback | None = None,
        cancel: threading.Event | None = None,
    ) -> str:
        """Download the engine onto the drive. Returns the active backend name."""
        self.hardware = hardware
        self.paths.runtime.mkdir(parents=True, exist_ok=True)

        wanted = [(_CPU_ASSET, "cpu")]
        gpu_asset = _GPU_ASSETS.get(hardware.gpu_vendor or "")
        if gpu_asset and (hardware.gpu_vram_bytes or 0) >= 2 * 1024**3:
            wanted.append((gpu_asset, "vulkan"))

        assets = self._release_assets()
        backend = "cpu"
        for index, (needle, label) in enumerate(wanted):
            asset = next((item for item in assets if needle in item["name"]), None)
            if asset is None:
                if label == "cpu":
                    raise RuntimeError_(
                        "No compatible Windows engine was found in the latest llama.cpp release.",
                        hint="Check your internet connection and try again; the release may be mid-publish.",
                    )
                log.info("No %s package in this release; continuing on the CPU engine", label)
                continue
            self._fetch_asset(asset, label, on_progress, cancel, index, len(wanted))
            if label != "cpu":
                backend = label

        if self._server_binary() is None:
            raise RuntimeError_(
                "The engine was downloaded but no server program was found inside it.",
                hint="Delete the PocketMind/runtime folder on the drive and run setup again.",
            )
        self._backend = backend
        return backend

    def _release_assets(self) -> list[dict]:
        """Assets from the newest release that actually ships a Windows engine."""
        request = Request(_RELEASE_API, headers={"User-Agent": _USER_AGENT, "Accept": "application/vnd.github+json"})
        try:
            with urlopen(request, timeout=30) as response:
                releases = json.loads(response.read())
        except (HTTPError, URLError, OSError, ValueError) as exc:
            raise RuntimeError_(
                "Could not reach the engine download service.",
                hint="Check your internet connection, then choose Resume.",
            ) from exc

        if isinstance(releases, dict):  # a single release, if the API shape changes
            releases = [releases]
        for release in releases:
            assets = [
                asset for asset in release.get("assets", []) if str(asset.get("name", "")).endswith(".zip")
            ]
            if any(_CPU_ASSET in str(asset["name"]) for asset in assets):
                log.info("Using llama.cpp release %s", release.get("tag_name"))
                return assets

        raise RuntimeError_(
            "No recent llama.cpp release contains a Windows engine package.",
            hint="This is usually temporary. Try again in a few minutes.",
        )

    def _fetch_asset(
        self,
        asset: dict,
        label: str,
        on_progress: ProgressCallback | None,
        cancel: threading.Event | None,
        index: int,
        total: int,
    ) -> None:
        archive = self.paths.runtime / str(asset["name"])
        marker = self.paths.runtime / f".{label}-installed"
        if marker.exists() and self._server_binary() is not None:
            log.info("%s engine already present", label)
            return

        def report(done: int, size: int | None, speed: float) -> None:
            if on_progress is None:
                return
            fraction = (done / size) if size else 0.0
            overall = (index + fraction) / total
            on_progress(
                f"Installing the {label.upper()} engine",
                overall,
                f"{_mb(done)} of {_mb(size) if size else '?'} at {_mb(int(speed))}/s",
            )

        downloads.download([str(asset["browser_download_url"])], archive, on_progress=report, cancel=cancel)
        try:
            with zipfile.ZipFile(archive) as package:
                package.extractall(self.paths.runtime)
        except (zipfile.BadZipFile, OSError) as exc:
            archive.unlink(missing_ok=True)
            raise RuntimeError_(
                "The engine download was damaged and has been removed.",
                hint="Choose Resume to download it again.",
            ) from exc
        finally:
            archive.unlink(missing_ok=True)
        marker.write_text(str(asset["name"]), encoding="utf-8")

    def install_model(
        self,
        model_id: str,
        *,
        on_progress: ProgressCallback | None = None,
        cancel: threading.Event | None = None,
    ) -> InstalledModel:
        entry = catalog.get_entry(model_id)
        if entry is None:
            raise RuntimeError_(f"Unknown model: {model_id}")
        target = self.paths.models / entry.filename
        target.parent.mkdir(parents=True, exist_ok=True)

        if target.exists() and target.stat().st_size > 1024**2:
            log.info("Model %s already present", model_id)
            return InstalledModel(id=entry.id, name=entry.name, path=target, byte_size=target.stat().st_size)

        def report(done: int, size: int | None, speed: float) -> None:
            if on_progress is None:
                return
            fraction = (done / size) if size else 0.0
            eta = f", about {_duration((size - done) / speed)} left" if size and speed > 0 else ""
            on_progress(
                f"Downloading {entry.name}",
                fraction,
                f"{_mb(done)} of {_mb(size) if size else '?'} at {_mb(int(speed))}/s{eta}",
            )

        result = downloads.download(
            list(entry.urls), target, on_progress=report, cancel=cancel, verify_gguf=True
        )
        return InstalledModel(id=entry.id, name=entry.name, path=result.path, byte_size=result.byte_size)

    def remove_model(self, model_id: str) -> None:
        entry = catalog.get_entry(model_id)
        if entry is None:
            raise RuntimeError_(f"Unknown model: {model_id}")
        if self._active and self._active.id == model_id:
            self.stop_runtime()
        (self.paths.models / entry.filename).unlink(missing_ok=True)

    # -- lifecycle ---------------------------------------------------------

    def _server_binary(self) -> Path | None:
        if not self.paths.runtime.exists():
            return None
        return next(self.paths.runtime.rglob(_SERVER_NAME), None)

    def verify_engine(self) -> None:
        """Prove the engine can actually run on this computer.

        Called right after installing it, so a machine that will refuse to load
        it is discovered before several gigabytes of model are downloaded.
        """
        server = self._server_binary()
        if server is None:
            raise RuntimeError_(
                "The inference engine is not installed on this drive.",
                hint="Run setup again to reinstall it.",
            )
        try:
            with _no_error_dialogs():
                result = subprocess.run(
                    [str(server), "--version"],
                    capture_output=True,
                    timeout=60,
                    cwd=str(server.parent),
                    creationflags=_NO_WINDOW,
                )
        except (OSError, subprocess.SubprocessError) as exc:
            raise RuntimeError_(
                "The inference engine could not be started on this computer.",
                hint="The drive may have been disconnected. Reconnect it and choose Resume.",
            ) from exc

        if _is_app_control_block(result.returncode):
            raise RuntimeError_(_app_control_message(), hint="")
        if result.returncode not in (0, 1):
            detail = (result.stderr or result.stdout or b"").decode("utf-8", errors="replace").strip()
            raise RuntimeError_(
                f"The inference engine exited immediately (code {result.returncode}).",
                hint=detail[:300] or "Your antivirus or security software may be blocking it.",
            )
        log.info("Engine verified on this computer")

    def _choose_model(self, model_id: str | None) -> InstalledModel:
        installed = self.installed_models()
        if not installed:
            raise RuntimeError_(
                "No model is installed on this drive yet.",
                hint="Open Models in Settings and install one.",
            )
        if model_id:
            match = next((model for model in installed if model.id == model_id), None)
            if match is None:
                raise RuntimeError_(f"Model {model_id} is not installed on this drive.")
            return match
        return next((model for model in installed if model.is_default), installed[0])

    def _gpu_layer_count(self, model: InstalledModel) -> int:
        """How many transformer layers to push onto the GPU.

        llama.cpp clamps a too-large value to the model's real layer count, so
        999 is the idiomatic way to say "all of them".
        """
        if self._backend == "cpu" or not self.hardware:
            return 0
        vram = self.hardware.gpu_vram_bytes or 0
        if vram <= 0:
            return 0
        # Leave ~1 GB of VRAM for context and the desktop compositor.
        usable = max(vram - 1024**3, 0)
        if usable >= model.byte_size * 1.15:
            return 999
        if usable <= 0:
            return 0
        # Partial offload: assume ~40 layers and offload proportionally, minus a
        # safety margin so a mis-estimated VRAM figure does not crash the engine.
        return max(0, int((usable / model.byte_size) * 40 * 0.85))

    def _context_for(self, requested: int | None) -> int:
        ram_gb = ((self.hardware.ram_bytes if self.hardware else 0) or 0) / 1024**3
        ceiling = 8192 if ram_gb >= 16 else 4096 if ram_gb >= 8 else 2048
        return max(1024, min(requested or 4096, ceiling))

    def _host_blocks_engine(self) -> bool:
        """Will this computer refuse to load the engine at all?

        Read live rather than from the cached hardware profile: the user can
        switch Smart App Control off while PocketMind is running, and should
        not have to restart it to be believed.
        """
        from pocketmind.services.hardware import app_control_state

        return app_control_state() == "enforcing"

    def start_runtime(self, model_id: str | None = None, *, context_length: int | None = None) -> RuntimeStatus:
        # Checked before anything is spawned. Launching a process that the
        # loader will reject wastes time and used to raise a modal dialog over
        # the user's browser.
        if self._host_blocks_engine():
            raise RuntimeError_(_app_control_message(), hint="")

        with self._lock:
            if self._process and self._process.poll() is None:
                if model_id is None or (self._active and self._active.id == model_id):
                    return self.status()
                self._stop_locked()

            server = self._server_binary()
            if server is None:
                raise RuntimeError_(
                    "The inference engine is not installed on this drive.",
                    hint="Run setup again, or reinstall the runtime from Settings.",
                )
            model = self._choose_model(model_id)
            layers = self._gpu_layer_count(model)
            threads = max(1, min((self.hardware.physical_cores if self.hardware else 4) or 4, 16))
            context = self._context_for(context_length)

            if _port_in_use(config.RUNTIME_HOST, config.RUNTIME_PORT):
                # Almost always an engine left behind when PocketMind was closed
                # ungracefully. If it answers a health check it is usable, so
                # adopt it rather than refusing to start for ever.
                if self.health_check():
                    log.info("Reusing an engine already listening on port %d", config.RUNTIME_PORT)
                    self._active = model
                    self._gpu_layers = layers
                    self._context_length = context
                    return self.status()
                raise RuntimeError_(
                    f"Port {config.RUNTIME_PORT} is already in use by another program.",
                    hint="Close whatever is using it, or restart the computer, then try again.",
                )

            command = [
                str(server),
                "-m", str(model.path),
                "--host", config.RUNTIME_HOST,
                "--port", str(config.RUNTIME_PORT),
                "-c", str(context),
                "-t", str(threads),
                "-ngl", str(layers),
                "--no-warmup",
            ]
            log.info(
                "Starting engine: backend=%s layers=%s threads=%s context=%s", self._backend, layers, threads, context
            )
            # The engine's own output is the only diagnosis available when it
            # refuses to start, so it goes to a log on the drive rather than
            # being discarded.
            engine_log = self.paths.logs / "engine.log"
            try:
                engine_log.parent.mkdir(parents=True, exist_ok=True)
                self._engine_log = engine_log.open("wb")
            except OSError:
                self._engine_log = None

            try:
                with _no_error_dialogs():
                    self._process = subprocess.Popen(
                        command,
                        cwd=str(server.parent),
                        stdout=self._engine_log or subprocess.DEVNULL,
                        stderr=subprocess.STDOUT if self._engine_log else subprocess.DEVNULL,
                        creationflags=_NO_WINDOW,
                    )
            except OSError as exc:
                self._close_log()
                raise RuntimeError_(
                    "The inference engine could not be started on this computer.",
                    hint="The drive may have been removed, or this CPU may not support the engine build.",
                ) from exc
            self._active = model
            self._gpu_layers = layers
            self._context_length = context

        # Loading several gigabytes from a USB drive is slow; wait outside the
        # lock so status polling stays responsive while it happens.
        if not self._wait_until_ready(timeout=420):
            exit_code = self._process.poll() if self._process else None
            tail = self._log_tail()
            self.stop_runtime()
            if _is_app_control_block(exit_code):
                raise RuntimeError_(_app_control_message(), hint="")
            if exit_code is not None:
                raise RuntimeError_(
                    f"The inference engine stopped while loading the model (code {exit_code}).",
                    hint=tail or "Check PocketMind/logs/engine.log on the drive for details.",
                )
            raise RuntimeError_(
                "The model did not finish loading in time.",
                hint="Slow drives can take several minutes. If it keeps failing, try a smaller model.",
            )
        return self.status()

    def _log_tail(self, lines: int = 6) -> str:
        try:
            text = (self.paths.logs / "engine.log").read_text(encoding="utf-8", errors="replace")
        except OSError:
            return ""
        return " ".join(text.strip().splitlines()[-lines:])[:300]

    def _close_log(self) -> None:
        handle, self._engine_log = self._engine_log, None
        if handle is not None:
            try:
                handle.close()  # type: ignore[attr-defined]
            except OSError:
                pass

    def _wait_until_ready(self, *, timeout: float) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            process = self._process
            if process is None or process.poll() is not None:
                return False
            if self.health_check():
                return True
            time.sleep(1.0)
        return False

    def stop_runtime(self) -> None:
        with self._lock:
            self._stop_locked()

    def _stop_locked(self) -> None:
        process, self._process = self._process, None
        self._active = None
        if process is None or process.poll() is not None:
            self._close_log()
            return
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
        self._close_log()
        log.info("Engine stopped")

    def health_check(self) -> bool:
        try:
            with urlopen(f"http://{config.RUNTIME_HOST}:{config.RUNTIME_PORT}/health", timeout=2) as response:
                return getattr(response, "status", 200) == 200
        except (HTTPError, URLError, OSError):
            return False

    def status(self) -> RuntimeStatus:
        owned = self._process is not None and self._process.poll() is None
        # An adopted engine has no process handle of ours but is still serving.
        running = owned or (self._active is not None and self.health_check())
        installed = self.installed_models()
        blocked = _app_control_message() if self._host_blocks_engine() else None
        return RuntimeStatus(
            runtime_installed=self._server_binary() is not None,
            model_installed=bool(installed),
            running=running,
            model_name=self._active.name if self._active else (installed[0].name if installed else None),
            backend=self._backend,
            gpu_layers=self._gpu_layers if running else None,
            context_length=self._context_length if running else None,
            detail=(
                "Running locally on this computer" if running
                else "Blocked by this computer" if blocked
                else "Not running"
            ),
            blocked_reason=blocked,
        )

    # -- inference ---------------------------------------------------------

    def _ensure_running(self) -> None:
        if not (self._process and self._process.poll() is None and self.health_check()):
            self.start_runtime()

    def _payload(self, messages: Sequence[dict[str, str]], stream: bool, options: dict) -> bytes:
        return json.dumps(
            {
                "model": self._active.id if self._active else "local",
                "messages": list(messages),
                "stream": stream,
                "temperature": float(options.get("temperature", 0.7)),
                "max_tokens": int(options.get("max_tokens", 1024)),
            }
        ).encode("utf-8")

    def _request(self, body: bytes, timeout: float):
        return urlopen(
            Request(
                f"http://{config.RUNTIME_HOST}:{config.RUNTIME_PORT}/v1/chat/completions",
                data=body,
                headers={"Content-Type": "application/json"},
            ),
            timeout=timeout,
        )

    def chat(self, messages: Sequence[dict[str, str]], **options: object) -> str:
        self._ensure_running()
        try:
            with self._request(self._payload(messages, False, options), 600) as response:
                data = json.loads(response.read())
        except (HTTPError, URLError, OSError, ValueError) as exc:
            raise RuntimeError_(
                "The local model stopped responding.",
                hint="Make sure the PocketMind drive is still connected, then try again.",
            ) from exc
        return str(data["choices"][0]["message"]["content"])

    def stream_chat(self, messages: Sequence[dict[str, str]], **options: object) -> Iterator[str]:
        self._ensure_running()
        try:
            response = self._request(self._payload(messages, True, options), 600)
        except (HTTPError, URLError, OSError) as exc:
            raise RuntimeError_(
                "The local model stopped responding.",
                hint="Make sure the PocketMind drive is still connected, then try again.",
            ) from exc

        with response:
            for raw in response:
                line = raw.decode("utf-8", errors="replace").strip()
                if not line.startswith("data:"):
                    continue
                payload = line[5:].strip()
                if payload == "[DONE]":
                    return
                try:
                    delta = json.loads(payload)["choices"][0].get("delta", {})
                except (ValueError, KeyError, IndexError):
                    continue
                piece = delta.get("content")
                if piece:
                    yield piece


def _is_app_control_block(exit_code: int | None) -> bool:
    """Windows reports the same code as signed or unsigned depending on the caller."""
    if exit_code is None:
        return False
    return (exit_code & 0xFFFFFFFF) == _APP_CONTROL_EXIT_CODE


def _app_control_message() -> str:
    from pocketmind.services.hardware import APP_CONTROL_BLOCKER

    return (
        "This computer blocked the local AI engine from starting. " + APP_CONTROL_BLOCKER
    )


def _port_in_use(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.settimeout(0.5)
        return probe.connect_ex((host, port)) == 0


def _atomic_write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(data, indent=2), encoding="utf-8")
    temporary.replace(path)


def _mb(value: int | None) -> str:
    if value is None:
        return "?"
    if value >= 1024**3:
        return f"{value / 1024**3:.1f} GB"
    return f"{value / 1024**2:.0f} MB"


def _duration(seconds: float) -> str:
    seconds = max(int(seconds), 0)
    if seconds < 60:
        return f"{seconds}s"
    if seconds < 3600:
        return f"{seconds // 60}m {seconds % 60}s"
    return f"{seconds // 3600}h {(seconds % 3600) // 60}m"
