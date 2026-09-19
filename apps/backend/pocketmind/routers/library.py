"""Memories, documents, and the 'what do you know about me?' view."""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, UploadFile

from pocketmind import config
from pocketmind.logs import get_logger
from pocketmind.schemas import (
    Document,
    FolderImportRequest,
    KnowledgeSummary,
    Memory,
    MemoryRequest,
    MemoryUpdate,
)
from pocketmind.services import rag
from pocketmind.services.session import session

log = get_logger("library")

router = APIRouter(prefix="/api", tags=["library"])


# -- memories --------------------------------------------------------------


@router.get("/memories", response_model=list[Memory])
def list_memories(category: str | None = None) -> list[Memory]:
    _, database, _, _ = session.require()
    return [Memory(**row) for row in database.list_memories(category)]


@router.get("/memories/search", response_model=list[Memory])
def search_memories(q: str, limit: int = 10) -> list[Memory]:
    _, database, _, _ = session.require()
    ids = [row["id"] for row in database.search_memories(q, limit=limit)]
    lookup = {row["id"]: row for row in database.list_memories()}
    return [Memory(**lookup[identifier]) for identifier in ids if identifier in lookup]


@router.post("/memories", response_model=Memory, status_code=201)
def add_memory(request: MemoryRequest) -> Memory:
    _, database, _, _ = session.require()
    memory_id = database.add_memory(request.content, request.category, request.importance)
    row = next((item for item in database.list_memories() if item["id"] == memory_id), None)
    if row is None:  # pragma: no cover - the insert just succeeded
        raise HTTPException(500, "The memory could not be saved.")
    return Memory(**row)


@router.patch("/memories/{memory_id}")
def update_memory(memory_id: int, request: MemoryUpdate) -> dict[str, str]:
    _, database, _, _ = session.require()
    if not database.update_memory(
        memory_id, content=request.content, category=request.category, importance=request.importance
    ):
        raise HTTPException(404, "That memory no longer exists.")
    return {"status": "updated"}


@router.delete("/memories/{memory_id}")
def delete_memory(memory_id: int) -> dict[str, str]:
    _, database, _, _ = session.require()
    if not database.delete_memory(memory_id):
        raise HTTPException(404, "That memory no longer exists.")
    return {"status": "deleted"}


# -- documents -------------------------------------------------------------


@router.get("/documents", response_model=list[Document])
def list_documents() -> list[Document]:
    _, database, _, _ = session.require()
    return [Document(**row) for row in database.list_documents()]


@router.post("/documents", status_code=201)
async def upload_document(file: UploadFile = File(...)) -> dict[str, object]:
    """Index one uploaded file. The bytes never leave this computer."""
    _, database, _, _ = session.require()
    settings = database.load_settings()
    filename = Path(file.filename or "untitled").name

    if Path(filename).suffix.lower() not in rag.SUPPORTED_SUFFIXES:
        raise HTTPException(
            400,
            f"PocketMind cannot read this file type yet. Supported: "
            f"{', '.join(sorted(rag.SUPPORTED_SUFFIXES))}",
        )

    data = bytearray()
    while chunk := await file.read(1024 * 1024):
        data.extend(chunk)
        if len(data) > config.MAX_UPLOAD_BYTES:
            raise HTTPException(
                413, f"That file is larger than the {config.MAX_UPLOAD_BYTES // 1024**2} MB limit for uploads."
            )
    if not data:
        raise HTTPException(400, "That file is empty.")

    try:
        result = rag.ingest(
            database,
            filename,
            bytes(data),
            chunk_size=settings.chunk_size,
            chunk_overlap=settings.chunk_overlap,
        )
    except rag.UnsupportedDocument as exc:
        raise HTTPException(400, str(exc)) from exc

    return {
        "status": "skipped" if result.document_id is None else "indexed",
        "filename": result.filename,
        "chunks": result.chunk_count,
        "detail": result.skipped_reason,
    }


@router.post("/documents/import-folder")
def import_folder(request: FolderImportRequest) -> dict[str, object]:
    """Index a folder from this computer into the drive's knowledge base."""
    _, database, _, _ = session.require()
    settings = database.load_settings()
    folder = Path(request.folder).expanduser()
    try:
        results = rag.import_folder(
            database,
            folder,
            recursive=request.recursive,
            chunk_size=settings.chunk_size,
            chunk_overlap=settings.chunk_overlap,
        )
    except FileNotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc

    indexed = [item for item in results if item.document_id is not None]
    skipped = [item for item in results if item.document_id is None]
    return {
        "indexed": len(indexed),
        "skipped": len(skipped),
        "passages": sum(item.chunk_count for item in indexed),
        "files": [item.filename for item in indexed][:100],
        "skipped_files": [{"filename": item.filename, "reason": item.skipped_reason} for item in skipped][:50],
    }


@router.delete("/documents/{document_id}")
def delete_document(document_id: int) -> dict[str, str]:
    _, database, _, _ = session.require()
    if not database.delete_document(document_id):
        raise HTTPException(404, "That document is no longer in your knowledge base.")
    return {"status": "deleted"}


# -- transparency ----------------------------------------------------------


@router.get("/knowledge", response_model=KnowledgeSummary)
def knowledge() -> KnowledgeSummary:
    """Everything PocketMind holds about the user, grouped for review (PRD 73)."""
    _, database, vault, _ = session.require()
    grouped: dict[str, list[Memory]] = defaultdict(list)
    for row in database.list_memories():
        grouped[row["category"]].append(Memory(**row))

    return KnowledgeSummary(
        display_name=session.profile.get("display_name"),
        use_cases=list(session.profile.get("use_cases") or []),
        memories_by_category=dict(grouped),
        documents=[Document(**row) for row in database.list_documents()],
        conversation_count=database.counts()["conversations"],
        vault_entry_count=vault.status().secret_count,
        note=(
            "Everything listed here is stored on your drive and can be deleted from this screen. "
            "Vault contents are never shown to the assistant and are not included above."
        ),
    )
