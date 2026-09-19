"""Model tiers, storage budgets, and the recommendation engine."""

from __future__ import annotations

import pytest

from pocketmind import config
from pocketmind.schemas import HardwareProfile, ModelTier, UseCase
from pocketmind.services import catalog
from tests.test_drives import make_drive

GB = 1024**3


def hardware(*, ram_gb=16, vram_gb=0, cores=8) -> HardwareProfile:
    return HardwareProfile(
        operating_system="Windows 11",
        architecture="AMD64",
        cpu_name="Test CPU",
        physical_cores=cores,
        logical_cores=cores * 2,
        ram_bytes=int(ram_gb * GB),
        gpu_name="Test GPU" if vram_gb else None,
        gpu_vram_bytes=int(vram_gb * GB) if vram_gb else None,
        gpu_vendor="nvidia" if vram_gb else None,
        performance_stars=3,
        performance_label="Capable",
    )


@pytest.fixture
def offline_catalog(monkeypatch):
    """Never touch the network in tests; use the published estimates."""
    monkeypatch.setattr(catalog, "_probe", lambda entry, timeout: (None, True))
    return catalog


@pytest.mark.parametrize(
    ("gigabytes", "tier"),
    [(0.4, ModelTier.TINY), (1.9, ModelTier.TINY), (2.5, ModelTier.SMALL),
     (4.9, ModelTier.SMALL), (5.5, ModelTier.MEDIUM), (9.9, ModelTier.MEDIUM), (12, ModelTier.LARGE)],
)
def test_tier_boundaries_match_the_specification(gigabytes, tier):
    assert catalog.tier_for(int(gigabytes * GB)) is tier


def test_minimum_ram_allows_for_context_and_overhead():
    assert catalog.minimum_ram_for(4 * GB) > 4 * GB


def test_budget_accounts_for_every_component(offline_catalog):
    drive = make_drive(free_bytes=30 * GB, total_bytes=32 * GB)
    models, _, _ = catalog.resolve_catalog(online=False)
    model = next(item for item in models if item.id == "qwen2.5-7b-instruct-q4_k_m")

    budget = catalog.build_budget(drive, model, bundle_portable_python=True)
    assert budget.required_bytes == (
        model.download_size_bytes
        + config.RUNTIME_BUDGET_BYTES
        + config.WORKSPACE_BUDGET_BYTES
        + config.RESERVE_BYTES
        + config.PORTABLE_PYTHON_BUDGET_BYTES
    )
    assert budget.is_sufficient


def test_budget_explains_a_drive_that_is_too_small(offline_catalog):
    drive = make_drive(free_bytes=3 * GB, total_bytes=4 * GB)
    models, _, _ = catalog.resolve_catalog(online=False)
    model = next(item for item in models if item.id == "qwen2.5-14b-instruct-q4_k_m")

    budget = catalog.build_budget(drive, model, bundle_portable_python=True)
    assert not budget.is_sufficient
    assert "Not enough space" in budget.message
    assert "smaller model" in budget.message


def test_a_small_drive_still_gets_a_recommendation(offline_catalog):
    drive = make_drive(free_bytes=6 * GB, total_bytes=8 * GB)
    result = catalog.recommend(hardware(ram_gb=8), drive, {UseCase.ASSISTANT}, online=False)
    assert result.recommended is not None
    assert result.recommended.model.download_size_bytes < 3 * GB


def test_a_capable_machine_is_offered_a_larger_model(offline_catalog):
    drive = make_drive(free_bytes=60 * GB, total_bytes=64 * GB)
    result = catalog.recommend(hardware(ram_gb=32, vram_gb=12, cores=12), drive,
                               {UseCase.CODING, UseCase.DOCUMENTS}, online=False)
    assert result.recommended is not None
    assert result.recommended.model.download_size_bytes > 3 * GB


def test_coding_use_case_shifts_the_recommendation(offline_catalog):
    drive = make_drive(free_bytes=60 * GB, total_bytes=64 * GB)
    coding = catalog.recommend(hardware(ram_gb=16, vram_gb=8), drive, {UseCase.CODING}, online=False)
    assert any("programming" in reason.lower() for reason in coding.recommended.reasons)


def test_models_that_do_not_fit_are_blocked_with_a_reason(offline_catalog):
    drive = make_drive(free_bytes=4 * GB, total_bytes=8 * GB)
    result = catalog.recommend(hardware(ram_gb=4), drive, {UseCase.ASSISTANT}, online=False)
    blocked = [fit for fit in result.all_models if fit.blockers]
    assert blocked
    for fit in blocked:
        assert fit.score == 0.0
        assert all(blocker.strip() for blocker in fit.blockers)


def test_a_machine_with_no_room_gets_no_recommendation(offline_catalog):
    drive = make_drive(free_bytes=1 * GB, total_bytes=2 * GB)
    result = catalog.recommend(hardware(ram_gb=4), drive, set(), online=False)
    assert result.recommended is None
    assert all(fit.blockers for fit in result.all_models)


