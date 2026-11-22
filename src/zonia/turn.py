"""One turn of the conversation: the only place that calls the LLM.

1. Call 1: the LLM returns the fields, the intent and a reply.
2. Code merges the fields and decides the new stage and status.
3. If the status changed and a directive exists: call 2 writes the reply again.
   If the conversation enters closing or the candidate corrects the summary:
   code writes the summary and no extra call is made.
"""

from dataclasses import dataclass, field

from pydantic import BaseModel
from pydantic_ai import Agent
from pydantic_ai.messages import ModelMessage, ModelRequest, ModelResponse, TextPart, UserPromptPart

from zonia.flow import decide, render_summary
from zonia.models import Intent, ScreeningFields, Stage, Status, Turn
from zonia.prompt import DIRECTIVES, turn_instructions


@dataclass
class Conversation:
    """Everything the code keeps between turns."""

    history: list[ModelMessage] = field(default_factory=list)
    fields: ScreeningFields = field(default_factory=ScreeningFields)
    stage: Stage = Stage.INTRODUCTION
    status: Status = Status.ACTIVE


class TurnResult(BaseModel):
    """What one turn produced, for the caller and for the evals."""

    message: str
    reply: str
    intent: Intent
    stage: Stage
    status: Status
    llm_calls: int
    reply_source: str  # "call_1", "call_2" or "summary"


async def run_turn(agent: Agent[None, Turn], conversation: Conversation, text: str) -> TurnResult:
    """Run one turn and update the conversation.

    The conversation changes only at the end, so a turn that raises
    (for example, a rate-limit error) leaves it as it was and can be retried.
    """
    c = conversation
    result = await agent.run(text, message_history=c.history, instructions=turn_instructions(c.fields))
    fields = c.fields.model_copy(update=result.output.fields.model_dump(exclude_none=True))
    intent = result.output.intent
    stage, status = decide(c.stage, c.status, intent, fields)
    show_summary = (
        stage == Stage.CLOSING
        and status == Status.ACTIVE
        and (c.stage != Stage.CLOSING or intent == Intent.CORRECTS_SUMMARY)
    )

    if status != c.status and status in DIRECTIVES:
        result_2 = await agent.run(
            text, message_history=c.history, output_type=str, instructions=DIRECTIVES[status]
        )
        reply, history, calls, source = result_2.output, result_2.all_messages(), 2, "call_2"
    elif show_summary:
        reply = render_summary(fields)
        history = [
            *c.history,
            ModelRequest(parts=[UserPromptPart(content=text)]),
            ModelResponse(parts=[TextPart(content=reply)]),
        ]
        calls, source = 1, "summary"
    else:
        reply, history, calls, source = result.output.reply, result.all_messages(), 1, "call_1"

    c.history, c.fields, c.stage, c.status = history, fields, stage, status
    return TurnResult(
        message=text, reply=reply, intent=intent, stage=stage, status=status,
        llm_calls=calls, reply_source=source,
    )
