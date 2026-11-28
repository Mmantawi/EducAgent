"""Check a child's math answer against the answer key, in code.

check_answer returns one of four results:
- correct: the same value, in any form or unit the parser reads ("1/2", "0.5", "نص").
- wrong: a readable answer with a different value or the wrong kind of unit.
- partial: partly right. The right number with its unit missing, or only some of
  the right choice letters with nothing wrong added.
- cannot_check: the answer or the key could not be read with confidence.

The rule that matters most: never mark a child wrong because of a guess. Anything
unclear is cannot_check, so the tutor can ask the child to write it again.

Exact values only. There is no rounding tolerance yet, so answers to "round to"
questions or long divisions such as 121.1 ÷ 9 need their exact key.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional, Union

from ai.evaluation.normalize import Answer, parse_answer, units_of


class Result(str, Enum):
    CORRECT = "correct"
    WRONG = "wrong"
    PARTIAL = "partial"
    CANNOT_CHECK = "cannot_check"


@dataclass(frozen=True)
class Check:
    result: Result
    reason: str
    student: Optional[Answer] = None
    expected: Optional[Answer] = None


def check_answer(student_text: str, answer_key: Union[str, Answer]) -> Check:
    """Compare what the child wrote with the answer key."""
    expected = answer_key if isinstance(answer_key, Answer) else parse_answer(answer_key)
    if expected is None:
        return Check(Result.CANNOT_CHECK, "The answer key could not be read.")
    student = parse_answer(student_text)
    if student is None:
        return Check(Result.CANNOT_CHECK, "The answer could not be read with confidence.", expected=expected)

    if expected.kind == "choice":
        return _check_choices(student, expected)
    if student.kind == "choice":
        return Check(Result.CANNOT_CHECK, "Choice letters were given, but the key is a value.", student, expected)
    if expected.kind == "quantity":
        return _check_quantity(student, expected)
    return _check_number(student, expected)


def _check_number(student: Answer, expected: Answer) -> Check:
    if student.value == expected.value:
        reason = "Same value." if student.kind == "number" else "Same value. The unit was not needed."
        return Check(Result.CORRECT, reason, student, expected)
    return Check(Result.WRONG, "A different value.", student, expected)


def _check_quantity(student: Answer, expected: Answer) -> Check:
    if student.kind == "number":
        if student.value == expected.value:
            return Check(Result.PARTIAL, "The right number, but the unit is missing.", student, expected)
        # 4380 for a key of 4.38 kg is right if the child meant grams, so ask instead of guessing.
        matching = [
            unit.name for unit in units_of(expected.unit.dimension)
            if unit != expected.unit and student.value * unit.factor == expected.in_base_unit()
        ]
        if matching:
            return Check(
                Result.CANNOT_CHECK,
                f"The number is right if the unit is {' or '.join(matching)}, but no unit was given.",
                student,
                expected,
            )
        return Check(Result.WRONG, "A different value, and the unit is missing.", student, expected)
    if student.unit.dimension != expected.unit.dimension:
        return Check(
            Result.WRONG,
            f"A {student.unit.dimension} unit was used, but the answer is a {expected.unit.dimension}.",
            student,
            expected,
        )
    if student.in_base_unit() == expected.in_base_unit():
        same_unit = student.unit.name == expected.unit.name
        return Check(Result.CORRECT, "Same amount." if same_unit else "Same amount in another unit.", student, expected)
    return Check(Result.WRONG, "A different amount.", student, expected)


def _check_choices(student: Answer, expected: Answer) -> Check:
    if student.kind != "choice":
        return Check(Result.CANNOT_CHECK, "A value was given, but the question needs choice letters.", student, expected)
    given, right = set(student.choices), set(expected.choices)
    arabic_letters = {"أ", "ب", "جـ", "د", "هـ", "و"}
    if bool(given & arabic_letters) != bool(right & arabic_letters):
        return Check(Result.CANNOT_CHECK, "Arabic and English choice letters were mixed.", student, expected)
    if given == right:
        return Check(Result.CORRECT, "Same choices.", student, expected)
    if given < right:
        missing = len(right - given)
        return Check(Result.PARTIAL, f"Right so far, with {missing} choice(s) missing.", student, expected)
    return Check(Result.WRONG, "At least one wrong choice.", student, expected)
