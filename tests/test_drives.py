"""The product's central safety rule: nothing installs to an internal drive."""

from __future__ import annotations

import pytest

from pocketmind.schemas import Drive, DriveKind
from pocketmind.services import drives


def make_drive(**overrides) -> Drive:
    defaults = dict(
        id="E:",
        mount_point="E:\\",
        label="PORTABLE",
        filesystem="exFAT",
        kind=DriveKind.REMOVABLE,
        total_bytes=32 * 1024**3,
        free_bytes=30 * 1024**3,
        used_bytes=2 * 1024**3,
        is_system_drive=False,
        volume_serial="AABBCCDD",
        bus_type="USB",
        is_external=True,
        is_eligible=True,
        ineligible_reason=None,
        has_pocketmind=False,
    )
    return Drive(**{**defaults, **overrides})


@pytest.fixture
def fake_drives(monkeypatch):
    listing = [
        make_drive(id="C:", mount_point="C:\\", kind=DriveKind.FIXED, bus_type="NVMe",
                   is_external=False, is_system_drive=True, is_eligible=False,
                   ineligible_reason="This is the drive your computer starts from."),
        make_drive(id="D:", mount_point="D:\\", kind=DriveKind.FIXED, bus_type="SATA",
                   is_external=False, is_eligible=False, ineligible_reason="This looks like an internal drive."),
        make_drive(id="E:"),
        make_drive(id="F:", mount_point="F:\\", kind=DriveKind.FIXED, bus_type="USB", is_external=True),
        make_drive(id="Z:", mount_point="Z:\\", kind=DriveKind.NETWORK, bus_type=None,
                   is_external=False, is_eligible=False, ineligible_reason="PocketMind needs a drive it can write to."),
    ]
    monkeypatch.setattr(drives, "list_drives", lambda: listing)
    return listing


def test_system_drive_is_never_eligible(fake_drives):
    assert drives.get_eligible_drive("C:") is None


def test_internal_drive_is_never_eligible(fake_drives):
    assert drives.get_eligible_drive("D:") is None


def test_network_drive_is_never_eligible(fake_drives):
    assert drives.get_eligible_drive("Z:") is None


def test_removable_drive_is_eligible(fake_drives):
    drive = drives.get_eligible_drive("E:")
    assert drive is not None and drive.id == "E:"


def test_portable_ssd_over_usb_is_eligible(fake_drives):
    """Portable SSDs report as fixed disks; bus type is what makes them usable."""
    drive = drives.get_eligible_drive("F:")
    assert drive is not None and drive.kind == DriveKind.FIXED


def test_unknown_drive_id_is_rejected(fake_drives):
    assert drives.get_eligible_drive("Q:") is None


def test_real_listing_never_marks_the_system_drive_eligible():
    """Runs against the actual machine — a regression guard on the real code path."""
    for drive in drives.list_drives():
        if drive.is_system_drive:
            assert not drive.is_eligible
            assert drive.ineligible_reason


def test_report_warns_about_fat32(fake_drives, monkeypatch):
    monkeypatch.setattr(drives, "measure_write_speed", lambda drive, **kwargs: 120.0)
    monkeypatch.setattr(drives, "describe_existing_data", lambda drive: (False, []))
    report = drives.build_report(make_drive(filesystem="FAT32"))
    assert any("4 GB" in warning for warning in report.warnings)


def test_report_warns_about_slow_storage(fake_drives, monkeypatch):
    monkeypatch.setattr(drives, "measure_write_speed", lambda drive, **kwargs: 6.5)
    monkeypatch.setattr(drives, "describe_existing_data", lambda drive: (False, []))
    report = drives.build_report(make_drive())
    assert report.is_slow
    assert any("Slow storage" in warning for warning in report.warnings)


def test_report_mentions_existing_files_without_offering_to_delete_them(fake_drives, monkeypatch):
    monkeypatch.setattr(drives, "measure_write_speed", lambda drive, **kwargs: 90.0)
    monkeypatch.setattr(drives, "describe_existing_data", lambda drive: (True, ["holiday.jpg", "tax.pdf"]))
    report = drives.build_report(make_drive())
    assert report.has_existing_data
    combined = " ".join(report.warnings).lower()
    assert "will not touch them" in combined
    assert "format" not in combined and "erase" not in combined
