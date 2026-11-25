"""The language of the candidate's last message, decided by code before the LLM is called.

lingua (a language detector that runs without internet) chooses between Spanish and English.
Names of people and places pull an English message to Spanish ("I live in Triana, Sevilla"),
so code removes them first: the words with a capital letter that do not start a sentence.
The language changes only when at least MIN_WORDS words are left and lingua's confidence
is at least MIN_CONFIDENCE; otherwise the conversation keeps its current language.
"""

import re
from functools import cache

from lingua import Language as LinguaLanguage
from lingua import LanguageDetector, LanguageDetectorBuilder

from zonia.domain.models import Language

MIN_CONFIDENCE = 0.7  # from 0 to 1; below this, the current language is kept
MIN_WORDS = 2  # one word alone ("Glovo", "Sure") is not enough to change the language

_CODES = {LinguaLanguage.SPANISH: "es", LinguaLanguage.ENGLISH: "en"}
_TOKENS = re.compile(r"[^\W\d_]+(?:'[^\W\d_]+)?|[.!?¿¡]")


@cache
def _detector() -> LanguageDetector:
    """Built once, on first use: building it loads the language models."""
    return LanguageDetectorBuilder.from_languages(*_CODES).build()


def without_names(text: str) -> list[str]:
    """The words of text without names: a word with a capital letter is dropped
    unless it starts a sentence or is the English "I" ("I", "I'm", "I've")."""
    words, sentence_start = [], True
    for token in _TOKENS.findall(text):
        if token in ".!?¿¡":
            sentence_start = True
            continue
        if sentence_start or not token[0].isupper() or token == "I" or token.startswith("I'"):
            words.append(token)
        sentence_start = False
    return words


def detect_language(text: str, current: Language) -> Language:
    """The language of text, or current when lingua is not sure enough."""
    words = without_names(text)
    if len(words) < MIN_WORDS:
        return current
    values = _detector().compute_language_confidence_values(" ".join(words))
    if not values or values[0].value < MIN_CONFIDENCE:
        return current
    return _CODES[values[0].language]
