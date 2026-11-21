import os

from dotenv import load_dotenv
from pydantic_ai import Agent
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider

from zonia.models import ScreeningFields, Turn

load_dotenv(".env")

model = OpenAIChatModel(
    os.environ["ZONIA_MODEL"],
    provider=OpenAIProvider(base_url=os.environ["ZONIA_BASE_URL"], api_key=os.environ["ZONIA_API_KEY"]),
)


SYSTEM = (
    "Eres Sonia, la asistente de IA de Grupo Sazón. "
    "Entrevistas a candidatos para el puesto de repartidor. "
    "Escribe mensajes cortos, como en WhatsApp."
)

agent = Agent(model, output_type=Turn, instructions=SYSTEM)


def main() -> None:
    history = []
    fields = ScreeningFields()
    while True:
        text = input("> ")
        result = agent.run_sync(text, message_history=history)
        history = result.all_messages()
        fields = fields.model_copy(update=result.output.fields.model_dump(exclude_none=True))
        print(result.output.reply)
        print(fields)
