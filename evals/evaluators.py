"""Checks applied to each transcript.

Code checks measure what can be measured exactly. The LLM judge is used only
for what code cannot measure: whether a question repeats known data, and
whether a reply follows its directive.
"""

from dataclasses import dataclass
from typing import Any

from pydantic_evals.evaluators import EvaluationReason, Evaluator, EvaluatorContext
from pydantic_evals.evaluators.llm_as_a_judge import judge_output

from conversation import MODEL, Script, Transcript, with_retries
from zonia.models import Intent, Stage, Status

Ctx = EvaluatorContext[Script, Transcript, None]


@dataclass
class FinalState(Evaluator[Script, Transcript, None]):
    """The conversation ends in the expected status (and stage, if given)."""

    status: Status
    stage: Stage | None = None

    def evaluate(self, ctx: Ctx) -> dict[str, EvaluationReason]:
        out = ctx.output
        result = {"status": EvaluationReason(out.status == self.status, f"expected {self.status}, got {out.status}")}
        if self.stage is not None:
            result["stage"] = EvaluationReason(out.stage == self.stage, f"expected {self.stage}, got {out.stage}")
        return result


@dataclass
class FieldsExtracted(Evaluator[Script, Transcript, None]):
    """The LLM extracted these values. Text matches if the expected text is contained, ignoring case."""

    expected: dict[str, Any]

    def evaluate(self, ctx: Ctx) -> dict[str, EvaluationReason]:
        result = {}
        for name, want in self.expected.items():
            got = getattr(ctx.output.fields, name)
            if isinstance(want, str) and isinstance(got, str):
                ok = want.lower() in got.lower()
            elif isinstance(want, list) and isinstance(got, list):
                ok = set(want) == set(got)
            else:
                ok = got == want
            result[f"field {name}"] = EvaluationReason(ok, f"expected {want!r}, got {got!r}")
        return result


@dataclass
class StatusAt(Evaluator[Script, Transcript, None]):
    """The status after the given turn (0 = first message). Shows that a reopened case was really closed first."""

    turn: int
    status: Status

    def evaluate(self, ctx: Ctx) -> dict[str, EvaluationReason]:
        turns = ctx.output.turns
        got = turns[self.turn].status if self.turn < len(turns) else None
        return {f"status turn {self.turn}": EvaluationReason(got == self.status, f"expected {self.status}, got {got}")}


@dataclass
class IntentAt(Evaluator[Script, Transcript, None]):
    """The LLM read this intent in the given turn (0 = first message)."""

    turn: int
    intent: Intent

    def evaluate(self, ctx: Ctx) -> dict[str, EvaluationReason]:
        turns = ctx.output.turns
        got = turns[self.turn].intent if self.turn < len(turns) else None
        return {f"intent turn {self.turn}": EvaluationReason(got == self.intent, f"expected {self.intent}, got {got}")}


@dataclass
class SummaryAt(Evaluator[Script, Transcript, None]):
    """The summary written by code is the reply of the given turn (0 = first message)."""

    turn: int

    def evaluate(self, ctx: Ctx) -> dict[str, EvaluationReason]:
        turns = ctx.output.turns
        got = turns[self.turn].reply_source if self.turn < len(turns) else None
        return {f"summary turn {self.turn}": EvaluationReason(got == "summary", f"reply source: {got}")}


@dataclass
class LlmCalls(Evaluator[Script, Transcript, None]):
    """Cost: LLM calls made by the agent in the whole conversation (judge calls not counted)."""

    def evaluate(self, ctx: Ctx) -> dict[str, int]:
        return {"llm_calls": sum(t.llm_calls for t in ctx.output.turns)}


@dataclass
class Judge(Evaluator[Script, Transcript, None]):
    """An LLM reads the whole transcript and says whether it meets the rubric."""

    name: str
    rubric: str

    async def evaluate(self, ctx: Ctx) -> dict[str, EvaluationReason]:
        grade = await with_retries(lambda: judge_output(ctx.output.text(), self.rubric, model=MODEL))
        return {self.name: EvaluationReason(grade.pass_, grade.reason)}
