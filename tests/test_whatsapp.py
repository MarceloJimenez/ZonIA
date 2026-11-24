"""WhatsApp adapter: a Meta Cloud API webhook request becomes a turn, and the reply goes back through the sender.

No network: a fake LLM and a fake sender. The signatures are made like Meta makes them.
"""

import asyncio
import hashlib
import hmac
import json
import time

import pytest
from fastapi.testclient import TestClient
from pydantic_ai import Agent
from pydantic_ai.models.function import FunctionModel

from test_turn import FakeLLM, make_agent
from zonia.adapters import http
from zonia.adapters.http import WEBHOOK_PATH, create_app, e164
from zonia.config import GREETING
from zonia.storage import Storage
from zonia.domain.conversation import new_conversation
from zonia.texts.replies import FAILURE_REPLY, TEXT_ONLY_REPLY
from zonia.agent.llm import build_agent

SECRET = "test-app-secret"
VERIFY = "test-verify-token"
PHONE = "+34600111222"


class FakeSender:
    def __init__(self):
        self.sent: list[tuple[str, str]] = []

    def send(self, phone: str, text: str) -> None:
        self.sent.append((phone, text))


@pytest.fixture
def db(tmp_path):
    return tmp_path / "zonia.db"


@pytest.fixture
def applied(db) -> int:
    """A conversation for PHONE, as after an application: greeting sent, no answer yet."""
    storage = Storage(db)
    conversation_id = storage.create(new_conversation("ES"), GREETING, phone=PHONE)
    storage.close()
    return conversation_id


def hanging_agent() -> Agent:
    """An agent whose LLM never answers in time, like Gemini when it hangs."""
    async def hang(messages, info):
        await asyncio.sleep(10)

    return build_agent(FunctionModel(hang))


def client(db, fake: FakeLLM, sender: FakeSender, agent: Agent | None = None) -> TestClient:
    return TestClient(create_app(db, agent or make_agent(fake), sender, SECRET, VERIFY))


def post(test_client: TestClient, body: str = "Soy Ana López", message_id: str = "wamid.1", signed: bool = True, message: dict | None = None):
    """One webhook request, shaped like Meta's, with one message from PHONE."""
    message = message or {"from": PHONE.removeprefix("+"), "id": message_id, "type": "text", "text": {"body": body}}
    payload = {"object": "whatsapp_business_account", "entry": [{"changes": [{"field": "messages", "value": {"messages": [message]}}]}]}
    raw = json.dumps(payload).encode()
    signature = "sha256=" + hmac.new(SECRET.encode(), raw, hashlib.sha256).hexdigest() if signed else "sha256=wrong"
    return test_client.post(WEBHOOK_PATH, content=raw, headers={"X-Hub-Signature-256": signature, "Content-Type": "application/json"})


def test_meta_verifies_the_webhook_with_the_verify_token(db):
    test_client = client(db, FakeLLM([]), FakeSender())
    ok = test_client.get(WEBHOOK_PATH, params={"hub.mode": "subscribe", "hub.verify_token": VERIFY, "hub.challenge": "1234"})
    assert (ok.status_code, ok.text) == (200, "1234")
    wrong = test_client.get(WEBHOOK_PATH, params={"hub.mode": "subscribe", "hub.verify_token": "other", "hub.challenge": "1234"})
    assert wrong.status_code == 403


def test_a_message_runs_a_turn_and_the_reply_is_saved_and_sent(db, applied):
    sender = FakeSender()
    fake = FakeLLM([{"fields": {"full_name": "Ana López"}, "reply": "Gracias, Ana. ¿Tienes carné de conducir?"}])
    response = post(client(db, fake, sender))
    assert response.status_code == 200
    assert sender.sent == [(PHONE, "Gracias, Ana. ¿Tienes carné de conducir?")]
    storage = Storage(db)
    assert storage.load(applied).fields.full_name == "Ana López"
    assert storage.messages(applied)[-2:] == [("candidate", "Soy Ana López"), ("agent", sender.sent[0][1])]


def test_an_llm_that_does_not_answer_in_time_sends_the_failure_reply(db, applied, monkeypatch):
    monkeypatch.setattr(http, "CHAT_TIME_LIMIT", 0.05)
    sender = FakeSender()
    started = time.monotonic()
    response = post(client(db, FakeLLM([]), sender, hanging_agent()))
    assert time.monotonic() - started < 2  # the LLM would hang for 10 s
    assert response.status_code == 200
    assert sender.sent == [(PHONE, FAILURE_REPLY["es"])]
    storage = Storage(db)
    assert storage.load(applied).fields.full_name is None


def test_a_request_without_a_valid_signature_is_refused(db, applied):
    sender = FakeSender()
    fake = FakeLLM([{}])
    assert post(client(db, fake, sender), signed=False).status_code == 403
    assert sender.sent == []
    assert fake.instructions == []  # no LLM call


def test_the_same_message_sent_twice_runs_one_turn(db, applied):
    sender = FakeSender()
    fake = FakeLLM([{"fields": {"full_name": "Ana López"}}, {}])
    test_client = client(db, fake, sender)
    post(test_client, message_id="wamid.1")
    post(test_client, message_id="wamid.1")
    assert len(sender.sent) == 1
    assert len(fake.instructions) == 1
    assert Storage(db).load(applied).turns == 1


def test_a_phone_with_no_application_gets_no_reply(db):
    sender = FakeSender()
    fake = FakeLLM([{}])
    assert post(client(db, fake, sender)).status_code == 200
    assert sender.sent == []
    assert fake.instructions == []


def test_a_message_with_only_a_file_gets_the_text_only_reply_and_no_turn(db, applied):
    sender = FakeSender()
    fake = FakeLLM([{}])
    audio = {"from": PHONE.removeprefix("+"), "id": "wamid.2", "type": "audio", "audio": {"mime_type": "audio/ogg"}}
    post(client(db, fake, sender), message=audio)
    assert sender.sent == [(PHONE, TEXT_ONLY_REPLY["es"])]
    assert fake.instructions == []
    assert Storage(db).load(applied).turns == 0


def test_the_newest_conversation_of_the_phone_gets_the_message(db, applied):
    storage = Storage(db)
    newer = storage.create(new_conversation("ES"), GREETING, phone=PHONE)
    storage.close()
    post(client(db, FakeLLM([{"fields": {"full_name": "Ana López"}}]), FakeSender()))
    storage = Storage(db)
    assert storage.load(newer).turns == 1
    assert storage.load(applied).turns == 0


def test_a_mexican_mobile_with_the_extra_1_matches_the_application_phone():
    assert e164("5215512345678") == "+525512345678"
    assert e164("34600111222") == "+34600111222"
