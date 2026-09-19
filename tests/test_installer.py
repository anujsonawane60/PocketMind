"""Installation orchestration: ordering, checkpoints, resume, and failure handling.

Network and subprocess work is replaced with fakes so the whole flow can be
exercised without downloading gigabytes.
"""

from __future__ import annotations

import json
from pathlib import Path

from pocketmind import config
from pocketmind.providers.base import RuntimeError_
from pocketmind.schemas import InstallRequest, JobState, StepStatus
from pocketmind.services import installer
from pocketmind.services.installer import InstallJob
from pocketmind.services.vault import Vault
from tests.fakes import FakeProvider
from tests.test_catalog import hardware
from tests.test_drives import make_drive


def build_job(mount: Path, *, bundle_python: bool = False) -> InstallJob:
    request = InstallRequest(
        drive_id="T:",
        model_id="qwen2.5-3b-instruct-q4_k_m",
        profile={"display_name": "Alex", "use_cases": ["assistant", "coding"], "experience": "new"},
        vault_password="a long enough master pass 9!",
        bundle_portable_python=bundle_python,
        accept_model_license=True,
    )
    drive = make_drive(id="T:", mount_point=str(mount))
    job = InstallJob(request, drive, hardware())
    return job


def run(job: InstallJob) -> None:
    """Run the job synchronously so assertions are deterministic."""
    job._state = JobState.RUNNING
    job._run()


def test_a_complete_installation_produces_a_usable_drive(fake_install):
    job = build_job(fake_install)
    run(job)
    status = job.status()

    assert status.state == JobState.COMPLETED, status.error
    assert status.overall_progress == 1.0
    paths = job.paths

    for folder in config.INSTALL_FOLDERS:
        assert (paths.root / folder).is_dir()
    assert paths.config_file.exists()
    assert paths.profile_file.exists()
    assert paths.database.exists()
    assert paths.vault_file.exists()
    assert paths.launcher.exists()
    assert paths.start_here.exists()
    assert (paths.app / "pocketmind" / "main.py").exists()


def test_the_launcher_sits_at_the_drive_root_and_prefers_the_bundled_python(fake_install):
    job = build_job(fake_install)
    run(job)
    launcher = job.paths.launcher
    assert launcher.parent == Path(fake_install)
    assert launcher.name == "START_POCKETMIND.cmd"

    text = launcher.read_text(encoding="utf-8")
    assert "runtime\\python\\python.exe" in text
    assert "uvicorn" in text
    assert text.index("EMBEDDED") < text.index("where python")  # bundled Python is tried first


def test_the_profile_becomes_the_first_memories(fake_install):
    job = build_job(fake_install)
    run(job)

    from pocketmind.services.data import PocketDatabase

    database = PocketDatabase(job.paths.database)
    try:
        contents = [memory["content"] for memory in database.list_memories()]
        assert any("My name is Alex." == item for item in contents)
        # Checkbox values become readable sentences, not raw enum names.
        assert "I want PocketMind to help me with programming." in contents
        assert "I want PocketMind to help me with personal organisation and planning." in contents
        assert not any(item.endswith("with assistant.") for item in contents)
        assert "Alex" in database.load_settings().system_prompt
    finally:
        database.close()


def test_the_vault_is_created_locked_with_the_chosen_password(fake_install):
    job = build_job(fake_install)
    run(job)

    vault = Vault(job.paths.vault_file)
    assert vault.status().state == "locked"
    vault.unlock("a long enough master pass 9!")
    assert vault.status().state == "unlocked"


def test_steps_run_in_the_documented_order(fake_install):
    job = build_job(fake_install)
    run(job)
    assert FakeProvider.calls[0] == "runtime"
    # The engine is proven to run here before gigabytes of model are fetched.
    assert FakeProvider.calls[1] == "verify-engine"
    assert FakeProvider.calls[2].startswith("model:")
    assert "start" in FakeProvider.calls
    assert FakeProvider.calls[-1] == "stop"  # the engine never stays running after setup


def test_the_engine_is_checked_before_the_model_is_downloaded(fake_install):
    """A machine that cannot run the engine should not cost the user a download."""

    def refuse(self):
        raise RuntimeError_("This computer blocked the engine.", hint="Try another computer.")

    original, FakeProvider.verify_engine = FakeProvider.verify_engine, refuse
    try:
        job = build_job(fake_install)
        run(job)
    finally:
        FakeProvider.verify_engine = original

    assert job.status().state == JobState.FAILED
    assert not any(call.startswith("model:") for call in FakeProvider.calls)


def test_a_checkpoint_is_written_so_progress_survives(fake_install):
    job = build_job(fake_install)
    run(job)
    payload = json.loads(job.paths.install_state_file.read_text(encoding="utf-8"))
    assert payload["model_id"] == "qwen2.5-3b-instruct-q4_k_m"
    assert "model" in payload["completed"]
    assert "vault" in payload["completed"]


