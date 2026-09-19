"""Host hardware inspection.

Model recommendations are only as good as this module, so each value is read
from the most accurate source available and falls back gracefully. VRAM in
particular is never read from ``Win32_VideoController.AdapterRAM`` alone: that
field is a signed 32-bit value and reports roughly 4 GB for every card larger
than that.
"""

from __future__ import annotations

import json
import os
import platform
import re
import subprocess

import psutil

from pocketmind.logs import get_logger
from pocketmind.schemas import HardwareProfile

log = get_logger("hardware")

_IS_WINDOWS = os.name == "nt"
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

# Display adapter class key. Each numbered subkey is one installed adapter.
_DISPLAY_CLASS = r"SYSTEM\CurrentControlSet\Control\Class\{4d36e968-e325-11ce-bfc1-08002be10318}"

_cached: HardwareProfile | None = None


def _run(command: list[str], timeout: float) -> str | None:
    try:
        result = subprocess.run(
            command, capture_output=True, text=True, timeout=timeout, check=True, creationflags=_NO_WINDOW
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return result.stdout


def _cpu_name() -> str:
    if _IS_WINDOWS:
        try:
            import winreg

            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\DESCRIPTION\System\CentralProcessor\0") as key:
                name, _ = winreg.QueryValueEx(key, "ProcessorNameString")
            if isinstance(name, str) and name.strip():
                return re.sub(r"\s+", " ", name).strip()
        except OSError:
            pass
    # platform.processor() returns the raw family string on Windows, which is
    # better than nothing but not something to show a user by choice.
    return (platform.processor() or platform.machine() or "Unknown CPU").strip()


def _nvidia_gpu() -> tuple[str, int] | None:
    output = _run(
        ["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"], timeout=6
    )
    if not output:
        return None
    first = next((line for line in output.splitlines() if line.strip()), "")
    parts = [part.strip() for part in first.split(",")]
    if len(parts) < 2 or not parts[1].isdigit():
        return None
    return parts[0], int(parts[1]) * 1024**2


def _registry_gpu() -> tuple[str, int | None] | None:
    """Read adapter name and the 64-bit VRAM value the driver reports."""
    if not _IS_WINDOWS:
        return None
    try:
        import winreg
    except ImportError:
        return None

    best: tuple[str, int | None] | None = None
    for index in range(8):
        try:
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, f"{_DISPLAY_CLASS}\\{index:04d}") as key:
                try:
                    name, _ = winreg.QueryValueEx(key, "DriverDesc")
                except OSError:
                    continue
                vram: int | None = None
                try:
                    raw, kind = winreg.QueryValueEx(key, "HardwareInformation.qwMemorySize")
                    if isinstance(raw, int):
                        vram = raw
                    elif isinstance(raw, bytes):
                        vram = int.from_bytes(raw[:8], "little")
                    del kind
                except OSError:
                    pass
        except OSError:
            continue
        candidate = (str(name), vram if vram and vram > 0 else None)
        # Prefer whichever adapter reports the most memory: that is the one
        # llama.cpp will be able to offload onto.
        if best is None or (candidate[1] or 0) > (best[1] or 0):
            best = candidate
    return best


def _wmi_gpu() -> tuple[str, int | None] | None:
    if not _IS_WINDOWS:
        return None
    output = _run(
        [
            "powershell",
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            "Get-CimInstance Win32_VideoController | Select-Object Name,AdapterRAM | ConvertTo-Json -Compress",
        ],
        timeout=8,
    )
    if not output:
        return None
    try:
        parsed = json.loads(output)
    except ValueError:
        return None
    rows = parsed if isinstance(parsed, list) else [parsed]
    for row in rows:
        if not isinstance(row, dict) or not row.get("Name"):
            continue
        ram = row.get("AdapterRAM")
        # Negative means the signed 32-bit field overflowed; treat as unknown.
        vram = int(ram) if isinstance(ram, int) and ram > 0 else None
        return str(row["Name"]), vram
    return None


def _vendor_of(name: str | None) -> str | None:
    if not name:
        return None
    lowered = name.lower()
    if "nvidia" in lowered or "geforce" in lowered or "rtx" in lowered or "quadro" in lowered:
        return "nvidia"
    if "amd" in lowered or "radeon" in lowered:
        return "amd"
    if "intel" in lowered or "arc" in lowered:
        return "intel"
    if "apple" in lowered:
        return "apple"
    return "other"


def _detect_gpu() -> tuple[str | None, int | None, bool]:
    """Return (name, vram_bytes, vram_is_estimate)."""
    nvidia = _nvidia_gpu()
    if nvidia:
        return nvidia[0], nvidia[1], False

    registry = _registry_gpu()
    if registry and registry[1]:
        return registry[0], registry[1], False

    wmi = _wmi_gpu()
    if wmi:
        # AdapterRAM caps at ~4 GB, so anything at the ceiling is a floor value.
        estimate = wmi[1] is not None and wmi[1] >= 4 * 1024**3 - 1024**2
        return wmi[0], wmi[1], estimate

    if registry:
        return registry[0], None, True
    return None, None, True


