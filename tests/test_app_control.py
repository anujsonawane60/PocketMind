"""Behaviour when Windows refuses to load unsigned code.

Smart App Control ships enabled on many Windows 11 machines. It blocks the
llama.cpp binaries, which are published unsigned. PocketMind has to say so
plainly, before a multi-gigabyte download rather than after, and still let the
user prepare a drive for a computer that will run it.
"""

from __future__ import annotations

import subprocess

import pytest

from pocketmind.providers.base import RuntimeError_
from pocketmind.providers.llamacpp import _app_control_message, _is_app_control_block
from pocketmind.schemas import StepStatus
from pocketmind.services import hardware
from tests.test_installer import build_job, run

APP_CONTROL_EXIT = 0xC0E90002


def test_the_block_exit_code_is_recognised_signed_or_unsigned():
    assert _is_app_control_block(APP_CONTROL_EXIT)
    assert _is_app_control_block(-1058471934)  # same value, as Windows reports it signed
    assert not _is_app_control_block(0)
    assert not _is_app_control_block(1)
    assert not _is_app_control_block(None)


def test_the_message_tells_the_user_what_to_do():
    message = _app_control_message()
    assert "Smart App Control" in message
    assert "not digitally signed" in message
    assert "another computer" in message or "without Smart App Control" in message
    # It must warn that turning it off is one-way.
    assert "reinstalling" in message


@pytest.mark.parametrize(
    ("registry_value", "expected"),
    [(0, "off"), (1, "enforcing"), (2, "evaluation")],
)
def test_app_control_state_is_read_from_the_policy_key(monkeypatch, registry_value, expected):
    import winreg

    class FakeKey:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    monkeypatch.setattr(winreg, "OpenKey", lambda *args, **kwargs: FakeKey())
    monkeypatch.setattr(winreg, "QueryValueEx", lambda key, name: (registry_value, 4))
    assert hardware.app_control_state() == expected


def test_a_missing_policy_key_means_no_enforcement(monkeypatch):
    import winreg

    def missing(*args, **kwargs):
        raise OSError("not found")

    monkeypatch.setattr(winreg, "OpenKey", missing)
    assert hardware.app_control_state() == "off"


def test_the_hardware_profile_reports_the_blocker(monkeypatch):
    monkeypatch.setattr(hardware, "app_control_state", lambda: "enforcing")
    profile = hardware.inspect_hardware(refresh=True)
    assert profile.app_control == "enforcing"
    assert profile.app_control_blocks_engine
    assert profile.blockers and "Smart App Control" in profile.blockers[0]
    hardware.inspect_hardware(refresh=True)  # restore the real value for other tests


def test_engine_verification_reports_a_block_rather_than_a_timeout(tmp_path, monkeypatch):
    from pocketmind import config
    from pocketmind.providers.llamacpp import LlamaCppProvider
    from tests.test_catalog import hardware as fake_hardware

    paths = config.InstallPaths(tmp_path / "PocketMind")
    paths.create_folders()
    (paths.runtime / "llama-server.exe").write_bytes(b"stub")
    provider = LlamaCppProvider(paths, fake_hardware())

    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args, APP_CONTROL_EXIT, b"", b""),
    )
    with pytest.raises(RuntimeError_) as error:
        provider.verify_engine()
    assert "Smart App Control" in str(error.value)


def test_starting_the_runtime_is_refused_before_a_process_is_spawned(tmp_path, monkeypatch):
    """A doomed spawn wastes time and used to raise a modal dialog over the browser."""
    from pocketmind import config
    from pocketmind.providers.llamacpp import LlamaCppProvider
    from tests.test_catalog import hardware as fake_hardware

    paths = config.InstallPaths(tmp_path / "PocketMind")
    paths.create_folders()
    (paths.runtime / "llama-server.exe").write_bytes(b"stub")

    provider = LlamaCppProvider(paths, fake_hardware())
    monkeypatch.setattr(hardware, "app_control_state", lambda: "enforcing")

    def explode(*args, **kwargs):
        raise AssertionError("no process may be started on a blocked machine")

    monkeypatch.setattr(subprocess, "Popen", explode)
    with pytest.raises(RuntimeError_) as error:
        provider.start_runtime("qwen2.5-0.5b-instruct-q4_k_m")
    assert "Smart App Control" in str(error.value)


def test_status_reports_the_block_so_the_interface_can_warn_first(tmp_path, monkeypatch):
    from pocketmind import config
    from pocketmind.providers.llamacpp import LlamaCppProvider
    from tests.test_catalog import hardware as fake_hardware

    paths = config.InstallPaths(tmp_path / "PocketMind")
    paths.create_folders()
    provider = LlamaCppProvider(paths, fake_hardware())

    monkeypatch.setattr(hardware, "app_control_state", lambda: "enforcing")
    status = provider.status()
    assert status.blocked_reason and "Smart App Control" in status.blocked_reason
    assert status.detail == "Blocked by this computer"

    monkeypatch.setattr(hardware, "app_control_state", lambda: "off")
    assert provider.status().blocked_reason is None


