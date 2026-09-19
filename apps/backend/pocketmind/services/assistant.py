"""Prompt construction and memory handling.

Two rules from the PRD shape this module:

* Section 70 — the whole memory database is never injected into a prompt. Only
  passages and memories that match the question are retrieved, which keeps the
  context small and limits how much personal information the model ever sees.
* Section 30 — the secret vault is not reachable from here at all. There is no
  import of the vault module in this file, by design.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from pocketmind.logs import get_logger
from pocketmind.schemas import Settings
from pocketmind.services.data import PocketDatabase

log = get_logger("assistant")

_FALLBACK_PROMPT = (
    "You are PocketMind, a private assistant that runs entirely on the user's own computer from their "
    "USB drive. Use the memories and document passages you are given when they are relevant, and say so "
    "when they are not enough. Never invent personal details. You cannot read the user's secret vault."
)

# "Remember that I prefer FastAPI" and friends. Deliberately conservative: a
# false positive silently saves something the user did not mean to keep.
_EXPLICIT_MEMORY = re.compile(
    r"^\s*(?:please\s+)?(?:remember|note|keep in mind|don'?t forget)\s+(?:that\s+|this[:,]?\s+)?(?P<content>.+?)\s*$",
    re.IGNORECASE | re.DOTALL,
)

_CATEGORY_HINTS = (
    ("preferences", ("prefer", "favourite", "favorite", "i like", "i dislike", "i hate", "i always", "i never")),
    ("goals", ("goal", "want to", "plan to", "aiming", "by the end of", "i will")),
    ("projects", ("project", "building", "working on", "repo", "repository")),
    ("learning", ("learning", "studying", "course", "practising", "practicing", "revising")),
    ("work", ("work", "job", "client", "meeting", "manager", "team", "deadline")),
    ("relationships", ("my wife", "my husband", "my partner", "my friend", "my brother", "my sister", "my mother", "my father")),
)


@dataclass
class RetrievedContext:
    memories: list[dict] = field(default_factory=list)
    passages: list[dict] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)

    @property
    def is_empty(self) -> bool:
        return not self.memories and not self.passages


def load_profile(profile_path: Path) -> dict:
    try:
        return json.loads(profile_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def detect_memory_request(message: str) -> str | None:
    """Return the fact to save when the user explicitly asked to remember it."""
    if len(message) > 600:
        return None
    match = _EXPLICIT_MEMORY.match(message.strip())
    if not match:
        return None
    content = match.group("content").strip().strip('"').strip()
    # "remember" alone, or a question like "remember what I said?", is not a save.
    if len(content) < 4 or content.endswith("?"):
        return None
    return content[:2000]


def categorise(content: str) -> str:
    lowered = content.lower()
    for category, hints in _CATEGORY_HINTS:
        if any(hint in lowered for hint in hints):
            return category
    return "personal"


def retrieve(
    database: PocketDatabase,
    settings: Settings,
    question: str,
    *,
    use_memory: bool = True,
    use_documents: bool = True,
) -> RetrievedContext:
    """Fetch only what is relevant to this question."""
    context = RetrievedContext()

    if use_memory and settings.memory_enabled:
        context.memories = database.search_memories(question, limit=settings.memory_results)

    if use_documents and settings.documents_enabled:
        context.passages = database.search_chunks(question, limit=settings.retrieval_results)
        seen: set[str] = set()
        for passage in context.passages:
            name = str(passage["filename"])
            if name not in seen:
                seen.add(name)
                context.sources.append(name)

    log.info(
        "Retrieved %d memories and %d passages for a question", len(context.memories), len(context.passages)
    )
    return context


def build_messages(
    database: PocketDatabase,
    settings: Settings,
    profile: dict,
    conversation_id: int,
    question: str,
    context: RetrievedContext,
) -> list[dict[str, str]]:
    """Assemble the exact message list sent to the local model."""
    system = settings.system_prompt.strip() or _FALLBACK_PROMPT
    name = profile.get("display_name")
    if name and name not in system:
        system = f"{system}\nThe user's name is {name}."

    blocks = [system]

    if context.memories:
        remembered = "\n".join(
            f"- ({memory['category']}) {memory['content']}" for memory in context.memories
        )
        blocks.append(
            "Things the user has asked you to remember. Use them only when they are relevant:\n" + remembered
        )

    if context.passages:
        excerpts = "\n\n".join(
            f"[{passage['filename']} · passage {int(passage['ordinal']) + 1}]\n{passage['content']}"
            for passage in context.passages
        )
        blocks.append(
            "Passages from the user's own documents. Cite the file name when you use one, and say so if "
            "they do not contain the answer:\n" + excerpts
        )

    messages: list[dict[str, str]] = [{"role": "system", "content": "\n\n".join(blocks)}]
    messages.extend(database.recent_messages(conversation_id, limit=12))
    messages.append({"role": "user", "content": question})
    return messages


def title_for(message: str) -> str:
    """A readable conversation title from the opening message."""
    cleaned = " ".join(message.split())
    if len(cleaned) <= 60:
        return cleaned or "New conversation"
    cut = cleaned[:60].rsplit(" ", 1)[0]
    return f"{cut}…"
