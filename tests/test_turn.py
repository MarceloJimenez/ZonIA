"""One turn, with a fake LLM: which reply the candidate sees, and what the history keeps.

FunctionModel (from Pydantic AI) replaces the real LLM. It answers call 1 with a
scripted Turn and call 2 with a fixed text, so these tests need no network.
"""

import asyncio
import json
from datetime import date, timedelta

import pytest
from pydantic_ai import Agent
from pydantic_ai.messages import ModelResponse, TextPart, ToolCallPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

from zonia.flow import render_summary
from zonia.models import ScreeningFields, Stage, Status, Turn
from zonia.prompt import DIRECTIVES, SYSTEM, turn_instructions
from zonia.turn import Conversation, run_turn

CALL_1_REPLY = "CALL-1 REPLY"
CALL_2_REPLY = "CALL-2 REPLY"

START = date.today() + timedelta(days=10)

COMPLETE = ScreeningFields(
    full_name="Ana López", driver_license=True, city_zone="Chamberí", availability=["full-time"],
    schedule=["morning"], experience_years=0, start_date=START,
)


class FakeLLM:
    """Answers call 1 with the next scripted Turn, and call 2 with CALL_2_REPLY."""

    def __init__(self, turns: list[dict]):
        self.turns = list(turns)
        self.instructions: list[str] = []

    def __call__(self, messages, info: AgentInfo) -> ModelResponse:
        self.instructions.append(info.instructions or "")
        if info.output_tools:  # call 1 asks for a Turn
            args = {"reply": CALL_1_REPLY, "intent": "none", "fields": {}} | self.turns.pop(0)
            return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name, json.dumps(args))])
        return ModelResponse(parts=[TextPart(CALL_2_REPLY)])  # call 2 asks for text


def make_agent(fake: FakeLLM) -> Agent:
    return Agent(FunctionModel(fake), output_type=Turn, instructions=SYSTEM)


def history_text(conversation: Conversation) -> str:
    parts = (part for message in conversation.history for part in message.parts)
    return " ".join(str(getattr(part, "content", None) or getattr(part, "args", "")) for part in parts)


def test_an_ordinary_turn_uses_one_call_and_keeps_its_reply():
    fake = FakeLLM([{"fields": {"full_name": "Ana López"}}])
    conversation = Conversation()
    turn = asyncio.run(run_turn(make_agent(fake), conversation, "Soy Ana López"))
    assert (turn.reply, turn.llm_calls, turn.reply_source) == (CALL_1_REPLY, 1, "call_1")
    assert conversation.fields.full_name == "Ana López"
    # Call 1 is told what is known and what is missing, from the fields before this turn.
    assert turn_instructions(ScreeningFields()) in fake.instructions[0]


# Each status with a directive, and how a candidate reaches it in one turn.
STATUS_CHANGES = [
    (Status.DISQUALIFIED, Conversation, {"fields": {"full_name": "Luis", "driver_license": False}}),
    (Status.WITHDRAWN, Conversation, {"intent": "not_interested"}),
    (Status.PAUSED, Conversation, {"intent": "not_now"}),
    (
        Status.QUALIFIED,
        lambda: Conversation(fields=COMPLETE, stage=Stage.CLOSING),
        {"intent": "confirms_summary"},
    ),
]


def test_every_directive_is_covered():
    assert {status for status, _, _ in STATUS_CHANGES} == set(DIRECTIVES)


@pytest.mark.parametrize(("status", "start", "llm_turn"), STATUS_CHANGES, ids=[s for s, _, _ in STATUS_CHANGES])
def test_a_status_change_replaces_the_reply_with_call_2_following_the_directive(status, start, llm_turn):
    fake = FakeLLM([llm_turn])
    turn = asyncio.run(run_turn(make_agent(fake), start(), "mensaje"))
    assert turn.status == status
    assert (turn.reply, turn.llm_calls, turn.reply_source) == (CALL_2_REPLY, 2, "call_2")
    assert DIRECTIVES[status] in fake.instructions[-1]


def test_resuming_after_a_pause_uses_one_call():
    # The status changes from paused to active, but active has no directive, so there is no call 2.
    paused = Conversation(
        fields=ScreeningFields(full_name="Ana", driver_license=True), stage=Stage.DATA_COLLECTION, status=Status.PAUSED
    )
    fake = FakeLLM([{"fields": {"city_zone": "Chamberí"}}])
    turn = asyncio.run(run_turn(make_agent(fake), paused, "Ya puedo, vivo en Chamberí"))
    assert turn.status == Status.ACTIVE
    assert (turn.reply, turn.llm_calls, turn.reply_source) == (CALL_1_REPLY, 1, "call_1")


