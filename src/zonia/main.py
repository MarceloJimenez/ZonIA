"""Terminal chat with Sonia, one turn per line typed.

`zonia` starts a new conversation and prints its id.
`zonia <id>` continues a saved conversation.
The database file is ZONIA_DB from .env, or zonia.db.
"""

import asyncio
import os
import sys

from zonia.llm import build_agent, build_model
from zonia.storage import Storage
from zonia.turn import Conversation, run_turn


def main() -> None:
    # The chat stays open after a final status: a later message can reopen it.
    # An empty line or Ctrl-D ends the chat.
    agent = build_agent(build_model())
    storage = Storage(os.environ.get("ZONIA_DB", "zonia.db"))
    if len(sys.argv) > 1:
        conversation_id = int(sys.argv[1])
        conversation = storage.load(conversation_id)
    else:
        conversation = Conversation(country=os.environ.get("ZONIA_COUNTRY", "ES"))
        conversation_id = storage.create(conversation)
    print(f"conversation={conversation_id}")
    while True:
        try:
            text = input("> ").strip()
        except EOFError:
            break
        if not text:
            break
        turn = asyncio.run(run_turn(agent, conversation, text))
        storage.save_turn(conversation_id, conversation, turn)
        print(turn.reply)
        print(conversation.fields)
        print(f"intent={turn.intent} stage={turn.stage} status={turn.status} calls={turn.llm_calls}")
    storage.close()
