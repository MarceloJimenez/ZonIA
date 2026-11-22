"""Terminal chat with Sonia, one turn per line typed."""

import asyncio

from zonia.flow import FINAL_STATUSES
from zonia.llm import build_agent, build_model
from zonia.turn import Conversation, run_turn


def main() -> None:
    # The chat ends at a final status. An empty line or Ctrl-D ends it early.
    agent = build_agent(build_model())
    conversation = Conversation()
    while conversation.status not in FINAL_STATUSES:
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
