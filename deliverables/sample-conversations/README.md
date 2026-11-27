# Sample conversations

Open index.html in a browser.

Played against the real LLM (`gemini-3.5-flash-lite`, prompt `sonia@7`) on 2026-11-27.
Sonia's replies are what the model wrote.

## Normal flow

The candidate's messages are a fixed script.

| Sample | What it shows | Channel | Country | Final status |
|---|---|---|---|---|
| [full_run_qualified](full_run_qualified.html) | A candidate gives every answer and qualifies | Web chat | ES | qualified |
| [asks_the_salary](asks_the_salary.html) | The candidate asks about pay, which is not in the job facts | Web chat | ES | qualified |
| [switches_to_english](switches_to_english.html) | The candidate switches to English in the middle | Web chat | ES | qualified |
| [no_licence](no_licence.html) | The candidate has no driving licence | Web chat | ES | disqualified |
| [zone_outside_the_list](zone_outside_the_list.html) | The candidate lives outside the service zones | Web chat | ES | disqualified |
| [mexico_uses_its_words](mexico_uses_its_words.html) | A candidate in Mexico: Sonia uses the Mexican words | Web chat | MX | disqualified |
| [withdraws_mid_conversation](withdraws_mid_conversation.html) | The candidate withdraws in the middle | Web chat | ES | withdrawn |

## Resilience

The candidate is another LLM agent that talks with Sonia. Each agent gets a persona: a name, its data and a way of behaving (a joker, a distrustful candidate, an attacker). Sonia does not know it talks to an agent. The agents run on the same model as Sonia, except the attacker, which runs on a stronger model (`gemini-3.5-flash`).

| Sample | What it shows | Channel | Country | Final status |
|---|---|---|---|---|
| [voz_dudoso](voz_dudoso.html) | A hesitant caller in Mexico who corrects herself and asks Sonia to repeat | Voice | MX | qualified |
| [manipulador](manipulador.html) | A candidate who pushes to be approved at once and claims to know the boss | Web chat | ES | qualified |
| [bromista](bromista.html) | A joker who wraps every answer in jokes, and Sonia keeps only the data | Web chat | ES | qualified |
| [hacker](hacker.html) | An attacker who tries prompt injection and fake system messages | Web chat | ES | qualified |
