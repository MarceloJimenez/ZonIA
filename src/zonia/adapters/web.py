"""Web chat: the candidate writes a phone number on a mock job page (/apply), and Sonia chats in the
browser at /chat/{case code}. The case code, not the row id, is in the URL: an id can be guessed.
"""

import re
import time

from fastapi import APIRouter, Form, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from zonia.adapters.conversations import Conversations
from zonia.config import GREETING, JOB_FACTS, zones_for
from zonia.domain.conversation import new_conversation

# The countries Sonia serves: phone prefix -> (country, digits after the prefix).
COUNTRY_PREFIXES = {"+34": ("ES", 9), "+52": ("MX", 10)}
PHONE_ERROR = "Escribe tu número con el prefijo de España (+34) o de México (+52)."
COUNTRY_PHONE_ERROR = "Ese número no es de {name}. Escribe un número que empiece por {prefix}."
COUNTRY_NAMES = {"ES": "España", "MX": "México"}
# The apply page starts with these numbers, so a demo needs no real phone. The candidate can change them.
DEMO_PHONES = {"ES": "+34 123 456 789", "MX": "+52 55 1234 5678"}
DEMO_PHONE = DEMO_PHONES["ES"]


def country_for(phone: str) -> tuple[str, str] | None:
    """(country, E.164 phone) for a phone typed on the apply page, or None when the prefix or length is wrong."""
    phone = re.sub(r"[\s().-]", "", phone)
    for prefix, (country, digits) in COUNTRY_PREFIXES.items():
        rest = phone.removeprefix(prefix)
        if phone.startswith(prefix) and rest.isdigit() and len(rest) == digits:
            return country, phone
    return None


def apply_context(phone: str, country: str, error: str | None) -> dict:
    """What the apply page shows: the job facts, the countries with their service zones, and the phone field."""
    countries = [
        {"code": code, "name": name, "zones": zones_for(code), "demo_phone": DEMO_PHONES[code]}
        for code, name in COUNTRY_NAMES.items()
    ]
    return {"facts": JOB_FACTS, "countries": countries, "country": country, "phone": phone, "error": error}


def web_routes(conversations: Conversations, templates: Jinja2Templates) -> APIRouter:
    router = APIRouter()

    @router.get("/apply", response_class=HTMLResponse)
    async def apply(request: Request) -> HTMLResponse:
        """The mock job page of Grupo Sazón: the job facts and one field, the phone number."""
        return templates.TemplateResponse(request, "apply.html", apply_context(DEMO_PHONE, "ES", None))

    @router.post("/applications")
    async def applications(
        request: Request, phone: str = Form(""), channel: str = Form("chat"), country: str = Form("")
    ) -> Response:
        """Opens a conversation with Sonia's greeting, then sends the candidate to the chosen channel: chat or voice.

        The candidate chooses the country; the phone must have its prefix. With no country, the prefix decides it.
        """
        match = country_for(phone)
        error = None
        if match is None:
            error = PHONE_ERROR
        elif country in COUNTRY_NAMES and match[0] != country:
            prefix = next(p for p, (c, _) in COUNTRY_PREFIXES.items() if c == country)
            error = COUNTRY_PHONE_ERROR.format(name=COUNTRY_NAMES[country], prefix=prefix)
        if error:
            context = apply_context(phone, country if country in COUNTRY_NAMES else "ES", error)
            return templates.TemplateResponse(request, "apply.html", context, status_code=422)
        country, e164_phone = match
        conversation = new_conversation(country)
        with conversations.storage() as storage:
            storage.create(conversation, GREETING, phone=e164_phone)
        page = "voice" if channel == "voice" else "chat"
        return RedirectResponse(f"/{page}/{conversation.case_code}", status_code=303)

    @router.get("/chat/{case_code}", response_class=HTMLResponse)
    async def chat(request: Request, case_code: str) -> HTMLResponse:
        with conversations.storage() as storage:
            conversation_id = storage.find_by_case_code(case_code)
            if conversation_id is None:
                raise HTTPException(status_code=404)
            messages = storage.messages(conversation_id)
        return templates.TemplateResponse(request, "chat.html", {"case_code": case_code, "messages": messages})

    @router.post("/chat/{case_code}/messages")
    async def chat_message(case_code: str, text: str = Form("")) -> dict[str, str]:
        """One candidate message: runs a turn and returns Sonia's reply. The page adds both to the chat."""
        text = text.strip()
        if not text:
            raise HTTPException(status_code=422)
        started = time.monotonic()
        async with conversations.open(case_code) as storage:
            conversation_id = storage.find_by_case_code(case_code)
            if conversation_id is None:
                raise HTTPException(status_code=404)
            turn = await conversations.take_turn(
                storage, conversation_id, text, channel="web", who=case_code, started=started
            )
        return {"reply": turn.reply}

    return router
