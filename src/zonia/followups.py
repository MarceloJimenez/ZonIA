"""Follow-ups when the candidate stops replying: reminders, then paused, then incomplete.

Design: docs/plans/Process design draft.md, section 4.1. The times are in config.FOLLOW_UPS.

run_followups() checks every conversation that waits for the candidate, once. In production a
scheduler (for example cron) runs `zonia-followups` every minute. Code writes the reminders; no LLM call.

A conversation does at most one step per check: the last step that is due. If the check did not
run for a while, an old reminder is not sent late.
"""

from dataclasses import dataclass
from datetime import datetime

from zonia import settings
from zonia.config import FOLLOW_UPS, FOLLOW_UPS_NO_REPLY, local_words_for
from zonia.domain.flow import open_fields
from zonia.domain.models import Status
from zonia.storage import Storage
from zonia.domain.conversation import Conversation

# What is missing, as the reminder says it. {license} and {area} are the country's words.
NEXT_ES = {
    "full_name": "tu nombre completo",
    "driver_license": "saber si tienes {license}",
    "city_zone": "saber en qué ciudad y {area} vives",
    "availability": "tu disponibilidad",
    "schedule": "tu horario preferido",
    "experience_years": "tu experiencia como repartidor",
    "experience_platform": "dónde trabajaste como repartidor",
    "start_date": "tu fecha de inicio",
}
NEXT_EN = {
    "full_name": "your full name",
    "driver_license": "whether you have a driving licence",
    "city_zone": "the city and area where you live",
    "availability": "your availability",
    "schedule": "your preferred schedule",
    "experience_years": "your experience as a delivery driver",
    "experience_platform": "where you worked as a delivery driver",
    "start_date": "your start date",
}
REMINDER_TEXT = {
    "es": {
        "ask": "¿Seguimos{name}?",
        "last": "Solo falta {thing}.",
        "next": "Lo siguiente es {thing}.",
        "confirm": "Solo falta que confirmes tus datos.",
    },
    "en": {
        "ask": "Shall we continue{name}?",
        "last": "There is only {thing} left.",
        "next": "Next is {thing}.",
        "confirm": "You only need to confirm your details.",
    },
}

# The candidate never answered the greeting. On WhatsApp this is a template approved by Meta, in Spanish like the greeting.
NO_REPLY_REMINDER = (
    "Hola de nuevo, soy Sonia, la asistente de IA de Grupo Sazón. "
    "Te escribí por tu solicitud de repartidor. ¿Seguimos? Si es así, dime tu nombre completo."
)


def reminder_text(c: Conversation) -> str:
    """The reminder for a conversation the candidate started: it names what is missing, like the design's example."""
    if c.turns == 0:
        return NO_REPLY_REMINDER
    t = REMINDER_TEXT[c.language]
    first_name = c.fields.full_name.split()[0] if c.fields.full_name else ""
    ask = t["ask"].format(name=f", {first_name}" if first_name else "")
    missing = open_fields(c.fields)
    if not missing:
        return f"{ask} {t['confirm']}"
    names = NEXT_ES if c.language == "es" else NEXT_EN
    thing = names[missing[0]].format(**local_words_for(c.country))
    return f"{ask} {t['last' if len(missing) == 1 else 'next'].format(thing=thing)}"


def steps_for(c: Conversation) -> list:
    """The follow-up table for this conversation: never answered, or stopped in the middle."""
    return FOLLOW_UPS_NO_REPLY if c.turns == 0 else FOLLOW_UPS


def first_step(c: Conversation) -> int:
    """Where the follow-ups start. A paused conversation (the candidate said "not now", or was
    silent for 30 minutes) skips reminder 1 and the pause."""
    if c.turns > 0 and c.status == Status.PAUSED:
        return max(c.followup_step, 2)
    return c.followup_step


def due_step(c: Conversation, waited) -> int | None:
    """The index of the last step that is due after waiting this long, or None."""
    due = None
    steps = steps_for(c)
    for i in range(first_step(c), len(steps)):
        if waited >= steps[i][0]:
            due = i
    return due


@dataclass
class FollowUp:
    """One step done, for the log."""

    conversation_id: int
    step: str  # "reminder", "pause" or "incomplete"
    reminder: str | None


def run_followups(storage: Storage, now: datetime) -> list[FollowUp]:
    """Check every active or paused conversation once, and do the step that is due."""
    done = []
    for conversation_id, waiting_since in storage.waiting():
        c = storage.load(conversation_id)
        i = due_step(c, now - waiting_since)
        if i is None:
            continue
        step = steps_for(c)[i][1]
        reminder = None
        if step == "reminder":
            reminder = reminder_text(c)
            c.add_agent_message(reminder)
        elif step == "pause":
            c.status = Status.PAUSED
        elif step == "incomplete":
            c.status = Status.INCOMPLETE
        c.followup_step = i + 1
        storage.save_followup(conversation_id, c, reminder)
        done.append(FollowUp(conversation_id, step, reminder))
    return done


def main() -> None:
    """`zonia-followups`: check every conversation once and print what was done."""
    settings.load()
    with Storage(settings.db_path()) as storage:
        for f in run_followups(storage, storage.clock()):
            print(f"conversation={f.conversation_id} step={f.step}" + (f" reminder={f.reminder!r}" if f.reminder else ""))
