"""HTTP endpoints of Sonia's service: the web chat, voice through ElevenLabs, and the webhook of Meta's WhatsApp Cloud API.

Design: docs/plans/System design.md, section 1. Each adapter turns a candidate message into a turn,
and the turn's reply into a message on the same channel. The core (zonia.turn) does not know the channel.

Web chat: the candidate writes a phone number on a mock job page (/apply), and Sonia chats in the
browser at /chat/{case code}. The case code, not the row id, is in the URL: an id can be guessed.

Voice: /voice/{case code} talks through an ElevenLabs agent. ElevenLabs turns speech into text and calls
/voice/chat/completions as its "custom LLM" (OpenAI chat format); Sonia's reply goes back as speech.
In the agent, the custom LLM URL is the public address + /voice, and the API key is ELEVENLABS_LLM_KEY.

`zonia-server` starts it on http://127.0.0.1:8001. Meta and ElevenLabs need a public address: ngrok gives one.
In the Meta app, the webhook URL is that address + WEBHOOK_PATH, and the verify token is META_VERIFY_TOKEN.
"""

import asyncio
import hashlib
import hmac
import json
import logging
import os
import re
import time
from collections import defaultdict
from pathlib import Path

from fastapi import BackgroundTasks, FastAPI, Form, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic_ai import Agent

from zonia.adapters.whatsapp import MetaSender, Sender
from zonia.config import GREETING, JOB_FACTS, zones_for
from zonia.models import Turn
from zonia.storage import Storage
from zonia.turn import new_conversation, run_turn_safely

logger = logging.getLogger(__name__)

# Seconds for one voice turn. Past it, Sonia says the technical-failure reply instead of leaving silence.
VOICE_TIME_LIMIT = 15
# Seconds for one chat or WhatsApp turn. Past it, Sonia says the technical-failure reply
# instead of leaving the candidate waiting. Longer than voice: a written reply can wait a little.
CHAT_TIME_LIMIT = 30

WEBHOOK_PATH = "/webhooks/whatsapp"
HERE = Path(__file__).parent.parent

# The countries Sonia serves: phone prefix -> (country, digits after the prefix).
COUNTRY_PREFIXES = {"+34": ("ES", 9), "+52": ("MX", 10)}
PHONE_ERROR = "Escribe tu número con el prefijo de España (+34) o de México (+52)."
COUNTRY_PHONE_ERROR = "Ese número no es de {name}. Escribe un número que empiece por {prefix}."
COUNTRY_NAMES = {"ES": "España", "MX": "México"}
# The apply page starts with these numbers, so a demo needs no real phone. The candidate can change them.
DEMO_PHONES = {"ES": "+34 123 456 789", "MX": "+52 55 1234 5678"}
DEMO_PHONE = DEMO_PHONES["ES"]

# A message with a photo, audio or other file and no text. Code writes the reply; no LLM call.
# Other formats are in docs/Backlog.md.
TEXT_ONLY_REPLY = {
    "es": "Por ahora solo puedo leer mensajes de texto. ¿Me lo escribes?",
    "en": "For now I can only read text messages. Could you write it?",
}


def signature_is_valid(app_secret: str, body: bytes, header: str) -> bool:
    """Meta signs the raw body with the app secret: X-Hub-Signature-256 = "sha256=" + HMAC-SHA256 in hex."""
    expected = "sha256=" + hmac.new(app_secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, header)


def e164(wa_id: str) -> str:
    """Meta sends the phone as digits only. Mexican mobiles can come as 521 + 10 digits; the application has 52 + 10."""
    if wa_id.startswith("521") and len(wa_id) == 13:
        wa_id = "52" + wa_id[3:]
    return "+" + wa_id


def country_for(phone: str) -> tuple[str, str] | None:
    """(country, E.164 phone) for a phone typed on the apply page, or None when the prefix or length is wrong."""
    phone = re.sub(r"[\s().-]", "", phone)
    for prefix, (country, digits) in COUNTRY_PREFIXES.items():
        rest = phone.removeprefix(prefix)
        if phone.startswith(prefix) and rest.isdigit() and len(rest) == digits:
            return country, phone
    return None


def log_turn(channel: str, who: str, text: str, reply: str, started: float) -> None:
    """One line per turn, so the server log shows each conversation live."""
    logger.info("%s %s | candidate: %s | sonia: %s | %.1f s", channel, who, text, reply, time.monotonic() - started)


def apply_context(phone: str, country: str, error: str | None) -> dict:
    """What the apply page shows: the job facts, the countries with their service zones, and the phone field."""
    countries = [
        {"code": code, "name": name, "zones": zones_for(code), "demo_phone": DEMO_PHONES[code]}
        for code, name in COUNTRY_NAMES.items()
    ]
    return {"facts": JOB_FACTS, "countries": countries, "country": country, "phone": phone, "error": error}


