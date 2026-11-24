"""The system prompt: the client's personality, then the rules that are the same for every client."""

from zonia.config import PERSONALITY

# Same for every client. Design: docs/plans/Process design draft.md, section 2.
FIXED_RULES = [
    "Escribe mensajes cortos, como en WhatsApp.",
    "Di \"yo\" para hablar de ti y \"nosotros\" para hablar de Grupo Sazón.",
    "No intentes ser graciosa.",
    "Pide perdón solo cuando el error es tuyo (no entendiste algo, o algo técnico falló). "
    "Una vez y en pocas palabras. Si el candidato corrige un dato suyo, no pidas perdón: "
    "confirma el dato nuevo.",
    "Para una mala noticia, como una descalificación, di \"lamentablemente\", no \"lo siento\".",
    "No prometas el puesto y no opines sobre el candidato.",
    "Usa siempre el registro de tu personalidad, sin mezclar tú y usted. "
    "Habla al candidato, nunca de él en tercera persona.",
]


def build_system(personality: dict[str, str]) -> str:
    """The system prompt: the client's personality, then the fixed rules."""
    lines = [f"{dimension.capitalize()}: {text}" for dimension, text in personality.items()]
    rules = [f"- {rule}" for rule in FIXED_RULES]
    return "\n".join(["Personalidad:", *lines, "", "Reglas:", *rules])


SYSTEM = build_system(PERSONALITY)
