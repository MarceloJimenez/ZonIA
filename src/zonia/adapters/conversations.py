"""What the three channels (web chat, voice, WhatsApp) do the same way with a candidate message.

One turn at a time per conversation, then: load the conversation, run the turn, save it, write the log line.
"""

import asyncio
import logging
import time
from collections import defaultdict
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from pydantic_ai import Agent

from zonia.agent.safety import run_turn_safely
from zonia.agent.schema import Turn
from zonia.agent.turn import TurnResult
from zonia.storage import Storage

logger = logging.getLogger(__name__)

# Seconds for one chat or WhatsApp turn. Past it, Sonia says the technical-failure reply
# instead of leaving the candidate waiting. Longer than voice: a written reply can wait a little.
CHAT_TIME_LIMIT = 30


class Conversations:
    """The database, Sonia's agent and the locks, shared by the three channels."""

    def __init__(self, db_path: str | Path, agent: Agent[None, Turn]):
        self.db_path = db_path
        self.agent = agent
        # One turn at a time per conversation (key: phone or case code): two quick messages must not change it at once.
        self.locks: defaultdict[str, asyncio.Lock] = defaultdict(asyncio.Lock)

    def storage(self) -> Storage:
        """A new connection to the database. Use it with `with`."""
        return Storage(self.db_path)

    @asynccontextmanager
    async def open(self, key: str) -> AsyncIterator[Storage]:
        """Waits for the conversation's lock, then opens the database. Both are released at the end."""
        async with self.locks[key]:
            with self.storage() as storage:
                yield storage

    async def take_turn(
        self,
        storage: Storage,
        conversation_id: int,
        text: str,
        *,
        channel: str,
        who: str,
        started: float,
        time_limit: float | None = None,
        external_id: str | None = None,
    ) -> TurnResult:
        """Loads the conversation, runs one turn, saves it and writes one log line.

        channel and who are for the log: for example "web" and the case code, or "whatsapp" and the phone.
        started is time.monotonic() when the message arrived, before the wait for the lock.
        time_limit is in seconds; None means CHAT_TIME_LIMIT.
        external_id is the channel's id for the candidate's message (the WhatsApp message id).
        """
        conversation = storage.load(conversation_id)
        limit = CHAT_TIME_LIMIT if time_limit is None else time_limit
        turn = await run_turn_safely(self.agent, conversation, text, time_limit=limit)
        storage.save_turn(
            conversation_id, conversation, turn.message, turn.reply,
            external_id=external_id, prompt_version=turn.prompt_version,
        )
        log_turn(channel, who, text, turn.reply, started)
        return turn


def log_turn(channel: str, who: str, text: str, reply: str, started: float) -> None:
    """One line per turn, so the server log shows each conversation live."""
    logger.info("%s %s | candidate: %s | sonia: %s | %.1f s", channel, who, text, reply, time.monotonic() - started)
