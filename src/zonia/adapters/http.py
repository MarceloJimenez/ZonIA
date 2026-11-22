"""HTTP endpoints of Sonia's service. Today: the Twilio webhook for WhatsApp.

Design: docs/plans/System design.md, section 1. The adapter turns a Twilio request into a turn,
and the turn's reply into a WhatsApp message. The core (zonia.turn) does not know the channel.

`zonia-server` starts it on http://127.0.0.1:8001. Twilio needs a public address: ngrok gives one,
and ZONIA_PUBLIC_URL in .env must be that address, because the signature check uses it.
"""

import asyncio
import logging
import os
from collections import defaultdict
from pathlib import Path

from fastapi import BackgroundTasks, FastAPI, HTTPException, Request, Response
from pydantic_ai import Agent
from twilio.request_validator import RequestValidator

from zonia.adapters.whatsapp import Sender, TwilioSender
from zonia.models import Turn
from zonia.storage import Storage
from zonia.turn import run_turn_safely

logger = logging.getLogger(__name__)

WEBHOOK_PATH = "/webhooks/twilio"

# A message with a photo, audio or other file and no text. Code writes the reply; no LLM call.
# Other formats are in docs/Backlog.md.
TEXT_ONLY_REPLY = {
    "es": "Por ahora solo puedo leer mensajes de texto. ¿Me lo escribes?",
    "en": "For now I can only read text messages. Could you write it?",
}

# Twilio expects TwiML in the answer. An empty <Response/> means "send nothing": Sonia replies through the API.
EMPTY_TWIML = '<?xml version="1.0" encoding="UTF-8"?><Response></Response>'


def create_app(db_path: str | Path, agent: Agent[None, Turn], sender: Sender, auth_token: str, public_url: str) -> FastAPI:
    app = FastAPI(title="ZonIA")
    validator = RequestValidator(auth_token)
    webhook_url = public_url.rstrip("/") + WEBHOOK_PATH
    # One turn at a time per phone: two quick messages must not change the same conversation at once.
    locks: defaultdict[str, asyncio.Lock] = defaultdict(asyncio.Lock)

    async def handle(phone: str, text: str, has_media: bool, message_sid: str) -> None:
        async with locks[phone]:
            storage = Storage(db_path)
            try:
                conversation_id = storage.find_by_phone(phone)
                if conversation_id is None:
                    logger.warning("WhatsApp message from a phone with no application: %s", message_sid)
                    return
                if storage.has_message(message_sid):
                    return  # Twilio sent the same message again
                conversation = storage.load(conversation_id)
                if not text:
                    if has_media:
                        await send(phone, TEXT_ONLY_REPLY[conversation.language])
                    return
                turn = await run_turn_safely(agent, conversation, text)
                storage.save_turn(conversation_id, conversation, turn, external_id=message_sid)
            finally:
                storage.close()
        await send(phone, turn.reply)

    async def send(phone: str, text: str) -> None:
        try:
            await asyncio.to_thread(sender.send, phone, text)
        except Exception:
            # The reply is saved; the candidate did not get it. The recruiter sees it in the dashboard.
            logger.exception("WhatsApp send failed")

    @app.post(WEBHOOK_PATH)
    async def twilio_webhook(request: Request, background: BackgroundTasks) -> Response:
        """One candidate message. Answer Twilio at once and run the turn after: Twilio waits 15 seconds at most."""
        form = {key: str(value) for key, value in (await request.form()).items()}
        if not validator.validate(webhook_url, form, request.headers.get("X-Twilio-Signature", "")):
            raise HTTPException(status_code=403)
        phone = form.get("From", "").removeprefix("whatsapp:")
        has_media = int(form.get("NumMedia") or 0) > 0
        background.add_task(handle, phone, form.get("Body", "").strip(), has_media, form.get("MessageSid", ""))
        return Response(EMPTY_TWIML, media_type="text/xml")

    return app


def main() -> None:
    import uvicorn

    from zonia.llm import build_agent, build_model  # loads .env

    logging.basicConfig(level=logging.INFO)
    app = create_app(
        os.environ.get("ZONIA_DB", "zonia.db"),
        build_agent(build_model()),
        TwilioSender.from_env(),
        os.environ["TWILIO_AUTH_TOKEN"],
        os.environ["ZONIA_PUBLIC_URL"],
    )
    uvicorn.run(app, host="127.0.0.1", port=8001)
