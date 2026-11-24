"""Technical failures: run_turn_safely tries again, then answers with a fixed reply. It never raises."""

import asyncio

from pydantic_ai import Agent
from pydantic_ai.exceptions import ModelAPIError, ModelHTTPError
from pydantic_ai.models.function import FunctionModel

from test_turn import CALL_1_REPLY, FakeLLM, make_agent
from zonia.config import contact_email_for
from zonia.domain.models import ScreeningFields, Status, Turn
from zonia.prompt import SYSTEM
from zonia.domain.conversation import Conversation
from zonia.turn import FAILURE_REPLY, RETRY_DELAYS, run_turn_safely


class FailingLLM(FakeLLM):
    """Raises the given errors first, one per LLM call, then answers like FakeLLM."""

    def __init__(self, errors: list[Exception], turns: list[dict] | None = None):
        super().__init__(turns or [])
        self.errors = list(errors)
        self.calls = 0

    def __call__(self, messages, info):
        self.calls += 1
        if self.errors:
            raise self.errors.pop(0)
        return super().__call__(messages, info)


def http(status_code: int) -> ModelHTTPError:
    return ModelHTTPError(status_code=status_code, model_name="fake")


def run(fake: FakeLLM, conversation: Conversation, text: str = "Soy Ana López", time_limit: float | None = None):
    waits: list[float] = []

    async def no_wait(seconds: float) -> None:
        waits.append(seconds)

    turn = asyncio.run(run_turn_safely(make_agent(fake), conversation, text, sleep=no_wait, time_limit=time_limit))
    return turn, waits


def test_a_rate_limit_is_tried_again_and_the_turn_succeeds():
    fake = FailingLLM([http(429), http(429)], [{"fields": {"full_name": "Ana López"}}])
    conversation = Conversation()
    turn, waits = run(fake, conversation)
    assert (turn.reply, turn.reply_source) == (CALL_1_REPLY, "call_1")
    assert conversation.fields.full_name == "Ana López"
    assert waits == RETRY_DELAYS[:2]


def test_the_provider_retry_after_is_used_and_capped():
    slow = ModelHTTPError(status_code=429, model_name="fake", retry_after=600)
    fast = ModelHTTPError(status_code=503, model_name="fake", retry_after=3)
    fake = FailingLLM([slow, fast], [{"fields": {"full_name": "Ana López"}}])
    _, waits = run(fake, Conversation())
    assert waits == [30, 3]


def test_a_connection_failure_is_tried_again():
    fake = FailingLLM([ModelAPIError(model_name="fake", message="connection reset")], [{}])
    turn, _ = run(fake, Conversation())
    assert turn.reply_source == "call_1"


def test_a_server_error_that_never_passes_gives_the_failure_reply_and_changes_nothing():
    fake = FailingLLM([http(503)] * 10)
    conversation = Conversation(fields=ScreeningFields(full_name="Ana López"))
    turn, waits = run(fake, conversation, "Sí, tengo carnet")
    assert (turn.reply, turn.reply_source, turn.llm_calls) == (FAILURE_REPLY["es"], "fallback", 0)
    assert fake.calls == len(RETRY_DELAYS) + 1
    assert len(waits) == len(RETRY_DELAYS)
    assert conversation.fields == ScreeningFields(full_name="Ana López")
    assert conversation.history == []
    assert conversation.failed_turns == 1


def test_a_bad_request_is_not_tried_again():
    fake = FailingLLM([http(400)])
    turn, waits = run(fake, Conversation())
    assert turn.reply_source == "fallback"
    assert (fake.calls, waits) == (1, [])


def test_a_zone_outside_the_list_twice_gives_the_failure_reply():
    jalisco = {"fields": {"city_zone": "Guadalajara", "service_zone": "Jalisco"}}
    conversation = Conversation(fields=ScreeningFields(full_name="Luis", driver_license=True), country="ES")
    turn, _ = run(FailingLLM([], [jalisco, jalisco]), conversation, "Vivo en Guadalajara")
    assert turn.reply_source == "fallback"
    assert conversation.fields.service_zone is None


def test_the_second_failure_in_a_row_gives_the_contact_email_of_the_country():
    conversation = Conversation(country="MX")
    first, _ = run(FailingLLM([http(400)]), conversation)
    second, _ = run(FailingLLM([http(400)]), conversation)
    assert first.reply == FAILURE_REPLY["es"]
    assert contact_email_for("MX") in second.reply
    assert conversation.failed_turns == 2
    assert first.status == Status.ACTIVE
    assert second.status == Status.TECHNICAL_ERROR


def test_a_good_turn_after_a_technical_error_makes_the_conversation_active_again():
    conversation = Conversation()
    run(FailingLLM([http(400)]), conversation)
    run(FailingLLM([http(400)]), conversation)
    turn, _ = run(FailingLLM([], [{}]), conversation)
    assert turn.status == Status.ACTIVE
    assert conversation.status == Status.ACTIVE


def test_two_failures_keep_a_final_status():
    conversation = Conversation(status=Status.QUALIFIED)
    run(FailingLLM([http(400)]), conversation)
    second, _ = run(FailingLLM([http(400)]), conversation)
    assert second.status == Status.QUALIFIED


def test_a_turn_that_succeeds_resets_the_failures():
    conversation = Conversation()
    run(FailingLLM([http(400)]), conversation)
    run(FailingLLM([], [{}]), conversation)
    assert conversation.failed_turns == 0
    third, _ = run(FailingLLM([http(400)]), conversation)
    assert third.reply == FAILURE_REPLY["es"]


def test_an_llm_that_does_not_answer_in_the_time_limit_gives_the_failure_reply_and_changes_nothing():
    async def hang(messages, info):
        await asyncio.sleep(10)

    conversation = Conversation(fields=ScreeningFields(full_name="Ana López"))
    agent = Agent(FunctionModel(hang), output_type=Turn, instructions=SYSTEM)
    turn = asyncio.run(run_turn_safely(agent, conversation, "Sí, tengo carnet", time_limit=0.05))
    assert (turn.reply, turn.reply_source) == (FAILURE_REPLY["es"], "fallback")
    assert conversation.fields == ScreeningFields(full_name="Ana López")
    assert conversation.history == []
    assert conversation.failed_turns == 1


def test_no_new_try_starts_when_its_wait_passes_the_time_limit():
    fake = FailingLLM([http(503)] * 10)
    turn, waits = run(fake, Conversation(), time_limit=1.5)
    assert turn.reply_source == "fallback"
    assert (fake.calls, waits) == (2, [1])
