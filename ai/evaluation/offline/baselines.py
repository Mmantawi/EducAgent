"""Simple judges to compare real ones against. Neither is meant for real use.

- always_pass never fails a reply. Its catch rate is the floor.
- naive_answer_match fails a reply when the final answer's number appears in it as
  written. It misses other forms such as "0.43 L" for "430 mL", or numbers in words.
"""
from __future__ import annotations

import re

from ai.evaluation.contract import MAX_RUNG, Check, JudgeInput, JudgeVerdict, Layer, Outcome

_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩٫٬", "0123456789.,")
_NUMBER = re.compile(r"\d+(?:\.\d+)?")


def _plain_numbers(text: str) -> str:
    text = text.translate(_DIGITS)
    return re.sub(r"(?<=\d),(?=\d{3}(?:\D|$))", "", text)


def always_pass(judge_input: JudgeInput) -> JudgeVerdict:
    return JudgeVerdict(Outcome.PASS, Layer.CODE)


def naive_answer_match(judge_input: JudgeInput) -> JudgeVerdict:
    answer = judge_input.final_answer
    if answer is None or judge_input.allowed_rung >= MAX_RUNG:
        return JudgeVerdict(Outcome.PASS, Layer.CODE)
    match = _NUMBER.search(_plain_numbers(answer))
    if match is None:
        return JudgeVerdict(Outcome.PASS, Layer.CODE)
    number = re.escape(match.group())
    if re.search(rf"(?<![\d.]){number}(?![\d]|\.\d)", _plain_numbers(judge_input.tutor_reply)):
        return JudgeVerdict(Outcome.REGENERATE, Layer.CODE, (Check.LEAK,), f"Reply contains the answer {match.group()}")
    return JudgeVerdict(Outcome.PASS, Layer.CODE)


JUDGES = {
    "always_pass": always_pass,
    "naive_answer_match": naive_answer_match,
}
