"""Web chat: the candidate applies with a phone number on the mock job page, then chats with Sonia in the browser.

No network: a fake LLM. The WhatsApp sender is never called here.
"""

import pytest
from fastapi.testclient import TestClient

from test_turn import FakeLLM, make_agent
from test_whatsapp import FakeSender
from zonia.adapters.http import PHONE_ERROR, country_for, create_app
from zonia.config import GREETING, JOB_FACTS
from zonia.storage import Storage


@pytest.fixture
def db(tmp_path):
    return tmp_path / "zonia.db"


def client(db, fake: FakeLLM) -> TestClient:
    return TestClient(create_app(db, make_agent(fake), FakeSender(), "secret", "verify"), follow_redirects=False)


def apply(test_client: TestClient, phone: str) -> str:
    """Applies with phone and returns the chat URL."""
    response = test_client.post("/applications", data={"phone": phone})
    assert response.status_code == 303
    return response.headers["location"]


def test_the_apply_page_shows_the_job_facts_and_the_phone_field(db):
    page = client(db, FakeLLM([])).get("/apply")
    assert page.status_code == 200
    assert all(fact in page.text for fact in JOB_FACTS)
    assert 'name="phone"' in page.text


def test_a_spanish_phone_opens_a_spanish_conversation_with_the_greeting(db):
    chat_url = apply(client(db, FakeLLM([])), "+34 600 111 222")
    storage = Storage(db)
    conversation_id = storage.find_by_phone("+34600111222")
    conversation = storage.load(conversation_id)
    assert conversation.country == "ES"
    assert chat_url == f"/chat/{conversation.case_code}"
    assert storage.messages(conversation_id) == [("agent", text) for text in GREETING]


def test_a_mexican_phone_opens_a_mexican_conversation(db):
    apply(client(db, FakeLLM([])), "+52 (55) 1234-5678")
    storage = Storage(db)
    assert storage.load(storage.find_by_phone("+525512345678")).country == "MX"


def test_another_prefix_shows_the_error_and_opens_no_conversation(db):
    response = client(db, FakeLLM([])).post("/applications", data={"phone": "+56 9 6346 0381"})
    assert response.status_code == 422
    assert PHONE_ERROR in response.text
    assert Storage(db).conversations() == []


def test_the_chat_page_shows_the_greeting(db):
    test_client = client(db, FakeLLM([]))
    page = test_client.get(apply(test_client, "+34600111222"))
    assert page.status_code == 200
    assert GREETING[0] in page.text


def test_a_chat_message_runs_a_turn_and_the_reply_is_returned_and_saved(db):
    fake = FakeLLM([{"fields": {"full_name": "Ana López"}, "reply": "Gracias, Ana. ¿Tienes carné de conducir?"}])
    test_client = client(db, fake)
    chat_url = apply(test_client, "+34600111222")
    response = test_client.post(f"{chat_url}/messages", data={"text": "Soy Ana López"})
    assert response.json() == {"reply": "Gracias, Ana. ¿Tienes carné de conducir?"}
    storage = Storage(db)
    conversation_id = storage.find_by_phone("+34600111222")
    assert storage.load(conversation_id).fields.full_name == "Ana López"
    assert storage.messages(conversation_id)[-2:] == [("candidate", "Soy Ana López"), ("agent", response.json()["reply"])]


def test_an_unknown_case_code_is_not_found(db):
    test_client = client(db, FakeLLM([{}]))
    assert test_client.get("/chat/AAAA-BBBB").status_code == 404
    assert test_client.post("/chat/AAAA-BBBB/messages", data={"text": "Hola"}).status_code == 404


def test_an_empty_message_runs_no_turn(db):
    fake = FakeLLM([{}])
    test_client = client(db, fake)
    chat_url = apply(test_client, "+34600111222")
    assert test_client.post(f"{chat_url}/messages", data={"text": "   "}).status_code == 422
    assert fake.instructions == []


def test_a_phone_needs_the_right_number_of_digits_for_its_country():
    assert country_for("+34 600-111-222") == ("ES", "+34600111222")
    assert country_for("+34 60011122") is None
    assert country_for("600111222") is None
