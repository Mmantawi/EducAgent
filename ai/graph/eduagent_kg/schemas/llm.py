from typing import Literal

from pydantic import Field, model_validator

from .common import ContractModel
from .enums import NodeType, RelationshipType

ExtractableNodeType = Literal[
    NodeType.CONCEPT, NodeType.SKILL, NodeType.EXERCISE, NodeType.EXPERIMENT
]


class DraftEntity(ContractModel):
    local_id: str = Field(min_length=1, description="Stable descriptive ID within this response")
    node_type: ExtractableNodeType
    name: str = Field(min_length=1, description="Name in the textbook's language")
    aliases: list[str] = Field(default_factory=list)
    description: str | None = None
    evidence_text: str = Field(
        min_length=1, description="Exact supporting substring copied from the supplied section"
    )


class DraftRelationship(ContractModel):
    local_id: str = Field(min_length=1)
    relationship_type: RelationshipType
    source_local_id: str = Field(
        min_length=1, description="Entity local_id, or reserved `lesson`/`section`"
    )
    target_local_id: str = Field(min_length=1)
    evidence_text: str | None = Field(
        default=None, description="Exact supporting substring; required for directly extracted claims"
    )
    inferred: bool = False
    rationale: str | None = None
    description: str | None = Field(
        default=None, description="One sentence explaining how the source relates to the target"
    )
    strength: int | None = Field(
        default=None, ge=1, le=10, description="How strong/central the link is, 1 (weak) to 10 (essential)"
    )

    @model_validator(mode="after")
    def require_inference_rationale(self):
        if self.inferred and (not self.rationale or not self.rationale.strip()):
            raise ValueError("inferred relationships require a rationale")
        if not self.inferred and (not self.evidence_text or not self.evidence_text.strip()):
            raise ValueError("directly extracted relationships require evidence_text")
        if self.source_local_id == self.target_local_id:
            raise ValueError("self-referential relationships are not allowed")
        return self


class SectionExtractionDraft(ContractModel):
    entities: list[DraftEntity] = Field(default_factory=list)
    relationships: list[DraftRelationship] = Field(default_factory=list)
