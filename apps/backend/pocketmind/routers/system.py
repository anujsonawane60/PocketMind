"""Application state, dashboard, settings, runtime control, model management."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from pocketmind import config
from pocketmind.logs import get_logger
from pocketmind.schemas import (
    AppState,
    Dashboard,
    ExportRequest,
    ModelInfo,
    RuntimeStatus,
    Settings,
)
from pocketmind.services import catalog
from pocketmind.services.session import session

log = get_logger("system")

router = APIRouter(prefix="/api", tags=["system"])


class ModelActionRequest(BaseModel):
    model_id: str


@router.get("/state", response_model=AppState)
def state() -> AppState:
    """What the interface should show: the wizard, or the assistant."""
    return session.state()


@router.get("/dashboard", response_model=Dashboard)
def dashboard() -> Dashboard:
    paths, database, _, _ = session.require()
    counts = database.counts()
    pocketmind_bytes, used, total = session.storage_usage()
    drive = session.drive()
    return Dashboard(
        display_name=session.profile.get("display_name"),
        model_name=session.runtime_status().model_name,
        runtime=session.runtime_status(),
        vault=session.vault_status(),
        network=session.network_status(),
        drive_id=drive.id if drive else Path(paths.root).drive.upper(),
        storage_used_bytes=used,
        storage_total_bytes=total,
        pocketmind_bytes=pocketmind_bytes,
        memory_count=counts["memories"],
        document_count=counts["documents"],
        conversation_count=counts["conversations"],
        message_count=counts["messages"],
    )


@router.get("/settings", response_model=Settings)
def get_settings() -> Settings:
    return session.settings()


@router.put("/settings", response_model=Settings)
def update_settings(settings: Settings) -> Settings:
    return session.save_settings(settings)


@router.post("/tutorial-seen")
def tutorial_seen() -> dict[str, str]:
    session.mark_tutorial_seen()
    return {"status": "saved"}


@router.post("/system/update-drive")
def update_drive() -> dict[str, str]:
    """Refresh the drive's copy of PocketMind from the build running now.

    Your data is never touched: only the application folder and the launcher
    are replaced (PRD section 52 — updates must not delete user data).
    """
    from pocketmind.services.installer import copy_application

    paths, _, _, _ = session.require()
    version, copied = copy_application(paths)
    if not copied:
        return {
            "status": "current",
            "version": version,
            "detail": (
                f"You are already running PocketMind {version} from this drive, so there is nothing "
                "to copy. To update it, run PocketMind from the repository checkout and use this "
                "button there."
            ),
        }
    return {
        "status": "updated",
        "version": version,
        "detail": "The drive now runs this version. Your memories, documents, and vault were not touched.",
    }


# -- runtime ---------------------------------------------------------------


@router.get("/runtime", response_model=RuntimeStatus)
def runtime_status() -> RuntimeStatus:
    return session.runtime_status()


@router.post("/runtime/start", response_model=RuntimeStatus)
def start_runtime(request: ModelActionRequest | None = None) -> RuntimeStatus:
    _, database, _, provider = session.require()
    settings = database.load_settings()
    return provider.start_runtime(
        request.model_id if request else None, context_length=settings.context_length
    )


@router.post("/runtime/stop", response_model=RuntimeStatus)
def stop_runtime() -> RuntimeStatus:
    _, _, _, provider = session.require()
    provider.stop_runtime()
    return provider.status()


# -- models ----------------------------------------------------------------


@router.get("/models", response_model=list[ModelInfo])
def models() -> list[ModelInfo]:
    """Everything installable, marked with what is already on this drive."""
    _, _, _, provider = session.require()
    return list(provider.discover_models(online=session.is_online()))


@router.post("/models/install")
def install_model(request: ModelActionRequest) -> dict[str, object]:
    """Add another model to the drive, if there is room for it."""
    paths, _, _, provider = session.require()
    entry = catalog.get_entry(request.model_id)
    if entry is None:
        raise HTTPException(404, "Unknown model.")

    drive = session.drive()
    if drive is None:
        raise HTTPException(410, "The PocketMind drive is no longer connected.")
    catalogue, _, _ = catalog.resolve_catalog(online=session.is_online())
    model = next(item for item in catalogue if item.id == request.model_id)
    if drive.free_bytes < model.download_size_bytes + config.RESERVE_BYTES:
        raise HTTPException(
            400,
            f"Not enough space. {entry.name} needs about "
            f"{model.download_size_bytes / 1024**3:.1f} GB plus free headroom.",
        )

    installed = provider.install_model(request.model_id)
    return {"status": "installed", "model": installed.name, "path": str(installed.path)}


@router.post("/models/default")
def set_default_model(request: ModelActionRequest) -> dict[str, str]:
    _, _, _, provider = session.require()
    provider.set_default_model(request.model_id)
    return {"status": "saved"}


@router.delete("/models/{model_id}")
def remove_model(model_id: str) -> dict[str, str]:
    _, _, _, provider = session.require()
    if len(provider.installed_models()) <= 1:
        raise HTTPException(400, "This is the only model on the drive. Install another one before removing it.")
    provider.remove_model(model_id)
    return {"status": "removed"}


# -- export ----------------------------------------------------------------


@router.post("/export")
def export(request: ExportRequest) -> dict[str, object]:
    """Write a readable export to the drive's backups folder (PRD section 40)."""
    paths, database, vault, _ = session.require()
    if not request.acknowledge_sensitive:
        raise HTTPException(
            400,
            "This export contains your personal memories and conversations in readable form. "
            "Confirm you understand before continuing.",
        )

    payload: dict[str, object] = {
        "exported_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "app_version": config.APP_VERSION,
        "profile": session.profile,
    }
    if request.include_memories:
        payload["memories"] = database.list_memories()
    if request.include_conversations:
        payload["conversations"] = [
            {**conversation, "messages": database.list_messages(int(conversation["id"]))}
            for conversation in database.list_conversations()
        ]
    if request.include_documents:
        payload["documents"] = database.list_documents()
    if request.include_vault_names:
        payload["vault"] = {
            "note": "Names only. Secret values are never exported in readable form.",
            "entry_count": vault.status().secret_count,
        }

    stamp = datetime.now(UTC).strftime("%Y-%m-%d-%H%M%S")
    destination = paths.backups / f"pocketmind-export-{stamp}.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    log.info("Wrote an export to the drive's backups folder")
    return {
        "status": "exported",
        "path": str(destination),
        "warning": "This file is not encrypted. Keep it on your drive or delete it when you are done.",
    }
