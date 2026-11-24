"""Follow-ups when the candidate stops replying (design 4.1), with a fake clock: no waiting, no LLM."""

import asyncio
from datetime import UTC, datetime, timedelta

import pytest

from test_turn import FakeLLM, make_agent
from zonia.config import GREETING
from zonia.config import NO_REPLY_REMINDER
from zonia.followups import run_followups
from zonia.texts.replies import reminder_text
from zonia.domain.models import ScreeningFields, Stage, Status
from zonia.storage import Storage
from zonia.domain.conversation import Conversation, new_conversation
from zonia.agent.safety import run_turn_safely

START = datetime(2026, 11, 22, 9, 0, tzinfo=UTC)


class Clock:
    def __init__(self):
        self.now = START

    def __call__(self) -> datetime:
        return self.now

    def at(self, **delta) -> datetime:
        """Move the clock to START + delta and return it."""
        self.now = START + timedelta(**delta)
        return self.now


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def storage(tmp_path, clock):
    s = Storage(tmp_path / "zonia.db", clock=clock)
    yield s
    s.close()


def started(storage: Storage, llm_turn: dict | None = None, text: str = "Soy Ana López") -> int:
    """A saved conversation where the candidate answered once, at START."""
    conversation = new_conversation("ES")
    conversation_id = storage.create(conversation, GREETING)
    fake = FakeLLM([llm_turn or {"fields": {"full_name": "Ana López"}}])
    turn = asyncio.run(run_turn_safely(make_agent(fake), conversation, text))
    storage.save_turn(conversation_id, conversation, turn.message, turn.reply)
    return conversation_id


def steps(storage: Storage, clock: Clock, **delta) -> list[str]:
    return [f.step for f in run_followups(storage, clock.at(**delta))]


# --- A. The candidate stops in the middle of the conversation ---


def test_each_step_happens_at_its_time_and_only_once(storage, clock):
    conversation_id = started(storage)
    assert steps(storage, clock, minutes=9) == []
    assert steps(storage, clock, minutes=10) == ["reminder"]
    assert steps(storage, clock, minutes=11) == []
    assert steps(storage, clock, minutes=30) == ["pause"]
    assert storage.load(conversation_id).status == Status.PAUSED
    assert steps(storage, clock, hours=20) == ["reminder"]
    assert steps(storage, clock, hours=24) == ["incomplete"]
    assert storage.load(conversation_id).status == Status.INCOMPLETE
    assert steps(storage, clock, hours=48) == []  # incomplete is final: no more steps


def test_a_conversation_with_a_technical_error_gets_no_follow_ups(storage, clock):
    conversation_id = started(storage)
    conversation = storage.load(conversation_id)
    conversation.status = Status.TECHNICAL_ERROR
    storage.save_followup(conversation_id, conversation, None)
    assert steps(storage, clock, minutes=10) == []
    assert steps(storage, clock, hours=24) == []
    assert storage.load(conversation_id).status == Status.TECHNICAL_ERROR


def test_a_reminder_names_what_is_missing_and_is_saved_and_kept_in_the_history(storage, clock):
    conversation_id = started(storage)
    [followup] = run_followups(storage, clock.at(minutes=10))
    assert followup.reminder == "¿Seguimos, Ana? Lo siguiente es saber si tienes carné de conducir."
    assert storage.messages(conversation_id)[-1] == ("agent", followup.reminder)
    history = storage.load(conversation_id).history
    assert history[-1].parts[0].content == followup.reminder  # the LLM sees it on the next turn


def test_when_the_check_ran_late_only_the_last_step_that_is_due_happens(storage, clock):
    conversation_id = started(storage)
    assert steps(storage, clock, hours=25) == ["incomplete"]
    before = len(storage.messages(conversation_id))
    assert steps(storage, clock, hours=26) == []
    assert len(storage.messages(conversation_id)) == before == len(GREETING) + 2  # greeting, one turn, no reminders


def test_a_candidate_message_starts_the_follow_ups_again(storage, clock):
    conversation_id = started(storage)
    assert steps(storage, clock, minutes=30) == ["pause"]
    conversation = storage.load(conversation_id)
    fake = FakeLLM([{"fields": {"driver_license": True}}])
    turn = asyncio.run(run_turn_safely(make_agent(fake), conversation, "Sí, tengo carné"))
    storage.save_turn(conversation_id, conversation, turn.message, turn.reply)  # at minute 30
    assert storage.load(conversation_id).status == Status.ACTIVE
    assert steps(storage, clock, minutes=39) == []
    assert steps(storage, clock, minutes=40) == ["reminder"]


def test_not_now_skips_reminder_1_and_the_pause(storage, clock):
    conversation_id = started(storage, {"fields": {"full_name": "Ana López"}, "intent": "not_now"}, "Ahora no puedo")
    assert storage.load(conversation_id).status == Status.PAUSED
    assert steps(storage, clock, minutes=30) == []
    assert steps(storage, clock, hours=20) == ["reminder"]
    assert steps(storage, clock, hours=24) == ["incomplete"]


def test_a_final_status_gets_no_follow_ups(storage, clock):
    started(storage, {"fields": {"full_name": "Luis", "driver_license": False}}, "No tengo carné")
    assert steps(storage, clock, hours=24) == []


# --- B. The candidate never answers the greeting ---


def test_no_reply_to_the_greeting_gets_one_reminder_at_3_hours_then_incomplete(storage, clock):
    conversation_id = storage.create(new_conversation("ES"), GREETING)
    assert steps(storage, clock, hours=2, minutes=59) == []
    assert steps(storage, clock, hours=3) == ["reminder"]
    assert storage.messages(conversation_id)[-1] == ("agent", NO_REPLY_REMINDER)
    assert steps(storage, clock, hours=23) == []
    assert steps(storage, clock, hours=24) == ["incomplete"]


# --- The reminder text ---


def test_the_reminder_says_only_when_one_thing_is_left():
    fields = ScreeningFields(
        full_name="Ana López", driver_license=True, city_zone="Chamberí", service_zone="Comunidad de Madrid",
        availability=["full-time"], schedule=["morning"], experience_years=0,
    )
    assert reminder_text(Conversation(fields=fields, turns=3)) == "¿Seguimos, Ana? Solo falta tu fecha de inicio."


def test_the_reminder_in_closing_asks_to_confirm():
    conversation = Conversation(fields=ScreeningFields(full_name="Ana López"), stage=Stage.CLOSING, turns=5)
    conversation.fields = conversation.fields.model_copy(update={
        "driver_license": True, "city_zone": "Chamberí", "service_zone": "Comunidad de Madrid",
        "availability": ["full-time"], "schedule": ["morning"], "experience_years": 0,
        "start_date": START.date() + timedelta(days=10),
    })
    assert reminder_text(conversation) == "¿Seguimos, Ana? Solo falta que confirmes tus datos."


def test_the_reminder_uses_the_language_and_the_words_of_the_country():
    mexico = Conversation(fields=ScreeningFields(full_name="Luis Pérez"), country="MX", turns=1)
    assert reminder_text(mexico) == "¿Seguimos, Luis? Lo siguiente es saber si tienes licencia de manejo."
    english = Conversation(fields=ScreeningFields(full_name="Ana López"), language="en", turns=1)
    assert reminder_text(english) == "Shall we continue, Ana? Next is whether you have a driving licence."
