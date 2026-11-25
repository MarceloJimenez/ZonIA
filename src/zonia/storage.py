"""SQLite storage: conversations and their messages.

One row per conversation keeps everything run_turn needs to continue it:
country, stage, status, language, the fields and the LLM history (both as JSON).
The messages table keeps what the candidate wrote and what Sonia replied, in order.
waiting_since is the time of Sonia's last reply to the candidate: the follow-ups (zonia.followups) count from it.
phone is the candidate's number (E.164, for example "+34600111222"), from the apply page or WhatsApp; empty for the terminal chat.
A message's external_id is the channel's id for it (the WhatsApp message id): a message that comes twice is saved once.
"""

import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from pydantic_ai.messages import ModelMessagesTypeAdapter

from zonia.domain.conversation import Conversation, new_case_code
from zonia.domain.models import RecruiterOutcome, Role, ScreeningFields, Stage, Status

# The newest outcome the recruiter set for the conversation (c is the conversations row).
LATEST_OUTCOME = (
    "(SELECT outcome FROM recruiter_updates u WHERE u.conversation_id = c.id AND outcome IS NOT NULL"
    " ORDER BY u.id DESC LIMIT 1) AS outcome"
)

CASE_CODE_TRIES = 5  # a repeated code is almost impossible; 5 tries in a row is a bug

SCHEMA = """
CREATE TABLE IF NOT EXISTS conversations (
    id INTEGER PRIMARY KEY,
    country TEXT NOT NULL,
    phone TEXT,
    stage TEXT NOT NULL,
    status TEXT NOT NULL,
    fields TEXT NOT NULL,
    history TEXT NOT NULL,
    failed_turns INTEGER NOT NULL,
    case_code TEXT NOT NULL UNIQUE,
    turns INTEGER NOT NULL,
    language TEXT NOT NULL,
    followup_step INTEGER NOT NULL,
    waiting_since TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY,
    conversation_id INTEGER NOT NULL REFERENCES conversations(id),
    role TEXT NOT NULL CHECK (role IN ('candidate', 'agent')),
    text TEXT NOT NULL,
    external_id TEXT UNIQUE,
    created_at TEXT NOT NULL,
    prompt_version TEXT  -- the prompt that wrote an agent reply, for example "sonia@1"; NULL when code wrote it
);
CREATE INDEX IF NOT EXISTS conversations_phone ON conversations(phone);
CREATE TABLE IF NOT EXISTS recruiter_updates (
    id INTEGER PRIMARY KEY,
    conversation_id INTEGER NOT NULL REFERENCES conversations(id),
    outcome TEXT,
    note TEXT,
    created_at TEXT NOT NULL,
    CHECK (outcome IS NOT NULL OR note IS NOT NULL)
);
CREATE INDEX IF NOT EXISTS recruiter_updates_conversation ON recruiter_updates(conversation_id);
"""


def _utc_now() -> datetime:
    return datetime.now(UTC)


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
    case_code: str  # the candidate gets it on disqualification, to ask for a human review
    phone: str | None  # E.164, for example "+34600111222"; None for the terminal chat
    outcome: RecruiterOutcome | None  # the recruiter's newest outcome; None if there is none yet


