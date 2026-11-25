"""Voice: /voice/{case code} talks through an ElevenLabs agent.

ElevenLabs turns speech into text and calls /voice/chat/completions as its "custom LLM" (OpenAI chat format);
Sonia's reply goes back as speech. In the agent, the custom LLM URL is the public address + /voice,
and the API key is ELEVENLABS_LLM_KEY.

Before a call starts, VoiceCheck checks that ElevenLabs can reach this server: see VoiceCheck.ready.
"""

import hmac
import json
import logging
import secrets
import time

import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, PlainTextResponse, StreamingResponse
from fastapi.templating import Jinja2Templates

from zonia.adapters.conversations import Conversations
from zonia.config import contact_email_for
from zonia.domain.conversation import Conversation
from zonia.domain.flow import FINAL_STATUSES
from zonia.domain.models import Role, Status
from zonia.texts.replies import CONTACT_REPLY

logger = logging.getLogger(__name__)

ELEVENLABS_AGENTS_URL = "https://api.elevenlabs.io/v1/convai/agents"
# Seconds for each check before a call. Past it, the check fails: a slow path would also fail during the call.
CHECK_TIME_LIMIT = 3
# What the candidate sees when the check fails: on the apply page, and on the voice page before connecting.
VOICE_UNAVAILABLE_APPLY = "La llamada por voz no está disponible ahora. Prueba por chat."
VOICE_UNAVAILABLE_CALL = "La llamada por voz no está disponible ahora. Vuelve al inicio y elige el chat."

# Seconds for one voice turn. Past it, Sonia says the technical-failure reply instead of leaving silence.
VOICE_TIME_LIMIT = 15


def voice_stream(reply: str):
    """The reply as the OpenAI streaming format that ElevenLabs reads: one chunk with the whole text, then [DONE]."""
    chunk = {"id": "sonia", "object": "chat.completion.chunk", "created": int(time.time()), "model": "sonia"}
    text = {"index": 0, "delta": {"role": "assistant", "content": reply}, "finish_reason": None}
    stop = {"index": 0, "delta": {}, "finish_reason": "stop"}
    yield f"data: {json.dumps(chunk | {'choices': [text]}, ensure_ascii=False)}\n\n"
    yield f"data: {json.dumps(chunk | {'choices': [stop]})}\n\n"
    yield "data: [DONE]\n\n"


class VoiceCheck:
    """Checks, before a call, the two parts of the voice path that the server cannot cover when they fail.

    1. The tunnel (ngrok): the public address reaches this server. /voice/ping answers a code made at start,
       so a public address that reaches another server fails.
    2. The ElevenLabs agent: its custom LLM URL is the public address + /voice. Only with ELEVENLABS_API_KEY;
       without it, this part is not checked.
    A failure of the LLM itself needs no check: the turn then answers with the technical-failure reply.
    """

    def __init__(self, public_url: str, agent_id: str, api_key: str = "", transport: httpx.AsyncBaseTransport | None = None):
        """transport is for tests: an httpx.MockTransport instead of the network."""
        self.public_url = public_url.rstrip("/")
        self.agent_id = agent_id
        self.api_key = api_key
        self.transport = transport
        self.code = secrets.token_hex(16)

    async def ready(self) -> bool:
        """True when both parts work. Each failure goes to the log with its reason."""
        async with httpx.AsyncClient(timeout=CHECK_TIME_LIMIT, transport=self.transport) as client:
            return await self._tunnel_works(client) and await self._agent_calls_us(client)

    async def _tunnel_works(self, client: httpx.AsyncClient) -> bool:
        url = f"{self.public_url}/voice/ping"
        try:
            # ngrok's free plan can show a warning page instead of the answer; this header skips it.
            response = await client.get(url, headers={"ngrok-skip-browser-warning": "1"})
        except httpx.HTTPError as error:
            logger.warning("voice check | %s is not reachable: %s. Is ngrok running?", url, error)
            return False
        if response.status_code != 200 or response.text != self.code:
            logger.warning("voice check | %s answered %s, not this server. Is ngrok running on port 8001?", url, response.status_code)
            return False
        return True

    async def _agent_calls_us(self, client: httpx.AsyncClient) -> bool:
        if not self.api_key:
            return True
        try:
            response = await client.get(f"{ELEVENLABS_AGENTS_URL}/{self.agent_id}", headers={"xi-api-key": self.api_key})
            response.raise_for_status()
            prompt = response.json()["conversation_config"]["agent"]["prompt"]
        except (httpx.HTTPError, ValueError, KeyError, TypeError) as error:
            logger.warning("voice check | could not read the ElevenLabs agent %s: %s", self.agent_id, error)
            return False
        expected = f"{self.public_url}/voice"
        url = ((prompt.get("custom_llm") or {}).get("url") or "").rstrip("/")
        if prompt.get("llm") != "custom-llm" or url != expected:
            logger.warning(
                "voice check | the ElevenLabs agent uses llm=%s and url=%s; it must use custom-llm and %s",
                prompt.get("llm"), url or "(none)", expected,
            )
            return False
        return True


