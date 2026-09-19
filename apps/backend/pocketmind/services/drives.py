"""Removable and external drive detection.

The safety invariant of the whole product lives here: a drive is only ever
offered as an installation target if the operating system says it is external
*and* it is not the drive Windows booted from. Nothing is inferred from drive
letters, and nothing is written to a drive before the user asks for it.
"""

from __future__ import annotations

import ctypes
import json
import os
import subprocess
import time
from pathlib import Path

import psutil

from pocketmind import config
from pocketmind.logs import get_logger
from pocketmind.schemas import Drive, DriveKind, DriveReport

log = get_logger("drives")

_IS_WINDOWS = os.name == "nt"

# GetDriveTypeW return values.
_DRIVE_TYPES = {
    2: DriveKind.REMOVABLE,
    3: DriveKind.FIXED,
    4: DriveKind.NETWORK,
    5: DriveKind.CDROM,
    6: DriveKind.RAMDISK,
}

# Bus types that mean "the user can unplug this". Portable SSDs report as a
# fixed disk over a USB bus, and the PRD explicitly recommends them, so bus
# type has to be consulted as well as drive type.
_EXTERNAL_BUS_TYPES = {"USB", "SD", "MMC", "1394", "Thunderbolt"}

_bus_cache: tuple[float, dict[str, dict[str, object]]] = (0.0, {})
_BUS_CACHE_SECONDS = 10.0


def _windows_drive_kind(mount_point: str) -> DriveKind:
    try:
        value = ctypes.windll.kernel32.GetDriveTypeW(ctypes.c_wchar_p(mount_point))  # type: ignore[attr-defined]
    except (AttributeError, OSError):
        return DriveKind.UNKNOWN
    return _DRIVE_TYPES.get(value, DriveKind.UNKNOWN)


def _windows_volume_info(mount_point: str) -> tuple[str | None, str | None]:
    """Return (volume label, volume serial) for a mounted Windows volume."""
    if not _IS_WINDOWS:
        return None, None
    name = ctypes.create_unicode_buffer(261)
    filesystem = ctypes.create_unicode_buffer(261)
    serial = ctypes.c_ulong(0)
    component = ctypes.c_ulong(0)
    flags = ctypes.c_ulong(0)
    try:
        ok = ctypes.windll.kernel32.GetVolumeInformationW(  # type: ignore[attr-defined]
            ctypes.c_wchar_p(mount_point),
            name,
            ctypes.sizeof(name) // ctypes.sizeof(ctypes.c_wchar),
            ctypes.byref(serial),
            ctypes.byref(component),
            ctypes.byref(flags),
            filesystem,
            ctypes.sizeof(filesystem) // ctypes.sizeof(ctypes.c_wchar),
        )
    except (AttributeError, OSError):
        return None, None
    if not ok:
        return None, None
    return (name.value or None), f"{serial.value:08X}"


