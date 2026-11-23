"""Send WhatsApp messages through Meta's WhatsApp Cloud API.

During development this is Meta's test number: it only sends to the (at most 5) phones added as
recipients in the app's "API Setup" page. A free-text message only arrives within 24 hours of the
candidate's last message; outside that window WhatsApp asks for a template approved by Meta.
"""

import os
from typing import Protocol

import httpx

GRAPH_URL = "https://graph.facebook.com/v25.0"


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
