"""Find the final answer, or too many worked steps, in a tutor reply.

The answer counts as leaked in any form the parser reads: digits, Arabic digits,
thousands separators, number words, fractions, "884 جزء من مية" or "884 hundredths",
the same amount in another unit, and choice letters.

Limits, left to the LLM judge:
- Leaks described without the value ("a bit more than two").
- Worked steps written without an equals sign, such as a list of partial products.
- The judge does not see the problem text, so a number that is both in the problem
  and the answer would be flagged.
- Small answers such as 1 or 2 are flagged whenever the number appears, even in an
  unrelated hint ("two factors"). A needless regeneration is safer than a leak.
"""
from __future__ import annotations

import re
from fractions import Fraction
from typing import Iterator, List, Optional, Tuple

from ai.evaluation.checks import Finding
from ai.evaluation.contract import MAX_RUNG, Check, JudgeInput
from ai.evaluation.normalize import Answer, normalize_text, parse_answer, parse_number

_NUMBER_TOKEN = re.compile(r"\d[\d,]*(?:\.\d+)?(?:/\d+)?|\.\d+")
_EQUATION = re.compile(
    r"\d[\d,]*(?:\.\d+)?\s*[×x*÷/+-]\s*\d[\d,]*(?:\.\d+)?(?:\s*[×x*÷/+-]\s*\d[\d,]*(?:\.\d+)?)*\s*=\s*\d"
)
# "884 جزء من مية", "884 hundredths", "واحد من مية".
_PART_WORDS = {
    "عشره": 10, "ميه": 100, "مائه": 100, "مئه": 100, "مايه": 100, "الف": 1000,
    "tenths": 10, "hundredths": 100, "thousandths": 1000,
    "tenth": 10, "hundredth": 100, "thousandth": 1000,
}
_ARABIC_CHOICES = {"ا": "أ", "ب": "ب", "ج": "جـ", "د": "د", "ه": "هـ", "و": "و"}
_MAX_WORDS = 7
# Worked equations each rung may show. Rung 3 may show every step except the answer.
_EQUATIONS_ALLOWED = {0: 0, 1: 0, 2: 1}


def check_leak(judge_input: JudgeInput) -> Optional[Finding]:
    if judge_input.allowed_rung >= MAX_RUNG:
        return None
    text = normalize_text(judge_input.tutor_reply)
    if judge_input.final_answer:
        expected = parse_answer(judge_input.final_answer)
        if expected is not None:
            found = _find_answer(text, expected)
            if found:
                return Finding(Check.LEAK, f"The reply gives the answer as {found!r}.", "final_answer")

    allowed = _EQUATIONS_ALLOWED.get(judge_input.allowed_rung)
    if allowed is not None:
        worked = len(_EQUATION.findall(text))
        if worked > allowed:
            return Finding(
                Check.LEAK,
                f"The reply works out {worked} step(s), but rung {judge_input.allowed_rung} allows {allowed}.",
                "too_many_steps",
            )
    return None


def _find_answer(text: str, expected: Answer) -> Optional[str]:
    if expected.kind == "choice":
        return _find_choices(text, expected.choices)
    targets = _target_values(expected)
    for shown, value, unit in _candidates(text):
        if unit is not None and expected.kind == "quantity":
            if unit.dimension == expected.unit.dimension and value * unit.factor == expected.in_base_unit():
                return shown
        elif value in targets:
            return shown
    return None


def _target_values(expected: Answer) -> set:
    """Values that give the answer away when written as a bare number.

    Only the key's own number counts. Other units need the unit written ("0.43 L"),
    because bare numbers such as 1 or 100 appear in hints all the time.
    """
    return {expected.value}


def _candidates(text: str) -> Iterator[Tuple[str, Fraction, Optional[object]]]:
    """Every value written in the text, with the unit after it if there is one."""
    tokens = text.split()
    for index, token in enumerate(tokens):
        for match in _NUMBER_TOKEN.finditer(token):
            number_text = match.group().rstrip(",")
            value = parse_number(number_text)
            if value is None:
                continue
            following = tokens[index + 1:index + 4]
            yield from _with_parts_and_units(number_text, value, following, token[match.end():])

    for start in range(len(tokens)):
        for end in range(start + 1, min(start + _MAX_WORDS, len(tokens)) + 1):
            span = tokens[start:end]
            if any(ch.isdigit() for word in span for ch in word):
                break
            phrase = " ".join(span).strip(".,!?؟:;()")
            value = parse_number(phrase)
            if value is not None:
                yield from _with_parts_and_units(phrase, value, tokens[end:end + 3], "")
            elif end < len(tokens):
                yield from _split_parts(phrase, tokens[end:end + 3])


def _with_parts_and_units(shown: str, value: Fraction, following: List[str], attached: str):
    words = [word.strip(".,!?؟:;()") for word in following]
    part = _part_size(words)
    if part:
        yield f"{shown} {' '.join(words[:part[1]])}", value / part[0], None
        return
    unit_text = attached or (words[0] if words else "")
    if unit_text:
        quantity = parse_answer(f"1 {unit_text}")
        if quantity is not None and quantity.kind == "quantity":
            yield f"{shown} {unit_text}", value, quantity.unit
            return
    yield shown, value, None


def _part_size(words: List[str]) -> Optional[Tuple[int, int]]:
    """(denominator, words used) for "جزء من مية", "من مية" or "hundredths"."""
    if words[:1] and words[0] in _PART_WORDS:
        return _PART_WORDS[words[0]], 1
    for lead in (["جزء", "من"], ["من"]):
        size = len(lead)
        if words[:size] == lead and len(words) > size and words[size] in _PART_WORDS:
            return _PART_WORDS[words[size]], size + 1
    return None


def _split_parts(phrase: str, following: List[str]):
    """"اتنين وواحد من مية" is 2 plus 1/100."""
    words = [word.strip(".,!?؟:;()") for word in following]
    part = _part_size(words)
    if not part or " و" not in f" {phrase}":
        return
    left, _, right = phrase.rpartition(" و")
    whole, fraction = parse_number(left), parse_number(right)
    if whole is not None and fraction is not None:
        yield f"{phrase} {' '.join(words[:part[1]])}", whole + fraction / part[0], None


def _find_choices(text: str, choices: Tuple[str, ...]) -> Optional[str]:
    standalone = set()
    for word in re.split(r"[\s,()\[\].:;!?؟]+", text):
        if word in _ARABIC_CHOICES:
            standalone.add(_ARABIC_CHOICES[word])
        elif len(word) == 1 and word in "abcdef":
            standalone.add(word)
    if set(choices) <= standalone:
        return ", ".join(choices)
    return None
