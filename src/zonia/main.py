import os

from dotenv import load_dotenv
from openai import OpenAI

load_dotenv(".env")

client = OpenAI(base_url=os.environ["ZONIA_BASE_URL"], api_key=os.environ["ZONIA_API_KEY"])
MODEL = os.environ["ZONIA_MODEL"]


SYSTEM = (
    "Eres Sonia, la asistente de IA de Grupo Sazón. "
    "Entrevistas a candidatos para el puesto de repartidor. "
    "Escribe mensajes cortos, como en WhatsApp."
)


def main() -> None:
    history = [{"role": "system", "content": SYSTEM}]
    while True:
        text = input("> ")
        history.append({"role": "user", "content": text})
        response = client.chat.completions.create(model=MODEL, messages=history)
        reply = response.choices[0].message.content
        history.append({"role": "assistant", "content": reply})
        print(reply)
