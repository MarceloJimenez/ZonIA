"""Send WhatsApp messages through the Twilio API.

During development this is the Twilio sandbox: only phones that sent "join <code>" to the
sandbox number get messages, and the first message needs no template approved by Meta.
"""

import os
from typing import Protocol

from twilio.rest import Client


class Sender(Protocol):
    """Sends one WhatsApp message. Tests pass a fake one."""

    def send(self, phone: str, text: str) -> None: ...


class TwilioSender:
    """Sends through the Twilio API. phone is E.164, for example "+34600111222"."""

    def __init__(self, account_sid: str, auth_token: str, from_number: str):
        self.client = Client(account_sid, auth_token)
        self.from_number = from_number

    @classmethod
    def from_env(cls) -> "TwilioSender":
        """TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN and TWILIO_WHATSAPP_FROM (the sandbox number) from .env."""
        return cls(os.environ["TWILIO_ACCOUNT_SID"], os.environ["TWILIO_AUTH_TOKEN"], os.environ["TWILIO_WHATSAPP_FROM"])

    def send(self, phone: str, text: str) -> None:
        self.client.messages.create(from_=f"whatsapp:{self.from_number}", to=f"whatsapp:{phone}", body=text)
