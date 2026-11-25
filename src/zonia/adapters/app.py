"""Sonia's service: the web chat, voice through ElevenLabs, and the webhook of Meta's WhatsApp Cloud API.

Design: docs/plans/System design.md, section 1. Each adapter turns a candidate message into a turn,
and the turn's reply into a message on the same channel. The core (zonia.agent.turn) does not know the channel.
The channels: zonia.adapters.web, zonia.adapters.voice and zonia.adapters.whatsapp.

`zonia-server` starts it on http://127.0.0.1:8001. Meta and ElevenLabs need a public address: ngrok gives one.
Voice is on only with ELEVENLABS_AGENT_ID, ELEVENLABS_LLM_KEY and ZONIA_PUBLIC_URL in .env;
ELEVENLABS_API_KEY is optional and lets the check before each call read the agent's settings.
The WhatsApp webhook is on only when the four META_ variables are in .env.
"""

import logging
import os
from pathlib import Path

from fastapi import FastAPI
from pydantic_ai import Agent

from zonia import settings
from zonia.adapters.conversations import Conversations
from zonia.adapters.voice import VoiceCheck, voice_routes
from zonia.adapters.web import web_routes
from zonia.adapters.whatsapp import MetaSender, Sender, whatsapp_routes
from zonia.agent.llm import build_agent
from zonia.agent.schema import Turn
from zonia.pages import add_static_and_templates

META_VARIABLES = ("META_WHATSAPP_TOKEN", "META_PHONE_NUMBER_ID", "META_APP_SECRET", "META_VERIFY_TOKEN")


def create_app(
    db_path: str | Path,
    agent: Agent[None, Turn],
    sender: Sender | None,
    app_secret: str = "",
    verify_token: str = "",
    voice_check: VoiceCheck | None = None,
    voice_key: str = "",
) -> FastAPI:
    """voice_check and voice_key: without both, voice is off and the voice button is disabled."""
    app = FastAPI(title="ZonIA")
    templates = add_static_and_templates(app)
    conversations = Conversations(db_path, agent)  # one for the three channels, so they share the locks
    check = voice_check if voice_key else None
    app.include_router(web_routes(conversations, templates, check))
    if check is not None:
        app.include_router(voice_routes(conversations, templates, check, voice_key))
    if sender is not None:  # without the Meta variables there is no webhook, so nobody can post unsigned messages
        app.include_router(whatsapp_routes(conversations, sender, app_secret, verify_token))
    return app


def main() -> None:
    import uvicorn

    settings.load()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s", datefmt="%H:%M:%S")
    whatsapp = all(os.environ.get(name) for name in META_VARIABLES)
    agent_id, public_url = os.environ.get("ELEVENLABS_AGENT_ID", ""), os.environ.get("ZONIA_PUBLIC_URL", "")
    voice_check = VoiceCheck(public_url, agent_id, os.environ.get("ELEVENLABS_API_KEY", "")) if agent_id and public_url else None
    app = create_app(
        settings.db_path(),
        build_agent(),
        MetaSender.from_env() if whatsapp else None,
        os.environ.get("META_APP_SECRET", ""),
        os.environ.get("META_VERIFY_TOKEN", ""),
        voice_check,
        os.environ.get("ELEVENLABS_LLM_KEY", ""),
    )
    logging.getLogger(__name__).info("Open http://127.0.0.1:8001/apply")
    uvicorn.run(app, host="127.0.0.1", port=8001)
