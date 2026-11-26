from pydantic import Field, model_validator

from ..ontology import assert_relationship_allowed
from .common import ContractModel
from .enums import ClaimDisposition, NodeType, RelationshipType, ReviewStatus
from .provenance import ExtractionMetadata, SourceReference


class ExtractedEntity(ContractModel):
    local_id: str = Field(min_length=1, description="Fragment-scoped identifier")
    node_type: NodeType
    name: str = Field(min_length=1)
    description: str | None = None
    aliases: list[str] = Field(default_factory=list)
    attributes: dict[str, str | int | float | bool | None] = Field(default_factory=dict)
    provenance: list[SourceReference] = Field(min_length=1)
    extraction: ExtractionMetadata


class ExtractedRelationship(ContractModel):
    local_id: str = Field(min_length=1)
    relationship_type: RelationshipType
    source_local_id: str = Field(min_length=1)
    target_local_id: str = Field(min_length=1)
    source_type: NodeType
    target_type: NodeType
    provenance: list[SourceReference] = Field(min_length=1)
    extraction: ExtractionMetadata
    rationale: str | None = None
    description: str | None = None
    strength: int | None = Field(default=None, ge=1, le=10)

    @model_validator(mode="after")
    def validate_semantics(self):
        assert_relationship_allowed(self.relationship_type, self.source_type, self.target_type)
        if self.source_local_id == self.target_local_id:
            raise ValueError("self-referential relationships are not allowed")
        if self.extraction.disposition == ClaimDisposition.INFERRED:
            if self.extraction.review_status != ReviewStatus.CANDIDATE:
                raise ValueError("inferred relationships must have candidate review status")
            if not self.rationale or not self.rationale.strip():
                raise ValueError("inferred relationships require a rationale")
        return self


class GraphFragment(ContractModel):
    fragment_id: str = Field(min_length=1)
    document_id: str = Field(min_length=1)
    book_id: str = Field(min_length=1)
    section_id: str = Field(min_length=1)
    entities: list[ExtractedEntity]
    relationships: list[ExtractedRelationship]
    warnings: list[str] = Field(
        default_factory=list, description="Model output items dropped during assembly, and why"
    )

    @model_validator(mode="after")
    def validate_local_references(self):
        entity_map = {entity.local_id: entity for entity in self.entities}
        if len(entity_map) != len(self.entities):
            raise ValueError("entity local_id values must be unique within a fragment")
        relationship_ids = [item.local_id for item in self.relationships]
        if len(set(relationship_ids)) != len(relationship_ids):
            raise ValueError("relationship local_id values must be unique within a fragment")
        for relationship in self.relationships:
            source = entity_map.get(relationship.source_local_id)
            target = entity_map.get(relationship.target_local_id)
            if source is None or target is None:
                raise ValueError("relationship endpoints must reference fragment entities")
            if source.node_type != relationship.source_type or target.node_type != relationship.target_type:
                raise ValueError("relationship endpoint type does not match referenced entity")
        return self

