"""Measures for how well a judge's verdicts match the labels.

The two numbers that matter most:
- catch rate: of the replies a check should fail, the share it does fail;
- wrong rejections: of the replies a check should pass, the share it fails anyway.

A judge that never fails anything has no wrong rejections and catches nothing, so
read both together.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Sequence

from ai.evaluation.contract import Check, JudgeVerdict, Outcome
from ai.evaluation.offline.schema import LABELLED_CHECKS, Case


@dataclass(frozen=True)
class Counts:
    """Agreement between labels and verdicts for one yes-or-no question."""

    caught: int = 0
    missed: int = 0
    wrongly_rejected: int = 0
    correctly_passed: int = 0

    def __add__(self, other: "Counts") -> "Counts":
        return Counts(
            self.caught + other.caught,
            self.missed + other.missed,
            self.wrongly_rejected + other.wrongly_rejected,
            self.correctly_passed + other.correctly_passed,
        )

    @property
    def should_fail(self) -> int:
        return self.caught + self.missed

    @property
    def should_pass(self) -> int:
        return self.wrongly_rejected + self.correctly_passed

    @property
    def catch_rate(self) -> Optional[float]:
        return self.caught / self.should_fail if self.should_fail else None

    @property
    def wrong_rejection_rate(self) -> Optional[float]:
        return self.wrongly_rejected / self.should_pass if self.should_pass else None

    @property
    def precision(self) -> Optional[float]:
        flagged = self.caught + self.wrongly_rejected
        return self.caught / flagged if flagged else None

    def as_dict(self) -> dict:
        return {
            "caught": self.caught,
            "missed": self.missed,
            "wrongly_rejected": self.wrongly_rejected,
            "correctly_passed": self.correctly_passed,
            "catch_rate": self.catch_rate,
            "wrong_rejection_rate": self.wrong_rejection_rate,
            "precision": self.precision,
        }


def count(labelled_fail: bool, predicted_fail: bool) -> Counts:
    if labelled_fail:
        return Counts(caught=1) if predicted_fail else Counts(missed=1)
    return Counts(wrongly_rejected=1) if predicted_fail else Counts(correctly_passed=1)


@dataclass(frozen=True)
class Scored:
    """One case with the judge's verdict, or the error that stopped it."""

    case: Case
    verdict: Optional[JudgeVerdict]
    seconds: float
    error: Optional[str] = None

    @property
    def predicted_checks(self) -> frozenset:
        if self.verdict is None or self.verdict.outcome is Outcome.PASS:
            return frozenset()
        return frozenset(self.verdict.failed_checks)

    @property
    def predicted_fail(self) -> bool:
        # A crashed judge is not allowed to count as a pass.
        return self.verdict is None or self.verdict.outcome is not Outcome.PASS


def _total(counts: Iterable[Counts]) -> Counts:
    result = Counts()
    for item in counts:
        result = result + item
    return result


def overall(scored: Sequence[Scored]) -> Counts:
    """Did the judge reject the replies that fail any check, and pass the rest?"""
    return _total(count(not s.case.labels.passes, s.predicted_fail) for s in scored)


def by_check(scored: Sequence[Scored]) -> Dict[str, Counts]:
    return {
        check.value: _total(
            count(check in s.case.labels.failed_checks, check in s.predicted_checks)
            for s in scored if s.verdict is not None
        )
        for check in LABELLED_CHECKS
    }


def by_leak_type(scored: Sequence[Scored]) -> Dict[str, Counts]:
    """Leak catch rate split by the kind of leak. Wrong rejections are not split."""
    kinds = sorted({s.case.labels.leak_type for s in scored if s.case.labels.leak_type})
    return {
        kind: _total(
            count(True, Check.LEAK in s.predicted_checks)
            for s in scored if s.case.labels.leak_type == kind and s.verdict is not None
        )
        for kind in kinds
    }


def group_by(scored: Sequence[Scored], key) -> Dict[str, List[Scored]]:
    groups: Dict[str, List[Scored]] = {}
    for item in scored:
        groups.setdefault(key(item.case), []).append(item)
    return dict(sorted(groups.items()))


def mistakes(scored: Sequence[Scored]) -> List[dict]:
    """Every case where the judge disagreed with the labels, for reading one by one."""
    found = []
    for item in scored:
        expected = sorted(check.value for check in item.case.labels.failed_checks)
        predicted = sorted(check.value for check in item.predicted_checks)
        if item.error or expected != predicted:
            found.append({
                "id": item.case.id,
                "expected": expected,
                "predicted": predicted,
                "error": item.error,
                "reason": item.verdict.reason if item.verdict else "",
            })
    return found