class Storage:
    """A SQLite database file. ":memory:" keeps it in memory, for tests.

    clock gives the current time; tests pass a fake one.
    """

    def __init__(self, path: str | Path, clock: Callable[[], datetime] = _utc_now):
        self.clock = clock
        self.db = sqlite3.connect(path)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA foreign_keys = ON")
        self.db.executescript(SCHEMA)
        self._add_prompt_version()

    def _add_prompt_version(self) -> None:
        """A database made before the prompt had a version gets the messages.prompt_version column."""
        columns = {row["name"] for row in self.db.execute("PRAGMA table_info(messages)")}
        if "prompt_version" not in columns:
            with self.db:
                self.db.execute("ALTER TABLE messages ADD COLUMN prompt_version TEXT")

    def close(self) -> None:
        self.db.close()

    def __enter__(self) -> "Storage":
        return self

    def __exit__(self, *exc_info: object) -> None:
        # Close only, as the try/finally blocks did: each method commits its own writes.
        self.close()

    def create(self, conversation: Conversation, agent_messages: list[str] = (), phone: str | None = None) -> int:
        """Save a new conversation and return its id.

        agent_messages are Sonia's first messages (the greeting), saved before any turn.
        phone is the candidate's phone number, from the apply page (web chat) or WhatsApp.
        A conversation without a case code gets one here. The column is UNIQUE: if the
        code is already taken, a new code is made, before any candidate sees it.
        """
        given = conversation.case_code is not None
        for _ in range(CASE_CODE_TRIES):
            if not given:
                conversation.case_code = new_case_code()
            try:
                return self._insert(conversation, agent_messages, phone)
            except sqlite3.IntegrityError:
                if given:
                    raise
        raise RuntimeError(f"No free case code after {CASE_CODE_TRIES} tries")

    def _insert(self, conversation: Conversation, agent_messages: list[str], phone: str | None) -> int:
        now = self.clock().isoformat()
        with self.db:
            cursor = self.db.execute(
                "INSERT INTO conversations"
                " (country, phone, stage, status, fields, history, failed_turns, case_code, turns, language, followup_step,"
                " waiting_since, created_at, updated_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (conversation.country, phone, *self._state(conversation), now, now, now),
            )
            self.db.executemany(
                "INSERT INTO messages (conversation_id, role, text, created_at) VALUES (?, ?, ?, ?)",
                [(cursor.lastrowid, Role.AGENT, text, now) for text in agent_messages],
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
            case_code=row["case_code"],
            turns=row["turns"],
            language=row["language"],
            followup_step=row["followup_step"],
        )

    def save_turn(
        self,
        conversation_id: int,
        conversation: Conversation,
        message: str,
        reply: str,
        external_id: str | None = None,
        prompt_version: str | None = None,
    ) -> None:
        """Save the conversation after one turn, and the turn's two messages.

        message is what the candidate wrote; reply is what Sonia answered.
        external_id is the channel's id for the candidate's message (the WhatsApp message id).
        prompt_version is the prompt that wrote the reply (TurnResult.prompt_version).

        One transaction: either everything is saved, or nothing is. Sonia has just replied,
        so waiting_since starts again.
        """
        now = self.clock().isoformat()
        with self.db:
            updated = self.db.execute(
                "UPDATE conversations SET stage = ?, status = ?, fields = ?, history = ?, failed_turns = ?,"
                " case_code = ?, turns = ?, language = ?, followup_step = ?, waiting_since = ?, updated_at = ?"
                " WHERE id = ?",
                (*self._state(conversation), now, now, conversation_id),
            )
            if updated.rowcount == 0:
                raise KeyError(conversation_id)
            self.db.executemany(
                "INSERT INTO messages (conversation_id, role, text, external_id, created_at, prompt_version)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                [
                    (conversation_id, Role.CANDIDATE, message, external_id, now, None),
                    (conversation_id, Role.AGENT, reply, None, now, prompt_version),
                ],
            )

    def find_by_phone(self, phone: str) -> int | None:
        """The id of the newest conversation with this WhatsApp number, or None."""
        row = self.db.execute("SELECT id FROM conversations WHERE phone = ? ORDER BY id DESC LIMIT 1", (phone,)).fetchone()
        return None if row is None else row["id"]

    def find_by_case_code(self, case_code: str) -> int | None:
        """The id of the conversation with this case code, or None. The web chat URL uses it."""
        row = self.db.execute("SELECT id FROM conversations WHERE case_code = ?", (case_code,)).fetchone()
        return None if row is None else row["id"]

    def has_message(self, external_id: str) -> bool:
        """True if a message with this channel id is already saved."""
        return self.db.execute("SELECT 1 FROM messages WHERE external_id = ?", (external_id,)).fetchone() is not None

    def waiting(self) -> list[tuple[int, datetime]]:
        """(id, waiting_since) of every conversation that waits for the candidate: active or paused."""
        rows = self.db.execute(
            "SELECT id, waiting_since FROM conversations WHERE status IN (?, ?) ORDER BY id",
            (Status.ACTIVE.value, Status.PAUSED.value),
        )
        return [(row["id"], datetime.fromisoformat(row["waiting_since"])) for row in rows]

    def save_followup(self, conversation_id: int, conversation: Conversation, reminder: str | None) -> None:
        """Save a follow-up step: the new status, history and step, and the reminder if Sonia sent one.

        waiting_since does not change: the next steps count from Sonia's last reply.
        """
        now = self.clock().isoformat()
        with self.db:
            updated = self.db.execute(
                "UPDATE conversations SET status = ?, history = ?, followup_step = ?, updated_at = ? WHERE id = ?",
                (
                    conversation.status.value,
                    ModelMessagesTypeAdapter.dump_json(conversation.history).decode(),
                    conversation.followup_step,
                    now,
                    conversation_id,
                ),
            )
            if updated.rowcount == 0:
                raise KeyError(conversation_id)
            if reminder is not None:
                self.db.execute(
                    "INSERT INTO messages (conversation_id, role, text, created_at) VALUES (?, ?, ?, ?)",
                    (conversation_id, Role.AGENT, reminder, now),
                )

    def save_call_failure(self, conversation_id: int, status: Status, notice: str) -> None:
        """Save a voice call that broke: the new status and Sonia's notice, which the voice page said.

        No turn ran, so the stage, fields and history do not change.
        """
        now = self.clock().isoformat()
        with self.db:
            updated = self.db.execute(
                "UPDATE conversations SET status = ?, updated_at = ? WHERE id = ?", (status.value, now, conversation_id)
            )
            if updated.rowcount == 0:
                raise KeyError(conversation_id)
            self.db.execute(
                "INSERT INTO messages (conversation_id, role, text, created_at) VALUES (?, ?, ?, ?)",
                (conversation_id, Role.AGENT, notice, now),
            )

    def conversations(self) -> list[ConversationRow]:
        """Every conversation, newest first."""
        rows = self.db.execute(
            "SELECT id, country, phone, stage, status, fields, case_code, created_at, updated_at,"
            f" {LATEST_OUTCOME} FROM conversations c"
            " ORDER BY created_at DESC, id DESC"
        )
        return [self._row(row) for row in rows]

    def conversation(self, conversation_id: int) -> ConversationRow:
        """The conversation with this id, as the dashboard shows it. Raises KeyError if there is none."""
        row = self.db.execute(
            "SELECT id, country, phone, stage, status, fields, case_code, created_at, updated_at,"
            f" {LATEST_OUTCOME} FROM conversations c WHERE id = ?",
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
            case_code=row["case_code"],
            phone=row["phone"],
            outcome=None if row["outcome"] is None else RecruiterOutcome(row["outcome"]),
        )

    def add_recruiter_update(
        self, conversation_id: int, outcome: RecruiterOutcome | None, note: str | None
    ) -> None:
        """Save what the recruiter did: an outcome, a note, or both. Rows are never changed, so they are the history.

        Raises KeyError if there is no conversation with this id, and ValueError if both are empty.
        """
        if outcome is None and not note:
            raise ValueError("An update needs an outcome or a note")
        try:
            with self.db:
                self.db.execute(
                    "INSERT INTO recruiter_updates (conversation_id, outcome, note, created_at) VALUES (?, ?, ?, ?)",
                    (conversation_id, None if outcome is None else outcome.value, note or None, self.clock().isoformat()),
                )
        except sqlite3.IntegrityError:
            raise KeyError(conversation_id)

    def recruiter_updates(self, conversation_id: int) -> list[tuple[datetime, RecruiterOutcome | None, str | None]]:
        """(time, outcome, note) of every recruiter update of the conversation, newest first."""
        rows = self.db.execute(
            "SELECT outcome, note, created_at FROM recruiter_updates WHERE conversation_id = ? ORDER BY id DESC",
            (conversation_id,),
        )
        return [
            (
                datetime.fromisoformat(row["created_at"]),
                None if row["outcome"] is None else RecruiterOutcome(row["outcome"]),
                row["note"],
            )
            for row in rows
        ]

    def messages(self, conversation_id: int) -> list[tuple[str, str]]:
        """(role, text) for every message of the conversation, in order."""
        rows = self.db.execute(
            "SELECT role, text FROM messages WHERE conversation_id = ? ORDER BY id", (conversation_id,)
        )
        return [(row["role"], row["text"]) for row in rows]

    @staticmethod
    def _state(c: Conversation) -> tuple[str, str, str, str, int, str | None, int, str, int]:
        """stage, status, fields, history, failed_turns, case_code, turns, language and followup_step,
        as stored in the conversations row."""
        history = ModelMessagesTypeAdapter.dump_json(c.history).decode()
        return c.stage.value, c.status.value, c.fields.model_dump_json(), history, c.failed_turns, c.case_code, c.turns, c.language, c.followup_step
