import os

from dotenv import load_dotenv
from pydantic_ai import Agent, AgentRunResult
from pydantic_ai.messages import ModelMessage
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider

from zonia.flow import FINAL_STATUSES, decide
from zonia.models import ScreeningFields, Stage, Status, Turn
from zonia.prompt import DIRECTIVES, SYSTEM

load_dotenv(".env")

model = OpenAIChatModel(
    os.environ["ZONIA_MODEL"],
    provider=OpenAIProvider(base_url=os.environ["ZONIA_BASE_URL"], api_key=os.environ["ZONIA_API_KEY"]),
)

agent = Agent(model, output_type=Turn, instructions=SYSTEM)


def rewrite_reply(text: str, history: list[ModelMessage], directive: str) -> AgentRunResult[str]:
    """Call 2: write the reply again, following the directive.

    Runs on the history from before call 1, so the dropped reply never enters it.
    """
    print("call 2")
    return agent.run_sync(text, message_history=history, output_type=str, instructions=directive)


def main() -> None:
    history: list[ModelMessage] = []
    fields = ScreeningFields()
    stage = Stage.INTRODUCTION
    status = Status.ACTIVE
    while status not in FINAL_STATUSES:
        text = input("> ")
        result = agent.run_sync(text, message_history=history)
        fields = fields.model_copy(update=result.output.fields.model_dump(exclude_none=True))
        old_status = status
        stage, status = decide(stage, status, result.output.intent, fields)
        if status != old_status and status in DIRECTIVES:
            result_2 = rewrite_reply(text, history, DIRECTIVES[status])
            reply, history = result_2.output, result_2.all_messages()
        else:
            reply, history = result.output.reply, result.all_messages()
        print(reply)
        print(fields)
        print(f"intent={result.output.intent} stage={stage} status={status}")
