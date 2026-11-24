"""The LLM model and the agent.

Sonia is a Pydantic AI agent spec (sonia.yaml): the model, its settings, the system prompt and the version.
The provider address and key come from the environment (see zonia.settings).
"""

import os
from pathlib import Path

from pydantic_ai import Agent
from pydantic_ai.agent.spec import AgentSpec
from pydantic_ai.models import Model
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider

from zonia.agent.schema import Turn

SONIA_PATH = Path(__file__).parent / "sonia.yaml"
SONIA = AgentSpec.from_file(SONIA_PATH)


def build_model(name: str) -> OpenAIChatModel:
    """A chat model on the OpenAI-compatible endpoint set in .env."""
    provider = OpenAIProvider(
        base_url=os.environ["ZONIA_BASE_URL"],
        api_key=os.environ["ZONIA_API_KEY"],
    )
    return OpenAIChatModel(name, provider=provider)


def build_agent(model: Model | None = None) -> Agent[None, Turn]:
    """Sonia from sonia.yaml: returns a Turn (fields, intent, reply) on call 1.

    model replaces the spec's model, for tests (a fake model) and evals (a paced one).
    """
    return Agent.from_file(SONIA_PATH, model=model or build_model(SONIA.model), output_type=Turn)


def spec_version(spec: AgentSpec) -> str:
    """The spec's name and version, for example "sonia@1"."""
    return f"{spec.name}@{spec.metadata['version']}"


def describe(spec: AgentSpec) -> str:
    """One line for a report: the version, the model and its settings, read from the spec."""
    return f"`{spec_version(spec)}`: model `{spec.model}`, settings `{spec.model_settings or {}}`"
