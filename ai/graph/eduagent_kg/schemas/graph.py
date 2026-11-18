from datetime import datetime, timezone

from pydantic import Field, model_validator

from ..ontology import assert_relationship_allowed
from .common import ContractModel, CurriculumMetadata
from .enums import ClaimDisposition, NodeType, RelationshipType, ReviewStatus
from .provenance import SourceReference
from .review import ReviewDecision


class CanonicalEntity(CurriculumMetadata):
    canonical_id: str = Field(min_length=1, description="Persistent semantic graph identifier")
    node_type: NodeType
    name: str = Field(min_length=1)
    normalized_name: str = Field(min_length=1)
    description: str | None = None
    aliases: list[str] = Field(default_factory=list)
    attributes: dict[str, str | int | float | bool | None] = Field(default_factory=dict)
    source_local_ids: list[str] = Field(default_factory=list)
    provenance: list[SourceReference] = Field(min_length=1)
    review_status: ReviewStatus = ReviewStatus.UNREVIEWED


class CanonicalRelationship(ContractModel):
    canonical_id: str = Field(min_length=1)
    relationship_type: RelationshipType
    source_canonical_id: str = Field(min_length=1)
    target_canonical_id: str = Field(min_length=1)
    source_type: NodeType
    target_type: NodeType
    disposition: ClaimDisposition
    review_status: ReviewStatus
    provenance: list[SourceReference] = Field(min_length=1)
    rationale: str | None = None
    review_history: list[ReviewDecision] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_semantics(self):
        assert_relationship_allowed(self.relationship_type, self.source_type, self.target_type)
        if self.source_canonical_id == self.target_canonical_id:
            raise ValueError("self-referential relationships are not allowed")
        if self.disposition == ClaimDisposition.INFERRED:
            if self.review_status == ReviewStatus.UNREVIEWED:
                raise ValueError("inferred relationships must be candidates until reviewed")
            if not self.rationale or not self.rationale.strip():
                raise ValueError("inferred relationships require a rationale")
        return self


class CanonicalGraph(ContractModel):
    contract_version: str = "1.0"
    graph_id: str = Field(min_length=1)
    subjects: list[str]
    grades: list[int]
    book_ids: list[str]
    nodes: list[CanonicalEntity]
    relationships: list[CanonicalRelationship]
    candidate_relationships: list[CanonicalRelationship] = Field(default_factory=list)
    generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

