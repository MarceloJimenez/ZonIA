"""Voice: /voice/{case code} talks through an ElevenLabs agent.

ElevenLabs turns speech into text and calls /voice/chat/completions as its "custom LLM" (OpenAI chat format);
Sonia's reply goes back as speech. In the agent, the custom LLM URL is the public address + /voice,
and the API key is ELEVENLABS_LLM_KEY.
"""

import hmac
import json
import logging
import time

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.templating import Jinja2Templates

from zonia.adapters.conversations import Conversations
from zonia.domain.models import Role

logger = logging.getLogger(__name__)

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


def voice_routes(
    conversations: Conversations, templates: Jinja2Templates, elevenlabs_agent_id: str, voice_key: str
) -> APIRouter:
    router = APIRouter()
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
        if all(role == Role.AGENT for role, _ in messages):
            first_message = " ".join(text for _, text in messages)
        else:
            first_message = next(text for role, text in reversed(messages) if role == Role.AGENT)
        context = {"case_code": case_code, "messages": messages, "agent_id": elevenlabs_agent_id, "first_message": first_message}
        return templates.TemplateResponse(request, "voice.html", context)

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
