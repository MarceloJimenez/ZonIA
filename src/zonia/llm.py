"""The LLM model and the agent. The provider comes from the environment (see zonia.settings)."""

import os

from pydantic_ai import Agent
from pydantic_ai.models import Model
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider

from zonia.models import Turn
from zonia.prompt import SYSTEM


def build_model(name: str | None = None) -> OpenAIChatModel:
    """A chat model on the OpenAI-compatible endpoint set in .env. Default: ZONIA_MODEL."""
    provider = OpenAIProvider(
        base_url=os.environ["ZONIA_BASE_URL"],
        api_key=os.environ["ZONIA_API_KEY"],
    )
    return OpenAIChatModel(name or os.environ["ZONIA_MODEL"], provider=provider)


def build_agent(model: Model) -> Agent[None, Turn]:
    """Sonia: returns a Turn (fields, intent, reply) on call 1."""
    return Agent(model, output_type=Turn, instructions=SYSTEM)