def test_every_recommendation_explains_itself(offline_catalog):
    drive = make_drive(free_bytes=40 * GB, total_bytes=64 * GB)
    result = catalog.recommend(hardware(ram_gb=16, vram_gb=6), drive,
                               {UseCase.ASSISTANT, UseCase.DOCUMENTS}, online=False)
    for fit in (result.recommended, result.alternative, result.lightweight):
        if fit is None:
            continue
        assert len(fit.reasons) >= 2
        assert fit.expected_speed


def test_the_alternative_comes_from_a_different_family_when_possible(offline_catalog):
    drive = make_drive(free_bytes=60 * GB, total_bytes=64 * GB)
    result = catalog.recommend(hardware(ram_gb=32, vram_gb=12), drive, {UseCase.ASSISTANT}, online=False)
    if result.alternative and result.recommended:
        assert result.alternative.model.id != result.recommended.model.id


def test_a_gpu_makes_a_model_report_as_faster(offline_catalog):
    drive = make_drive(free_bytes=60 * GB, total_bytes=64 * GB)
    models, _, _ = catalog.resolve_catalog(online=False)
    model = next(item for item in models if item.id == "qwen2.5-3b-instruct-q4_k_m")

    on_gpu = catalog.evaluate(model, hardware(vram_gb=12), drive, set(), bundle_portable_python=False)
    on_cpu = catalog.evaluate(model, hardware(vram_gb=0), drive, set(), bundle_portable_python=False)
    assert "graphics card" in on_gpu.expected_speed
    assert "CPU" in on_cpu.expected_speed


def test_offline_catalog_is_marked_as_estimated():
    models, refreshed, note = catalog.resolve_catalog(online=False)
    assert not refreshed
    assert note and "estimate" in note
    assert all(model.size_is_estimate for model in models)


def test_fat32_blocks_models_over_four_gigabytes(offline_catalog):
    """Free space is not the only constraint: FAT32 caps a single file at 4 GB."""
    drive = make_drive(free_bytes=29 * GB, total_bytes=30 * GB, filesystem="FAT32")
    result = catalog.recommend(hardware(ram_gb=32, vram_gb=12), drive, {UseCase.CODING}, online=False)

    for fit in result.all_models:
        if fit.model.download_size_bytes > 4 * GB:
            assert fit.blockers, f"{fit.model.id} should be blocked on FAT32"
            assert any("FAT32" in blocker for blocker in fit.blockers)
            assert any("exFAT" in blocker for blocker in fit.blockers)
    assert result.recommended is not None
    assert result.recommended.model.download_size_bytes < 4 * GB


def test_exfat_and_ntfs_have_no_file_size_cap(offline_catalog):
    for filesystem in ("exFAT", "NTFS"):
        drive = make_drive(free_bytes=40 * GB, total_bytes=64 * GB, filesystem=filesystem)
        result = catalog.recommend(hardware(ram_gb=32, vram_gb=12), drive, {UseCase.CODING}, online=False)
        big = [fit for fit in result.all_models if fit.model.download_size_bytes > 4 * GB]
        assert any(not fit.blockers for fit in big), filesystem


def test_memory_check_leaves_headroom_for_the_operating_system(offline_catalog):
    """A model that fits on paper but leaves 2 GB for Windows is bad advice."""
    drive = make_drive(free_bytes=60 * GB, total_bytes=64 * GB, filesystem="NTFS")
    models, _, _ = catalog.resolve_catalog(online=False)
    model = next(item for item in models if item.id == "qwen2.5-14b-instruct-q4_k_m")

    tight = catalog.evaluate(model, hardware(ram_gb=14), drive, set(), bundle_portable_python=False)
    assert not tight.fits_memory
    assert any("free for Windows" in blocker for blocker in tight.blockers)

    roomy = catalog.evaluate(model, hardware(ram_gb=32), drive, set(), bundle_portable_python=False)
    assert roomy.fits_memory


def test_a_faster_model_outranks_a_slower_larger_one(offline_catalog):
    """Speed carries enough weight that a crawling model is not the top pick."""
    drive = make_drive(free_bytes=60 * GB, total_bytes=64 * GB, filesystem="NTFS")
    result = catalog.recommend(hardware(ram_gb=16, vram_gb=0, cores=4), drive,
                               {UseCase.ASSISTANT}, online=False)
    assert result.recommended is not None
    assert "Slow" not in result.recommended.expected_speed


def test_every_catalog_entry_is_well_formed():
    for entry in catalog.CATALOG:
        assert entry.urls, f"{entry.id} has no download URL"
        assert entry.filename.endswith(".gguf")
        assert entry.license and entry.license_url
        assert entry.estimated_bytes > 0
        assert entry.best_for
