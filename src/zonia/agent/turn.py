"""One turn of the conversation: the only place that calls the LLM.

1. Call 1: the LLM returns the fields, the intent and a reply.
2. Code merges the fields and decides the new stage and status.
3. Code checks the new values (zonia.domain.validation). An invalid value is not saved.
4. If the status changed and a directive exists, or a value was not valid: call 2 writes the reply again.
   If the conversation enters closing, a value changes in closing, or a closed conversation
   reopens in closing: code writes the summary and no extra call is made.
5. A new disqualification: code adds the review email and the case code to the reply.

Before call 1, code decides the language of the candidate's message (zonia.domain.language).
Both calls, the summary and the fixed texts written by code use it.
"""

from dataclasses import replace
from datetime import date
from enum import StrEnum

from pydantic import BaseModel
from pydantic_ai import Agent
from pydantic_ai.messages import ModelRequest, ModelResponse, TextPart, UserPromptPart

from zonia.agent.prompts.call_1 import local_words, turn_instructions
from zonia.agent.prompts.call_2 import directive, invalid_directive, reply_language
from zonia.agent.schema import Turn, turn_model
from zonia.config import contact_email_for
from zonia.domain.conversation import Conversation, new_case_code
from zonia.domain.flow import FINAL_STATUSES, decide
from zonia.domain.language import detect_language
from zonia.domain.models import Intent, Language, ScreeningFields, Stage, Status
from zonia.domain.validation import start_date_from, validate
from zonia.texts.replies import REVIEW_REPLY
from zonia.texts.summary import render_summary


class ReplySource(StrEnum):
    """Who wrote the reply of a turn."""

    CALL_1 = "call_1"
    CALL_2 = "call_2"
    SUMMARY = "summary"  # code wrote the summary
    FALLBACK = "fallback"  # the turn failed: a fixed reply
    LIMIT = "limit"  # the turn limit was reached: a fixed reply


class TurnResult(BaseModel):
    """What one turn produced, for the caller and for the evals."""

    message: str
    reply: str
    intent: Intent
    stage: Stage
    status: Status
    language: Language  # the language of the reply
    llm_calls: int  # 0 when the turn failed (FALLBACK) or the turn limit was reached (LIMIT)
    reply_source: ReplySource
    invalid_fields: list[str] = []  # values the candidate gave that code dropped
    prompt_version: str | None = None  # the prompt that wrote the reply, for example "sonia@1"; None when code wrote it


async def run_turn(
    agent: Agent[None, Turn], conversation: Conversation, text: str, today: date | None = None
) -> TurnResult:
    """Run one turn and update the conversation.

    The conversation changes only at the end, so a turn that raises
    (for example, a rate-limit error) leaves it as it was and can be retried.
    """
    c = conversation
    today = today or date.today()
    language = detect_language(text, c.language)
    result = await agent.run(
        text,
        message_history=c.history,
        output_type=turn_model(c.country),
        instructions=turn_instructions(c.fields, today, language=language, country=c.country, status=c.status),
    )
    fields, problems = _merge_fields(c, result.output.fields, today)
    intent = result.output.intent
    stage, status = decide(c.stage, c.status, intent, fields)

    # Call 2 replaces the reply: a new status first, then a value to ask again.
    call_2_directive = _call_2_directive(c, status, fields, problems)
    if call_2_directive:
        result_2 = await agent.run(
            text, message_history=c.history, output_type=str,
            instructions=f"{call_2_directive}\n\n{local_words(c.country, language)}\n\n{reply_language(language)}",
        )
        reply, history, calls, source = result_2.output, result_2.all_messages(), 2, ReplySource.CALL_2
        prompt_version = _prompt_version(agent, result_2.metadata)
    elif _shows_summary(c, stage, status, intent, fields):
        reply = render_summary(fields, language, c.country)
        history, calls, source = _summary_history(c, text, reply), 1, ReplySource.SUMMARY
        prompt_version = None
    else:
        reply, history, calls, source = result.output.reply, result.all_messages(), 1, ReplySource.CALL_1
        prompt_version = _prompt_version(agent, result.metadata)

    case_code = c.case_code
    if status == Status.DISQUALIFIED and status != c.status:
        reply, history, case_code = _add_review(c, reply, history, language)

    c.history, c.fields, c.stage, c.status, c.failed_turns = history, fields, stage, status, 0
    c.case_code, c.language = case_code, language
    return TurnResult(
        message=text, reply=reply, intent=intent, stage=stage, status=status, language=language,
        llm_calls=calls, reply_source=source, invalid_fields=list(problems), prompt_version=prompt_version,
    )


def _prompt_version(agent: Agent, metadata: dict | None) -> str | None:
    """The agent's name and the version in its spec (sonia.yaml), for example "sonia@1".

    None for an agent built without a spec.
    """
    return f"{agent.name}@{metadata['version']}" if metadata and "version" in metadata else None


def _merge_fields(c: Conversation, new: ScreeningFields, today: date) -> tuple[ScreeningFields, dict[str, str]]:
    """The fields after this turn, and the problems of the new values.

    An invalid value is not saved: the field stays empty, or keeps its earlier value.
    The LLM gives the start date as day, month and year; code builds the date here.
    """
    new_values = new.model_dump(exclude_none=True)
    date_problem = {}
    if (said := new_values.pop("start_date", None)) is not None:
        start = start_date_from(said["day"], said["month"], said.get("year"), today)
        if start is None:
            date_problem = {"start_date": "esa fecha no existe"}
        else:
            new_values["start_date"] = start
    problems = validate(ScreeningFields(**new_values), today) | date_problem
    valid = {name: value for name, value in new_values.items() if name not in problems}
    return c.fields.model_copy(update=valid), problems


def _call_2_directive(c: Conversation, status: Status, fields: ScreeningFields, problems: dict[str, str]) -> str | None:
    """The instruction for call 2, or None: a new status first, then a value to ask again."""
    status_directive = directive(status, fields, c.country) if status != c.status else None
    return status_directive or (invalid_directive(problems, c.country) if problems else None)


def _shows_summary(c: Conversation, stage: Stage, status: Status, intent: Intent, fields: ScreeningFields) -> bool:
    """True when code shows the summary this turn.

    In closing, the summary comes back only when a value changed. A "no" with no new value
    gets the LLM's reply, which asks what is wrong; showing the same summary again was a loop.
    """
    changed = fields != c.fields
    return (
        stage == Stage.CLOSING
        and status == Status.ACTIVE
        and (
            c.stage != Stage.CLOSING
            or changed
            or (c.status in FINAL_STATUSES and intent != Intent.CORRECTS_SUMMARY)
        )
    )


def _summary_history(c: Conversation, text: str, reply: str) -> list:
    """The history with the candidate's message and the summary written by code."""
    return [
        *c.history,
        ModelRequest(parts=[UserPromptPart(content=text)]),
        ModelResponse(parts=[TextPart(content=reply)]),
    ]


def _add_review(c: Conversation, reply: str, history: list, language: Language) -> tuple[str, list, str]:
    """A new disqualification: code adds the review email and the case code, so both are exact.

    This always follows call 2, so the last history message is call 2's reply.
    Storage gives every conversation a unique code; a conversation that was never saved gets one here.
    Returns the reply, the history and the case code.
    """
    case_code = c.case_code or new_case_code()
    reply = f"{reply}\n\n{REVIEW_REPLY[language].format(email=contact_email_for(c.country), code=case_code)}"
    history = [*history[:-1], replace(history[-1], parts=[TextPart(content=reply)])]
    return reply, history, case_code
