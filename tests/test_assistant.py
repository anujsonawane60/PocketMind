"""Prompt construction and memory detection."""

from __future__ import annotations

import pytest

from pocketmind.schemas import Settings
from pocketmind.services import assistant
from pocketmind.services.data import PocketDatabase


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        ("Remember that I prefer FastAPI for backends.", "I prefer FastAPI for backends."),
        ("remember I am learning distributed systems", "I am learning distributed systems"),
        ("Please remember that my sister's birthday is in June.", "my sister's birthday is in June."),
        ("Note that the office moves in March.", "the office moves in March."),
    ],
)
def test_explicit_memory_requests_are_detected(message, expected):
    assert assistant.detect_memory_request(message) == expected


@pytest.mark.parametrize(
    "message",
    [
        "What do you remember about me?",
        "Do you remember what I said yesterday?",
        "remember",
        "I was trying to remember the name of that library we discussed last week, any ideas?",
    ],
)
def test_questions_and_noise_are_not_saved_as_memories(message):
    assert assistant.detect_memory_request(message) is None


@pytest.mark.parametrize(
    ("content", "category"),
    [
        ("I prefer dark mode everywhere.", "preferences"),
        ("My goal is to ship the beta by June.", "goals"),
        ("I am working on the PocketMind project.", "projects"),
        ("I am learning Rust this year.", "learning"),
        ("My partner is called Sam.", "relationships"),
        ("I was born in Pune.", "personal"),
    ],
)
def test_memories_are_categorised(content, category):
    assert assistant.categorise(content) == category


def test_retrieval_only_returns_relevant_memories(database: PocketDatabase):
    database.add_memory("I prefer FastAPI for backend projects.", "preferences")
    database.add_memory("My cat is called Biscuit.", "personal")
    database.add_memory("I am revising for a statistics exam.", "learning")

    context = assistant.retrieve(database, Settings(), "which backend framework do I like?")
    contents = [memory["content"] for memory in context.memories]
    assert any("FastAPI" in item for item in contents)
    assert not any("Biscuit" in item for item in contents)


def test_the_whole_memory_database_is_never_injected(database: PocketDatabase):
    """PRD section 70: retrieval, not a dump of everything."""
    for index in range(40):
        database.add_memory(f"Unrelated fact number {index} about gardening.", "personal")
    database.add_memory("I prefer Postgres over MySQL.", "preferences")

    settings = Settings(memory_results=5)
    context = assistant.retrieve(database, settings, "which database do I prefer?")
    assert len(context.memories) <= 5


def test_memory_can_be_turned_off(database: PocketDatabase):
    database.add_memory("I prefer FastAPI.", "preferences")
    context = assistant.retrieve(database, Settings(memory_enabled=False), "what do I prefer?")
    assert context.memories == []


def test_documents_can_be_turned_off(database: PocketDatabase):
    database.add_document("a.md", "hash", 10, ["FastAPI is a Python web framework."])
    context = assistant.retrieve(database, Settings(documents_enabled=False), "what is FastAPI?")
    assert context.passages == []


def test_prompt_contains_retrieved_context_and_history(database: PocketDatabase):
    conversation_id = database.create_conversation("Chat")
    database.add_message(conversation_id, "user", "Earlier question.")
    database.add_message(conversation_id, "assistant", "Earlier answer.")
    database.add_memory("I prefer FastAPI for backend projects.", "preferences")
    database.add_document("stack.md", "hash", 10, ["We deploy FastAPI services on Fly.io."])

    settings = Settings()
    context = assistant.retrieve(database, settings, "where do we deploy FastAPI?")
    messages = assistant.build_messages(
        database, settings, {"display_name": "Alex"}, conversation_id, "where do we deploy FastAPI?", context
    )

    assert messages[0]["role"] == "system"
    system = messages[0]["content"]
    assert "Alex" in system
    assert "FastAPI" in system
    assert "stack.md" in system
    assert messages[-1] == {"role": "user", "content": "where do we deploy FastAPI?"}
    assert {"role": "assistant", "content": "Earlier answer."} in messages


def test_the_vault_is_unreachable_from_prompt_construction():
    """A structural guarantee, not a runtime check: this module cannot read secrets."""
    source = (assistant.__file__)
    with open(source, encoding="utf-8") as handle:
        text = handle.read()
    assert "from pocketmind.services.vault" not in text
    assert "import vault" not in text


def test_conversation_titles_stay_readable():
    assert assistant.title_for("Hello there") == "Hello there"
    long_title = assistant.title_for("word " * 50)
    assert len(long_title) <= 61
    assert long_title.endswith("…")
