"""Voice: ElevenLabs calls /voice/chat/completions as its custom LLM, with the case code as extra body.

No network: a fake LLM. The request shape is the one a probe server logged on 2026-11-23.
"""

import asyncio
import json

import httpx
import pytest
from fastapi.testclient import TestClient

from test_turn import FakeLLM, make_agent
from test_whatsapp import FakeSender
from zonia.adapters.app import create_app
from zonia.adapters.voice import VOICE_UNAVAILABLE_APPLY, VOICE_UNAVAILABLE_CALL, VoiceCheck
from zonia.config import GREETING, contact_email_for
from zonia.domain.models import Status
from zonia.storage import Storage
from zonia.texts.replies import CONTACT_REPLY

KEY = "voice-key"
AUTH = {"authorization": f"Bearer {KEY}"}


PUBLIC_URL = "https://public.test"


class FakeCheck(VoiceCheck):
    """The check before a call, with a fixed answer and no network."""

    def __init__(self, works: bool = True):
        super().__init__(PUBLIC_URL, "agent_test")
        self.works = works

    async def ready(self) -> bool:
        return self.works


@pytest.fixture
def db(tmp_path):
    return tmp_path / "zonia.db"


def client(db, fake: FakeLLM, check: VoiceCheck | None = None) -> TestClient:
    app = create_app(db, make_agent(fake), FakeSender(), "secret", "verify", check or FakeCheck(), KEY)
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
    assert response.status_code == 404  # without the ElevenLabs settings there is no voice route


def test_with_no_meta_variables_the_whatsapp_webhook_is_off(db):
    app = create_app(db, make_agent(FakeLLM([{}])), None)
    test_client = TestClient(app, follow_redirects=False)
    assert test_client.post("/webhooks/whatsapp", json={}).status_code == 404
    assert test_client.post("/applications", data={"phone": "+34600111222", "country": "ES"}).status_code == 303


def test_with_no_elevenlabs_settings_the_voice_button_is_disabled_with_a_note(db):
    test_client = TestClient(create_app(db, make_agent(FakeLLM([{}])), None), follow_redirects=False)
    page = test_client.get("/apply").text
    assert 'value="voice" disabled>' in page
    assert "La voz no está configurada" in page
    response = test_client.post("/applications", data={"phone": "+34600111222", "country": "ES", "channel": "voice"})
    assert response.headers["location"].startswith("/chat/")
    assert test_client.get(response.headers["location"].replace("/chat/", "/voice/")).status_code == 404


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


def settings_of(page) -> dict:
    """The voice page's JSON settings."""
    return json.loads(page.text.split("const settings = ")[1].split(";\n")[0])


def status_and_messages(db, case_code: str) -> tuple[str, list[tuple[str, str]]]:
    storage = Storage(db)
    conversation_id = storage.find_by_case_code(case_code)
    return storage.load(conversation_id).status, storage.messages(conversation_id)


def test_the_voice_page_carries_the_technical_problem_notice_with_the_countrys_email(db):
    test_client = client(db, FakeLLM([]))
    settings = settings_of(test_client.get(f"/voice/{apply(test_client)}"))
    assert settings["failureNotice"] == CONTACT_REPLY["es"].format(email=contact_email_for("ES"))
    assert settings["speechLang"] == "es-ES"


def test_a_broken_call_saves_sonias_notice_once_and_marks_a_technical_error(db):
    test_client = client(db, FakeLLM([]))
    case_code = apply(test_client)
    notice = CONTACT_REPLY["es"].format(email=contact_email_for("ES"))
    first = test_client.post(f"/voice/{case_code}/failure")
    second = test_client.post(f"/voice/{case_code}/failure")  # the page can report one break twice
    assert first.json() == second.json() == {"notice": notice}
    status, messages = status_and_messages(db, case_code)
    assert status == Status.TECHNICAL_ERROR
    assert messages.count(("agent", notice)) == 1
    assert messages[-1] == ("agent", notice)


def test_a_call_that_ends_after_a_final_status_gets_no_notice(db):
    test_client = client(db, FakeLLM([]))
    case_code = apply(test_client)
    storage = Storage(db)
    with storage.db:
        storage.db.execute("UPDATE conversations SET status = ? WHERE case_code = ?", (Status.QUALIFIED.value, case_code))
    before = status_and_messages(db, case_code)
    assert test_client.post(f"/voice/{case_code}/failure").json() == {"notice": None}
    assert status_and_messages(db, case_code) == before


