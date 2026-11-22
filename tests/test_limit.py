"""The turn limit: from message MAX_TURNS on, the LLM is not called and an open conversation ends."""

from test_failures import FailingLLM, http, run
from test_turn import COMPLETE
from zonia.config import MAX_TURNS, contact_email_for
from zonia.models import Stage, Status
from zonia.turn import Conversation


def test_the_messages_before_the_limit_run_as_usual():
    conversation = Conversation(turns=MAX_TURNS - 2)
    turn, _ = run(FailingLLM([], [{}]), conversation)
    assert (turn.reply_source, conversation.turns, conversation.status) == ("call_1", MAX_TURNS - 1, Status.ACTIVE)


def test_the_message_at_the_limit_ends_an_open_conversation_as_incomplete_without_the_llm():
    fake = FailingLLM([], [{}])
    conversation = Conversation(turns=MAX_TURNS - 1, country="MX")
    turn, _ = run(fake, conversation)
    assert fake.calls == 0
    assert (turn.reply_source, turn.llm_calls) == ("limit", 0)
    assert turn.status == conversation.status == Status.INCOMPLETE
    assert contact_email_for("MX") in turn.reply


def test_a_paused_conversation_at_the_limit_ends_as_incomplete():
    conversation = Conversation(turns=MAX_TURNS - 1, status=Status.PAUSED)
    run(FailingLLM([]), conversation)
    assert conversation.status == Status.INCOMPLETE


def test_a_final_status_is_kept_at_the_limit():
    conversation = Conversation(fields=COMPLETE, stage=Stage.CLOSING, status=Status.QUALIFIED, turns=MAX_TURNS - 1)
    turn, _ = run(FailingLLM([]), conversation)
    assert (turn.reply_source, conversation.status) == ("limit", Status.QUALIFIED)


def test_every_message_after_the_limit_gets_the_same_reply_and_no_llm_call():
    fake = FailingLLM([], [{}])
    conversation = Conversation(turns=MAX_TURNS + 5)
    first, _ = run(fake, conversation)
    second, _ = run(fake, conversation)
    assert first.reply == second.reply
    assert fake.calls == 0
    assert conversation.status == Status.INCOMPLETE  # a later message does not reopen it, unlike a time-out


def test_failed_turns_count_towards_the_limit():
    conversation = Conversation()
    run(FailingLLM([http(400)]), conversation)
    assert conversation.turns == 1
