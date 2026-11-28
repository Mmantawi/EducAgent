"""Format, loading and validation for judge test cases.

A case is one tutor reply with its labels. See LABEL_GUIDE.md for what the labels mean.
Cases live in a JSON file holding a list of objects; `load_cases` checks every one
and reports all problems at once.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Tuple

from ai.evaluation.contract import (
    MAX_RUNG,
    MIN_RUNG,
    AnswerSource,
    Check,
    JudgeInput,
    Language,
    PageRef,
    RetrievedPage,
)

# Checks a human labels. JUDGE_UNAVAILABLE is a runtime result, never a label.
LABELLED_CHECKS = tuple(check for check in Check if check is not Check.JUDGE_UNAVAILABLE)
LEAK_TYPES = ("final_answer", "too_many_steps")
CATEGORIES = ("normal", "attack")
SPLITS = ("dev", "test")
LABEL_STATUSES = ("draft", "reviewed")
ROLES = ("student", "tutor")


class CaseError(ValueError):
    """One or more cases do not follow the format."""


@dataclass(frozen=True)
class Message:
    role: str
    text: str


@dataclass(frozen=True)
class Labels:
    failed_checks: Tuple[Check, ...] = ()
    leak_type: Optional[str] = None
    notes: str = ""

    @property
    def passes(self) -> bool:
        return not self.failed_checks


@dataclass(frozen=True)
class Case:
    id: str
    language: Language
    grade: int
    subject: str
    category: str
    split: str
    label_status: str
    problem_text: str
    allowed_rung: int
    student_message: str
    tutor_reply: str
    labels: Labels
    final_answer: Optional[str] = None
    answer_source: Optional[AnswerSource] = None
    history: Tuple[Message, ...] = ()
    retrieved_pages: Tuple[RetrievedPage, ...] = ()
    cited_pages: Tuple[PageRef, ...] = ()

    def to_judge_input(self) -> JudgeInput:
        """What the live judge would receive for this turn."""
        return JudgeInput(
            student_message=self.student_message,
            tutor_reply=self.tutor_reply,
            allowed_rung=self.allowed_rung,
            grade=self.grade,
            language=self.language,
            retrieved_pages=self.retrieved_pages,
            cited_pages=self.cited_pages,
            final_answer=self.final_answer,
            answer_source=self.answer_source,
        )


@dataclass
class _Problems:
    messages: List[str] = field(default_factory=list)

    def add(self, case_id: str, message: str) -> None:
        self.messages.append(f"{case_id}: {message}")


def _page_ref(raw: dict) -> PageRef:
    return PageRef(source=str(raw["source"]), page=int(raw["page"]))


def _parse_case(raw: dict, problems: _Problems) -> Optional[Case]:
    case_id = str(raw.get("id", "<no id>"))
    try:
        problem, turn, labels = raw["problem"], raw["turn"], raw["labels"]
        failed = tuple(Check(name) for name in labels.get("failed_checks", []))
        answer_source = problem.get("answer_source")
        case = Case(
            id=case_id,
            language=Language(raw["language"]),
            grade=int(raw["grade"]),
            subject=str(raw["subject"]),
            category=str(raw["category"]),
            split=str(raw["split"]),
            label_status=str(raw["label_status"]),
            problem_text=str(problem["text"]),
            final_answer=problem.get("final_answer"),
            answer_source=AnswerSource(answer_source) if answer_source else None,
            history=tuple(Message(str(m["role"]), str(m["text"])) for m in raw.get("history", [])),
            allowed_rung=int(turn["allowed_rung"]),
            student_message=str(turn["student_message"]),
            retrieved_pages=tuple(
                RetrievedPage(ref=_page_ref(page), text=str(page["text"])) for page in turn.get("retrieved_pages", [])
            ),
            cited_pages=tuple(_page_ref(page) for page in turn.get("cited_pages", [])),
            tutor_reply=str(turn["tutor_reply"]),
            labels=Labels(failed_checks=failed, leak_type=labels.get("leak_type"), notes=str(labels.get("notes", ""))),
        )
    except (KeyError, TypeError, ValueError) as error:
        problems.add(case_id, f"cannot read: {type(error).__name__}: {error}")
        return None

    for value, allowed, name in (
        (case.category, CATEGORIES, "category"),
        (case.split, SPLITS, "split"),
        (case.label_status, LABEL_STATUSES, "label_status"),
    ):
        if value not in allowed:
            problems.add(case_id, f"{name} must be one of {allowed}, got {value!r}")
    if not MIN_RUNG <= case.allowed_rung <= MAX_RUNG:
        problems.add(case_id, f"allowed_rung must be {MIN_RUNG}-{MAX_RUNG}")
    if (case.final_answer is None) != (case.answer_source is None):
        problems.add(case_id, "final_answer and answer_source must be set together")
    if Check.JUDGE_UNAVAILABLE in case.labels.failed_checks:
        problems.add(case_id, "judge_unavailable is a runtime result, not a label")
    if len(set(case.labels.failed_checks)) != len(case.labels.failed_checks):
        problems.add(case_id, "a check is listed twice")
    has_leak = Check.LEAK in case.labels.failed_checks
    if has_leak and case.labels.leak_type not in LEAK_TYPES:
        problems.add(case_id, f"a leak needs leak_type, one of {LEAK_TYPES}")
    if not has_leak and case.labels.leak_type is not None:
        problems.add(case_id, "leak_type is set but leak is not a failed check")
    for message in case.history:
        if message.role not in ROLES:
            problems.add(case_id, f"history role must be one of {ROLES}, got {message.role!r}")
    if not case.tutor_reply.strip() or not case.student_message.strip():
        problems.add(case_id, "student_message and tutor_reply must not be empty")
    return case


def parse_cases(raw_cases: list) -> List[Case]:
    """Check and convert raw case objects. Raises CaseError listing every problem."""
    if not isinstance(raw_cases, list):
        raise CaseError("the file must hold a list of cases")
    problems = _Problems()
    cases = [case for case in (_parse_case(raw, problems) for raw in raw_cases) if case]
    seen = set()
    for case in cases:
        if case.id in seen:
            problems.add(case.id, "id is used more than once")
        seen.add(case.id)
    if problems.messages:
        raise CaseError("\n".join(problems.messages))
    return cases


def load_cases(path) -> List[Case]:
    """Load and check cases from a JSON file."""
    return parse_cases(json.loads(Path(path).read_text(encoding="utf-8")))