def test_a_broken_call_with_an_unknown_case_code_is_not_found(db):
    assert client(db, FakeLLM([])).post("/voice/AAAA-BBBB/failure").status_code == 404


def test_applying_by_voice_when_the_check_fails_makes_no_conversation(db):
    test_client = client(db, FakeLLM([]), FakeCheck(works=False))
    response = test_client.post("/applications", data={"phone": "+34600111222", "country": "MX", "channel": "voice"})
    assert response.status_code == 503
    assert VOICE_UNAVAILABLE_APPLY in response.text
    assert Storage(db).conversations() == []
    chat = test_client.post("/applications", data={"phone": "+34600111222", "country": "MX", "channel": "chat"})
    assert chat.headers["location"].startswith("/chat/")  # chat does not need the voice path


def test_the_voice_page_asks_the_check_before_each_call(db):
    check = FakeCheck()
    test_client = client(db, FakeLLM([]), check)
    case_code = apply(test_client)
    assert settings_of(test_client.get(f"/voice/{case_code}"))["unavailable"] == VOICE_UNAVAILABLE_CALL
    assert test_client.get(f"/voice/{case_code}/ready").json() == {"ready": True}
    check.works = False
    assert test_client.get(f"/voice/{case_code}/ready").json() == {"ready": False}
    assert test_client.get("/voice/AAAA-BBBB/ready").status_code == 404


def test_the_ping_answers_the_code_made_at_start(db):
    check = FakeCheck()
    assert client(db, FakeLLM([]), check).get("/voice/ping").text == check.code


def agent_settings(llm: str, url: str) -> dict:
    """The part of ElevenLabs' answer for GET /v1/convai/agents/{id} that the check reads."""
    return {"conversation_config": {"agent": {"prompt": {"llm": llm, "custom_llm": {"url": url}}}}}


def check_with(public_answer, agent_answer=None, api_key: str = "") -> tuple[VoiceCheck, list[httpx.Request]]:
    """A VoiceCheck whose network is a function: the public address answers public_answer(check),
    ElevenLabs answers agent_answer. Returns the check and the requests it made."""
    requests: list[httpx.Request] = []

    def answer(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.host == "public.test":
            return public_answer(check)
        return agent_answer

    check = VoiceCheck(PUBLIC_URL, "agent_test", api_key, transport=httpx.MockTransport(answer))
    return check, requests


def own_code(check: VoiceCheck) -> httpx.Response:
    return httpx.Response(200, text=check.code)


def test_the_check_passes_when_the_public_address_reaches_this_server(db):
    check, requests = check_with(own_code)
    assert asyncio.run(check.ready())
    assert [str(r.url) for r in requests] == [f"{PUBLIC_URL}/voice/ping"]  # without an API key, the agent is not read


def test_the_check_fails_when_the_public_address_is_down_or_reaches_another_server(db):
    def offline(check):
        raise httpx.ConnectError("offline")

    assert not asyncio.run(check_with(offline)[0].ready())
    assert not asyncio.run(check_with(lambda check: httpx.Response(404, text="ERR_NGROK_3200"))[0].ready())
    assert not asyncio.run(check_with(lambda check: httpx.Response(200, text="another code"))[0].ready())


def test_with_an_api_key_the_check_reads_the_agents_custom_llm_url(db):
    good = httpx.Response(200, json=agent_settings("custom-llm", f"{PUBLIC_URL}/voice"))
    check, requests = check_with(own_code, good, api_key="el-key")
    assert asyncio.run(check.ready())
    assert str(requests[1].url) == "https://api.elevenlabs.io/v1/convai/agents/agent_test"
    assert requests[1].headers["xi-api-key"] == "el-key"


def test_the_check_fails_when_the_agent_calls_another_url_or_another_llm(db):
    other_url = httpx.Response(200, json=agent_settings("custom-llm", "https://old-name.ngrok-free.dev/voice"))
    other_llm = httpx.Response(200, json=agent_settings("gemini-2.5-flash", f"{PUBLIC_URL}/voice"))
    refused = httpx.Response(401, json={"detail": "invalid key"})
    for answer in (other_url, other_llm, refused):
        assert not asyncio.run(check_with(own_code, answer, api_key="el-key")[0].ready())