def call_failure_notice(conversation: Conversation) -> str:
    """What Sonia says when a voice call breaks: there is a technical problem, and how to reach a person."""
    return CONTACT_REPLY[conversation.language].format(email=contact_email_for(conversation.country))


def voice_routes(conversations: Conversations, templates: Jinja2Templates, check: VoiceCheck, voice_key: str) -> APIRouter:
    router = APIRouter()

    @router.get("/voice/ping", response_class=PlainTextResponse)
    async def ping() -> str:
        """The code made at start. VoiceCheck calls this through the public address."""
        return check.code
    # Case code -> (the last request's messages, its reply). ElevenLabs can send the same request twice.
    voice_replies: dict[str, tuple[str, str]] = {}

    @router.get("/voice/{case_code}", response_class=HTMLResponse)
    async def voice(request: Request, case_code: str) -> HTMLResponse:
        """Talks with Sonia by voice. She starts with her last message, so the candidate hears the open question.

        In a new conversation she says the whole greeting: its first message introduces her.
        """
        with conversations.storage() as storage:
            conversation_id = storage.find_by_case_code(case_code)
            if conversation_id is None:
                raise HTTPException(status_code=404)
            messages = storage.messages(conversation_id)
            conversation = storage.load(conversation_id)
        if all(role == Role.AGENT for role, _ in messages):
            first_message = " ".join(text for _, text in messages)
        else:
            first_message = next(text for role, text in reversed(messages) if role == Role.AGENT)
        context = {
            "case_code": case_code, "messages": messages, "agent_id": check.agent_id,
            "first_message": first_message, "failure_notice": call_failure_notice(conversation),
            "speech_lang": f"{conversation.language}-{conversation.country}",  # for the browser's voice: es-ES, es-MX
            "unavailable": VOICE_UNAVAILABLE_CALL,
        }
        return templates.TemplateResponse(request, "voice.html", context)

    @router.get("/voice/{case_code}/ready")
    async def ready(case_code: str) -> dict:
        """The voice page asks this before each call. If the check fails, the page does not connect."""
        with conversations.storage() as storage:
            if storage.find_by_case_code(case_code) is None:
                raise HTTPException(status_code=404)
        return {"ready": await check.ready()}

    @router.post("/voice/{case_code}/failure")
    async def call_failure(case_code: str) -> dict:
        """The voice page tells us that the call broke. Sonia's notice is saved and the case goes to technical_error.

        A call can break anywhere (ngrok, ElevenLabs, the LLM), so the page says the notice itself.
        If the conversation already has a final status, the call ended because the conversation ended: no notice.
        """
        async with conversations.open(case_code) as storage:
            conversation_id = storage.find_by_case_code(case_code)
            if conversation_id is None:
                raise HTTPException(status_code=404)
            conversation = storage.load(conversation_id)
            if conversation.status in FINAL_STATUSES:
                return {"notice": None}
            notice = call_failure_notice(conversation)
            if storage.messages(conversation_id)[-1:] != [(Role.AGENT, notice)]:  # the page can report one break twice
                storage.save_call_failure(conversation_id, Status.TECHNICAL_ERROR, notice)
                logger.warning("voice %s | the call broke; Sonia said the technical-problem notice", case_code)
        return {"notice": notice}

    @router.post("/voice/chat/completions")
    async def voice_turn(request: Request) -> StreamingResponse:
        """ElevenLabs sends the whole history; only the candidate's last message is used. Our database has the rest."""
        if not voice_key or not hmac.compare_digest(request.headers.get("authorization", ""), f"Bearer {voice_key}"):
            raise HTTPException(status_code=401)
        body = await request.json()
        case_code = str((body.get("elevenlabs_extra_body") or {}).get("case_code", ""))
        messages = [m for m in body.get("messages", []) if m.get("role") != "system"]  # the system message has the time
        said = [m.get("content") for m in messages if m.get("role") == "user"]
        text = said[-1].strip() if said and isinstance(said[-1], str) else ""
        if not text:
            raise HTTPException(status_code=422)
        request_key = json.dumps(messages, sort_keys=True, ensure_ascii=False)
        started = time.monotonic()
        async with conversations.open(case_code) as storage:
            last_key, last_reply = voice_replies.get(case_code, ("", ""))
            if request_key == last_key:
                logger.info("voice %s | ElevenLabs sent the same turn again; reply reused | %.1f s", case_code, time.monotonic() - started)
                return StreamingResponse(voice_stream(last_reply), media_type="text/event-stream")
            conversation_id = storage.find_by_case_code(case_code)
            if conversation_id is None:
                raise HTTPException(status_code=404)
            turn = await conversations.take_turn(
                storage, conversation_id, text,
                channel="voice", who=case_code, started=started, time_limit=VOICE_TIME_LIMIT,
            )
            voice_replies[case_code] = (request_key, turn.reply)
        return StreamingResponse(voice_stream(turn.reply), media_type="text/event-stream")

    return router
