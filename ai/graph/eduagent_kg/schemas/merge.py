from pydantic import Field

from .common import ContractModel


class MergeStatistics(ContractModel):
    total_extracted_entities: int = Field(ge=0)
    total_canonical_entities: int = Field(ge=0)
    duplicate_candidates: int = Field(ge=0)
    confirmed_merges: int = Field(ge=0)
    relationship_counts_by_type: dict[str, int] = Field(default_factory=dict)
    invalid_edges: int = Field(ge=0)
    detected_cycles: int = Field(ge=0)
    pending_reviews: int = Field(ge=0)
    approved_relationships: int = Field(ge=0)
    rejected_relationships: int = Field(ge=0)
