"""Test doubles.

This lives in its own module rather than in ``conftest.py`` on purpose: pytest
imports ``conftest`` under a different module name than ``tests.conftest``, so a
class defined there would exist twice and a fixture patching one copy would not
be the copy the tests assert against.
"""

from __future__ import annotations

from pocketmind.providers.base import InstalledModel, RuntimeError_


class FakeProvider:
    """Stands in for llama.cpp. Records what it was asked to do, in order."""

    calls: list[str] = []
    fail_verify = False

    def __init__(self, paths, hardware_profile=None):
        self.paths = paths

    @classmethod
    def reset(cls) -> None:
        cls.calls = []
        cls.fail_verify = False

    def install_runtime(self, hardware_profile, *, on_progress=None, cancel=None):
        FakeProvider.calls.append("runtime")
        if on_progress:
            on_progress("Installing the CPU engine", 1.0, "")
        (self.paths.runtime / "llama-server.exe").write_bytes(b"fake")
        return "cpu"

    def verify_engine(self):
        FakeProvider.calls.append("verify-engine")

    def install_model(self, model_id, *, on_progress=None, cancel=None):
        FakeProvider.calls.append(f"model:{model_id}")
        if on_progress:
            on_progress("Downloading", 1.0, "")
        path = self.paths.models / "model.gguf"
        path.write_bytes(b"GGUF" + b"\0" * 2048)
        return InstalledModel(id=model_id, name="Test Model", path=path, byte_size=2052)

    def start_runtime(self, model_id=None, *, context_length=None):
        FakeProvider.calls.append("start")

    def chat(self, messages, **options):
        if FakeProvider.fail_verify:
            raise RuntimeError_("The model did not load.", hint="Try a smaller model.")
        return "ready"

    def stop_runtime(self):
        FakeProvider.calls.append("stop")
