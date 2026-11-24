"""The state of one conversation, kept between turns, and how a new one starts.

The history is in Pydantic AI's message format, because the LLM reads it on each turn.
Outside agent code and storage, this is the only module that knows that format: the rest use add_agent_message.
"""

import secrets
from dataclasses import dataclass, field

from pydantic_ai.messages import ModelMessage, ModelResponse, TextPart

from zonia.config import GREETING
from zonia.domain.models import Country, Language, ScreeningFields, Stage, Status


@dataclass
class Conversation:
    """Everything the code keeps between turns."""

    history: list[ModelMessage] = field(default_factory=list)
    fields: ScreeningFields = field(default_factory=ScreeningFields)
    stage: Stage = Stage.INTRODUCTION
    status: Status = Status.ACTIVE
    country: Country = "ES"
    failed_turns: int = 0  # turns in a row that ended in a technical failure
    case_code: str | None = None  # storage gives it; the candidate gets it on disqualification
    turns: int = 0  # candidate messages so far, failed turns included
    language: Language = "es"  # the language of the candidate's last message
    followup_step: int = 0  # follow-up steps done since the candidate's last message (zonia.followups)

    def add_agent_message(self, text: str) -> None:
        """Add a message Sonia sent to the history, so the LLM sees it on the next turn."""
        self.history = [*self.history, ModelResponse(parts=[TextPart(content=text)])]


# No 0/O and no 1/I: a candidate types the code into an email. 32^8 is more than a trillion codes.
CASE_CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


def new_case_code() -> str:
    """A random case code that cannot be guessed, like "K7PX-3QMD"."""
    chars = "".join(secrets.choice(CASE_CODE_ALPHABET) for _ in range(8))
    return f"{chars[:4]}-{chars[4:]}"


def new_conversation(country: Country = "ES") -> Conversation:
    """A conversation that starts with Sonia's greeting.

    The greeting is in the history, so on turn 1 the LLM knows what Sonia asked.
    """
    conversation = Conversation(country=country)
    conversation.add_agent_message("\n".join(GREETING))
    return conversation
