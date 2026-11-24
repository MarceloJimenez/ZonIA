# ZonIA

Sonia is an AI agent that screens delivery-driver candidates for Grupo Sazón, a restaurant chain in Spain and Mexico. She talks with each candidate by text or by voice, collects the screening data, checks the hard requirements, and leaves a summary for the recruiter.

## Setup

You need Python 3.12 or newer and [uv](https://docs.astral.sh/uv/).

1. Install the dependencies: `uv sync`.
2. Create a file `.env` in the project folder with the variables below.
3. Run the tests: `uv run pytest`.

Sonia's model, its settings and her system prompt are in `src/zonia/agent/sonia.yaml`, a [Pydantic AI agent spec](https://ai.pydantic.dev/agent-spec/).
Its `metadata.version` names the prompt: each message Sonia writes saves it, for example `sonia@1`.
When the text the LLM reads changes, `tests/test_prompt_version.py` fails until you raise the version.

| Variable | Needed by | What it is |
|---|---|---|
| `ZONIA_BASE_URL` | every command that calls the LLM | An OpenAI-compatible endpoint. For Gemini: `https://generativelanguage.googleapis.com/v1beta/openai/` |
| `ZONIA_API_KEY` | same | The API key of that provider. |
| `ZONIA_DB` | optional | The SQLite database file. Default: `zonia.db`. |
| `ZONIA_COUNTRY` | optional, `zonia` only | `ES` (Spain) or `MX` (Mexico) for a new terminal chat. Default: `ES`. |
| `META_APP_SECRET`, `META_VERIFY_TOKEN`, `META_WHATSAPP_TOKEN`, `META_PHONE_NUMBER_ID` | `zonia-server` | Meta's WhatsApp Cloud API. The server does not start without them. For the web chat only, any value works. |
| `ELEVENLABS_AGENT_ID` | `zonia-server`, voice | The id of the ElevenLabs agent. |
| `ELEVENLABS_LLM_KEY` | `zonia-server`, voice | A secret you make (for example `openssl rand -hex 32`). ElevenLabs sends it on each request. Use a different value from the LLM key. |

## Run it

| Command | What it does |
|---|---|
| `uv run zonia` | Chat with Sonia in the terminal. `uv run zonia <id>` continues a saved conversation. |
| `uv run zonia-server` | The candidate side on http://127.0.0.1:8001: the job page, the web chat, voice, and the WhatsApp webhook. |
| `uv run zonia-dashboard` | The recruiter dashboard on http://127.0.0.1:8000: every candidate, the status, the data and the summary. |
| `uv run zonia-followups` | Checks every open conversation once and sends the reminders that are due. In production a scheduler (for example cron) runs it every minute. |
| `uv run pytest` | The unit tests, with a fake LLM. |
| `uv run python evals/run.py` | The evals: 29 scripted conversations with the real LLM. See [evals/README.md](evals/README.md). |
| `uv run python evals/samples.py` | Writes the sample conversations in [deliverables/sample-conversations/](deliverables/sample-conversations/). |

### Web chat

1. Start `uv run zonia-server`.
2. Open http://127.0.0.1:8001/apply. This is a mock job page with the job facts.
3. Write a phone number that starts with `+34` (Spain) or `+52` (Mexico), and send it. The page starts with a test number.
4. The chat opens at `/chat/<case code>`. The case code is the conversation's public id.

### Voice

Voice uses an ElevenLabs agent with the "custom LLM" option. ElevenLabs turns speech into text, calls Sonia's server, and turns her reply into speech.

1. Give the server a public address, for example `ngrok http 8001`.
2. In the ElevenLabs agent, set the custom LLM URL to `<public address>/voice`.
3. Add the value of `ELEVENLABS_LLM_KEY` as the agent's API key secret.
4. In the agent's security settings, allow overrides of the first message and of the custom LLM extra body.
5. Publish the agent. Calls use the published version, not the draft.
6. In the web chat, click "Hablar por voz".

### WhatsApp

1. Create a Meta app with the WhatsApp product, and fill in the four `META_` variables.
2. Give the server a public address, for example `ngrok http 8001`.
3. In the Meta app, set the webhook URL to `<public address>/webhooks/whatsapp` and the verify token to `META_VERIFY_TOKEN`.

Meta delivers messages only after the business is verified. Until then, the web chat is the demo channel.

## Architecture

```text
 WhatsApp ─┐
 Web chat ─┼─> adapters (src/zonia/adapters/) ─────────> core: one turn (src/zonia/agent/turn.py) ──> LLM
 Voice ────┘                                                   │
 Terminal (src/zonia/cli.py) ───────────────────────────────────┤
                                                               └──> SQLite (src/zonia/storage.py)
 Recruiter dashboard (src/zonia/dashboard/) ──> SQLite
```

- **One core, many channels.** Each channel has an adapter. The adapter gives the candidate's text to the core and sends the reply back on the same channel. The core does not know the channel.
- **The LLM reads, code decides.** In each turn the LLM returns the extracted fields, the candidate's intent and a reply ([src/zonia/agent/turn.py](src/zonia/agent/turn.py)). Code then checks the values ([src/zonia/domain/validation.py](src/zonia/domain/validation.py)) and decides the stage and the status ([src/zonia/domain/flow.py](src/zonia/domain/flow.py)).
- **A second LLM call only when needed.** When the status changes, or a value is not valid, a second call writes the reply again with a directive. Code writes the summary, so the data in it is exact.
- **Stages:** `introduction`, `data_collection`, `closing`.
- **Statuses:** `active`, `paused`, `qualified`, `disqualified`, `withdrawn`, `incomplete`, and `technical_error` after 2 failed turns in a row. `technical_error` is not final: a good turn makes the conversation `active` again. The dashboard highlights it, so the recruiter contacts the candidate.
- **Storage:** SQLite keeps each conversation, its data and every message. The recruiter reads it in the dashboard.

## Key decisions

1. **Ports and adapters.** All conversation logic is in one core. To add a channel, you write an adapter, and the core does not change.
2. **Text first.** 60% of candidates do not answer phone calls, and WhatsApp is the main messaging app in Spain and Mexico. So the main channel is written messages. A web chat gives the same experience for the demo.
3. **Voice in the browser through ElevenLabs.** ElevenLabs handles speech. Sonia's server stays the only "brain", so voice follows the same flow and the same checks as text.
4. **Business settings are configuration, not code.** Service zones, the job facts Sonia may share, the greeting, the turn limit, the follow-up times, the contact emails and Sonia's personality are in [src/zonia/config.py](src/zonia/config.py).
5. **Sonia never invents facts.** She answers questions only from the job facts. For anything else, she says she does not have that information.
6. **Spanish and English, with each country's words.** Sonia replies in the candidate's language. In Spain she says "carné de conducir" and "barrio"; in Mexico, "licencia de manejo" and "colonia".
7. **A person can always review.** A disqualified candidate gets a contact email and a case code to ask for a human review.

## Improvements

- After a final status, keep Sonia inside the job facts: in a test she gave opinions and invented company facts.
- Fix a wrong zone after a correction: when a candidate corrects the zone in the summary, the LLM can mark a valid zone as outside the service area.
- Mark a field "needs review" after 2 failed tries, so the conversation moves on.
- Save the candidate's message before the LLM call, so a crash does not lose it.
- Warn the candidate before the turn limit (60 messages).
- Voice: answer the "..." that ElevenLabs sends on silence without an LLM call, and end the call after a long silence.
- Accept voice notes and locations on WhatsApp.
- Consider other languages of Spain and Mexico, such as Catalan or Nahuatl.

## Deliverables

- [Process design document](https://claude.ai/artifact/HbgPjrbaGQnAesS8GQ1rss): stages, fields and validation, outcomes, edge cases, personality, and message tone.
- [Sample conversations](deliverables/sample-conversations/README.md): 7 conversations played against the real LLM.