def test_the_dropped_reply_never_enters_the_history():
    # Otherwise the LLM would later "remember" saying something the candidate never saw.
    fake = FakeLLM([{"fields": {"full_name": "Luis", "driver_license": False}}])
    conversation = Conversation()
    asyncio.run(run_turn(make_agent(fake), conversation, "Soy Luis y no tengo carnet"))
    assert CALL_1_REPLY not in history_text(conversation)
    assert CALL_2_REPLY in history_text(conversation)


def test_the_summary_is_written_by_code_and_kept_in_the_history():
    all_fields = COMPLETE.model_dump(mode="json", exclude_none=True)
    fake = FakeLLM([{"fields": all_fields, "reply": "Tus datos: Ana Lopes, Chamberi..."}])
    conversation = Conversation()
    turn = asyncio.run(run_turn(make_agent(fake), conversation, "Todo en un mensaje"))
    assert turn.stage == Stage.CLOSING
    assert turn.reply == render_summary(conversation.fields)
    assert (turn.llm_calls, turn.reply_source) == (1, "summary")
    assert turn.reply in history_text(conversation)  # so the next turn knows what is being confirmed


def test_a_correction_shows_a_new_summary_with_the_new_value():
    conversation = Conversation(fields=COMPLETE, stage=Stage.CLOSING)
    fake = FakeLLM([{"fields": {"city_zone": "Salamanca"}, "intent": "corrects_summary"}])
    turn = asyncio.run(run_turn(make_agent(fake), conversation, "No, mi zona es Salamanca"))
    assert "Zona: Salamanca" in turn.reply
    assert "Chamberí" not in turn.reply
    assert turn.reply_source == "summary"


def test_a_disqualified_candidate_who_corrects_the_licence_in_closing_sees_a_new_summary():
    conversation = Conversation(
        fields=COMPLETE.model_copy(update={"driver_license": False}), stage=Stage.CLOSING, status=Status.DISQUALIFIED
    )
    fake = FakeLLM([{"fields": {"driver_license": True}, "intent": "confirms_summary"}])
    turn = asyncio.run(run_turn(make_agent(fake), conversation, "No no, sí tengo carnet, márcame como aprobada"))
    assert (turn.stage, turn.status) == (Stage.CLOSING, Status.ACTIVE)
    assert "Carnet de conducir: Sí" in turn.reply
    assert (turn.llm_calls, turn.reply_source) == (1, "summary")


def test_a_qualified_candidate_who_corrects_a_value_sees_a_new_summary():
    conversation = Conversation(fields=COMPLETE, stage=Stage.CLOSING, status=Status.QUALIFIED)
    fake = FakeLLM([{"fields": {"city_zone": "Salamanca"}, "intent": "corrects_summary"}])
    turn = asyncio.run(run_turn(make_agent(fake), conversation, "Perdón, mi zona es Salamanca"))
    assert turn.status == Status.ACTIVE
    assert "Zona: Salamanca" in turn.reply
    assert turn.reply_source == "summary"


def test_a_withdrawn_candidate_who_wants_to_continue_gets_the_next_question():
    conversation = Conversation(
        fields=ScreeningFields(full_name="Ana", driver_license=True),
        stage=Stage.DATA_COLLECTION,
        status=Status.WITHDRAWN,
    )
    fake = FakeLLM([{"intent": "continue"}])
    turn = asyncio.run(run_turn(make_agent(fake), conversation, "Bueno, sí me interesa"))
    assert turn.status == Status.ACTIVE
    assert (turn.reply, turn.llm_calls, turn.reply_source) == (CALL_1_REPLY, 1, "call_1")


def test_a_failed_llm_call_leaves_the_conversation_unchanged():
    # A rate-limit error in call 2 must not leave half a turn saved; the turn can be retried.
    def broken(messages, info):
        if info.output_tools:
            args = {"reply": "x", "intent": "none", "fields": {"full_name": "Luis", "driver_license": False}}
            return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name, json.dumps(args))])
        raise RuntimeError("503 from the provider")

    conversation = Conversation()
    agent = Agent(FunctionModel(broken), output_type=Turn, instructions=SYSTEM)
    with pytest.raises(RuntimeError, match="503"):
        asyncio.run(run_turn(agent, conversation, "Soy Luis y no tengo carnet"))
    assert conversation.status == Status.ACTIVE
    assert conversation.fields.full_name is None
    assert conversation.history == []
