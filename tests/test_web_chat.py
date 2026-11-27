"""Web chat: the candidate applies with a phone number on the mock job page, then chats with Sonia in the browser.

No network: a fake LLM. The WhatsApp sender is never called here.
"""

import time

import pytest
from fastapi.testclient import TestClient

from test_turn import FakeLLM, make_agent
from test_voice import FakeCheck
from test_whatsapp import FakeSender, hanging_agent
from zonia.adapters import conversations
from zonia.adapters.app import create_app
from zonia.adapters.web import COUNTRY_ERROR, DEMO_PHONE, DEMO_PHONES, PHONE_ERROR, international_phone
from zonia.config import GREETING, JOB_FACTS, zones_for
from zonia.storage import Storage
from zonia.texts.replies import FAILURE_REPLY


@pytest.fixture
def db(tmp_path):
    return tmp_path / "zonia.db"


def client(db, fake: FakeLLM, agent=None) -> TestClient:
    agent = agent or make_agent(fake)
    return TestClient(create_app(db, agent, FakeSender(), "secret", "verify", FakeCheck(), "voice-key"), follow_redirects=False)


def apply(test_client: TestClient, phone: str, country: str = "ES") -> str:
    """Applies with phone from country and returns the chat URL."""
    response = test_client.post("/applications", data={"phone": phone, "country": country})
    assert response.status_code == 303
    return response.headers["location"]


def test_the_apply_page_shows_the_job_facts_and_the_phone_field(db):
    page = client(db, FakeLLM([])).get("/apply")
    assert page.status_code == 200
    assert all(fact in page.text for fact in JOB_FACTS)
    assert 'name="phone"' in page.text
    assert 'name="channel" value="chat"' in page.text and 'name="channel" value="voice"' in page.text
    assert f'value="{DEMO_PHONE}"' in page.text
    assert international_phone(DEMO_PHONE) == "+34123456789"


def test_a_spanish_phone_opens_a_spanish_conversation_with_the_greeting(db):
    chat_url = apply(client(db, FakeLLM([])), "+34 600 111 222")
    storage = Storage(db)
    conversation_id = storage.find_by_phone("+34600111222")
    conversation = storage.load(conversation_id)
    assert conversation.country == "ES"
    assert chat_url == f"/chat/{conversation.case_code}"
    assert storage.messages(conversation_id) == [("agent", text) for text in GREETING]


def test_a_mexican_phone_opens_a_mexican_conversation(db):
    apply(client(db, FakeLLM([])), "+52 (55) 1234-5678", "MX")
    storage = Storage(db)
    assert storage.load(storage.find_by_phone("+525512345678")).country == "MX"


def test_a_phone_from_another_country_opens_a_conversation_in_the_chosen_country(db):
    test_client = client(db, FakeLLM([]))
    apply(test_client, "+56 9 6346 0381", "ES")  # a Chilean number, living in Spain
    apply(test_client, "+502 5123 4567", "MX")  # a Guatemalan number, living in Mexico
    storage = Storage(db)
    assert storage.load(storage.find_by_phone("+56963460381")).country == "ES"
    assert storage.load(storage.find_by_phone("+50251234567")).country == "MX"


def test_a_phone_with_no_prefix_shows_the_error_and_opens_no_conversation(db):
    response = client(db, FakeLLM([])).post("/applications", data={"phone": "600 111 222", "country": "ES"})
    assert response.status_code == 422
    assert PHONE_ERROR in response.text
    assert Storage(db).conversations() == []


def test_no_country_shows_the_error_and_opens_no_conversation(db):
    response = client(db, FakeLLM([])).post("/applications", data={"phone": "+34600111222"})
    assert response.status_code == 422
    assert COUNTRY_ERROR in response.text
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


def test_an_llm_that_does_not_answer_in_time_gives_the_failure_reply(db, monkeypatch):
    monkeypatch.setattr(conversations, "CHAT_TIME_LIMIT", 0.05)
    test_client = client(db, FakeLLM([]), hanging_agent())
    chat_url = apply(test_client, "+34600111222")
    started = time.monotonic()
    response = test_client.post(f"{chat_url}/messages", data={"text": "Soy Ana López"})
    assert time.monotonic() - started < 2  # the LLM would hang for 10 s
    assert response.json() == {"reply": FAILURE_REPLY["es"]}
    storage = Storage(db)
    assert storage.load(storage.find_by_phone("+34600111222")).fields.full_name is None


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


def test_a_phone_needs_a_prefix_and_8_to_15_digits():
    assert international_phone("+34 600-111-222") == "+34600111222"
    assert international_phone("+56 9 6346 0381") == "+56963460381"
    assert international_phone("+34 600") is None
    assert international_phone("+1234567890123456") is None
    assert international_phone("600111222") is None


def test_the_apply_page_shows_both_countries_with_their_service_zones(db):
    page = client(db, FakeLLM([])).get("/apply").text
    assert 'name="country" value="ES"' in page and 'name="country" value="MX"' in page
    assert all(zone in page for zone in zones_for("ES") + zones_for("MX"))
    assert international_phone(DEMO_PHONES["MX"]) == "+525512345678"


def test_the_chosen_country_opens_a_conversation_in_that_country(db):
    response = client(db, FakeLLM([])).post("/applications", data={"phone": "+52 55 1234 5678", "country": "MX"})
    assert response.status_code == 303
    storage = Storage(db)
    assert storage.load(storage.find_by_phone("+525512345678")).country == "MX"


def test_the_apply_page_and_the_chat_link_to_the_recruiter_dashboard(db, monkeypatch):
    monkeypatch.setenv("ZONIA_DASHBOARD_URL", "http://dashboard.test/")
    test_client = client(db, FakeLLM([]))
    assert '<a class="sz-demo__link" href="http://dashboard.test/" target="_blank" rel="noopener">' in test_client.get("/apply").text
    chat_url = apply(test_client, "+34 600 111 222")
    case_code = chat_url.rsplit("/", 1)[1]
    assert f'href="http://dashboard.test/?view=all&amp;q={case_code}" target="_blank"' in test_client.get(chat_url).text
