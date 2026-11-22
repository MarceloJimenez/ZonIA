"""One turn of the conversation: the only place that calls the LLM.

1. Call 1: the LLM returns the fields, the intent and a reply.
2. Code merges the fields and decides the new stage and status.
3. Code checks the new values (zonia.validation). An invalid value is not saved.
4. If the status changed and a directive exists, or a value was not valid: call 2 writes the reply again.
   If the conversation enters closing, the candidate corrects the summary, or a closed
   conversation reopens in closing: code writes the summary and no extra call is made.
5. A new disqualification: code adds the review email and the case code to the reply.
"""

import asyncio
import logging
import secrets
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field, replace
from datetime import date

from pydantic import BaseModel
from pydantic_ai import Agent
from pydantic_ai.exceptions import ModelAPIError, ModelHTTPError
from pydantic_ai.messages import ModelMessage, ModelRequest, ModelResponse, TextPart, UserPromptPart

from zonia.config import GREETING, contact_email_for
from zonia.flow import FINAL_STATUSES, decide, render_summary
from zonia.models import Intent, ScreeningFields, Stage, Status, Turn, turn_model
from zonia.prompt import directive, invalid_directive, turn_instructions
from zonia.validation import validate


@dataclass
class Conversation:
    """Everything the code keeps between turns."""

    history: list[ModelMessage] = field(default_factory=list)
    fields: ScreeningFields = field(default_factory=ScreeningFields)
    stage: Stage = Stage.INTRODUCTION
    status: Status = Status.ACTIVE
    country: str = "ES"  # "ES" or "MX"; decides the service zones
    failed_turns: int = 0  # turns in a row that ended in a technical failure
    case_code: str | None = None  # storage gives it; the candidate gets it on disqualification


REVIEW_REPLY = "Si quieres que una persona revise tu caso, escribe a {email} con el código {code}."

# No 0/O and no 1/I: a candidate types the code into an email. 32^8 is more than a trillion codes.
CASE_CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


def new_case_code() -> str:
    """A random case code that cannot be guessed, like "K7PX-3QMD"."""
    chars = "".join(secrets.choice(CASE_CODE_ALPHABET) for _ in range(8))
    return f"{chars[:4]}-{chars[4:]}"


def new_conversation(country: str = "ES") -> Conversation:
    """A conversation that starts with Sonia's greeting.

    The greeting is in the history, so on turn 1 the LLM knows what Sonia asked.
    """
    greeting = ModelResponse(parts=[TextPart(content="\n".join(GREETING))])
    return Conversation(history=[greeting], country=country)


class TurnResult(BaseModel):
    """What one turn produced, for the caller and for the evals."""

    message: str
    reply: str
    intent: Intent
    stage: Stage
    status: Status
    llm_calls: int  # 0 when the turn failed (reply_source "fallback")
    reply_source: str  # "call_1", "call_2", "summary" or "fallback"
    invalid_fields: list[str] = []  # values the candidate gave that code dropped


