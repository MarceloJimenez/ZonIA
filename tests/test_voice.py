"""Voice: ElevenLabs calls /voice/chat/completions as its custom LLM, with the case code as extra body.

No network: a fake LLM. The request shape is the one a probe server logged on 2026-11-23.
"""

import json

import pytest
from fastapi.testclient import TestClient

from test_turn import FakeLLM, make_agent
from test_whatsapp import FakeSender
from zonia.adapters.app import create_app
from zonia.config import GREETING
from zonia.storage import Storage

KEY = "voice-key"
AUTH = {"authorization": f"Bearer {KEY}"}


@pytest.fixture
def db(tmp_path):
    return tmp_path / "zonia.db"


def client(db, fake: FakeLLM) -> TestClient:
    app = create_app(db, make_agent(fake), FakeSender(), "secret", "verify", "agent_test", KEY)
    return TestClient(app, follow_redirects=False)


def apply(test_client: TestClient) -> str:
    """Applies with a Spanish phone and returns the case code."""
    response = test_client.post("/applications", data={"phone": "+34600111222", "country": "ES"})
    return response.headers["location"].removeprefix("/chat/")


def request_body(case_code: str, said: str) -> dict:
    return {
        "model": "sonia",
        "stream": True,
        "messages": [
            {"role": "system", "content": "The current date and time is Monday, 11:45"},
            {"role": "assistant", "content": " ".join(GREETING)},
            {"role": "user", "content": said},
        ],
        "elevenlabs_extra_body": {"case_code": case_code},
    }


def streamed_reply(response) -> str:
    """The reply text from the SSE lines: data: {chunk} ... data: [DONE]."""
    lines = [line.removeprefix("data: ") for line in response.text.splitlines() if line.startswith("data: ")]
    assert lines[-1] == "[DONE]"
    return "".join(json.loads(line)["choices"][0]["delta"].get("content", "") for line in lines[:-1])


def test_a_voice_request_runs_a_turn_and_streams_the_reply(db):
    fake = FakeLLM([{"fields": {"full_name": "Ana López"}, "reply": "Gracias, Ana. ¿Tienes carné de conducir?"}])
    test_client = client(db, fake)
    case_code = apply(test_client)
    response = test_client.post("/voice/chat/completions", json=request_body(case_code, "Soy Ana López"), headers=AUTH)
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert streamed_reply(response) == "Gracias, Ana. ¿Tienes carné de conducir?"
    storage = Storage(db)
    conversation_id = storage.find_by_case_code(case_code)
    assert storage.load(conversation_id).fields.full_name == "Ana López"
    assert storage.messages(conversation_id)[-2:] == [("candidate", "Soy Ana López"), ("agent", streamed_reply(response))]


def test_a_repeated_request_gets_the_same_reply_and_runs_no_second_turn(db):
    fake = FakeLLM([{"reply": "Gracias. ¿Tienes carné de conducir?"}])
    test_client = client(db, fake)
    case_code = apply(test_client)
    body = request_body(case_code, "Sí, seguimos")
    first = test_client.post("/voice/chat/completions", json=body, headers=AUTH)
    body["messages"][0]["content"] = "The current date and time is Monday, 11:46"  # the time can change between the two
    second = test_client.post("/voice/chat/completions", json=body, headers=AUTH)
    assert streamed_reply(second) == streamed_reply(first)
    assert len(fake.instructions) == 1
    storage = Storage(db)
    assert storage.messages(storage.find_by_case_code(case_code)).count(("candidate", "Sí, seguimos")) == 1


def test_a_request_without_the_key_is_refused(db):
    fake = FakeLLM([{}])
    test_client = client(db, fake)
    case_code = apply(test_client)
    body = request_body(case_code, "Hola")
    assert test_client.post("/voice/chat/completions", json=body).status_code == 401
    assert test_client.post("/voice/chat/completions", json=body, headers={"authorization": "Bearer wrong"}).status_code == 401
    assert fake.instructions == []


def test_with_no_key_configured_voice_is_off(db):
    app = create_app(db, make_agent(FakeLLM([{}])), FakeSender(), "secret", "verify")
    response = TestClient(app).post("/voice/chat/completions", json=request_body("AAAA-BBBB", "Hola"), headers={"authorization": "Bearer "})
    assert response.status_code == 401


def test_with_no_meta_variables_the_whatsapp_webhook_is_off(db):
    app = create_app(db, make_agent(FakeLLM([{}])), None)
    test_client = TestClient(app, follow_redirects=False)
    assert test_client.post("/webhooks/whatsapp", json={}).status_code == 404
    assert test_client.post("/applications", data={"phone": "+34600111222", "country": "ES"}).status_code == 303


def test_an_unknown_case_code_is_not_found(db):
    test_client = client(db, FakeLLM([{}]))
    response = test_client.post("/voice/chat/completions", json=request_body("AAAA-BBBB", "Hola"), headers=AUTH)
    assert response.status_code == 404
    assert test_client.get("/voice/AAAA-BBBB").status_code == 404


def first_message(page) -> str:
    """The first message Sonia says, from the page's JSON settings."""
    return json.loads(page.text.split("const settings = ")[1].split(";\n")[0])["firstMessage"]


def test_in_a_new_conversation_the_voice_page_starts_with_the_whole_greeting(db):
    test_client = client(db, FakeLLM([]))
    case_code = apply(test_client)
    page = test_client.get(f"/voice/{case_code}")
    assert page.status_code == 200
    assert "agent_test" in page.text
    assert case_code in page.text
    assert first_message(page) == " ".join(GREETING)


def test_after_the_candidate_answers_the_voice_page_starts_with_sonias_last_message(db):
    fake = FakeLLM([{"fields": {"full_name": "Ana López"}, "reply": "Gracias, Ana. ¿Tienes carné de conducir?"}])
    test_client = client(db, fake)
    case_code = apply(test_client)
    test_client.post(f"/chat/{case_code}/messages", data={"text": "Soy Ana López"})
    assert first_message(test_client.get(f"/voice/{case_code}")) == "Gracias, Ana. ¿Tienes carné de conducir?"


def test_applying_by_voice_opens_the_voice_page(db):
    response = client(db, FakeLLM([])).post("/applications", data={"phone": "+34600111222", "country": "ES", "channel": "voice"})
    assert response.status_code == 303
    assert response.headers["location"].startswith("/voice/")


def test_the_chat_and_voice_pages_link_back_to_the_job_page_not_to_each_other(db):
    test_client = client(db, FakeLLM([]))
    case_code = apply(test_client)
    chat_page = test_client.get(f"/chat/{case_code}").text
    voice_page = test_client.get(f"/voice/{case_code}").text
    assert 'href="/apply"' in chat_page and 'href="/apply"' in voice_page
    assert f'href="/voice/{case_code}"' not in chat_page
    assert f'href="/chat/{case_code}"' not in voice_page


def test_the_voice_page_has_the_turn_circle_and_the_call_controls(db):
    test_client = client(db, FakeLLM([]))
    page = test_client.get(f"/voice/{apply(test_client)}").text
    for control in ['id="orb"', 'id="start"', 'id="mute"', 'id="stop"']:
        assert control in page
