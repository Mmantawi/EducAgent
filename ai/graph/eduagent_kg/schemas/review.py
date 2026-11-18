from datetime import datetime, timezone

from pydantic import Field

from .common import ContractModel
from .enums import DecisionType, ReviewStatus, Severity


class ReviewDecision(ContractModel):
    target_id: str = Field(min_length=1)
    reviewer_id: str = Field(min_length=1)
    decision: DecisionType
    reason: str = Field(min_length=1)
    decided_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    replacement_payload: dict | None = None


class ValidationIssue(ContractModel):
    code: str = Field(min_length=1)
    severity: Severity
    message: str = Field(min_length=1)
    target_id: str | None = None


class ValidationReport(ContractModel):
    graph_id: str = Field(min_length=1)
    validator_version: str = Field(min_length=1)
    is_valid: bool
    issues: list[ValidationIssue] = Field(default_factory=list)
    checked_node_count: int = Field(ge=0)
    checked_relationship_count: int = Field(ge=0)
    relationship_counts_by_type: dict[str, int] = Field(default_factory=dict)
    cycles_by_type: dict[str, list[list[str]]] = Field(default_factory=dict)
    generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class ReviewItem(ContractModel):
    review_id: str = Field(min_length=1)
    category: str = Field(min_length=1)
    target_id: str = Field(min_length=1)
    status: ReviewStatus = ReviewStatus.CANDIDATE
    reason: str = Field(min_length=1)
    payload: dict = Field(default_factory=dict)
    history: list[ReviewDecision] = Field(default_factory=list)


class ReviewQueue(ContractModel):
    graph_id: str = Field(min_length=1)
    items: list[ReviewItem] = Field(default_factory=list)