def test_error_dialogs_are_suppressed_around_spawning(monkeypatch):
    """Windows shows a modal 'Bad Image' box unless the error mode is inherited."""
    from pocketmind.providers import llamacpp

    calls = []

    class FakeKernel:
        def SetErrorMode(self, value):
            calls.append(value)
            return 0

    monkeypatch.setattr(llamacpp.ctypes, "windll", type("W", (), {"kernel32": FakeKernel()})())
    monkeypatch.setattr(llamacpp.os, "name", "nt")

    with llamacpp._no_error_dialogs():
        pass

    assert calls, "the error mode was never set"
    # Critical errors and the fault dialog must both be suppressed, then restored.
    assert calls[0] & 0x0001 and calls[0] & 0x0002
    assert calls[-1] == 0


def test_switching_smart_app_control_off_takes_effect_without_a_restart(monkeypatch):
    """The cached hardware profile must not keep insisting the model is blocked."""
    monkeypatch.setattr(hardware, "app_control_state", lambda: "enforcing")
    blocked = hardware.inspect_hardware(refresh=True)
    assert blocked.app_control_blocks_engine and blocked.blockers

    # The user switches it off while PocketMind is still running.
    monkeypatch.setattr(hardware, "app_control_state", lambda: "off")
    refreshed = hardware.inspect_hardware()  # note: no refresh=True
    assert not refreshed.app_control_blocks_engine
    assert refreshed.blockers == []
    hardware.inspect_hardware(refresh=True)


def test_the_provider_reads_the_policy_live_not_from_the_cached_profile(tmp_path, monkeypatch):
    from pocketmind import config
    from pocketmind.providers.llamacpp import LlamaCppProvider
    from tests.test_catalog import hardware as fake_hardware

    paths = config.InstallPaths(tmp_path / "PocketMind")
    paths.create_folders()

    stale = fake_hardware()
    stale.app_control_blocks_engine = True  # profile captured before it was switched off
    provider = LlamaCppProvider(paths, stale)

    monkeypatch.setattr(hardware, "app_control_state", lambda: "off")
    assert provider._host_blocks_engine() is False
    assert provider.status().blocked_reason is None


def test_engine_verification_passes_on_a_healthy_machine(tmp_path, monkeypatch):
    from pocketmind import config
    from pocketmind.providers.llamacpp import LlamaCppProvider
    from tests.test_catalog import hardware as fake_hardware

    paths = config.InstallPaths(tmp_path / "PocketMind")
    paths.create_folders()
    (paths.runtime / "llama-server.exe").write_bytes(b"stub")
    provider = LlamaCppProvider(paths, fake_hardware())

    monkeypatch.setattr(
        subprocess, "run", lambda *args, **kwargs: subprocess.CompletedProcess(args, 0, b"version b1", b"")
    )
    provider.verify_engine()  # must not raise


def test_a_blocked_machine_still_produces_a_complete_drive(fake_install, monkeypatch):
    """The drive is built for use elsewhere; only the on-device test is skipped."""
    from pocketmind.schemas import JobState
    from tests.test_catalog import hardware as fake_hardware

    profile = fake_hardware()
    profile.app_control_blocks_engine = True
    profile.app_control = "enforcing"

    job = build_job(fake_install)
    job.hardware = profile
    run(job)

    status = job.status()
    assert status.state == JobState.COMPLETED
    verify = next(step for step in status.steps if step.key == "verify")
    assert verify.status == StepStatus.SKIPPED
    assert "will work on a computer without Smart App Control" in verify.detail
    # Everything else still happened.
    assert job.paths.database.exists()
    assert job.paths.vault_file.exists()
    assert job.paths.launcher.exists()


def test_install_is_refused_until_the_user_acknowledges(installation, monkeypatch):
    """Not a hard block — an explanation plus a way to continue deliberately."""
    from fastapi.testclient import TestClient

    from pocketmind.main import app
    from pocketmind.services import drives
    from pocketmind.services.session import session
    from tests.test_drives import make_drive

    monkeypatch.setattr(hardware, "app_control_state", lambda: "enforcing")
    hardware.inspect_hardware(refresh=True)
    monkeypatch.setattr(drives, "get_eligible_drive", lambda drive_id: make_drive(filesystem="NTFS"))

    body = {
        "drive_id": "E:",
        "model_id": "qwen2.5-0.5b-instruct-q4_k_m",
        "profile": {"display_name": "Alex", "use_cases": ["assistant"]},
        "vault_password": "a long enough master pass 9!",
        "accept_model_license": True,
    }
    try:
        with TestClient(app) as client:
            session.unbind()
            refused = client.post("/api/setup/install", json=body)
            assert refused.status_code == 400
            detail = refused.json()["detail"]
            assert "Smart App Control" in detail
            assert "Prepare anyway" in detail
    finally:
        session.unbind()
        hardware.inspect_hardware(refresh=True)