def voice_stream(reply: str):
    """The reply as the OpenAI streaming format that ElevenLabs reads: one chunk with the whole text, then [DONE]."""
    chunk = {"id": "sonia", "object": "chat.completion.chunk", "created": int(time.time()), "model": "sonia"}
    text = {"index": 0, "delta": {"role": "assistant", "content": reply}, "finish_reason": None}
    stop = {"index": 0, "delta": {}, "finish_reason": "stop"}
    yield f"data: {json.dumps(chunk | {'choices': [text]}, ensure_ascii=False)}\n\n"
    yield f"data: {json.dumps(chunk | {'choices': [stop]})}\n\n"
    yield "data: [DONE]\n\n"


def create_app(
    db_path: str | Path,
    agent: Agent[None, Turn],
    sender: Sender,
    app_secret: str,
    verify_token: str,
    elevenlabs_agent_id: str = "",
    voice_key: str = "",
) -> FastAPI:
    app = FastAPI(title="ZonIA")
    app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")
    templates = Jinja2Templates(directory=HERE / "templates")
    # One turn at a time per conversation (key: phone or case code): two quick messages must not change it at once.
    locks: defaultdict[str, asyncio.Lock] = defaultdict(asyncio.Lock)
    # Voice: case code -> (the last request's messages, its reply). ElevenLabs can send the same request twice.
    voice_replies: dict[str, tuple[str, str]] = {}

    @app.get("/apply", response_class=HTMLResponse)
    async def apply(request: Request) -> HTMLResponse:
        """The mock job page of Grupo Sazón: the job facts and one field, the phone number."""
        return templates.TemplateResponse(request, "apply.html", apply_context(DEMO_PHONE, "ES", None))

    @app.post("/applications")
    async def applications(
        request: Request, phone: str = Form(""), channel: str = Form("chat"), country: str = Form("")
    ) -> Response:
        """Opens a conversation with Sonia's greeting, then sends the candidate to the chosen channel: chat or voice.

        The candidate chooses the country; the phone must have its prefix. With no country, the prefix decides it.
        """
        match = country_for(phone)
        error = None
        if match is None:
            error = PHONE_ERROR
        elif country in COUNTRY_NAMES and match[0] != country:
            prefix = next(p for p, (c, _) in COUNTRY_PREFIXES.items() if c == country)
            error = COUNTRY_PHONE_ERROR.format(name=COUNTRY_NAMES[country], prefix=prefix)
        if error:
            context = apply_context(phone, country if country in COUNTRY_NAMES else "ES", error)
            return templates.TemplateResponse(request, "apply.html", context, status_code=422)
        country, e164_phone = match
        conversation = new_conversation(country)
        storage = Storage(db_path)
        try:
            storage.create(conversation, GREETING, phone=e164_phone)
        finally:
            storage.close()
        page = "voice" if channel == "voice" else "chat"
        return RedirectResponse(f"/{page}/{conversation.case_code}", status_code=303)

    @app.get("/chat/{case_code}", response_class=HTMLResponse)
    async def chat(request: Request, case_code: str) -> HTMLResponse:
        storage = Storage(db_path)
        try:
            conversation_id = storage.find_by_case_code(case_code)
            if conversation_id is None:
                raise HTTPException(status_code=404)
            messages = storage.messages(conversation_id)
        finally:
            storage.close()
        return templates.TemplateResponse(request, "chat.html", {"case_code": case_code, "messages": messages})

    @app.post("/chat/{case_code}/messages")
    async def chat_message(case_code: str, text: str = Form("")) -> dict[str, str]:
        """One candidate message: runs a turn and returns Sonia's reply. The page adds both to the chat."""
        text = text.strip()
        if not text:
            raise HTTPException(status_code=422)
        started = time.monotonic()
        async with locks[case_code]:
            storage = Storage(db_path)
            try:
                conversation_id = storage.find_by_case_code(case_code)
                if conversation_id is None:
                    raise HTTPException(status_code=404)
                conversation = storage.load(conversation_id)
                turn = await run_turn_safely(agent, conversation, text, time_limit=CHAT_TIME_LIMIT)
                storage.save_turn(conversation_id, conversation, turn)
            finally:
                storage.close()
        log_turn("web", case_code, text, turn.reply, started)
        return {"reply": turn.reply}

    @app.get("/voice/{case_code}", response_class=HTMLResponse)
    async def voice(request: Request, case_code: str) -> HTMLResponse:
        """Talks with Sonia by voice. She starts with her last message, so the candidate hears the open question.

        In a new conversation she says the whole greeting: its first message introduces her.
        """
        storage = Storage(db_path)
        try:
            conversation_id = storage.find_by_case_code(case_code)
            if conversation_id is None:
                raise HTTPException(status_code=404)
            messages = storage.messages(conversation_id)
        finally:
            storage.close()
        if all(role == "agent" for role, _ in messages):
            first_message = " ".join(text for _, text in messages)
        else:
            first_message = next(text for role, text in reversed(messages) if role == "agent")
        context = {"case_code": case_code, "messages": messages, "agent_id": elevenlabs_agent_id, "first_message": first_message}
        return templates.TemplateResponse(request, "voice.html", context)

    @app.post("/voice/chat/completions")
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
        async with locks[case_code]:
            last_key, last_reply = voice_replies.get(case_code, ("", ""))
            if request_key == last_key:
                logger.info("voice %s | ElevenLabs sent the same turn again; reply reused | %.1f s", case_code, time.monotonic() - started)
                return StreamingResponse(voice_stream(last_reply), media_type="text/event-stream")
            storage = Storage(db_path)
            try:
                conversation_id = storage.find_by_case_code(case_code)
                if conversation_id is None:
                    raise HTTPException(status_code=404)
                conversation = storage.load(conversation_id)
                turn = await run_turn_safely(agent, conversation, text, time_limit=VOICE_TIME_LIMIT)
                storage.save_turn(conversation_id, conversation, turn)
            finally:
                storage.close()
            voice_replies[case_code] = (request_key, turn.reply)
        log_turn("voice", case_code, text, turn.reply, started)
        return StreamingResponse(voice_stream(turn.reply), media_type="text/event-stream")

    async def handle(phone: str, text: str, has_media: bool, message_id: str) -> None:
        started = time.monotonic()
        async with locks[phone]:
            storage = Storage(db_path)
            try:
                conversation_id = storage.find_by_phone(phone)
                if conversation_id is None:
                    logger.warning("WhatsApp message from a phone with no application: %s", message_id)
                    return
                if storage.has_message(message_id):
                    return  # Meta sent the same message again
                conversation = storage.load(conversation_id)
                if not text:
                    if has_media:
                        await send(phone, TEXT_ONLY_REPLY[conversation.language])
                    return
                turn = await run_turn_safely(agent, conversation, text, time_limit=CHAT_TIME_LIMIT)
                storage.save_turn(conversation_id, conversation, turn, external_id=message_id)
            finally:
                storage.close()
        log_turn("whatsapp", phone, text, turn.reply, started)
        await send(phone, turn.reply)

    async def send(phone: str, text: str) -> None:
        try:
            await asyncio.to_thread(sender.send, phone, text)
        except Exception:
            # The reply is saved; the candidate did not get it. The recruiter sees it in the dashboard.
            logger.exception("WhatsApp send failed")

    @app.get(WEBHOOK_PATH)
    async def verify(request: Request) -> Response:
        """Meta calls this once, when the webhook URL is saved in the app, and expects hub.challenge back."""
        params = request.query_params
        if params.get("hub.mode") != "subscribe" or params.get("hub.verify_token") != verify_token:
            raise HTTPException(status_code=403)
        return Response(params.get("hub.challenge", ""), media_type="text/plain")

    @app.post(WEBHOOK_PATH)
    async def webhook(request: Request, background: BackgroundTasks) -> Response:
        """Candidate messages. Answer Meta at once and run the turn after: Meta sends again when the answer is slow."""
        body = await request.body()
        if not signature_is_valid(app_secret, body, request.headers.get("X-Hub-Signature-256", "")):
            raise HTTPException(status_code=403)
        for entry in (await request.json()).get("entry", []):
            for change in entry.get("changes", []):
                # "statuses" (sent, delivered, read) come in the same webhook; only "messages" start a turn.
                for message in change.get("value", {}).get("messages", []):
                    text = message.get("text", {}).get("body", "").strip() if message.get("type") == "text" else ""
                    has_media = message.get("type") != "text"
                    background.add_task(handle, e164(message["from"]), text, has_media, message["id"])
        return Response(status_code=200)

    return app


def main() -> None:
    import uvicorn

    from zonia.llm import build_agent, build_model  # loads .env

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s", datefmt="%H:%M:%S")
    app = create_app(
        os.environ.get("ZONIA_DB", "zonia.db"),
        build_agent(build_model()),
        MetaSender.from_env(),
        os.environ["META_APP_SECRET"],
        os.environ["META_VERIFY_TOKEN"],
        os.environ.get("ELEVENLABS_AGENT_ID", ""),
        os.environ.get("ELEVENLABS_LLM_KEY", ""),
    )
    uvicorn.run(app, host="127.0.0.1", port=8001)
