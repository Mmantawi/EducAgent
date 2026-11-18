from datetime import datetime
from typing import Literal

from pydantic import Field, model_validator

from .common import ContractModel
from .enums import NodeType, RelationshipType


class GoldEntity(ContractModel):
    gold_id: str
    node_type: NodeType
    name: str
    aliases: list[str] = Field(default_factory=list)
    evidence_text: str


class GoldRelationship(ContractModel):
    relationship_type: RelationshipType
    source_gold_id: str
    target_gold_id: str
    evidence_text: str


class GoldSection(ContractModel):
    document_id: str
    book_id: str
    section_id: str
    grade: int
    subject: str
    original_language: str
    page_start: int
    page_end: int
    text: str
    entities: list[GoldEntity] = Field(default_factory=list)
    relationships: list[GoldRelationship] = Field(default_factory=list)


class RetrievalGoldCase(ContractModel):
    query: str
    concept_name: str | None = None
    concept_id: str | None = None
    expected_direct_prerequisite_names: list[str] = Field(default_factory=list)
    expected_section_ids: list[str] = Field(default_factory=list)
    expect_missing: bool = False


class GoldDataset(ContractModel):
    dataset_id: str
    version: str
    annotation_status: Literal["draft_unverified", "verified"]
    annotator: str | None = None
    reviewed_at: datetime | None = None
    annotation_notes: str | None = None
    sections: list[GoldSection]
    retrieval_cases: list[RetrievalGoldCase] = Field(default_factory=list)

    @model_validator(mode="after")
    def verified_requires_human_metadata(self):
        if self.annotation_status == "verified" and (not self.annotator or not self.reviewed_at):
            raise ValueError("verified datasets require annotator and reviewed_at")
        return self


class PRFMetrics(ContractModel):
    true_positives: int
    false_positives: int
    false_negatives: int
    precision: float
    recall: float
    f1: float


class GraphIntegrityMetrics(ContractModel):
    cycle_count: int
    invalid_edge_count: int
    duplicate_canonical_node_count: int
    missing_provenance_count: int


class RetrievalMetrics(ContractModel):
    evaluated_cases: int
    direct_prerequisite_accuracy: float
    source_reference_accuracy: float
    missing_concept_accuracy: float


class EvaluationReport(ContractModel):
    dataset_id: str
    metrics_available: bool
    unavailable_reason: str | None = None
    entity_metrics: PRFMetrics | None = None
    relationship_metrics: PRFMetrics | None = None
    graph_integrity: GraphIntegrityMetrics | None = None
    retrieval_metrics: RetrievalMetrics | None = None
