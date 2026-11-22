"""The LLM model and the agent. The provider comes from .env."""

import os

from dotenv import load_dotenv
from pydantic_ai import Agent
from pydantic_ai.models import Model
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider

from zonia.models import Turn
from zonia.prompt import SYSTEM

load_dotenv(".env")


def build_model() -> OpenAIChatModel:
    """The chat model on the OpenAI-compatible endpoint set in .env."""
    provider = OpenAIProvider(
        base_url=os.environ["ZONIA_BASE_URL"],
        api_key=os.environ["ZONIA_API_KEY"],
    )
    return OpenAIChatModel(os.environ["ZONIA_MODEL"], provider=provider)


def build_agent(model: Model) -> Agent[None, Turn]:
    """Sonia: returns a Turn (fields, intent, reply) on call 1."""
    return Agent(model, output_type=Turn, instructions=SYSTEM)
