"""Everything Sonia's LLM reads belongs to one version: metadata.version in src/zonia/agent/sonia.yaml.

Each version is kept whole in tests/prompt_snapshots/sonia.v<version>.txt: the spec's model and settings,
the system prompt, and the texts code builds each turn, with fixed data.
- The text changed and the file of the current version exists: the test fails. Raise the version.
- The file of the current version does not exist: it is a new version, and the test writes the file.
Files of old versions stay in git: they are the exact text of each version.
"""

import json
from collections.abc import Callable
from pathlib import Path

from test_text_snapshots import COUNTRIES, FIELD_SETS, INVALID, LANGUAGES, NO_LICENSE, PARTIAL, SNAPSHOTS_TODAY
from zonia.agent.llm import SONIA, SONIA_PATH
from zonia.agent.prompts.call_1 import turn_instructions
from zonia.agent.prompts.call_2 import directive, invalid_directive, reply_language
from zonia.agent.schema import turn_model
from zonia.domain.models import Status
from zonia.domain.validation import validate

PROMPT_SNAPSHOTS = Path(__file__).parent / "prompt_snapshots"


def _texts() -> dict[str, Callable[[], str]]:
    """Section name -> the code that writes the text today. The file keeps them in this order."""
    texts: dict[str, Callable[[], str]] = {
        "spec": lambda: f"model: {SONIA.model}\nmodel_settings: {json.dumps(SONIA.model_settings or {})}",
        "system": lambda: SONIA.instructions,
    }
    for country in COUNTRIES:
        for set_name, fields in FIELD_SETS.items():
            texts[f"turn_instructions.{set_name}.{country}"] = (
                lambda f=fields, c=country: turn_instructions(f, SNAPSHOTS_TODAY, country=c)
            )
        texts[f"turn_instructions.partial.en.{country}"] = (
            lambda c=country: turn_instructions(PARTIAL, SNAPSHOTS_TODAY, language="en", country=c)
        )
        for status in Status:
            texts[f"directive.{status}.{country}"] = lambda s=status, c=country: str(directive(s, NO_LICENSE, c))
        texts[f"directive.zone.{country}"] = lambda c=country: str(directive(Status.DISQUALIFIED, PARTIAL, c))
        texts[f"invalid_directive.{country}"] = (
            lambda c=country: invalid_directive(validate(INVALID, SNAPSHOTS_TODAY), c)
        )
        texts[f"schema.{country}"] = lambda c=country: json.dumps(
            turn_model(c).model_json_schema(), ensure_ascii=False, indent=2
        )
    for language in LANGUAGES:
        texts[f"reply_language.{language}"] = lambda lang=language: reply_language(lang)
    return texts


def prompt_text() -> str:
    """Every text Sonia's LLM reads, in one file, each section under a line "=== <section name> ==="."""
    return "".join(f"=== {name} ===\n{write()}\n\n" for name, write in _texts().items())


def test_a_prompt_change_raises_the_version():
    version = SONIA.metadata["version"]
    path = PROMPT_SNAPSHOTS / f"sonia.v{version}.txt"
    text = prompt_text()
    if not path.exists():
        PROMPT_SNAPSHOTS.mkdir(exist_ok=True)
        path.write_text(text, encoding="utf-8")
    assert text == path.read_text(encoding="utf-8"), (
        f"The text Sonia's LLM reads changed, but the version is still {version}. "
        f"Raise metadata.version in {SONIA_PATH.name}, or undo the change. Diff against: {path}"
    )

