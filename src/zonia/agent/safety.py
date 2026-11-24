"""Technical failures and the turn limit around run_turn: tries again, waits, and gives a fixed reply."""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from datetime import date

from pydantic_ai import Agent
from pydantic_ai.exceptions import ModelAPIError, ModelHTTPError

from zonia.agent.schema import Turn
from zonia.agent.turn import TurnResult, run_turn
from zonia.config import MAX_TURNS, contact_email_for
from zonia.domain.conversation import Conversation
from zonia.domain.flow import FINAL_STATUSES
from zonia.domain.models import Intent, Status
from zonia.texts.replies import CONTACT_REPLY, FAILURE_REPLY, LIMIT_REPLY

logger = logging.getLogger(__name__)

RETRY_DELAYS = [1, 2, 4]  # seconds to wait before each new try
MAX_RETRY_WAIT = 30  # seconds; a longer Retry-After from the provider is cut to this


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
    time_limit: float | None = None,
) -> TurnResult:
    """run_turn that never raises, and stops at the turn limit.

    From message MAX_TURNS on, the LLM is not called: the candidate gets a fixed reply
    with the contact email, and an open conversation ends as incomplete.
    A final status (qualified, disqualified, withdrawn) is kept: it is a real result.

    A transient error is tried again, up to len(RETRY_DELAYS) times. If the turn still fails,
    the candidate gets a fixed reply and the conversation keeps its state.
    The first failure asks the candidate to repeat; from the second failure in a row on,
    the reply gives the contact email, so the candidate is not lost, and an open conversation
    becomes technical_error, so the recruiter sees it. A good turn later makes it active again (flow.decide).

    time_limit (seconds) bounds the whole turn, tries and waits included. When it passes,
    the turn fails the same way. Voice uses it: the candidate waits in silence.
    """
    c = conversation
    c.turns += 1
    c.followup_step = 0  # the candidate answered: the follow-ups start again
    if c.turns >= MAX_TURNS:
        if c.status not in FINAL_STATUSES:
            c.status = Status.INCOMPLETE
        return TurnResult(
            message=text, reply=LIMIT_REPLY[c.language].format(email=contact_email_for(c.country)),
            intent=Intent.NONE, stage=c.stage, status=c.status, language=c.language, llm_calls=0, reply_source="limit",
        )

    loop = asyncio.get_running_loop()
    deadline = None if time_limit is None else loop.time() + time_limit
    for attempt in range(len(RETRY_DELAYS) + 1):
        try:
            # run_turn changes the conversation only at its end, so stopping it in the middle changes nothing.
            remaining = None if deadline is None else deadline - loop.time()
            return await asyncio.wait_for(run_turn(agent, conversation, text, today), remaining)
        except TimeoutError:
            logger.error("Turn passed the time limit of %s s after %d tries", time_limit, attempt + 1)
            break
        except Exception as error:
            if not is_transient(error) or attempt == len(RETRY_DELAYS):
                logger.exception("Turn failed after %d tries", attempt + 1)
                break
            wait = min(getattr(error, "retry_after", None) or RETRY_DELAYS[attempt], MAX_RETRY_WAIT)
            if deadline is not None and loop.time() + wait >= deadline:
                logger.exception("Turn failed after %d tries: the next wait passes the time limit", attempt + 1)
                break
            await sleep(wait)

    c.failed_turns += 1
    if c.failed_turns == 1:
        reply = FAILURE_REPLY[c.language]
    else:
        reply = CONTACT_REPLY[c.language].format(email=contact_email_for(c.country))
        if c.status not in FINAL_STATUSES:
            c.status = Status.TECHNICAL_ERROR
    return TurnResult(
        message=text, reply=reply, intent=Intent.NONE, stage=c.stage, status=c.status, language=c.language,
        llm_calls=0, reply_source="fallback",
    )
