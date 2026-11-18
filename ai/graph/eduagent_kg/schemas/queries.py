from pydantic import Field

from .common import ContractModel
from .enums import RelationshipType
from .provenance import SourceReference


class ConceptSummary(ContractModel):
    concept_id: str
    name: str
    aliases: list[str] = Field(default_factory=list)
    description: str | None = None
    subject: str
    grade: int


class ConceptDetail(ConceptSummary):
    original_language: str
    sources: list[SourceReference] = Field(default_factory=list)


class RelationshipPathItem(ContractModel):
    concept: ConceptSummary
    depth: int = Field(ge=1)
    relationship_type: RelationshipType
    direction: str
    relationship_ids: list[str] = Field(default_factory=list)
    provenance: list[SourceReference] = Field(default_factory=list)


class ConceptSearchResponse(ContractModel):
    query: str
    results: list[ConceptSummary]


class PrerequisiteResponse(ContractModel):
    concept_id: str
    max_depth: int
    prerequisites: list[RelationshipPathItem]


class DependentsResponse(ContractModel):
    concept_id: str
    dependents: list[RelationshipPathItem]


class RelatedConceptsResponse(ContractModel):
    concept_id: str
    related: list[RelationshipPathItem]


class ExerciseSummary(ContractModel):
    exercise_id: str
    name: str
    description: str | None = None
    subject: str
    grade: int
    relationship_id: str
    provenance: list[SourceReference] = Field(default_factory=list)


class ExercisesResponse(ContractModel):
    concept_id: str
    exercises: list[ExerciseSummary]


class ConceptSourcesResponse(ContractModel):
    concept_id: str
    sources: list[SourceReference]


class ImportStatistics(ContractModel):
    graph_id: str
    nodes_submitted: int = Field(ge=0)
    approved_relationships_submitted: int = Field(ge=0)
    relationships_excluded: int = Field(ge=0)


class RAGSectionRequest(ContractModel):
    document_id: str
    book_id: str
    section_id: str
    page_start: int
    page_end: int


class TutorGraphContext(ContractModel):
    query: str
    found: bool
    concept: ConceptDetail | None = None
    prerequisites: list[RelationshipPathItem] = Field(default_factory=list)
    sources: list[SourceReference] = Field(default_factory=list)
    rag_section_requests: list[RAGSectionRequest] = Field(default_factory=list)
