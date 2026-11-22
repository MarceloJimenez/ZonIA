"""SQLite storage: conversations and their messages.

One row per conversation keeps everything run_turn needs to continue it:
country, stage, status, the fields and the LLM history (both as JSON).
The messages table keeps what the candidate wrote and what Sonia replied, in order.
"""

import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from pydantic_ai.messages import ModelMessagesTypeAdapter

from zonia.models import ScreeningFields, Stage, Status
from zonia.turn import Conversation, TurnResult

SCHEMA = """
CREATE TABLE IF NOT EXISTS conversations (
    id INTEGER PRIMARY KEY,
    country TEXT NOT NULL,
    stage TEXT NOT NULL,
    status TEXT NOT NULL,
    fields TEXT NOT NULL,
    history TEXT NOT NULL,
    failed_turns INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY,
    conversation_id INTEGER NOT NULL REFERENCES conversations(id),
    role TEXT NOT NULL CHECK (role IN ('candidate', 'agent')),
    text TEXT NOT NULL,
    created_at TEXT NOT NULL
);
"""


def _now() -> str:
    return datetime.now(UTC).isoformat()


@dataclass
class ConversationRow:
    """One conversation as the dashboard lists it: no history, plus the times."""

    id: int
    country: str
    stage: Stage
    status: Status
    fields: ScreeningFields
    created_at: datetime
    updated_at: datetime  # the time of the last saved turn


class Storage:
    """A SQLite database file. ":memory:" keeps it in memory, for tests."""

    def __init__(self, path: str | Path):
        self.db = sqlite3.connect(path)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA foreign_keys = ON")
        self.db.executescript(SCHEMA)

    def close(self) -> None:
        self.db.close()

    def create(self, conversation: Conversation, agent_messages: list[str] = ()) -> int:
        """Save a new conversation and return its id.

        agent_messages are Sonia's first messages (the greeting), saved before any turn.
        """
        now = _now()
        with self.db:
            cursor = self.db.execute(
                "INSERT INTO conversations"
                " (country, stage, status, fields, history, failed_turns, created_at, updated_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (conversation.country, *self._state(conversation), now, now),
            )
            self.db.executemany(
                "INSERT INTO messages (conversation_id, role, text, created_at) VALUES (?, 'agent', ?, ?)",
                [(cursor.lastrowid, text, now) for text in agent_messages],
            )
        return cursor.lastrowid

    def load(self, conversation_id: int) -> Conversation:
        """The conversation with this id. Raises KeyError if there is none."""
        row = self.db.execute("SELECT * FROM conversations WHERE id = ?", (conversation_id,)).fetchone()
        if row is None:
            raise KeyError(conversation_id)
        return Conversation(
            history=ModelMessagesTypeAdapter.validate_json(row["history"]),
            fields=ScreeningFields.model_validate_json(row["fields"]),
            stage=Stage(row["stage"]),
            status=Status(row["status"]),
            country=row["country"],
            failed_turns=row["failed_turns"],
        )

    def save_turn(self, conversation_id: int, conversation: Conversation, turn: TurnResult) -> None:
        """Save the conversation after one turn, and the turn's two messages.

        One transaction: either everything is saved, or nothing is.
        """
        now = _now()
        with self.db:
            updated = self.db.execute(
                "UPDATE conversations SET stage = ?, status = ?, fields = ?, history = ?, failed_turns = ?,"
                " updated_at = ? WHERE id = ?",
                (*self._state(conversation), now, conversation_id),
            )
            if updated.rowcount == 0:
                raise KeyError(conversation_id)
            self.db.executemany(
                "INSERT INTO messages (conversation_id, role, text, created_at) VALUES (?, ?, ?, ?)",
                [(conversation_id, "candidate", turn.message, now), (conversation_id, "agent", turn.reply, now)],
            )

    def conversations(self) -> list[ConversationRow]:
        """Every conversation, newest first."""
        rows = self.db.execute(
            "SELECT id, country, stage, status, fields, created_at, updated_at FROM conversations"
            " ORDER BY created_at DESC, id DESC"
        )
        return [self._row(row) for row in rows]

    def conversation(self, conversation_id: int) -> ConversationRow:
        """The conversation with this id, as the dashboard shows it. Raises KeyError if there is none."""
        row = self.db.execute(
            "SELECT id, country, stage, status, fields, created_at, updated_at FROM conversations WHERE id = ?",
            (conversation_id,),
        ).fetchone()
        if row is None:
            raise KeyError(conversation_id)
        return self._row(row)

    @staticmethod
    def _row(row: sqlite3.Row) -> ConversationRow:
        return ConversationRow(
            id=row["id"],
            country=row["country"],
            stage=Stage(row["stage"]),
            status=Status(row["status"]),
            fields=ScreeningFields.model_validate_json(row["fields"]),
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
        )

    def messages(self, conversation_id: int) -> list[tuple[str, str]]:
        """(role, text) for every message of the conversation, in order."""
        rows = self.db.execute(
            "SELECT role, text FROM messages WHERE conversation_id = ? ORDER BY id", (conversation_id,)
        )
        return [(row["role"], row["text"]) for row in rows]

    @staticmethod
    def _state(c: Conversation) -> tuple[str, str, str, str, int]:
        """stage, status, fields, history and failed_turns, as stored in the conversations row."""
        history = ModelMessagesTypeAdapter.dump_json(c.history).decode()
        return c.stage.value, c.status.value, c.fields.model_dump_json(), history, c.failed_turns
