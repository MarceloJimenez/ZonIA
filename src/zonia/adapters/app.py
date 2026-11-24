"""Sonia's service: the web chat, voice through ElevenLabs, and the webhook of Meta's WhatsApp Cloud API.

Design: docs/plans/System design.md, section 1. Each adapter turns a candidate message into a turn,
and the turn's reply into a message on the same channel. The core (zonia.agent.turn) does not know the channel.
The channels: zonia.adapters.web, zonia.adapters.voice and zonia.adapters.whatsapp.

`zonia-server` starts it on http://127.0.0.1:8001. Meta and ElevenLabs need a public address: ngrok gives one.
"""

import logging
import os
from pathlib import Path

from fastapi import FastAPI
from pydantic_ai import Agent

from zonia import settings
from zonia.adapters.conversations import Conversations
from zonia.adapters.voice import voice_routes
from zonia.adapters.web import web_routes
from zonia.adapters.whatsapp import MetaSender, Sender, whatsapp_routes
from zonia.agent.llm import build_agent
from zonia.agent.schema import Turn
from zonia.pages import add_static_and_templates


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
    templates = add_static_and_templates(app)
    conversations = Conversations(db_path, agent)  # one for the three channels, so they share the locks
    app.include_router(web_routes(conversations, templates))
    app.include_router(voice_routes(conversations, templates, elevenlabs_agent_id, voice_key))
    app.include_router(whatsapp_routes(conversations, sender, app_secret, verify_token))
    return app


def main() -> None:
    import uvicorn

    settings.load()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s", datefmt="%H:%M:%S")
    app = create_app(
        settings.db_path(),
        build_agent(),
        MetaSender.from_env(),
        os.environ["META_APP_SECRET"],
        os.environ["META_VERIFY_TOKEN"],
        os.environ.get("ELEVENLABS_AGENT_ID", ""),
        os.environ.get("ELEVENLABS_LLM_KEY", ""),
    )
    uvicorn.run(app, host="127.0.0.1", port=8001)