#: Message shown whenever this computer will refuse to load the engine.
APP_CONTROL_BLOCKER = (
    "Smart App Control is switched on for this computer, and it refuses to run software that is "
    "not digitally signed. The local AI engine PocketMind uses is published unsigned, so it "
    "cannot start here. Setting up your drive on a computer without Smart App Control will work, "
    "and the finished drive will then run anywhere that also has it switched off. You can turn it "
    "off under Windows Security, App & browser control, Smart App Control settings — but be aware "
    "Windows cannot switch it back on afterwards without reinstalling."
)


def app_control_state() -> str:
    """Is this computer enforcing a code-integrity policy?

    Smart App Control ships enabled on many new Windows 11 machines. It blocks
    unsigned binaries outright, which is worth discovering before downloading
    several gigabytes rather than after.
    """
    if not _IS_WINDOWS:
        return "off"
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SYSTEM\CurrentControlSet\Control\CI\Policy") as key:
            value, _ = winreg.QueryValueEx(key, "VerifiedAndReputablePolicyState")
    except OSError:
        return "off"
    return {0: "off", 1: "enforcing", 2: "evaluation"}.get(int(value), "unknown")


def _rate(ram_bytes: int, vram_bytes: int | None, cores: int | None) -> tuple[int, str, list[str]]:
    """Turn raw specs into a rating that describes rather than flatters."""
    ram_gb = ram_bytes / 1024**3
    vram_gb = (vram_bytes or 0) / 1024**3
    core_count = cores or 2
    notes: list[str] = []

    score = 0.0
    if ram_gb >= 32:
        score += 2.0
    elif ram_gb >= 16:
        score += 1.5
    elif ram_gb >= 8:
        score += 1.0
    else:
        score += 0.4
        notes.append(f"{ram_gb:.0f} GB of RAM limits you to smaller models.")

    if vram_gb >= 12:
        score += 2.0
        notes.append(f"{vram_gb:.0f} GB of video memory can hold a mid-size model entirely on the GPU.")
    elif vram_gb >= 8:
        score += 1.6
        notes.append(f"{vram_gb:.0f} GB of video memory will accelerate most small and mid-size models.")
    elif vram_gb >= 6:
        score += 1.2
    elif vram_gb >= 4:
        score += 0.8
    else:
        notes.append("No usable GPU memory was detected, so answers will be generated on the CPU.")

    if core_count >= 12:
        score += 1.0
    elif core_count >= 8:
        score += 0.8
    elif core_count >= 4:
        score += 0.5
    else:
        score += 0.2
        notes.append("Few CPU cores means slower responses when the GPU cannot be used.")

    stars = max(1, min(5, int(round(score))))
    labels = {
        1: "Basic — small models only",
        2: "Modest — small models run comfortably",
        3: "Capable — good for everyday assistant work",
        4: "Strong — mid-size models run well",
        5: "Excellent — large models are within reach",
    }
    return stars, labels[stars], notes


def inspect_hardware(*, refresh: bool = False) -> HardwareProfile:
    """Inspect the host. Cached, because probing shells out to PowerShell."""
    global _cached
    if _cached is not None and not refresh:
        # CPU, RAM and GPU do not change while PocketMind runs, but Smart App
        # Control does: a user who switches it off should not have to restart
        # to stop being told their model is blocked.
        _cached.app_control = app_control_state()
        _cached.app_control_blocks_engine = _cached.app_control == "enforcing"
        _cached.blockers = [APP_CONTROL_BLOCKER] if _cached.app_control_blocks_engine else []
        return _cached

    gpu_name, gpu_vram, vram_estimate = _detect_gpu()
    ram_bytes = psutil.virtual_memory().total
    physical = psutil.cpu_count(logical=False)
    logical = psutil.cpu_count(logical=True)
    stars, label, notes = _rate(ram_bytes, gpu_vram, physical or logical)
    if vram_estimate and gpu_vram:
        notes.append("Video memory could only be estimated; PocketMind will stay conservative when offloading.")

    control = app_control_state()
    blocked = control == "enforcing"
    blockers = [APP_CONTROL_BLOCKER] if blocked else []
    if blocked:
        log.warning("Smart App Control is enforcing; the inference engine will not be able to start")

    _cached = HardwareProfile(
        operating_system=f"{platform.system()} {platform.release()}".strip(),
        architecture=platform.machine() or "unknown",
        cpu_name=_cpu_name(),
        physical_cores=physical,
        logical_cores=logical,
        ram_bytes=ram_bytes,
        gpu_name=gpu_name,
        gpu_vram_bytes=gpu_vram,
        gpu_vendor=_vendor_of(gpu_name),
        vram_is_estimate=vram_estimate,
        performance_stars=stars,
        performance_label=label,
        performance_notes=notes,
        app_control=control,
        app_control_blocks_engine=blocked,
        blockers=blockers,
    )
    return _cached