def test_resuming_skips_work_that_already_finished(fake_install):
    run(build_job(fake_install))
    FakeProvider.calls = []

    second = build_job(fake_install)
    run(second)

    assert second.status().state == JobState.COMPLETED
    assert not any(call.startswith("model:") for call in FakeProvider.calls), "model was downloaded twice"
    assert all(
        step.status in (StepStatus.COMPLETED, StepStatus.SKIPPED) for step in second.status().steps
    )


def test_resuming_refreshes_the_application_copy(fake_install):
    """A drive must never keep running an older build than the one just installed."""
    job = build_job(fake_install)
    run(job)

    stale = job.paths.app / "pocketmind" / "main.py"
    stale.write_text("# stale build left behind by an earlier version\n", encoding="utf-8")

    run(build_job(fake_install))
    assert "stale build" not in stale.read_text(encoding="utf-8")
    assert "FastAPI" in stale.read_text(encoding="utf-8")


def test_updating_a_drive_replaces_code_but_not_data(fake_install):
    from pocketmind.services.installer import copy_application

    job = build_job(fake_install)
    run(job)

    database_before = job.paths.database.read_bytes()
    vault_before = job.paths.vault_file.read_bytes()
    (job.paths.app / "pocketmind" / "main.py").write_text("# stale\n", encoding="utf-8")

    version, copied = copy_application(job.paths)

    assert version == config.APP_VERSION
    assert copied
    assert "stale" not in (job.paths.app / "pocketmind" / "main.py").read_text(encoding="utf-8")
    assert job.paths.launcher.exists()
    assert job.paths.database.read_bytes() == database_before
    assert job.paths.vault_file.read_bytes() == vault_before


def test_a_drive_never_overwrites_the_code_it_is_running(fake_install, monkeypatch):
    """Source and destination would be the same folder, so clearing it first
    deletes the running application and leaves the drive unbootable."""
    from pocketmind.services import installer as installer_module

    job = build_job(fake_install)
    run(job)
    package_on_drive = job.paths.app / "pocketmind"
    assert (package_on_drive / "main.py").exists()

    # Pretend PocketMind was launched from the drive, as START_POCKETMIND.cmd does.
    monkeypatch.setattr(installer_module.config, "PACKAGE_DIR", package_on_drive)
    assert installer_module.running_from(job.paths)

    version, copied = installer_module.copy_application(job.paths)

    assert not copied, "it must refuse rather than delete itself"
    assert version == config.APP_VERSION
    assert (package_on_drive / "main.py").exists(), "the running application was destroyed"
    assert len(list(package_on_drive.iterdir())) > 5


def test_resuming_from_the_drive_does_not_wipe_the_application(fake_install, monkeypatch):
    from pocketmind.services import installer as installer_module

    job = build_job(fake_install)
    run(job)
    package_on_drive = job.paths.app / "pocketmind"

    monkeypatch.setattr(installer_module.config, "PACKAGE_DIR", package_on_drive)
    second = build_job(fake_install)
    run(second)

    assert second.status().state == JobState.COMPLETED
    assert (package_on_drive / "main.py").exists()
    app_step = next(step for step in second.status().steps if step.key == "app")
    assert "Already running" in app_step.detail


def test_a_different_model_invalidates_the_checkpoint(fake_install):
    run(build_job(fake_install))
    FakeProvider.calls = []

    second = build_job(fake_install)
    second.request.model_id = "qwen2.5-7b-instruct-q4_k_m"
    run(second)
    assert any(call.startswith("model:") for call in FakeProvider.calls)


def test_bundling_python_can_be_declined(fake_install):
    job = build_job(fake_install, bundle_python=False)
    run(job)
    python_step = next(step for step in job.status().steps if step.key == "python")
    assert python_step.status == StepStatus.SKIPPED
    assert "host" in python_step.detail.lower()


def test_a_failed_python_bundle_does_not_fail_the_install(fake_install, monkeypatch):
    def boom(paths, **kwargs):
        raise installer.portable_python.PortablePythonError("No internet.")

    monkeypatch.setattr(installer.portable_python, "install", boom)
    monkeypatch.setattr(installer.portable_python, "python_executable", lambda paths: None)

    job = build_job(fake_install, bundle_python=True)
    run(job)

    assert job.status().state == JobState.COMPLETED
    python_step = next(step for step in job.status().steps if step.key == "python")
    assert python_step.status == StepStatus.SKIPPED
    assert "Python installed on the computer" in python_step.detail


def test_a_failed_verification_reports_a_recoverable_error(fake_install):
    FakeProvider.fail_verify = True
    job = build_job(fake_install)
    run(job)

    status = job.status()
    assert status.state == JobState.FAILED
    assert status.can_resume
    assert status.recovery_hint
    assert "did not answer" in status.error


def test_cancelling_keeps_progress_and_offers_resume(fake_install):
    job = build_job(fake_install)
    job.cancel()
    run(job)

    status = job.status()
    assert status.state == JobState.CANCELLED
    assert status.can_resume
    assert "progress is saved" in status.message


def test_progress_never_exceeds_one(fake_install):
    job = build_job(fake_install)
    run(job)
    for step in job.status().steps:
        assert 0.0 <= step.progress <= 1.0
    assert job.status().overall_progress <= 1.0
