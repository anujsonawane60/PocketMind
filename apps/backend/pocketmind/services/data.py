"""SQLite storage for conversations, memories, documents, and settings.

The database file lives on the PocketMind drive, never on the host. One
connection is opened for the life of the application and closed on shutdown so
the drive can be ejected safely; every statement runs under a lock because
FastAPI serves requests from a thread pool.

Retrieval uses SQLite's FTS5 index with BM25 ranking rather than a LIKE scan,
so results are ranked by relevance and long documents do not drown short ones.
"""

from __future__ import annotations

import json
import re
import sqlite3
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pocketmind.logs import get_logger
from pocketmind.schemas import Settings

log = get_logger("data")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS conversations (
    id          INTEGER PRIMARY KEY,
    title       TEXT NOT NULL,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS messages (
    id              INTEGER PRIMARY KEY,
    conversation_id INTEGER NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    role            TEXT NOT NULL,
    content         TEXT NOT NULL,
    sources         TEXT NOT NULL DEFAULT '[]',
    created_at      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_messages_conversation ON messages(conversation_id, id);

CREATE TABLE IF NOT EXISTS memories (
    id          INTEGER PRIMARY KEY,
    category    TEXT NOT NULL,
    content     TEXT NOT NULL,
    importance  INTEGER NOT NULL DEFAULT 3,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS documents (
    id           INTEGER PRIMARY KEY,
    filename     TEXT NOT NULL,
    source_path  TEXT,
    sha256       TEXT NOT NULL UNIQUE,
    byte_size    INTEGER NOT NULL,
    status       TEXT NOT NULL DEFAULT 'indexed',
    indexed_at   TEXT,
    created_at   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS chunks (
    id          INTEGER PRIMARY KEY,
    document_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    ordinal     INTEGER NOT NULL,
    content     TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_chunks_document ON chunks(document_id, ordinal);

CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""

_FTS_SCHEMA = """
CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(content, tokenize='porter unicode61');
CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts USING fts5(content, tokenize='porter unicode61');
CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts USING fts5(content, tokenize='porter unicode61');
"""

_TOKEN = re.compile(r"[\w']+", re.UNICODE)
_STOPWORDS = frozenset(
    "a an and are as at be but by for from has have i if in is it its me my of on or our so that "
    "the their them there they this to was we were what when where which who will with you your".split()
)


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _match_query(text: str, *, limit_terms: int = 12) -> str | None:
    """Turn free text into a safe FTS5 MATCH expression.

    Quoting each term makes operator characters in user input inert, which is
    both a correctness fix and the reason a message containing a bare ``*`` or
    ``NOT`` cannot break search.
    """
    terms = [
        token.lower()
        for token in _TOKEN.findall(text)
        if len(token) > 2 and token.lower() not in _STOPWORDS
    ]
    if not terms:
        return None
    unique = list(dict.fromkeys(terms))[:limit_terms]
    return " OR ".join(f'"{term}"' for term in unique)


class PocketDatabase:
    """All local data for one PocketMind installation."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._connection = sqlite3.connect(self.path, check_same_thread=False)
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA foreign_keys = ON")
        self._connection.execute("PRAGMA journal_mode = WAL")
        self._connection.execute("PRAGMA synchronous = NORMAL")
        self.has_fts = self._initialise()

    # -- lifecycle ---------------------------------------------------------

    def _initialise(self) -> bool:
        with self._lock:
            self._connection.executescript(_SCHEMA)
            try:
                self._connection.executescript(_FTS_SCHEMA)
            except sqlite3.OperationalError as exc:
                log.warning("Full-text search is unavailable (%s); falling back to substring search", exc)
                return False
            self._connection.commit()
            return True

    def close(self) -> None:
        with self._lock:
            try:
                self._connection.commit()
            except sqlite3.Error:
                pass
            self._connection.close()

    def _execute(self, sql: str, params: tuple = ()) -> sqlite3.Cursor:
        with self._lock:
            cursor = self._connection.execute(sql, params)
            self._connection.commit()
            return cursor

    def _query(self, sql: str, params: tuple = ()) -> list[sqlite3.Row]:
        with self._lock:
            return self._connection.execute(sql, params).fetchall()

    # -- conversations -----------------------------------------------------

    def create_conversation(self, title: str) -> int:
        stamp = _now()
        cursor = self._execute(
            "INSERT INTO conversations(title, created_at, updated_at) VALUES (?, ?, ?)",
            (title.strip()[:120] or "New conversation", stamp, stamp),
        )
        return int(cursor.lastrowid or 0)

    def list_conversations(self) -> list[dict[str, Any]]:
        rows = self._query(
            """
            SELECT c.id, c.title, c.created_at, c.updated_at,
                   (SELECT COUNT(*) FROM messages m WHERE m.conversation_id = c.id) AS message_count
            FROM conversations c
            ORDER BY c.updated_at DESC, c.id DESC
            """
        )
        return [dict(row) for row in rows]

    def get_conversation(self, conversation_id: int) -> dict[str, Any] | None:
        rows = self._query("SELECT id, title, created_at, updated_at FROM conversations WHERE id = ?", (conversation_id,))
        return dict(rows[0]) if rows else None

    def rename_conversation(self, conversation_id: int, title: str) -> bool:
        cursor = self._execute(
            "UPDATE conversations SET title = ?, updated_at = ? WHERE id = ?",
            (title.strip()[:200], _now(), conversation_id),
        )
        return cursor.rowcount > 0

    def delete_conversation(self, conversation_id: int) -> bool:
        with self._lock:
            ids = [row["id"] for row in self._query("SELECT id FROM messages WHERE conversation_id = ?", (conversation_id,))]
            if self.has_fts and ids:
                self._connection.executemany("DELETE FROM messages_fts WHERE rowid = ?", [(i,) for i in ids])
            cursor = self._connection.execute("DELETE FROM conversations WHERE id = ?", (conversation_id,))
            self._connection.commit()
            return cursor.rowcount > 0

    def add_message(self, conversation_id: int, role: str, content: str, sources: list[str] | None = None) -> int:
        stamp = _now()
        with self._lock:
            cursor = self._connection.execute(
                "INSERT INTO messages(conversation_id, role, content, sources, created_at) VALUES (?, ?, ?, ?, ?)",
                (conversation_id, role, content, json.dumps(sources or []), stamp),
            )
            message_id = int(cursor.lastrowid or 0)
            if self.has_fts:
                self._connection.execute(
                    "INSERT INTO messages_fts(rowid, content) VALUES (?, ?)", (message_id, content)
                )
            self._connection.execute(
                "UPDATE conversations SET updated_at = ? WHERE id = ?", (stamp, conversation_id)
            )
            self._connection.commit()
        return message_id

    def list_messages(self, conversation_id: int) -> list[dict[str, Any]]:
        rows = self._query(
            "SELECT id, role, content, sources, created_at FROM messages WHERE conversation_id = ? ORDER BY id",
            (conversation_id,),
        )
        return [{**dict(row), "sources": json.loads(row["sources"] or "[]")} for row in rows]

    def recent_messages(self, conversation_id: int, limit: int = 12) -> list[dict[str, str]]:
        rows = self._query(
            "SELECT role, content FROM messages WHERE conversation_id = ? ORDER BY id DESC LIMIT ?",
            (conversation_id, limit),
        )
        return [{"role": row["role"], "content": row["content"]} for row in reversed(rows)]

    def search_conversations(self, query: str, limit: int = 20) -> list[dict[str, Any]]:
        match = _match_query(query)
        if not match:
            return []
        if self.has_fts:
            rows = self._query(
                """
                SELECT c.id, c.title, c.updated_at, snippet(messages_fts, 0, '', '', '…', 12) AS excerpt
                FROM messages_fts
                JOIN messages m ON m.id = messages_fts.rowid
                JOIN conversations c ON c.id = m.conversation_id
                WHERE messages_fts MATCH ?
                ORDER BY bm25(messages_fts)
                LIMIT ?
                """,
                (match, limit),
            )
        else:
            rows = self._query(
                """
                SELECT c.id, c.title, c.updated_at, substr(m.content, 1, 160) AS excerpt
                FROM messages m JOIN conversations c ON c.id = m.conversation_id
                WHERE lower(m.content) LIKE ? LIMIT ?
                """,
                (f"%{query.lower()}%", limit),
            )
        return [dict(row) for row in rows]

    # -- memories ----------------------------------------------------------

    def add_memory(self, content: str, category: str, importance: int = 3) -> int:
        stamp = _now()
        with self._lock:
            existing = self._connection.execute(
                "SELECT id FROM memories WHERE lower(content) = lower(?)", (content.strip(),)
            ).fetchone()
            if existing:
                return int(existing["id"])
            cursor = self._connection.execute(
                "INSERT INTO memories(category, content, importance, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                (category, content.strip(), importance, stamp, stamp),
            )
            memory_id = int(cursor.lastrowid or 0)
            if self.has_fts:
                self._connection.execute(
                    "INSERT INTO memories_fts(rowid, content) VALUES (?, ?)", (memory_id, content.strip())
                )
            self._connection.commit()
        return memory_id

    def list_memories(self, category: str | None = None) -> list[dict[str, Any]]:
        if category:
            rows = self._query(
                "SELECT * FROM memories WHERE category = ? ORDER BY importance DESC, id DESC", (category,)
            )
        else:
            rows = self._query("SELECT * FROM memories ORDER BY importance DESC, id DESC")
        return [dict(row) for row in rows]

    def update_memory(self, memory_id: int, *, content: str | None, category: str | None, importance: int | None) -> bool:
        fields, values = [], []
        if content is not None:
            fields.append("content = ?")
            values.append(content.strip())
        if category is not None:
            fields.append("category = ?")
            values.append(category)
        if importance is not None:
            fields.append("importance = ?")
            values.append(importance)
        if not fields:
            return False
        fields.append("updated_at = ?")
        values.extend([_now(), memory_id])
        with self._lock:
            cursor = self._connection.execute(f"UPDATE memories SET {', '.join(fields)} WHERE id = ?", tuple(values))
            if self.has_fts and content is not None:
                self._connection.execute("DELETE FROM memories_fts WHERE rowid = ?", (memory_id,))
                self._connection.execute(
                    "INSERT INTO memories_fts(rowid, content) VALUES (?, ?)", (memory_id, content.strip())
                )
            self._connection.commit()
            return cursor.rowcount > 0

    def delete_memory(self, memory_id: int) -> bool:
        with self._lock:
            if self.has_fts:
                self._connection.execute("DELETE FROM memories_fts WHERE rowid = ?", (memory_id,))
            cursor = self._connection.execute("DELETE FROM memories WHERE id = ?", (memory_id,))
            self._connection.commit()
            return cursor.rowcount > 0

    def search_memories(self, query: str, limit: int = 5) -> list[dict[str, Any]]:
        """Relevant memories only — the whole database is never sent to the model."""
        if limit <= 0:
            return []
        match = _match_query(query)
        if not match:
            return []
        if self.has_fts:
            rows = self._query(
                """
                SELECT m.id, m.category, m.content, m.importance
                FROM memories_fts JOIN memories m ON m.id = memories_fts.rowid
                WHERE memories_fts MATCH ?
                ORDER BY bm25(memories_fts) - (m.importance * 0.35)
                LIMIT ?
                """,
                (match, limit),
            )
        else:
            rows = self._query(
                "SELECT id, category, content, importance FROM memories WHERE lower(content) LIKE ? LIMIT ?",
                (f"%{query.lower()}%", limit),
            )
        return [dict(row) for row in rows]

    # -- documents ---------------------------------------------------------

    def document_exists(self, sha256: str) -> bool:
        return bool(self._query("SELECT 1 FROM documents WHERE sha256 = ?", (sha256,)))

    def add_document(
        self, filename: str, sha256: str, byte_size: int, chunks: list[str], source_path: str | None = None
    ) -> int:
        stamp = _now()
        with self._lock:
            cursor = self._connection.execute(
                """
                INSERT INTO documents(filename, source_path, sha256, byte_size, status, indexed_at, created_at)
                VALUES (?, ?, ?, ?, 'indexed', ?, ?)
                """,
                (filename, source_path, sha256, byte_size, stamp, stamp),
            )
            document_id = int(cursor.lastrowid or 0)
            for ordinal, chunk in enumerate(chunks):
                chunk_cursor = self._connection.execute(
                    "INSERT INTO chunks(document_id, ordinal, content) VALUES (?, ?, ?)",
                    (document_id, ordinal, chunk),
                )
                if self.has_fts:
                    self._connection.execute(
                        "INSERT INTO chunks_fts(rowid, content) VALUES (?, ?)", (chunk_cursor.lastrowid, chunk)
                    )
            self._connection.commit()
        return document_id

    def list_documents(self) -> list[dict[str, Any]]:
        rows = self._query(
            """
            SELECT d.*, (SELECT COUNT(*) FROM chunks c WHERE c.document_id = d.id) AS chunk_count
            FROM documents d ORDER BY d.id DESC
            """
        )
        return [dict(row) for row in rows]

    def delete_document(self, document_id: int) -> bool:
        with self._lock:
            chunk_ids = [
                row["id"] for row in self._connection.execute(
                    "SELECT id FROM chunks WHERE document_id = ?", (document_id,)
                ).fetchall()
            ]
            if self.has_fts and chunk_ids:
                self._connection.executemany("DELETE FROM chunks_fts WHERE rowid = ?", [(i,) for i in chunk_ids])
            cursor = self._connection.execute("DELETE FROM documents WHERE id = ?", (document_id,))
            self._connection.commit()
            return cursor.rowcount > 0

    def search_chunks(self, query: str, limit: int = 4) -> list[dict[str, Any]]:
        """Top-ranked passages, not whole documents."""
        if limit <= 0:
            return []
        match = _match_query(query)
        if not match:
            return []
        if self.has_fts:
            rows = self._query(
                """
                SELECT d.filename, c.content, c.ordinal, bm25(chunks_fts) AS rank
                FROM chunks_fts
                JOIN chunks c ON c.id = chunks_fts.rowid
                JOIN documents d ON d.id = c.document_id
                WHERE chunks_fts MATCH ?
                ORDER BY rank
                LIMIT ?
                """,
                (match, limit),
            )
        else:
            rows = self._query(
                """
                SELECT d.filename, c.content, c.ordinal, 0 AS rank
                FROM chunks c JOIN documents d ON d.id = c.document_id
                WHERE lower(c.content) LIKE ? LIMIT ?
                """,
                (f"%{query.lower()}%", limit),
            )
        return [dict(row) for row in rows]

    # -- settings and counts ----------------------------------------------

    def load_settings(self) -> Settings:
        rows = self._query("SELECT value FROM settings WHERE key = 'app'")
        if not rows:
            return Settings()
        try:
            return Settings.model_validate_json(rows[0]["value"])
        except ValueError:
            log.warning("Stored settings were invalid; falling back to defaults")
            return Settings()

    def save_settings(self, settings: Settings) -> Settings:
        self._execute(
            "INSERT INTO settings(key, value) VALUES ('app', ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (settings.model_dump_json(),),
        )
        return settings

    def counts(self) -> dict[str, int]:
        row = self._query(
            """
            SELECT (SELECT COUNT(*) FROM memories)      AS memories,
                   (SELECT COUNT(*) FROM documents)     AS documents,
                   (SELECT COUNT(*) FROM conversations) AS conversations,
                   (SELECT COUNT(*) FROM messages)      AS messages
            """
        )[0]
        return dict(row)
