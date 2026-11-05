"""Input and output format of the live judge.

Draft: the orchestrator and retrieval owners still need to agree this format.
Citations use (source, page) because that is what retrieval returns today.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional, Tuple

MIN_RUNG = 0
MAX_RUNG = 4


class Language(str, Enum):
    EGYPTIAN_ARABIC = "ar-EG"
    ENGLISH = "en"


class AnswerSource(str, Enum):
    """Where the final answer came from, so unverified answers can be treated differently."""

    BANK = "bank"
    COMPUTED = "computed"
    UNVERIFIED = "unverified"


class Check(str, Enum):
    LEAK = "leak"
    CITATION = "citation"
    GROUNDING = "grounding"
    LANGUAGE = "language"
    READING_LEVEL = "reading_level"
    SAFETY = "safety"
    JUDGE_UNAVAILABLE = "judge_unavailable"


class Outcome(str, Enum):
    PASS = "pass"
    REGENERATE = "regenerate"
    FALLBACK = "fallback"


class Layer(str, Enum):
    CODE = "code"
    LLM = "llm"


@dataclass(frozen=True)
class PageRef:
    source: str
    page: int


@dataclass(frozen=True)
class RetrievedPage:
    ref: PageRef
    text: str


@dataclass(frozen=True)
class JudgeInput:
    student_message: str
    tutor_reply: str
    allowed_rung: int
    grade: int
    language: Language
    retrieved_pages: Tuple[RetrievedPage, ...] = ()
    cited_pages: Tuple[PageRef, ...] = ()
    final_answer: Optional[str] = None
    answer_source: Optional[AnswerSource] = None

    def __post_init__(self) -> None:
        if not MIN_RUNG <= self.allowed_rung <= MAX_RUNG:
            raise ValueError(f"allowed_rung must be {MIN_RUNG}-{MAX_RUNG}, got {self.allowed_rung}")
        if (self.final_answer is None) != (self.answer_source is None):
            raise ValueError("final_answer and answer_source must be set together")


@dataclass(frozen=True)
class JudgeVerdict:
    outcome: Outcome
    layer: Layer
    failed_checks: Tuple[Check, ...] = ()
    reason: str = ""

    def __post_init__(self) -> None:
        if self.outcome is Outcome.PASS and self.failed_checks:
            raise ValueError("a passing verdict cannot have failed checks")
        if self.outcome is not Outcome.PASS and not self.failed_checks:
            raise ValueError("a failing verdict must name at least one failed check")
