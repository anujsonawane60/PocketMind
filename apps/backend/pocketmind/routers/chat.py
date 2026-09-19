"""Conversations and chat, including token-by-token streaming."""

from __future__ import annotations

import json
from collections.abc import Iterator

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from pocketmind.logs import describe, get_logger
from pocketmind.providers.base import RuntimeError_
from pocketmind.schemas import (
    ChatRequest,
    Conversation,
    ConversationRenameRequest,
    Message,
)
from pocketmind.services import assistant
from pocketmind.services.session import session

log = get_logger("chat")

router = APIRouter(prefix="/api", tags=["chat"])


@router.get("/conversations", response_model=list[Conversation])
def list_conversations() -> list[Conversation]:
    _, database, _, _ = session.require()
    return [Conversation(**row) for row in database.list_conversations()]


@router.get("/conversations/search")
def search_conversations(q: str) -> list[dict]:
    _, database, _, _ = session.require()
    return database.search_conversations(q)


@router.get("/conversations/{conversation_id}/messages", response_model=list[Message])
def list_messages(conversation_id: int) -> list[Message]:
    _, database, _, _ = session.require()
    if database.get_conversation(conversation_id) is None:
        raise HTTPException(404, "That conversation no longer exists.")
    return [Message(**row) for row in database.list_messages(conversation_id)]


@router.patch("/conversations/{conversation_id}")
def rename_conversation(conversation_id: int, request: ConversationRenameRequest) -> dict[str, str]:
    _, database, _, _ = session.require()
    if not database.rename_conversation(conversation_id, request.title):
        raise HTTPException(404, "That conversation no longer exists.")
    return {"status": "renamed"}


@router.delete("/conversations/{conversation_id}")
def delete_conversation(conversation_id: int) -> dict[str, str]:
    _, database, _, _ = session.require()
    if not database.delete_conversation(conversation_id):
        raise HTTPException(404, "That conversation no longer exists.")
    return {"status": "deleted"}


def _prepare(request: ChatRequest):
    """Shared setup for both chat endpoints."""
    paths, database, _, provider = session.require()
    settings = database.load_settings()

    conversation_id = request.conversation_id
    if conversation_id is None or database.get_conversation(conversation_id) is None:
        conversation_id = database.create_conversation(assistant.title_for(request.message))

    saved_memory: str | None = None
    if settings.memory_enabled and settings.auto_memory:
        candidate = assistant.detect_memory_request(request.message)
        if candidate:
            database.add_memory(candidate, assistant.categorise(candidate), importance=4)
            saved_memory = candidate

    context = assistant.retrieve(
        database,
        settings,
        request.message,
        use_memory=request.use_memory,
        use_documents=request.use_documents,
    )
    messages = assistant.build_messages(
        database, settings, session.profile, conversation_id, request.message, context
    )
    database.add_message(conversation_id, "user", request.message)
    log.info("Answering a message of %s in conversation %d", describe(request.message), conversation_id)
    return database, provider, settings, conversation_id, messages, context, saved_memory


@router.post("/chat")
def chat(request: ChatRequest) -> dict[str, object]:
    """Non-streaming reply, kept for scripting and for the API docs."""
    database, provider, settings, conversation_id, messages, context, saved = _prepare(request)
    answer = provider.chat(messages, temperature=settings.temperature, max_tokens=settings.max_tokens)
    database.add_message(conversation_id, "assistant", answer, context.sources)
    return {
        "conversation_id": conversation_id,
        "answer": answer,
        "sources": context.sources,
        "saved_memory": saved,
    }


def _event(name: str, payload: dict) -> str:
    return f"event: {name}\ndata: {json.dumps(payload)}\n\n"


@router.post("/chat/stream")
def chat_stream(request: ChatRequest) -> StreamingResponse:
    """Server-sent events so answers appear as they are generated."""
    database, provider, settings, conversation_id, messages, context, saved = _prepare(request)

    def events() -> Iterator[str]:
        yield _event(
            "start",
            {
                "conversation_id": conversation_id,
                "sources": context.sources,
                "memories_used": len(context.memories),
                "saved_memory": saved,
            },
        )
        pieces: list[str] = []
        try:
            for piece in provider.stream_chat(
                messages, temperature=settings.temperature, max_tokens=settings.max_tokens
            ):
                pieces.append(piece)
                yield _event("token", {"text": piece})
        except RuntimeError_ as exc:
            yield _event("error", {"detail": str(exc), "hint": getattr(exc, "hint", "")})
            return
        except Exception as exc:  # noqa: BLE001 - surfaced to the user, not swallowed
            log.exception("Streaming failed")
            yield _event("error", {"detail": f"The local model stopped unexpectedly ({exc.__class__.__name__})."})
            return

        answer = "".join(pieces)
        if answer.strip():
            database.add_message(conversation_id, "assistant", answer, context.sources)
        yield _event("done", {"conversation_id": conversation_id, "sources": context.sources})

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
