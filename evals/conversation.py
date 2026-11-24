"""The task under evaluation: play a scripted conversation against the real LLM."""

import asyncio
import time
from pathlib import Path

from pydantic import BaseModel
from pydantic_ai.exceptions import ModelRateLimitError, ModelUnavailableError
from pydantic_ai.agent.spec import AgentSpec
from pydantic_ai.models.wrapper import WrapperModel

from zonia.config import GREETING
from zonia.agent.llm import SONIA, build_agent, build_model
from zonia.domain.models import ScreeningFields, Stage, Status
from zonia.domain.conversation import new_conversation
from zonia.agent.turn import TurnResult, run_turn

SECONDS_BETWEEN_REQUESTS = 4.5  # Gemini free tier: 15 requests per minute
RETRY_WAIT_SECONDS = 30
MAX_ATTEMPTS = 5


class Script(BaseModel):
    """The candidate's messages, sent one per turn."""

    messages: list[str]
    country: str = "ES"  # decides the service zones


class Transcript(BaseModel):
    """What happened: every turn, and the state at the end."""

    turns: list[TurnResult]
    fields: ScreeningFields
    stage: Stage
    status: Status

    def text(self) -> str:
        """The conversation as a judge reads it."""
        greeting = "\n".join(f"Sonia: {text}" for text in GREETING)
        return "\n".join([greeting, *(f"Candidate: {t.message}\nSonia: {t.reply}" for t in self.turns)])


class PacedModel(WrapperModel):
    """Waits between requests so a run stays under the provider's rate limit."""

    _last = 0.0

    async def request(self, *args, **kwargs):
        wait = PacedModel._last + SECONDS_BETWEEN_REQUESTS - time.monotonic()
        if wait > 0:
            await asyncio.sleep(wait)
        PacedModel._last = time.monotonic()
        return await super().request(*args, **kwargs)


async def with_retries(make_call):
    """Retry on 429 (rate limit) and 503 (overloaded). Other errors fail the case."""
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            return await make_call()
        except (ModelRateLimitError, ModelUnavailableError):
            if attempt == MAX_ATTEMPTS:
                raise
            await asyncio.sleep(RETRY_WAIT_SECONDS)


MODEL = PacedModel(build_model(SONIA.model))
AGENT = build_agent(MODEL)

# The judge's model and settings: evals/judge.yaml.
JUDGE = AgentSpec.from_file(Path(__file__).parent / "judge.yaml")
JUDGE_MODEL = PacedModel(build_model(JUDGE.model))
JUDGE_SETTINGS = JUDGE.model_settings


async def converse(script: Script) -> Transcript:
    """Send each message as one turn. A final status does not stop it: a later message can reopen it."""
    conversation = new_conversation(script.country)
    turns = []
    for message in script.messages:
        turns.append(await with_retries(lambda: run_turn(AGENT, conversation, message)))
    return Transcript(
        turns=turns, fields=conversation.fields, stage=conversation.stage, status=conversation.status
    )
