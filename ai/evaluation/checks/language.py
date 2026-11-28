"""Check that the reply is in the student's language and short enough to read.

Language: counts Arabic and Latin letters, ignoring digits and symbols, so a variable
such as "p" or a unit such as "cm" in an Arabic reply is fine. Telling Egyptian Arabic
from formal Arabic is left to the LLM judge.

Length: a rough stand-in for reading level. Primary students lose track of very long
sentences. The limits are starting points to tune on the dev cases, not research
findings.
"""
from __future__ import annotations

import re
from typing import Optional

from ai.evaluation.checks import Finding
from ai.evaluation.contract import Check, JudgeInput, Language

MAX_WORDS_PER_SENTENCE = 25
MAX_WORDS = 70
# Below this share of letters in the student's script, the reply is in the wrong language.
MIN_SHARE_IN_LANGUAGE = 0.5

_ARABIC_LETTER = re.compile(r"[ء-ي]")
_LATIN_LETTER = re.compile(r"[A-Za-z]")
_SENTENCE_END = re.compile(r"[.!?؟\n]+")


def check_language(judge_input: JudgeInput) -> Optional[Finding]:
    reply = judge_input.tutor_reply
    arabic = len(_ARABIC_LETTER.findall(reply))
    latin = len(_LATIN_LETTER.findall(reply))
    if arabic + latin == 0:
        return None
    wanted = arabic if judge_input.language is Language.EGYPTIAN_ARABIC else latin
    share = wanted / (arabic + latin)
    if share < MIN_SHARE_IN_LANGUAGE:
        name = "Arabic" if judge_input.language is Language.EGYPTIAN_ARABIC else "English"
        return Finding(Check.LANGUAGE, f"Only {share:.0%} of the letters are {name}, the student's language.")
    return None


def check_length(judge_input: JudgeInput) -> Optional[Finding]:
    reply = judge_input.tutor_reply
    # Decimal points are not sentence ends.
    sentences = _SENTENCE_END.split(re.sub(r"(?<=\d)\.(?=\d)", "", reply))
    longest = max((len(sentence.split()) for sentence in sentences), default=0)
    total = len(reply.split())
    if longest > MAX_WORDS_PER_SENTENCE:
        return Finding(Check.READING_LEVEL, f"A sentence has {longest} words; the limit is {MAX_WORDS_PER_SENTENCE}.")
    if total > MAX_WORDS:
        return Finding(Check.READING_LEVEL, f"The reply has {total} words; the limit is {MAX_WORDS}.")
    return None
