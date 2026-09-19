"""The llama.cpp provider's decision-making, without downloading anything."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pocketmind import config
from pocketmind.providers.base import InstalledModel, LLMProvider, RuntimeError_
from pocketmind.providers.llamacpp import LlamaCppProvider
from tests.test_catalog import hardware

GB = 1024**3


@pytest.fixture
def provider(tmp_path) -> LlamaCppProvider:
    paths = config.InstallPaths(tmp_path / "PocketMind")
    paths.create_folders()
    paths.config_file.write_text(json.dumps({"default_model_id": None}), encoding="utf-8")
    return LlamaCppProvider(paths, hardware())


def fake_model(size_gb: float) -> InstalledModel:
    return InstalledModel(id="m", name="Model", path=Path("model.gguf"), byte_size=int(size_gb * GB))


def test_the_provider_satisfies_the_protocol(provider):
    assert isinstance(provider, LLMProvider)


def test_release_selection_skips_a_release_without_binaries(provider, monkeypatch):
    """llama.cpp marks a nightly pointer tag as 'latest' with no assets attached."""
    releases = [
        {"tag_name": "v0.4.1", "assets": [{"name": "nightly-tag.txt"}]},
        {"tag_name": "b11052", "assets": [
            {"name": "llama-b11052-bin-win-cpu-x64.zip", "browser_download_url": "https://example/cpu"},
            {"name": "llama-b11052-bin-win-vulkan-x64.zip", "browser_download_url": "https://example/vk"},
        ]},
    ]

    class FakeResponse:
        def read(self):
            return json.dumps(releases).encode()

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    monkeypatch.setattr("pocketmind.providers.llamacpp.urlopen", lambda *a, **k: FakeResponse())
    assets = provider._release_assets()
    assert [asset["name"] for asset in assets] == [
        "llama-b11052-bin-win-cpu-x64.zip",
        "llama-b11052-bin-win-vulkan-x64.zip",
    ]


def test_no_usable_release_is_reported_clearly(provider, monkeypatch):
    class FakeResponse:
        def read(self):
            return json.dumps([{"tag_name": "v1", "assets": [{"name": "notes.txt"}]}]).encode()

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    monkeypatch.setattr("pocketmind.providers.llamacpp.urlopen", lambda *a, **k: FakeResponse())
    with pytest.raises(RuntimeError_) as error:
        provider._release_assets()
    assert error.value.hint


def test_the_installed_backend_survives_a_restart(tmp_path):
    """Otherwise every launch after setup silently falls back to CPU-only."""
    from pocketmind.providers.llamacpp import LlamaCppProvider

    paths = config.InstallPaths(tmp_path / "PocketMind")
    paths.create_folders()
    paths.config_file.write_text(json.dumps({"backend": "vulkan"}), encoding="utf-8")
    (paths.runtime / ".vulkan-installed").write_text("x", encoding="utf-8")

    assert LlamaCppProvider(paths, hardware(vram_gb=8))._backend == "vulkan"


def test_a_claimed_backend_without_its_files_falls_back_to_cpu(tmp_path):
    from pocketmind.providers.llamacpp import LlamaCppProvider

    paths = config.InstallPaths(tmp_path / "PocketMind")
    paths.create_folders()
    paths.config_file.write_text(json.dumps({"backend": "vulkan"}), encoding="utf-8")
    # No .vulkan-installed marker: the package is not actually there.

    assert LlamaCppProvider(paths, hardware(vram_gb=8))._backend == "cpu"


def test_a_lingering_engine_is_adopted_instead_of_blocking_startup(tmp_path, monkeypatch):
    """Closing PocketMind ungracefully must not make the port unusable for ever."""
    from pocketmind.providers import llamacpp
    from pocketmind.providers.llamacpp import LlamaCppProvider
    from pocketmind.services import catalog

    paths = config.InstallPaths(tmp_path / "PocketMind")
    paths.create_folders()
    paths.config_file.write_text(json.dumps({}), encoding="utf-8")
    (paths.runtime / "llama-server.exe").write_bytes(b"stub")
    entry = catalog.CATALOG[0]
    (paths.models / entry.filename).write_bytes(b"GGUF" + b"\0" * (2 * 1024**2))

    provider = LlamaCppProvider(paths, hardware())
    monkeypatch.setattr(llamacpp, "_port_in_use", lambda host, port: True)
    monkeypatch.setattr(LlamaCppProvider, "health_check", lambda self: True)

    def explode(*args, **kwargs):
        raise AssertionError("a second engine must not be started on the same port")

    monkeypatch.setattr(llamacpp.subprocess, "Popen", explode)
    status = provider.start_runtime(entry.id)
    assert status.running


def test_a_foreign_program_on_the_port_is_reported_clearly(tmp_path, monkeypatch):
    from pocketmind.providers import llamacpp
    from pocketmind.providers.llamacpp import LlamaCppProvider
    from pocketmind.services import catalog

    paths = config.InstallPaths(tmp_path / "PocketMind")
    paths.create_folders()
    paths.config_file.write_text(json.dumps({}), encoding="utf-8")
    (paths.runtime / "llama-server.exe").write_bytes(b"stub")
    entry = catalog.CATALOG[0]
    (paths.models / entry.filename).write_bytes(b"GGUF" + b"\0" * (2 * 1024**2))

    provider = LlamaCppProvider(paths, hardware())
    monkeypatch.setattr(llamacpp, "_port_in_use", lambda host, port: True)
    monkeypatch.setattr(LlamaCppProvider, "health_check", lambda self: False)

    with pytest.raises(RuntimeError_) as error:
        provider.start_runtime(entry.id)
    assert "another program" in str(error.value)
    assert error.value.hint


def test_no_gpu_means_no_offloading(provider):
    provider.hardware = hardware(vram_gb=0)
    provider._backend = "cpu"
    assert provider._gpu_layer_count(fake_model(2)) == 0


def test_plenty_of_vram_offloads_everything(provider):
    provider.hardware = hardware(vram_gb=12)
    provider._backend = "vulkan"
    assert provider._gpu_layer_count(fake_model(4)) == 999


def test_limited_vram_offloads_partially(provider):
    provider.hardware = hardware(vram_gb=6)
    provider._backend = "vulkan"
    layers = provider._gpu_layer_count(fake_model(8))
    assert 0 < layers < 999


def test_vram_smaller_than_the_reserve_offloads_nothing(provider):
    """One gigabyte is held back for context and the desktop compositor."""
    provider.hardware = hardware(vram_gb=1)
    provider._backend = "vulkan"
    assert provider._gpu_layer_count(fake_model(4)) == 0


def test_context_length_is_capped_by_available_memory(provider):
    provider.hardware = hardware(ram_gb=4)
    assert provider._context_for(32768) == 2048
    provider.hardware = hardware(ram_gb=8)
    assert provider._context_for(32768) == 4096
    provider.hardware = hardware(ram_gb=32)
    assert provider._context_for(32768) == 8192


def test_a_modest_request_is_honoured(provider):
    provider.hardware = hardware(ram_gb=32)
    assert provider._context_for(2048) == 2048


def test_starting_without_an_engine_explains_what_to_do(provider):
    with pytest.raises(RuntimeError_) as error:
        provider.start_runtime()
    assert "engine is not installed" in str(error.value)
    assert error.value.hint


def test_starting_without_a_model_explains_what_to_do(provider):
    (provider.paths.runtime / "llama-server.exe").write_bytes(b"fake")
    with pytest.raises(RuntimeError_) as error:
        provider.start_runtime()
    assert "No model is installed" in str(error.value)
    assert error.value.hint


def test_status_is_safe_before_anything_is_installed(provider):
    status = provider.status()
    assert status.runtime_installed is False
    assert status.model_installed is False
    assert status.running is False


def test_installed_models_are_discovered_from_the_drive(provider):
    from pocketmind.services import catalog

    entry = catalog.CATALOG[0]
    (provider.paths.models / entry.filename).write_bytes(b"GGUF" + b"\0" * (2 * 1024**2))
    installed = provider.installed_models()
    assert [model.id for model in installed] == [entry.id]


def test_a_truncated_model_file_is_not_treated_as_installed(provider):
    from pocketmind.services import catalog

    (provider.paths.models / catalog.CATALOG[0].filename).write_bytes(b"GGUF")
    assert provider.installed_models() == []


def test_setting_a_default_model_requires_it_to_be_installed(provider):
    with pytest.raises(RuntimeError_):
        provider.set_default_model("qwen2.5-3b-instruct-q4_k_m")


def test_the_default_model_is_persisted(provider):
    from pocketmind.services import catalog

    entry = catalog.CATALOG[1]
    (provider.paths.models / entry.filename).write_bytes(b"GGUF" + b"\0" * (2 * 1024**2))
    provider.set_default_model(entry.id)

    stored = json.loads(provider.paths.config_file.read_text(encoding="utf-8"))
    assert stored["default_model_id"] == entry.id
    assert provider.installed_models()[0].is_default