def _bus_types() -> dict[str, dict[str, object]]:
    """Map drive letter -> {bus_type, is_boot, is_system}, via the Storage module.

    Best effort. If PowerShell is unavailable or slow the map comes back empty
    and callers fall back to GetDriveTypeW alone, which is more conservative.
    """
    global _bus_cache
    cached_at, cached = _bus_cache
    now = time.monotonic()
    if cached and now - cached_at < _BUS_CACHE_SECONDS:
        return cached
    if not _IS_WINDOWS:
        return {}

    script = (
        "Get-Disk | ForEach-Object { $d = $_; "
        "Get-Partition -DiskNumber $d.Number -ErrorAction SilentlyContinue | "
        "Where-Object { $_.DriveLetter } | ForEach-Object { "
        "[pscustomobject]@{ Letter = [string]$_.DriveLetter; Bus = [string]$d.BusType; "
        "Boot = [bool]$d.IsBoot; Sys = [bool]$d.IsSystem } } } | ConvertTo-Json -Compress"
    )
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True,
            text=True,
            timeout=12,
            check=True,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        parsed = json.loads(result.stdout or "[]")
    except (OSError, subprocess.SubprocessError, ValueError) as exc:
        log.debug("Bus type lookup unavailable: %s", exc.__class__.__name__)
        _bus_cache = (now, {})
        return {}

    rows = parsed if isinstance(parsed, list) else [parsed]
    table: dict[str, dict[str, object]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        letter = str(row.get("Letter") or "").strip().upper()
        if not letter:
            continue
        table[f"{letter}:"] = {
            "bus_type": str(row.get("Bus") or "") or None,
            "is_boot": bool(row.get("Boot")),
            "is_system": bool(row.get("Sys")),
        }
    _bus_cache = (now, table)
    return table


def _system_drive_id() -> str:
    return Path(os.environ.get("SystemDrive", "C:") + "\\").drive.upper() or "C:"


def list_drives() -> list[Drive]:
    """Every mounted volume, annotated with whether it may be used."""
    system_drive = _system_drive_id()
    buses = _bus_types()
    drives: list[Drive] = []

    for partition in psutil.disk_partitions(all=False):
        mount = partition.mountpoint
        try:
            usage = psutil.disk_usage(mount)
        except OSError:
            # Card readers with no card inserted land here.
            continue

        identifier = Path(mount).drive.upper() or mount
        kind = _windows_drive_kind(mount) if _IS_WINDOWS else DriveKind.UNKNOWN
        label, serial = _windows_volume_info(mount)
        bus = buses.get(identifier, {})
        bus_type = bus.get("bus_type")
        is_system = identifier == system_drive or bool(bus.get("is_boot")) or bool(bus.get("is_system"))
        is_external = kind == DriveKind.REMOVABLE or (bus_type in _EXTERNAL_BUS_TYPES)

        reason: str | None = None
        if is_system:
            reason = "This is the drive your computer starts from. PocketMind never installs here."
        elif kind in (DriveKind.CDROM, DriveKind.NETWORK, DriveKind.RAMDISK):
            reason = "PocketMind needs a drive it can write to and you can unplug."
        elif not is_external:
            reason = "This looks like an internal drive. Connect a USB drive or portable SSD."

        drives.append(
            Drive(
                id=identifier,
                mount_point=mount,
                label=label,
                filesystem=partition.fstype or None,
                kind=kind,
                total_bytes=usage.total,
                free_bytes=usage.free,
                used_bytes=usage.used,
                is_system_drive=is_system,
                volume_serial=serial,
                bus_type=bus_type,
                is_external=is_external,
                is_eligible=reason is None,
                ineligible_reason=reason,
                has_pocketmind=config.InstallPaths.for_mount(mount).config_file.exists(),
            )
        )

    return sorted(drives, key=lambda drive: (not drive.is_eligible, drive.id))


def get_drive(drive_id: str) -> Drive | None:
    return next((drive for drive in list_drives() if drive.id == drive_id), None)


def get_eligible_drive(drive_id: str) -> Drive | None:
    """The only lookup installation code is allowed to use."""
    drive = get_drive(drive_id)
    return drive if drive and drive.is_eligible else None


def find_installations() -> list[Drive]:
    """Connected drives that already contain a PocketMind installation."""
    return [drive for drive in list_drives() if drive.has_pocketmind]


def describe_existing_data(drive: Drive) -> tuple[bool, list[str]]:
    """List what is already on the drive, without reading any file content."""
    try:
        entries = sorted(
            entry.name
            for entry in Path(drive.mount_point).iterdir()
            if not entry.name.startswith("$") and entry.name.lower() != "system volume information"
        )
    except OSError:
        return False, []
    return bool(entries), entries[:25]


def measure_write_speed(drive: Drive, *, sample_bytes: int = 8 * 1024**2) -> float | None:
    """Time an 8 MB write so slow drives can be flagged before installation.

    The sample file is created inside the PocketMind folder and deleted again.
    This is the only write PocketMind performs before the user starts setup,
    and the UI discloses it.
    """
    target_dir = config.InstallPaths.for_mount(drive.mount_point).root
    probe = target_dir / ".pocketmind-speed-probe"
    payload = b"\0" * (1024**2)
    try:
        target_dir.mkdir(parents=True, exist_ok=True)
        started = time.perf_counter()
        with probe.open("wb") as handle:
            for _ in range(sample_bytes // len(payload)):
                handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        elapsed = time.perf_counter() - started
    except OSError as exc:
        log.warning("Write speed probe failed on %s: %s", drive.id, exc.__class__.__name__)
        return None
    finally:
        probe.unlink(missing_ok=True)
        try:
            # Leave no trace if we created the folder purely for the probe.
            target_dir.rmdir()
        except OSError:
            pass

    if elapsed <= 0:
        return None
    return round((sample_bytes / 1024**2) / elapsed, 1)


def build_report(drive: Drive, *, measure_speed: bool = True) -> DriveReport:
    has_data, entries = describe_existing_data(drive)
    speed = measure_write_speed(drive) if measure_speed else None
    is_slow = speed is not None and speed < config.SLOW_DRIVE_MB_PER_SECOND

    warnings: list[str] = []
    if drive.has_pocketmind:
        warnings.append("This drive already contains PocketMind. Continuing will reuse and update that installation.")
    elif has_data:
        warnings.append(
            "This drive already contains other files. PocketMind will not touch them; "
            "it only creates its own PocketMind folder."
        )
    if is_slow:
        warnings.append(
            f"Slow storage detected ({speed} MB/s). PocketMind will work, but the model will take "
            "longer to load. A USB 3.x drive or portable SSD is recommended."
        )
    if drive.filesystem and drive.filesystem.upper() in {"FAT32", "MSDOS"}:
        warnings.append(
            "This drive uses FAT32, which cannot hold a single file larger than 4 GB. "
            "Only smaller models will fit. Reformatting to exFAT or NTFS removes the limit."
        )

    status = "Ready" if drive.is_eligible else (drive.ineligible_reason or "Not usable")
    return DriveReport(
        drive=drive,
        has_existing_data=has_data,
        existing_entries=entries,
        has_pocketmind=drive.has_pocketmind,
        write_speed_mb_per_second=speed,
        is_slow=is_slow,
        warnings=warnings,
        status=status,
    )
