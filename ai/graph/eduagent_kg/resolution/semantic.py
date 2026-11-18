from abc import ABC, abstractmethod
from dataclasses import dataclass

from eduagent_kg.schemas.extraction import ExtractedEntity


@dataclass(frozen=True)
class SemanticCandidate:
    left_mention_id: str
    right_mention_id: str
    score: float
    rationale: str


class SemanticCandidateProvider(ABC):
    """Optional candidate generator; it never authorizes a merge."""

    @abstractmethod
    def candidates(
        self, mentions: list[tuple[str, ExtractedEntity]]
    ) -> list[SemanticCandidate]: ...
