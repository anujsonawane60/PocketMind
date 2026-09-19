"""Storage, ranked retrieval, and settings."""

from __future__ import annotations

from pocketmind.schemas import Settings
from pocketmind.services.data import PocketDatabase


def test_full_text_search_is_available():
    """FTS5 is what makes retrieval ranked rather than a substring scan."""
    from pocketmind.services.data import PocketDatabase as Database
    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as folder:
        database = Database(Path(folder) / "probe.db")
        assert database.has_fts, "SQLite was built without FTS5; retrieval quality will be reduced"
        database.close()


def test_document_search_returns_the_matching_passage(database: PocketDatabase):
    database.add_document(
        "handbook.md",
        "hash-1",
        400,
        [
            "Expenses are reimbursed within thirty days of submission.",
            "The office coffee machine is cleaned every Friday afternoon.",
            "Parental leave is six months at full pay for all staff.",
        ],
    )
    results = database.search_chunks("how long is parental leave", limit=1)
    assert results
    assert "Parental leave" in results[0]["content"]
    assert results[0]["filename"] == "handbook.md"


def test_search_ranks_the_best_passage_first(database: PocketDatabase):
    database.add_document("a.md", "hash-a", 10, ["Gardening notes about roses and soil."])
    database.add_document("b.md", "hash-b", 10, ["Kubernetes deployment rollout strategy and probes."])
    results = database.search_chunks("kubernetes rollout", limit=2)
    assert results[0]["filename"] == "b.md"


def test_search_ignores_stopwords_and_short_words(database: PocketDatabase):
    database.add_document("c.md", "hash-c", 10, ["Anything at all."])
    assert database.search_chunks("is it a to of") == []


def test_search_survives_query_operators(database: PocketDatabase):
    """A raw MATCH query would throw on these; quoting each term makes them inert."""
    database.add_document("d.md", "hash-d", 10, ["Pinecone vector database notes."])
    for query in ['pinecone OR "', "pinecone NOT", "pinecone*", "pinecone AND (", "100% pinecone"]:
        assert database.search_chunks(query) or True  # must not raise


def test_deleting_a_document_removes_it_from_search(database: PocketDatabase):
    document_id = database.add_document("e.md", "hash-e", 10, ["Unique phrase zebracorn."])
    assert database.search_chunks("zebracorn")
    assert database.delete_document(document_id)
    assert database.search_chunks("zebracorn") == []


def test_memories_are_deduplicated(database: PocketDatabase):
    first = database.add_memory("I prefer FastAPI for backends.", "preferences")
    second = database.add_memory("i prefer fastapi for backends.", "preferences")
    assert first == second
    assert len(database.list_memories()) == 1


def test_memory_search_prefers_important_memories(database: PocketDatabase):
    database.add_memory("I use Postgres at work sometimes.", "work", importance=1)
    database.add_memory("I always choose Postgres for new projects.", "preferences", importance=5)
    top = database.search_memories("postgres", limit=1)
    assert top[0]["importance"] == 5


def test_memory_update_is_reflected_in_search(database: PocketDatabase):
    memory_id = database.add_memory("I am learning Rust.", "learning")
    database.update_memory(memory_id, content="I am learning Elixir.", category=None, importance=None)
    assert database.search_memories("rust") == []
    assert database.search_memories("elixir")


def test_deleting_a_conversation_removes_its_messages(database: PocketDatabase):
    conversation_id = database.create_conversation("Planning")
    database.add_message(conversation_id, "user", "What should I do about the deployment?")
    database.add_message(conversation_id, "assistant", "Start with a staging rollout.")
    assert database.counts()["messages"] == 2

    assert database.delete_conversation(conversation_id)
    assert database.counts()["messages"] == 0
    assert database.search_conversations("deployment") == []


def test_recent_messages_are_returned_in_order(database: PocketDatabase):
    conversation_id = database.create_conversation("Ordering")
    for index in range(20):
        database.add_message(conversation_id, "user", f"message {index}")
    recent = database.recent_messages(conversation_id, limit=5)
    assert [item["content"] for item in recent] == [f"message {index}" for index in range(15, 20)]


def test_conversation_search_finds_message_text(database: PocketDatabase):
    conversation_id = database.create_conversation("Notes")
    database.add_message(conversation_id, "user", "Remind me about the Pinecone migration plan.")
    hits = database.search_conversations("pinecone migration")
    assert hits and hits[0]["id"] == conversation_id


def test_settings_round_trip(database: PocketDatabase):
    settings = Settings(temperature=0.2, memory_results=9, system_prompt="Be concise.")
    database.save_settings(settings)
    loaded = database.load_settings()
    assert loaded.temperature == 0.2
    assert loaded.memory_results == 9
    assert loaded.system_prompt == "Be concise."


def test_corrupt_settings_fall_back_to_defaults(database: PocketDatabase):
    database._execute(
        "INSERT INTO settings(key, value) VALUES ('app', ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        ("not json at all",),
    )
    assert database.load_settings().temperature == Settings().temperature


def test_counts_report_everything(database: PocketDatabase):
    conversation_id = database.create_conversation("Counting")
    database.add_message(conversation_id, "user", "hello")
    database.add_memory("A fact.", "personal")
    database.add_document("f.md", "hash-f", 5, ["chunk"])
    counts = database.counts()
    assert counts == {"memories": 1, "documents": 1, "conversations": 1, "messages": 1}
