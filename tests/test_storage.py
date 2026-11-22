"""SQLite storage: a saved conversation loads back the same and can continue."""

import asyncio

import pytest

from test_turn import COMPLETE, FakeLLM, make_agent
from zonia.models import Stage, Status
from zonia.storage import Storage
from zonia.turn import Conversation, run_turn


@pytest.fixture
def storage(tmp_path):
    s = Storage(tmp_path / "zonia.db")
    yield s
    s.close()


def test_a_new_conversation_loads_back_the_same(storage):
    conversation = Conversation(fields=COMPLETE, stage=Stage.CLOSING, status=Status.PAUSED, country="MX")
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


def test_an_unknown_id_raises_key_error(storage):
    with pytest.raises(KeyError):
        storage.load(999)
