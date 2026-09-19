"""Model catalog and recommendation engine (PRD sections 16, 17, 35, 36).

The catalog is data, not code: each entry is a standardised description of one
downloadable model, and the sizes are refreshed from the hosting provider at
runtime rather than trusted from this file. A new model can be offered by
adding an entry here or by a future provider adapter returning the same shape,
without touching the recommendation logic below.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from pocketmind import config
from pocketmind.logs import get_logger
from pocketmind.schemas import (
    Drive,
    HardwareProfile,
    ModelCapabilities,
    ModelFit,
    ModelInfo,
    ModelRecommendations,
    ModelTier,
    StorageBudget,
    UseCase,
)

log = get_logger("catalog")

_USER_AGENT = f"PocketMind/{config.APP_VERSION}"

#: Bytes of working memory a model needs beyond its own weights (KV cache,
#: context buffers, runtime overhead).
_MEMORY_OVERHEAD_BYTES = 1_200 * 1024**2
_MEMORY_HEADROOM = 1.25

#: Memory left to the operating system and whatever else the user is running.
#: Without this a model that fits on paper drives the machine into swapping.
_OS_RESERVE_BYTES = 3 * 1024**3

#: FAT-family filesystems cannot store a file of 4 GB or more, whatever the
#: drive's free space says. Many USB sticks ship formatted this way.
_FAT_FILESYSTEMS = frozenset({"FAT", "FAT32", "VFAT", "MSDOS"})
_FAT_MAX_FILE_BYTES = 4 * 1024**3 - 1


@dataclass(frozen=True)
class CatalogEntry:
    id: str
    name: str
    family: str
    parameter_count: str
    quantization: str
    estimated_bytes: int
    context_length: int
    filename: str
    urls: tuple[str, ...]
    license: str
    license_url: str
    best_for: str
    capabilities: ModelCapabilities
    use_cases: frozenset[UseCase] = field(default_factory=frozenset)
    provider: str = "huggingface"


def _hf(repo: str, filename: str) -> str:
    return f"https://huggingface.co/{repo}/resolve/main/{filename}?download=true"


CATALOG: tuple[CatalogEntry, ...] = (
    CatalogEntry(
        id="qwen2.5-0.5b-instruct-q4_k_m",
        name="Qwen 2.5 0.5B Instruct",
        family="Qwen 2.5",
        parameter_count="0.5B",
        quantization="Q4_K_M",
        estimated_bytes=420 * 1024**2,
        context_length=32768,
        filename="qwen2.5-0.5b-instruct-q4_k_m.gguf",
        urls=(_hf("Qwen/Qwen2.5-0.5B-Instruct-GGUF", "qwen2.5-0.5b-instruct-q4_k_m.gguf"),),
        license="Apache 2.0",
        license_url="https://huggingface.co/Qwen/Qwen2.5-0.5B-Instruct",
        best_for="Very low-resource machines and basic question answering",
        capabilities=ModelCapabilities(text=True),
        use_cases=frozenset({UseCase.ASSISTANT}),
    ),
    CatalogEntry(
        id="qwen2.5-1.5b-instruct-q4_k_m",
        name="Qwen 2.5 1.5B Instruct",
        family="Qwen 2.5",
        parameter_count="1.5B",
        quantization="Q4_K_M",
        estimated_bytes=1_120 * 1024**2,
        context_length=32768,
        filename="qwen2.5-1.5b-instruct-q4_k_m.gguf",
        urls=(_hf("Qwen/Qwen2.5-1.5B-Instruct-GGUF", "qwen2.5-1.5b-instruct-q4_k_m.gguf"),),
        license="Apache 2.0",
        license_url="https://huggingface.co/Qwen/Qwen2.5-1.5B-Instruct",
        best_for="Older laptops that still need a responsive assistant",
        capabilities=ModelCapabilities(text=True),
        use_cases=frozenset({UseCase.ASSISTANT, UseCase.JOURNALING}),
    ),
    CatalogEntry(
        id="qwen2.5-3b-instruct-q4_k_m",
        name="Qwen 2.5 3B Instruct",
        family="Qwen 2.5",
        parameter_count="3B",
        quantization="Q4_K_M",
        estimated_bytes=2_050 * 1024**2,
        context_length=32768,
        filename="qwen2.5-3b-instruct-q4_k_m.gguf",
        urls=(_hf("Qwen/Qwen2.5-3B-Instruct-GGUF", "qwen2.5-3b-instruct-q4_k_m.gguf"),),
        license="Qwen Research License",
        license_url="https://huggingface.co/Qwen/Qwen2.5-3B-Instruct",
        best_for="A fast general assistant with light coding help",
        capabilities=ModelCapabilities(text=True, coding=True),
        use_cases=frozenset({UseCase.ASSISTANT, UseCase.LEARNING, UseCase.JOURNALING}),
    ),
    CatalogEntry(
        id="llama-3.2-3b-instruct-q4_k_m",
        name="Llama 3.2 3B Instruct",
        family="Llama 3.2",
        parameter_count="3B",
        quantization="Q4_K_M",
        estimated_bytes=2_020 * 1024**2,
        context_length=131072,
        filename="Llama-3.2-3B-Instruct-Q4_K_M.gguf",
        urls=(_hf("bartowski/Llama-3.2-3B-Instruct-GGUF", "Llama-3.2-3B-Instruct-Q4_K_M.gguf"),),
        license="Llama 3.2 Community License",
        license_url="https://huggingface.co/meta-llama/Llama-3.2-3B-Instruct",
        best_for="Long documents and conversational assistance",
        capabilities=ModelCapabilities(text=True, tools=True),
        use_cases=frozenset({UseCase.ASSISTANT, UseCase.DOCUMENTS, UseCase.JOURNALING}),
    ),
    CatalogEntry(
        id="qwen2.5-7b-instruct-q4_k_m",
        name="Qwen 2.5 7B Instruct",
        family="Qwen 2.5",
        parameter_count="7B",
        quantization="Q4_K_M",
        estimated_bytes=4_680 * 1024**2,
        context_length=32768,
        # The official Qwen repository publishes this size as a split archive;
        # PocketMind only lists single-file quantisations so a download can
        # resume and verify as one object.
        filename="Qwen2.5-7B-Instruct-Q4_K_M.gguf",
        urls=(_hf("bartowski/Qwen2.5-7B-Instruct-GGUF", "Qwen2.5-7B-Instruct-Q4_K_M.gguf"),),
        license="Apache 2.0",
        license_url="https://huggingface.co/Qwen/Qwen2.5-7B-Instruct",
        best_for="General assistance, coding, reasoning, and document search",
        capabilities=ModelCapabilities(text=True, coding=True, reasoning=True, tools=True),
        use_cases=frozenset({UseCase.ASSISTANT, UseCase.LEARNING, UseCase.CODING, UseCase.DOCUMENTS, UseCase.FINANCE}),
    ),
    CatalogEntry(
        id="qwen2.5-coder-7b-instruct-q4_k_m",
        name="Qwen 2.5 Coder 7B Instruct",
        family="Qwen 2.5 Coder",
        parameter_count="7B",
        quantization="Q4_K_M",
        estimated_bytes=4_680 * 1024**2,
        context_length=32768,
        filename="qwen2.5-coder-7b-instruct-q4_k_m.gguf",
        urls=(_hf("Qwen/Qwen2.5-Coder-7B-Instruct-GGUF", "qwen2.5-coder-7b-instruct-q4_k_m.gguf"),),
        license="Apache 2.0",
        license_url="https://huggingface.co/Qwen/Qwen2.5-Coder-7B-Instruct",
        best_for="Programming work, code explanation, and technical notes",
        capabilities=ModelCapabilities(text=True, coding=True, reasoning=True, tools=True),
        use_cases=frozenset({UseCase.CODING, UseCase.LEARNING, UseCase.DOCUMENTS}),
    ),
    CatalogEntry(
        id="qwen2.5-14b-instruct-q4_k_m",
        name="Qwen 2.5 14B Instruct",
        family="Qwen 2.5",
        parameter_count="14B",
        quantization="Q4_K_M",
        estimated_bytes=8_990 * 1024**2,
        context_length=32768,
        filename="Qwen2.5-14B-Instruct-Q4_K_M.gguf",
        urls=(_hf("bartowski/Qwen2.5-14B-Instruct-GGUF", "Qwen2.5-14B-Instruct-Q4_K_M.gguf"),),
        license="Apache 2.0",
        license_url="https://huggingface.co/Qwen/Qwen2.5-14B-Instruct",
        best_for="Advanced reasoning and coding on a powerful computer",
        capabilities=ModelCapabilities(text=True, coding=True, reasoning=True, tools=True),
        use_cases=frozenset({UseCase.CODING, UseCase.DOCUMENTS, UseCase.LEARNING, UseCase.FINANCE}),
    ),
)

_BY_ID = {entry.id: entry for entry in CATALOG}


def get_entry(model_id: str) -> CatalogEntry | None:
    return _BY_ID.get(model_id)


def tier_for(size_bytes: int) -> ModelTier:
    gigabytes = size_bytes / 1024**3
    if gigabytes < 2:
        return ModelTier.TINY
    if gigabytes < 5:
        return ModelTier.SMALL
    if gigabytes < 10:
        return ModelTier.MEDIUM
    return ModelTier.LARGE


def minimum_ram_for(size_bytes: int) -> int:
    return int(size_bytes * _MEMORY_HEADROOM) + _MEMORY_OVERHEAD_BYTES


def _probe(entry: CatalogEntry, timeout: float) -> tuple[int | None, bool]:
    """Ask the host how big the file really is, and whether it is still there."""
    for url in entry.urls:
        request = Request(url, method="HEAD", headers={"User-Agent": _USER_AGENT})
        try:
            with urlopen(request, timeout=timeout) as response:
                length = response.headers.get("Content-Length")
                # Hugging Face reports the real object size on the redirect target.
                linked = response.headers.get("X-Linked-Size")
                size = int(linked or length or 0)
                return (size or None), True
        except (HTTPError, URLError, OSError, ValueError) as exc:
            log.debug("Catalog probe failed for %s: %s", entry.id, exc.__class__.__name__)
            continue
    return None, False


def resolve_catalog(*, online: bool, timeout: float = 6.0) -> tuple[list[ModelInfo], bool, str | None]:
    """Turn catalog entries into API models, refreshing sizes when online."""
    sizes: dict[str, tuple[int | None, bool]] = {}
    refreshed = False
    note: str | None = None

    if online:
        try:
            with ThreadPoolExecutor(max_workers=min(8, len(CATALOG))) as pool:
                results = pool.map(lambda entry: (entry.id, _probe(entry, timeout)), CATALOG)
                sizes = dict(results)
            refreshed = any(available for _, available in sizes.values())
            if not refreshed:
                note = "Could not reach the model provider, so sizes below are estimates."
        except Exception as exc:  # pragma: no cover - defensive, network is unpredictable
            log.warning("Catalog refresh failed: %s", exc.__class__.__name__)
            note = "Could not reach the model provider, so sizes below are estimates."
    else:
        note = "Internet access is turned off, so sizes below are estimates."

    models: list[ModelInfo] = []
    for entry in CATALOG:
        live_size, available = sizes.get(entry.id, (None, not online))
        size = live_size or entry.estimated_bytes
        models.append(
            ModelInfo(
                id=entry.id,
                name=entry.name,
                family=entry.family,
                provider=entry.provider,
                parameter_count=entry.parameter_count,
                quantization=entry.quantization,
                download_size_bytes=size,
                size_is_estimate=live_size is None,
                context_length=entry.context_length,
                tier=tier_for(size),
                capabilities=entry.capabilities,
                min_ram_bytes=minimum_ram_for(size),
                license=entry.license,
                license_url=entry.license_url,
                best_for=entry.best_for,
                available=available,
            )
        )
    return models, refreshed, note


def build_budget(drive: Drive, model: ModelInfo, *, bundle_portable_python: bool) -> StorageBudget:
    python_bytes = config.PORTABLE_PYTHON_BUDGET_BYTES if bundle_portable_python else 0
    required = config.total_install_budget(model.download_size_bytes, include_portable_python=bundle_portable_python)
    remaining = drive.free_bytes - required
    sufficient = remaining >= 0

    if sufficient:
        message = (
            f"{_gb(model.download_size_bytes)} for the model plus "
            f"{_gb(required - model.download_size_bytes)} for the runtime, your data, and free headroom. "
            f"About {_gb(drive.free_bytes - required + config.RESERVE_BYTES)} stays available on the drive."
        )
    else:
        message = (
            f"Not enough space. PocketMind needs {_gb(required)} on {drive.id} and "
            f"{_gb(drive.free_bytes)} is free. Choose a smaller model or a larger drive."
        )

    return StorageBudget(
        drive_id=drive.id,
        drive_total_bytes=drive.total_bytes,
        drive_free_bytes=drive.free_bytes,
        model_bytes=model.download_size_bytes,
        runtime_bytes=config.RUNTIME_BUDGET_BYTES,
        portable_python_bytes=python_bytes,
        workspace_bytes=config.WORKSPACE_BUDGET_BYTES,
        reserve_bytes=config.RESERVE_BYTES,
        required_bytes=required,
        remaining_bytes=max(remaining, 0),
        is_sufficient=sufficient,
        message=message,
    )


def _gb(value: int) -> str:
    gigabytes = value / 1024**3
    if gigabytes < 1:
        return f"{value / 1024**2:.0f} MB"
    return f"{gigabytes:.1f} GB"


def _expected_speed(model: ModelInfo, hardware: HardwareProfile) -> tuple[str, float]:
    """Describe how fast this model will feel, and score that for ranking."""
    vram = hardware.gpu_vram_bytes or 0
    cores = hardware.physical_cores or hardware.logical_cores or 2
    # Weights plus a little context need to fit in VRAM for full offload.
    if vram >= model.download_size_bytes * 1.2:
        return "Fast — runs on your graphics card", 1.0
    if vram >= model.download_size_bytes * 0.6:
        return "Medium — partly on your graphics card", 0.7
    if model.download_size_bytes <= 2 * 1024**3 and cores >= 4:
        return "Medium — runs on the CPU", 0.55
    if model.download_size_bytes <= 5 * 1024**3 and cores >= 8:
        return "Slower — runs on the CPU", 0.35
    return "Slow — large model on the CPU", 0.15


def evaluate(
    model: ModelInfo,
    hardware: HardwareProfile,
    drive: Drive,
    use_cases: set[UseCase],
    *,
    bundle_portable_python: bool,
) -> ModelFit:
    budget = build_budget(drive, model, bundle_portable_python=bundle_portable_python)
    usable_ram = max(hardware.ram_bytes - _OS_RESERVE_BYTES, 0)
    fits_memory = model.min_ram_bytes <= usable_ram
    speed_text, speed_score = _expected_speed(model, hardware)

    reasons: list[str] = []
    blockers: list[str] = []

    if not model.available:
        blockers.append("This model is not reachable right now. Check your internet connection and rescan.")

    filesystem = (drive.filesystem or "").upper()
    if filesystem in _FAT_FILESYSTEMS and model.download_size_bytes > _FAT_MAX_FILE_BYTES:
        blockers.append(
            f"{drive.id} is formatted as {filesystem}, which cannot hold a single file of 4 GB or more. "
            f"This model is {_gb(model.download_size_bytes)}. Reformat the drive as exFAT or NTFS, "
            "or choose a smaller model."
        )

    if budget.is_sufficient:
        reasons.append(f"Fits {drive.id} with {_gb(budget.remaining_bytes + config.RESERVE_BYTES)} left free")
    else:
        blockers.append(budget.message)

    if fits_memory:
        reasons.append(
            f"Needs about {_gb(model.min_ram_bytes)} of RAM, leaving room on your {_gb(hardware.ram_bytes)}"
        )
    else:
        blockers.append(
            f"Needs about {_gb(model.min_ram_bytes)} of RAM. This computer has {_gb(hardware.ram_bytes)}, "
            f"and {_gb(_OS_RESERVE_BYTES)} of that has to stay free for Windows"
        )

    entry = _BY_ID.get(model.id)
    matched = use_cases & entry.use_cases if entry else set()
    for case in sorted(matched, key=lambda item: item.value):
        reasons.append(_USE_CASE_REASONS[case])
    if model.capabilities.reasoning:
        reasons.append("Handles multi-step reasoning")
    # Speed is reported separately as `expected_speed`. Listing "Slow — large
    # model on the CPU" among the ticked benefits read as a selling point.

    # Ranking: capability, how well it matches what the user said they want,
    # and how fast it will actually feel on this machine. Speed carries real
    # weight — a larger model that answers at a word per second is worse advice
    # than a smaller one that keeps up with the user.
    size_score = min(model.download_size_bytes / (8 * 1024**3), 1.0)
    match_score = len(matched) / max(len(use_cases), 1) if use_cases else 0.5
    score = (size_score * 0.30) + (match_score * 0.35) + (speed_score * 0.35)
    if blockers:
        score = 0.0

    return ModelFit(
        model=model,
        fits_storage=budget.is_sufficient,
        fits_memory=fits_memory,
        is_recommended=False,
        expected_speed=speed_text,
        score=round(score, 4),
        reasons=reasons,
        blockers=blockers,
    )


_USE_CASE_REASONS = {
    UseCase.ASSISTANT: "Good general personal assistant",
    UseCase.LEARNING: "Suitable for study and explanation",
    UseCase.CODING: "Trained for programming tasks",
    UseCase.DOCUMENTS: "Works well for document question answering",
    UseCase.JOURNALING: "Comfortable with reflective, personal writing",
    UseCase.FINANCE: "Careful with numbers and structured records",
}


def recommend(
    hardware: HardwareProfile,
    drive: Drive,
    use_cases: set[UseCase],
    *,
    online: bool,
    bundle_portable_python: bool = True,
    installed_ids: set[str] | None = None,
) -> ModelRecommendations:
    models, refreshed, note = resolve_catalog(online=online)
    installed = installed_ids or set()
    for model in models:
        model.installed = model.id in installed

    fits = [
        evaluate(model, hardware, drive, use_cases, bundle_portable_python=bundle_portable_python)
        for model in models
    ]
    viable = sorted((fit for fit in fits if not fit.blockers), key=lambda fit: fit.score, reverse=True)

    recommended = viable[0] if viable else None
    alternative = next(
        (fit for fit in viable[1:] if recommended and fit.model.family != recommended.model.family),
        viable[1] if len(viable) > 1 else None,
    )
    lightweight = min(viable, key=lambda fit: fit.model.download_size_bytes) if viable else None
    if lightweight and recommended and lightweight.model.id == recommended.model.id:
        lightweight = None
    if alternative and recommended and alternative.model.id == recommended.model.id:
        alternative = None

    if recommended:
        recommended.is_recommended = True

    fits.sort(key=lambda fit: (bool(fit.blockers), -fit.score, fit.model.download_size_bytes))
    return ModelRecommendations(
        hardware=hardware,
        drive=drive,
        recommended=recommended,
        alternative=alternative,
        lightweight=lightweight,
        all_models=fits,
        catalog_refreshed=refreshed,
        catalog_note=note,
    )
