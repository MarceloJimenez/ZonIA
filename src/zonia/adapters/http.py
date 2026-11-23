"""HTTP endpoints of Sonia's service. Today: the webhook of Meta's WhatsApp Cloud API.

Design: docs/plans/System design.md, section 1. The adapter turns a WhatsApp webhook request into a turn,
and the turn's reply into a WhatsApp message. The core (zonia.turn) does not know the channel.

`zonia-server` starts it on http://127.0.0.1:8001. Meta needs a public address: ngrok gives one.
In the Meta app, the webhook URL is that address + WEBHOOK_PATH, and the verify token is META_VERIFY_TOKEN.
"""

import asyncio
import hashlib
import hmac
import logging
import os
from collections import defaultdict
from pathlib import Path

from fastapi import BackgroundTasks, FastAPI, HTTPException, Request, Response
from pydantic_ai import Agent

from zonia.adapters.whatsapp import MetaSender, Sender
from zonia.models import Turn
from zonia.storage import Storage
from zonia.turn import run_turn_safely

logger = logging.getLogger(__name__)

WEBHOOK_PATH = "/webhooks/whatsapp"

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


def create_app(db_path: str | Path, agent: Agent[None, Turn], sender: Sender, app_secret: str, verify_token: str) -> FastAPI:
    app = FastAPI(title="ZonIA")
    # One turn at a time per phone: two quick messages must not change the same conversation at once.
    locks: defaultdict[str, asyncio.Lock] = defaultdict(asyncio.Lock)

    async def handle(phone: str, text: str, has_media: bool, message_id: str) -> None:
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
                turn = await run_turn_safely(agent, conversation, text)
                storage.save_turn(conversation_id, conversation, turn, external_id=message_id)
            finally:
                storage.close()
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

    logging.basicConfig(level=logging.INFO)
    app = create_app(
        os.environ.get("ZONIA_DB", "zonia.db"),
        build_agent(build_model()),
        MetaSender.from_env(),
        os.environ["META_APP_SECRET"],
        os.environ["META_VERIFY_TOKEN"],
    )
    uvicorn.run(app, host="127.0.0.1", port=8001)
