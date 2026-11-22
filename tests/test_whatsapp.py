"""WhatsApp adapter: a Twilio webhook request becomes a turn, and the reply goes back through the sender.

No network: a fake LLM and a fake sender. The signatures are made with Twilio's own validator.
"""

import pytest
from fastapi.testclient import TestClient
from twilio.request_validator import RequestValidator

from test_turn import FakeLLM, make_agent
from zonia.adapters.http import TEXT_ONLY_REPLY, WEBHOOK_PATH, create_app
from zonia.config import GREETING
from zonia.storage import Storage
from zonia.turn import new_conversation

TOKEN = "test-auth-token"
PUBLIC_URL = "https://sonia.example.com"
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


def client(db, fake: FakeLLM, sender: FakeSender) -> TestClient:
    return TestClient(create_app(db, make_agent(fake), sender, TOKEN, PUBLIC_URL))


def post(test_client: TestClient, body: str = "Soy Ana López", sid: str = "SM1", signed: bool = True, **extra):
    form = {"From": f"whatsapp:{PHONE}", "Body": body, "MessageSid": sid, "NumMedia": "0", **extra}
    signature = RequestValidator(TOKEN).compute_signature(PUBLIC_URL + WEBHOOK_PATH, form) if signed else "wrong"
    return test_client.post(WEBHOOK_PATH, data=form, headers={"X-Twilio-Signature": signature})


def test_a_message_runs_a_turn_and_the_reply_is_saved_and_sent(db, applied):
    sender = FakeSender()
    fake = FakeLLM([{"fields": {"full_name": "Ana López"}, "reply": "Gracias, Ana. ¿Tienes carné de conducir?"}])
    response = post(client(db, fake, sender))
    assert response.status_code == 200
    assert sender.sent == [(PHONE, "Gracias, Ana. ¿Tienes carné de conducir?")]
    storage = Storage(db)
    assert storage.load(applied).fields.full_name == "Ana López"
    assert storage.messages(applied)[-2:] == [("candidate", "Soy Ana López"), ("agent", sender.sent[0][1])]


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
    post(test_client, sid="SM1")
    post(test_client, sid="SM1")
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
    post(client(db, fake, sender), body="", NumMedia="1", MediaContentType0="audio/ogg")
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
