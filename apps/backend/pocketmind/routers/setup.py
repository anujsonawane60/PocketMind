"""Setup wizard: drives, hardware, model choice, and the installation job."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from pocketmind.schemas import (
    Drive,
    DriveReport,
    DriveSpeedRequest,
    HardwareProfile,
    InstallationSummary,
    InstallRequest,
    InstallStatus,
    JobState,
    ModelRecommendations,
    StorageBudget,
    StorageCheckRequest,
    UseCase,
)
from pocketmind.services import catalog, drives, hardware
from pocketmind.services.installer import InstallJob
from pocketmind.services.session import session
from pocketmind.services.vault import password_strength

router = APIRouter(prefix="/api/setup", tags=["setup"])


class RecommendationRequest(BaseModel):
    drive_id: str
    use_cases: list[UseCase] = Field(default_factory=list)
    bundle_portable_python: bool = True


class PasswordCheckRequest(BaseModel):
    password: str = Field(max_length=1024)


class OpenRequest(BaseModel):
    root: str


@router.get("/drives", response_model=list[Drive])
def list_drives() -> list[Drive]:
    """Every mounted volume, with internal and system drives marked ineligible."""
    return drives.list_drives()


@router.post("/drive-report", response_model=DriveReport)
def drive_report(request: DriveSpeedRequest) -> DriveReport:
    """Validate a chosen drive and measure its write speed (PRD sections 12, 58)."""
    drive = drives.get_drive(request.drive_id)
    if drive is None:
        raise HTTPException(404, "That drive is no longer connected. Reconnect it and rescan.")
    if not drive.is_eligible:
        raise HTTPException(400, drive.ineligible_reason or "This drive cannot be used for PocketMind.")
    return drives.build_report(drive)


@router.get("/hardware", response_model=HardwareProfile)
def inspect(refresh: bool = False) -> HardwareProfile:
    return hardware.inspect_hardware(refresh=refresh)


@router.post("/recommendations", response_model=ModelRecommendations)
def recommendations(request: RecommendationRequest) -> ModelRecommendations:
    """Hardware-aware model suggestions with the reasoning behind them."""
    drive = drives.get_eligible_drive(request.drive_id)
    if drive is None:
        raise HTTPException(400, "Select a connected removable drive or portable SSD first.")
    return catalog.recommend(
        hardware.inspect_hardware(),
        drive,
        set(request.use_cases),
        online=session.is_online(),
        bundle_portable_python=request.bundle_portable_python,
    )


@router.post("/storage-check", response_model=StorageBudget)
def storage_check(request: StorageCheckRequest) -> StorageBudget:
    drive = drives.get_eligible_drive(request.drive_id)
    if drive is None:
        raise HTTPException(400, "Select a connected removable drive or portable SSD first.")
    models, _, _ = catalog.resolve_catalog(online=session.is_online())
    model = next((item for item in models if item.id == request.model_id), None)
    if model is None:
        raise HTTPException(404, "Unknown model.")
    return catalog.build_budget(drive, model, bundle_portable_python=request.bundle_portable_python)


@router.post("/password-strength")
def check_password(request: PasswordCheckRequest) -> dict[str, object]:
    """Scored locally; the password is never stored or logged."""
    label, suggestions = password_strength(request.password)
    return {"label": label, "suggestions": suggestions, "long_enough": len(request.password) >= 12}


@router.post("/install", response_model=InstallStatus)
def install(request: InstallRequest) -> InstallStatus:
    """Start (or resume) the installation. All work happens in the background."""
    drive = drives.get_eligible_drive(request.drive_id)
    if drive is None:
        raise HTTPException(400, "That drive is not connected, or is not a drive PocketMind can install to.")

    entry = catalog.get_entry(request.model_id)
    if entry is None:
        raise HTTPException(404, "Unknown model.")
    if not request.accept_model_license:
        raise HTTPException(
            400, f"{entry.name} is distributed under the {entry.license}. Accept it before installing."
        )

    models, _, _ = catalog.resolve_catalog(online=session.is_online())
    model = next(item for item in models if item.id == request.model_id)
    budget = catalog.build_budget(drive, model, bundle_portable_python=request.bundle_portable_python)
    if not budget.is_sufficient:
        raise HTTPException(400, budget.message)

    profile = hardware.inspect_hardware()
    if profile.app_control_blocks_engine and not request.build_anyway:
        # Not a hard refusal: a drive built here still works elsewhere, so the
        # choice belongs to the user rather than to PocketMind.
        raise HTTPException(
            400,
            f"{hardware.APP_CONTROL_BLOCKER} PocketMind can still prepare this drive so it works on "
            "another computer — choose Prepare anyway to continue.",
        )

    existing = session.install_job
    if existing is not None and existing.status().state == JobState.RUNNING:
        raise HTTPException(409, "An installation is already running.")

    job = InstallJob(request, drive, profile)
    session.install_job = job
    job.start()
    return job.status()


@router.get("/install/status", response_model=InstallStatus)
def install_status() -> InstallStatus:
    job = session.install_job
    if job is None:
        return InstallStatus(state=JobState.IDLE, message="No installation has been started.")
    return job.status()


@router.post("/install/cancel", response_model=InstallStatus)
def cancel_install() -> InstallStatus:
    job = session.install_job
    if job is None:
        raise HTTPException(404, "No installation is running.")
    job.cancel()
    return job.status()


@router.post("/open", response_model=InstallationSummary)
def open_installation(request: OpenRequest) -> InstallationSummary:
    """Open a PocketMind drive and switch the application into assistant mode."""
    return session.bind(request.root)


@router.get("/installations", response_model=list[InstallationSummary])
def installations() -> list[InstallationSummary]:
    return session.discover()
