"""WhatsApp through Meta's WhatsApp Cloud API: the webhook that receives candidate messages, and the sender.

In the Meta app, the webhook URL is the public address + WEBHOOK_PATH, and the verify token is META_VERIFY_TOKEN.
During development this is Meta's test number: it only sends to the (at most 5) phones added as
recipients in the app's "API Setup" page. A free-text message only arrives within 24 hours of the
candidate's last message; outside that window WhatsApp asks for a template approved by Meta.
"""

import asyncio
import hashlib
import hmac
import logging
import os
import time
from typing import Protocol

import httpx
from fastapi import APIRouter, BackgroundTasks, HTTPException, Request, Response

from zonia.adapters.conversations import Conversations
from zonia.texts.replies import TEXT_ONLY_REPLY

logger = logging.getLogger(__name__)

GRAPH_URL = "https://graph.facebook.com/v25.0"
WEBHOOK_PATH = "/webhooks/whatsapp"


class Sender(Protocol):
    """Sends one WhatsApp message. Tests pass a fake one."""

    def send(self, phone: str, text: str) -> None: ...


class MetaSender:
    """Sends through the Cloud API. phone is E.164, for example "+34600111222"."""

    def __init__(self, access_token: str, phone_number_id: str):
        self.url = f"{GRAPH_URL}/{phone_number_id}/messages"
        self.headers = {"Authorization": f"Bearer {access_token}"}

    @classmethod
    def from_env(cls) -> "MetaSender":
        """META_WHATSAPP_TOKEN and META_PHONE_NUMBER_ID (the test number's id) from .env."""
        return cls(os.environ["META_WHATSAPP_TOKEN"], os.environ["META_PHONE_NUMBER_ID"])

    def send(self, phone: str, text: str) -> None:
        body = {"messaging_product": "whatsapp", "to": phone.removeprefix("+"), "type": "text", "text": {"body": text}}
        response = httpx.post(self.url, headers=self.headers, json=body, timeout=10)
        if response.is_error:
            # Meta's error text says why (for example: number not in the recipient list, 24-hour window closed).
            raise RuntimeError(f"WhatsApp send failed: {response.status_code} {response.text}")


def signature_is_valid(app_secret: str, body: bytes, header: str) -> bool:
    """Meta signs the raw body with the app secret: X-Hub-Signature-256 = "sha256=" + HMAC-SHA256 in hex."""
    expected = "sha256=" + hmac.new(app_secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, header)


def e164(wa_id: str) -> str:
    """Meta sends the phone as digits only. Mexican mobiles can come as 521 + 10 digits; the application has 52 + 10."""
    if wa_id.startswith("521") and len(wa_id) == 13:
        wa_id = "52" + wa_id[3:]
    return "+" + wa_id


def whatsapp_routes(conversations: Conversations, sender: Sender, app_secret: str, verify_token: str) -> APIRouter:
    router = APIRouter()

    async def handle(phone: str, text: str, has_media: bool, message_id: str) -> None:
        started = time.monotonic()
        async with conversations.open(phone) as storage:
            conversation_id = storage.find_by_phone(phone)
            if conversation_id is None:
                logger.warning("WhatsApp message from a phone with no application: %s", message_id)
                return
            if storage.has_message(message_id):
                return  # Meta sent the same message again
            if not text:
                if has_media:
                    await send(phone, TEXT_ONLY_REPLY[storage.load(conversation_id).language])
                return
            turn = await conversations.take_turn(
                storage, conversation_id, text, channel="whatsapp", who=phone, started=started, external_id=message_id
            )
        await send(phone, turn.reply)

    async def send(phone: str, text: str) -> None:
        try:
            await asyncio.to_thread(sender.send, phone, text)
        except Exception:
            # The reply is saved; the candidate did not get it. The recruiter sees it in the dashboard.
            logger.exception("WhatsApp send failed")

    @router.get(WEBHOOK_PATH)
    async def verify(request: Request) -> Response:
        """Meta calls this once, when the webhook URL is saved in the app, and expects hub.challenge back."""
        params = request.query_params
        if params.get("hub.mode") != "subscribe" or params.get("hub.verify_token") != verify_token:
            raise HTTPException(status_code=403)
        return Response(params.get("hub.challenge", ""), media_type="text/plain")

    @router.post(WEBHOOK_PATH)
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

    return router
