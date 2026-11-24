"""SQLite storage: a saved conversation loads back the same and can continue."""

import asyncio
import sqlite3

import pytest

from test_failures import FailingLLM, http
from test_turn import COMPLETE, FakeLLM, make_agent
from zonia.config import GREETING
from zonia.models import Stage, Status
from zonia import storage as storage_module
from zonia.storage import Storage
from zonia.turn import FAILURE_REPLY, Conversation, new_conversation, run_turn, run_turn_safely


@pytest.fixture
def storage(tmp_path):
    s = Storage(tmp_path / "zonia.db")
    yield s
    s.close()


def test_a_new_conversation_loads_back_the_same(storage):
    conversation = Conversation(
        fields=COMPLETE, stage=Stage.CLOSING, status=Status.DISQUALIFIED, country="MX", failed_turns=2, case_code="K7PX-3QMD", turns=7, language="en", followup_step=2,
    )
    loaded = storage.load(storage.create(conversation))
    assert loaded == conversation


def test_after_a_turn_the_saved_conversation_has_the_new_state_and_history(storage):
    fake = FakeLLM([{"fields": {"full_name": "Ana López"}}])
    conversation = Conversation()
    conversation_id = storage.create(conversation)
    turn = asyncio.run(run_turn(make_agent(fake), conversation, "Soy Ana López"))
    storage.save_turn(conversation_id, conversation, turn)

    loaded = storage.load(conversation_id)
    assert loaded == conversation
    assert loaded.fields.full_name == "Ana López"
    assert loaded.stage == Stage.DATA_COLLECTION


def test_a_loaded_conversation_continues_without_asking_again(storage):
    fake = FakeLLM([{"fields": {"full_name": "Ana López"}}, {"fields": {"driver_license": True}}])
    agent = make_agent(fake)
    first = Conversation()
    conversation_id = storage.create(first)
    storage.save_turn(conversation_id, first, asyncio.run(run_turn(agent, first, "Soy Ana López")))

    # A new process: only the database is left.
    second = storage.load(conversation_id)
    storage.save_turn(conversation_id, second, asyncio.run(run_turn(agent, second, "Sí, tengo carnet")))

    loaded = storage.load(conversation_id)
    assert (loaded.fields.full_name, loaded.fields.driver_license) == ("Ana López", True)
    assert loaded.stage == Stage.DATA_COLLECTION
    # The second turn's history starts with the whole first turn.
    assert loaded.history[: len(first.history)] == first.history
    # The second turn was told the name is already known, so it does not ask for it again.
    assert "Ana López" in fake.instructions[1]


def test_messages_are_kept_in_order(storage):
    fake = FakeLLM([{"fields": {"full_name": "Ana López"}}, {"fields": {"driver_license": True}}])
    agent = make_agent(fake)
    conversation = Conversation()
    conversation_id = storage.create(conversation)
    for text in ["Soy Ana López", "Sí, tengo carnet"]:
        storage.save_turn(conversation_id, conversation, asyncio.run(run_turn(agent, conversation, text)))

    assert storage.messages(conversation_id) == [
        ("candidate", "Soy Ana López"),
        ("agent", "CALL-1 REPLY"),
        ("candidate", "Sí, tengo carnet"),
        ("agent", "CALL-1 REPLY"),
    ]


def test_a_failed_turn_keeps_the_candidate_message_and_the_failure_count(storage):
    conversation = Conversation()
    conversation_id = storage.create(conversation)
    turn = asyncio.run(run_turn_safely(make_agent(FailingLLM([http(400)])), conversation, "Soy Ana López"))
    storage.save_turn(conversation_id, conversation, turn)

    assert storage.messages(conversation_id) == [("candidate", "Soy Ana López"), ("agent", FAILURE_REPLY["es"])]
    assert storage.load(conversation_id).failed_turns == 1


def test_the_greeting_is_saved_as_sonias_first_messages(storage):
    conversation = new_conversation()
    conversation_id = storage.create(conversation, GREETING)
    assert storage.messages(conversation_id) == [("agent", text) for text in GREETING]
    assert storage.load(conversation_id) == conversation


def test_a_new_conversation_gets_a_case_code(storage):
    conversation = Conversation()
    conversation_id = storage.create(conversation)
    assert conversation.case_code is not None
    assert storage.load(conversation_id).case_code == conversation.case_code


def test_a_repeated_case_code_is_replaced_before_it_is_saved(storage, monkeypatch):
    storage.create(Conversation(case_code="AAAA-AAAA"))
    codes = iter(["AAAA-AAAA", "BBBB-BBBB"])
    monkeypatch.setattr(storage_module, "new_case_code", lambda: next(codes))
    conversation = Conversation()
    conversation_id = storage.create(conversation)
    assert storage.load(conversation_id).case_code == conversation.case_code == "BBBB-BBBB"


def test_a_repeated_case_code_given_by_the_caller_is_rejected(storage):
    storage.create(Conversation(case_code="AAAA-AAAA"))
    with pytest.raises(sqlite3.IntegrityError):
        storage.create(Conversation(case_code="AAAA-AAAA"))


def test_an_unknown_id_raises_key_error(storage):
    with pytest.raises(KeyError):
        storage.load(999)


def test_with_block_closes_the_connection(tmp_path):
    with Storage(tmp_path / "zonia.db") as s:
        s.create(new_conversation("ES"))
    with pytest.raises(sqlite3.ProgrammingError):
        s.db.execute("SELECT 1")


def test_with_block_closes_the_connection_after_an_error(tmp_path):
    with pytest.raises(KeyError):
        with Storage(tmp_path / "zonia.db") as s:
            s.load(999)
    with pytest.raises(sqlite3.ProgrammingError):
        s.db.execute("SELECT 1")