async def run_turn(
    agent: Agent[None, Turn], conversation: Conversation, text: str, today: date | None = None
) -> TurnResult:
    """Run one turn and update the conversation.

    The conversation changes only at the end, so a turn that raises
    (for example, a rate-limit error) leaves it as it was and can be retried.
    """
    c = conversation
    today = today or date.today()
    result = await agent.run(
        text,
        message_history=c.history,
        output_type=turn_model(c.country),
        instructions=turn_instructions(c.fields, today),
    )
    # An invalid value is not saved: the field stays empty, or keeps its earlier value.
    new_values = result.output.fields.model_dump(exclude_none=True)
    problems = validate(ScreeningFields(**new_values), today)
    valid = {name: value for name, value in new_values.items() if name not in problems}
    fields = c.fields.model_copy(update=valid)
    intent = result.output.intent
    stage, status = decide(c.stage, c.status, intent, fields)
    show_summary = (
        stage == Stage.CLOSING
        and status == Status.ACTIVE
        and (c.stage != Stage.CLOSING or intent == Intent.CORRECTS_SUMMARY or c.status in FINAL_STATUSES)
    )

    # Call 2 replaces the reply: a new status first, then a value to ask again.
    status_directive = directive(status, fields) if status != c.status else None
    call_2_directive = status_directive or (invalid_directive(problems) if problems else None)
    if call_2_directive:
        result_2 = await agent.run(
            text, message_history=c.history, output_type=str, instructions=call_2_directive
        )
        reply, history, calls, source = result_2.output, result_2.all_messages(), 2, "call_2"
    elif show_summary:
        reply = render_summary(fields)
        history = [
            *c.history,
            ModelRequest(parts=[UserPromptPart(content=text)]),
            ModelResponse(parts=[TextPart(content=reply)]),
        ]
        calls, source = 1, "summary"
    else:
        reply, history, calls, source = result.output.reply, result.all_messages(), 1, "call_1"

    # A new disqualification: code adds the review email and the case code, so both are exact.
    # This always follows call 2, so the last history message is call 2's reply.
    # Storage gives every conversation a unique code; a conversation that was never saved gets one here.
    case_code = c.case_code
    if status == Status.DISQUALIFIED and status != c.status:
        case_code = case_code or new_case_code()
        reply = f"{reply}\n\n{REVIEW_REPLY.format(email=contact_email_for(c.country), code=case_code)}"
        history = [*history[:-1], replace(history[-1], parts=[TextPart(content=reply)])]

    c.history, c.fields, c.stage, c.status, c.failed_turns = history, fields, stage, status, 0
    c.case_code = case_code
    return TurnResult(
        message=text, reply=reply, intent=intent, stage=stage, status=status,
        llm_calls=calls, reply_source=source, invalid_fields=list(problems),
    )


# --- Technical failures -----------------------------------------------------

logger = logging.getLogger(__name__)

RETRY_DELAYS = [1, 2, 4]  # seconds to wait before each new try
MAX_RETRY_WAIT = 30  # seconds; a longer Retry-After from the provider is cut to this

FAILURE_REPLY = "Perdona, he tenido un problema técnico. ¿Puedes repetir tu último mensaje?"
CONTACT_REPLY = (
    "Seguimos con un problema técnico. Escríbenos a {email} con tu nombre y tu teléfono, "
    "y una persona del equipo seguirá con tu candidatura. También puedes intentarlo aquí más tarde."
)


def is_transient(error: Exception) -> bool:
    """True for errors that may pass if we try again: 429, 5xx, or no connection.

    Pydantic AI raises the same classes for every LLM provider.
    """
    if isinstance(error, ModelHTTPError):
        return error.status_code == 429 or error.status_code >= 500
    return isinstance(error, ModelAPIError)  # no HTTP status: the connection failed


async def run_turn_safely(
    agent: Agent[None, Turn],
    conversation: Conversation,
    text: str,
    today: date | None = None,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> TurnResult:
    """run_turn that never raises.

    A transient error is tried again, up to len(RETRY_DELAYS) times. If the turn still fails,
    the candidate gets a fixed reply and the conversation keeps its state.
    The first failure asks the candidate to repeat; from the second failure in a row on,
    the reply gives the contact email, so the candidate is not lost.
    """
    for attempt in range(len(RETRY_DELAYS) + 1):
        try:
            return await run_turn(agent, conversation, text, today)
        except Exception as error:
            if not is_transient(error) or attempt == len(RETRY_DELAYS):
                logger.exception("Turn failed after %d tries", attempt + 1)
                break
            wait = getattr(error, "retry_after", None) or RETRY_DELAYS[attempt]
            await sleep(min(wait, MAX_RETRY_WAIT))

    c = conversation
    c.failed_turns += 1
    reply = FAILURE_REPLY if c.failed_turns == 1 else CONTACT_REPLY.format(email=contact_email_for(c.country))
    return TurnResult(
        message=text, reply=reply, intent=Intent.NONE, stage=c.stage, status=c.status,
        llm_calls=0, reply_source="fallback",
    )
