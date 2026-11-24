# Evals

How Sonia is checked against the real LLM. The unit tests in `tests/` check the code alone with a fake LLM. The evals here check what only the real LLM can show: whether it reads the candidate's messages correctly and whether its replies say the right thing.

## Run

```bash
uv run python evals/run.py                       # all cases
uv run python evals/run.py no_licence full_run_qualified   # only these cases
```

The run uses the provider in `.env`. It waits 4.5 s between LLM requests to stay under the Gemini free tier (15 requests per minute), and it retries a turn on a 429 or 503 error. A full run takes about 6 minutes.

Each run prints a table and saves a report in `reports/`, named by date and time. A report holds the model, the commit, the result of every check, the reason for every failure, and every transcript.

## Simulated candidates

`personas.py` lets an LLM play a candidate with a personality, for example one who jokes or one who answers with one word. The conversations are not scripted. They show how Sonia handles odd, silly or unclear answers.

```bash
uv run python evals/personas.py             # every persona
uv run python evals/personas.py bromista    # only the named personas
```

An LLM judge checks 4 rules for each conversation (`RULES` in `personas.py`). The result is not an exact pass or fail: a person reads the transcripts. The report is saved in `reports/` as `personas_<date>_<time>.md`.

## How a case works

1. A case is a scripted conversation: a list of candidate messages (`cases.py`).
2. `converse()` sends each message as one turn through the real agent. It does not stop at a final status, because a later message can reopen the conversation (`conversation.py`).
3. The checks read the transcript and the final state (`evaluators.py`).

| Check | Kind | What it checks |
|---|---|---|
| `FinalState` | code | The final status, and the stage if given. |
| `FieldsExtracted` | code | The values the LLM extracted. Text matches if contained, ignoring case. |
| `StatusAt` | code | The status after one turn. Shows that a reopened conversation was really closed first. |
| `IntentAt` | code | The intent the LLM read in one turn. |
| `SummaryAt` | code | The summary written by code is the reply of one turn. |
| `LlmCalls` | code | Cost: LLM calls made by the agent (a score, not a pass/fail). |
| `Judge` | LLM | An LLM reads the transcript and decides whether a written rule holds. |

Code checks are used for everything that can be measured exactly. The LLM judge (`pydantic_evals` `judge_output`) is used only for what code cannot measure: whether a question repeats known data, and whether a final reply follows its directive. Every case also runs the judge rule "no repeated question".

## Cases

| Case | What it shows |
|---|---|
| `intent_continue` | "Sí, empecemos" is read as `continue`. |
| `not_now_in_first_message` | "Escríbeme mañana" pauses the conversation, and the reply says so. |
| `not_interested_in_first_message` | "No me interesa" ends it as `withdrawn`, with a goodbye. |
| `withdraws_mid_conversation` | A withdrawal after the name keeps the stage where it happened. |
| `pauses_mid_conversation` | A pause after the name keeps the stage where it happened. |
| `no_licence` | "No tengo carnet" disqualifies, and the reply gives the reason kindly. |
| `no_licence_in_first_message` | The same, when it comes with the name. |
| `zone_outside_the_list` | "Vivo en Salamanca" (a region with no service) disqualifies, and the reply gives the reason kindly. |
| `reopens_after_outside_zone` | A candidate disqualified by zone who then says "Barcelona" goes back to data collection, with the zone "Cataluña". |
| `first_name_only` | "Soy Ana" is not saved: the name needs a surname. The conversation stays in introduction and Sonia asks for the surname. |
| `vague_zone` | "Cerca del centro" saves no zone and does not disqualify. Sonia asks for the city. |
| `voice_lowercase` | A voice call in lowercase (Mexico) gives a summary with capitals in the name and the platform. |
| `availability_specific_weekdays` | "Puedo martes miercoles y jueves" saves no availability. Sonia asks the candidate to choose full-time, part-time or weekends. |
| `availability_other_weekdays` | The same with "puedo lunes miercoles y viernes". |
| `past_start_date` | A date in the past is not saved. Sonia says it has passed and asks for a new one. |
| `start_tomorrow` | "Mañana" becomes tomorrow's date, because the turn is told today's date. |
| `start_date_without_year` | A day and month that already passed this year, without a year, becomes that day next year. |
| `full_run_qualified` | Six messages, all fields extracted, summary by code, qualified. |
| `corrects_the_summary` | A correction shows a new summary with the new value. |
| `everything_in_first_message` | All data in one message gives the summary at once. |
| `zone_before_it_is_asked` | Data given early is not asked again. |
| `no_experience_no_platform_question` | With no experience, the platform is never asked. "Licencia de manejo" (Mexico) is read as a licence. |
| `asks_the_salary_twice` | A candidate who asks about pay a second time gets no figure and not the same sentence as the first time, in other, shorter words. |
| `reopens_after_no_licence` | A disqualified candidate who says they do have a licence goes back to data collection. |
| `reopens_after_withdrawing` | "Bueno, sí me interesa" is read as `continue` and reopens a withdrawn conversation. |
| `qualified_corrects_a_field` | A qualified candidate who corrects a value sees a new summary and is active again. |
| `qualified_no_longer_interested` | A qualified candidate who is no longer interested ends as `withdrawn`. |
| `goodbye_keeps_qualified` | "Gracias, adiós" after qualifying changes nothing, and the reply is a short goodbye. |
| `background_conversation` | A message that is another conversation (voice, background) saves nothing. Sonia says she did not understand and asks again in other words. |

## Limits

- Each case runs once. LLM output varies, so one pass is evidence, not proof.
- The judge is a larger Gemini model than the agent's (`ZONIA_JUDGE_MODEL` in `.env`), with high reasoning effort. It is still from the same family as the agent, so it can favour the agent's style.
