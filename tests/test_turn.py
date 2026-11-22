"""One turn, with a fake LLM: which reply the candidate sees, and what the history keeps.

FunctionModel (from Pydantic AI) replaces the real LLM. It answers call 1 with a
scripted Turn and call 2 with a fixed text, so these tests need no network.
"""

import asyncio
import json
from datetime import date, timedelta

import pytest
from pydantic_ai import Agent
from pydantic_ai.exceptions import UnexpectedModelBehavior
from pydantic_ai.messages import ModelResponse, TextPart, ToolCallPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

from zonia.config import GREETING, contact_email_for
from zonia.flow import render_summary
from zonia.models import ScreeningFields, Stage, Status, Turn
from zonia.prompt import DIRECTIVES, SYSTEM, ZONE_DIRECTIVE, turn_instructions
from zonia.turn import CASE_CODE_ALPHABET, Conversation, new_case_code, new_conversation, run_turn

CALL_1_REPLY = "CALL-1 REPLY"
CALL_2_REPLY = "CALL-2 REPLY"

START = date.today() + timedelta(days=10)

COMPLETE = ScreeningFields(
    full_name="Ana López", driver_license=True, city_zone="Chamberí", service_zone="Comunidad de Madrid", availability=["full-time"],
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
    assert turn_instructions(ScreeningFields(), date.today()) in fake.instructions[0]


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
    # A disqualification adds the review email and the case code after call 2's reply.
    assert turn.reply.startswith(CALL_2_REPLY)
    assert (turn.llm_calls, turn.reply_source) == (2, "call_2")
    assert DIRECTIVES[status] in fake.instructions[-1]


def test_resuming_after_a_pause_uses_one_call():
    # The status changes from paused to active, but active has no directive, so there is no call 2.
    paused = Conversation(
        fields=ScreeningFields(full_name="Ana", driver_license=True), stage=Stage.DATA_COLLECTION, status=Status.PAUSED
    )
    fake = FakeLLM([{"fields": {"city_zone": "Chamberí", "service_zone": "Comunidad de Madrid"}}])
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
    fake = FakeLLM([{"fields": {"city_zone": "Salamanca", "service_zone": "Comunidad de Madrid"}, "intent": "corrects_summary"}])
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
    fake = FakeLLM([{"fields": {"city_zone": "Salamanca", "service_zone": "Comunidad de Madrid"}, "intent": "corrects_summary"}])
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


# --- Service zones ----------------------------------------------------------


def test_a_place_outside_the_service_zones_disqualifies_with_the_zone_directive():
    fields = {"full_name": "Luis", "driver_license": True, "city_zone": "Salamanca", "service_zone": "outside"}
    fake = FakeLLM([{"fields": fields}])
    turn = asyncio.run(run_turn(make_agent(fake), Conversation(), "Soy Luis, tengo carnet y vivo en Salamanca"))
    assert turn.status == Status.DISQUALIFIED
    assert turn.reply.startswith(CALL_2_REPLY)
    assert turn.llm_calls == 2
    assert ZONE_DIRECTIVE in fake.instructions[-1]


def test_no_licence_wins_over_the_zone_in_the_directive():
    fields = {"full_name": "Luis", "driver_license": False, "city_zone": "Salamanca", "service_zone": "outside"}
    fake = FakeLLM([{"fields": fields}])
    asyncio.run(run_turn(make_agent(fake), Conversation(), "mensaje"))
    assert DIRECTIVES[Status.DISQUALIFIED] in fake.instructions[-1]


def test_a_service_zone_outside_the_list_is_rejected_and_the_llm_is_asked_again():
    # "Sevilla" is a place, not a service zone. Validation fails and Pydantic AI retries call 1.
    fake = FakeLLM([
        {"fields": {"city_zone": "Sevilla", "service_zone": "Sevilla"}},
        {"fields": {"city_zone": "Sevilla", "service_zone": "Andalucía"}},
    ])
    conversation = Conversation(fields=ScreeningFields(full_name="Ana", driver_license=True))
    turn = asyncio.run(run_turn(make_agent(fake), conversation, "Vivo en Sevilla"))
    assert (conversation.fields.city_zone, conversation.fields.service_zone) == ("Sevilla", "Andalucía")
    assert turn.status == Status.ACTIVE
    assert fake.turns == []  # both scripted answers were used


def test_a_place_without_a_service_zone_is_rejected_and_the_llm_is_asked_again():
    fake = FakeLLM([
        {"fields": {"city_zone": "Barcelona"}},
        {"fields": {"city_zone": "Barcelona", "service_zone": "Cataluña"}},
    ])
    conversation = Conversation(fields=ScreeningFields(full_name="Ana", driver_license=True))
    asyncio.run(run_turn(make_agent(fake), conversation, "Vivo en Barcelona"))
    assert conversation.fields.service_zone == "Cataluña"


def test_the_service_zones_depend_on_the_country():
    # Jalisco is a service zone in Mexico; in Spain it fails validation twice and the turn fails.
    jalisco = {"fields": {"city_zone": "Guadalajara", "service_zone": "Jalisco"}}
    mexico = Conversation(fields=ScreeningFields(full_name="Luis", driver_license=True), country="MX")
    asyncio.run(run_turn(make_agent(FakeLLM([jalisco])), mexico, "Vivo en Guadalajara"))
    assert mexico.fields.service_zone == "Jalisco"
    spain = Conversation(fields=ScreeningFields(full_name="Luis", driver_license=True), country="ES")
    with pytest.raises(UnexpectedModelBehavior):
        asyncio.run(run_turn(make_agent(FakeLLM([jalisco, jalisco])), spain, "Vivo en Guadalajara"))
    assert spain.fields.service_zone is None  # a failed turn changes nothing


def test_a_candidate_disqualified_by_zone_reopens_with_a_place_in_a_service_zone():
    conversation = Conversation(
        fields=COMPLETE.model_copy(update={"city_zone": "Salamanca", "service_zone": "outside"}),
        stage=Stage.CLOSING,
        status=Status.DISQUALIFIED,
    )
    fake = FakeLLM([{"fields": {"city_zone": "Vigo", "service_zone": "Galicia"}}])
    turn = asyncio.run(run_turn(make_agent(fake), conversation, "Perdón, vivo en Vigo"))
    assert (turn.status, turn.stage, turn.reply_source) == (Status.ACTIVE, Stage.CLOSING, "summary")
    assert "Zona: Vigo" in turn.reply


# --- Invalid values ---------------------------------------------------------
# The candidate's errors: code does not save the value, and call 2 asks again.


def test_an_invalid_value_is_not_saved_and_call_2_asks_again():
    past = (date.today() - timedelta(days=5)).isoformat()
    fake = FakeLLM([{"fields": {"start_date": past, "availability": ["full-time"]}}])
    conversation = Conversation(fields=ScreeningFields(full_name="Ana López", driver_license=True))
    turn = asyncio.run(run_turn(make_agent(fake), conversation, "Tiempo completo, empiezo el lunes pasado"))
    assert conversation.fields.start_date is None
    assert conversation.fields.availability == ["full-time"]  # the valid value in the same message is kept
    assert (turn.reply, turn.llm_calls, turn.invalid_fields) == (CALL_2_REPLY, 2, ["start_date"])
    assert "fecha en que puede empezar" in fake.instructions[-1]


def test_an_invalid_correction_keeps_the_earlier_value():
    conversation = Conversation(fields=COMPLETE, stage=Stage.CLOSING)
    past = (date.today() - timedelta(days=5)).isoformat()
    fake = FakeLLM([{"fields": {"start_date": past}, "intent": "corrects_summary"}])
    turn = asyncio.run(run_turn(make_agent(fake), conversation, "No, empiezo el lunes pasado"))
    assert conversation.fields.start_date == START
    assert turn.reply_source == "call_2"  # not the summary: the candidate must hear what is wrong


def test_a_first_name_alone_keeps_the_candidate_in_introduction():
    fake = FakeLLM([{"fields": {"full_name": "Ana"}}])
    conversation = Conversation()
    turn = asyncio.run(run_turn(make_agent(fake), conversation, "Soy Ana"))
    assert conversation.fields.full_name is None
    assert (turn.stage, turn.reply_source) == (Stage.INTRODUCTION, "call_2")
    assert "apellido" in fake.instructions[-1]


def test_a_new_status_wins_over_an_invalid_value():
    fake = FakeLLM([{"fields": {"full_name": "Luis", "driver_license": False}}])
    turn = asyncio.run(run_turn(make_agent(fake), Conversation(), "Soy Luis y no tengo carnet"))
    assert turn.status == Status.DISQUALIFIED
    assert DIRECTIVES[Status.DISQUALIFIED] in fake.instructions[-1]


def test_call_1_is_told_today_s_date():
    fake = FakeLLM([{}])
    asyncio.run(run_turn(make_agent(fake), Conversation(), "Hola", today=date(2026, 11, 22)))
    assert "domingo, 22 de noviembre de 2026" in fake.instructions[0]


def test_a_new_conversation_starts_with_the_greeting_and_turn_1_keeps_it():
    conversation = new_conversation("MX")
    assert conversation.country == "MX"
    assert history_text(conversation) == "\n".join(GREETING)
    fake = FakeLLM([{"intent": "continue", "fields": {"full_name": "Ana López"}}])
    asyncio.run(run_turn(make_agent(fake), conversation, "Sí, soy Ana López"))
    # Turn 1 sends the greeting to the LLM, so the history still starts with it.
    assert history_text(conversation).startswith("\n".join(GREETING))
    assert conversation.stage == Stage.DATA_COLLECTION


NO_LICENCE = {"fields": {"full_name": "Luis", "driver_license": False}}


def test_a_disqualification_gives_the_review_email_and_a_case_code():
    conversation = Conversation(country="MX")
    turn = asyncio.run(run_turn(make_agent(FakeLLM([NO_LICENCE])), conversation, "Soy Luis y no tengo carnet"))
    code = conversation.case_code
    assert code is not None
    assert turn.reply.endswith(f"escribe a {contact_email_for('MX')} con el código {code}.")
    # The LLM sees what the candidate saw, code included.
    assert code in history_text(conversation)


def test_the_case_code_stays_the_same_when_disqualified_again():
    conversation = Conversation()
    licence = {"fields": {"driver_license": True}}
    fake = FakeLLM([NO_LICENCE, licence, {"fields": {"driver_license": False}}])
    agent = make_agent(fake)
    asyncio.run(run_turn(agent, conversation, "Soy Luis y no tengo carnet"))
    first = conversation.case_code
    asyncio.run(run_turn(agent, conversation, "Perdón, sí tengo carnet"))
    assert conversation.status == Status.ACTIVE
    turn = asyncio.run(run_turn(agent, conversation, "Bueno, en realidad no lo tengo"))
    assert conversation.case_code == first
    assert first in turn.reply


def test_other_status_changes_get_no_case_code():
    conversation = Conversation()
    turn = asyncio.run(run_turn(make_agent(FakeLLM([{"intent": "not_interested"}])), conversation, "No me interesa"))
    assert conversation.case_code is None
    assert turn.reply == CALL_2_REPLY


def test_a_case_code_has_8_characters_without_0_o_1_or_i():
    codes = {new_case_code() for _ in range(200)}
    assert len(codes) == 200
    for code in codes:
        assert len(code) == 9 and code[4] == "-"
        assert set(code.replace("-", "")) <= set(CASE_CODE_ALPHABET)
        assert not set(code) & set("0O1I")
