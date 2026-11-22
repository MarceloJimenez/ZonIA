"""Terminal chat with Sonia, one turn per line typed."""

import asyncio
import os

from zonia.llm import build_agent, build_model
from zonia.turn import Conversation, run_turn


def main() -> None:
    # The chat stays open after a final status: a later message can reopen it.
    # An empty line or Ctrl-D ends the chat.
    agent = build_agent(build_model())
    conversation = Conversation(country=os.environ.get("ZONIA_COUNTRY", "ES"))
    while True:
        try:
            text = input("> ").strip()
        except EOFError:
            break
        if not text:
            break
        turn = asyncio.run(run_turn(agent, conversation, text))
        print(turn.reply)
        print(conversation.fields)
        print(f"intent={turn.intent} stage={turn.stage} status={turn.status} calls={turn.llm_calls}")
