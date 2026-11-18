from abc import ABC, abstractmethod

from eduagent_kg.schemas.queries import (
    ConceptDetail, ConceptSearchResponse, ConceptSourcesResponse, DependentsResponse,
    ExercisesResponse, PrerequisiteResponse, RelatedConceptsResponse,
)


class GraphQueryRepository(ABC):
    @abstractmethod
    def search_concepts(self, query: str, subject: str | None, grade: int | None, limit: int): ...

    @abstractmethod
    def get_concept(self, concept_id: str): ...

    @abstractmethod
    def get_prerequisites(self, concept_id: str, max_depth: int): ...

    @abstractmethod
    def get_dependents(self, concept_id: str): ...

    @abstractmethod
    def get_related_concepts(self, concept_id: str): ...

    @abstractmethod
    def get_exercises(self, concept_id: str): ...

    @abstractmethod
    def get_concept_sources(self, concept_id: str): ...


class SemanticConceptSearchProvider(ABC):
    """Future extension point that preserves the public search response contract."""

    @abstractmethod
    def search(self, query: str, subject: str | None, grade: int | None, limit: int): ...


class GraphQueryService:
    def __init__(self, repository: GraphQueryRepository) -> None:
        self.repository = repository

    def search_concepts(
        self, query: str, subject: str | None = None, grade: int | None = None, limit: int = 5
    ) -> ConceptSearchResponse:
        if not query.strip():
            raise ValueError("query must not be empty")
        if not 1 <= limit <= 100:
            raise ValueError("limit must be between 1 and 100")
        return ConceptSearchResponse(
            query=query,
            results=self.repository.search_concepts(query, subject, grade, limit),
        )

    def get_concept(self, concept_id: str) -> ConceptDetail | None:
        return self.repository.get_concept(concept_id)

    def get_prerequisites(self, concept_id: str, max_depth: int = 1) -> PrerequisiteResponse:
        if not 1 <= max_depth <= 10:
            raise ValueError("max_depth must be between 1 and 10")
        return PrerequisiteResponse(
            concept_id=concept_id, max_depth=max_depth,
            prerequisites=self.repository.get_prerequisites(concept_id, max_depth),
        )

    def get_dependents(self, concept_id: str) -> DependentsResponse:
        return DependentsResponse(
            concept_id=concept_id, dependents=self.repository.get_dependents(concept_id)
        )

    def get_related_concepts(self, concept_id: str) -> RelatedConceptsResponse:
        return RelatedConceptsResponse(
            concept_id=concept_id, related=self.repository.get_related_concepts(concept_id)
        )

    def get_exercises(self, concept_id: str) -> ExercisesResponse:
        return ExercisesResponse(
            concept_id=concept_id, exercises=self.repository.get_exercises(concept_id)
        )

    def get_concept_sources(self, concept_id: str) -> ConceptSourcesResponse:
        return ConceptSourcesResponse(
            concept_id=concept_id, sources=self.repository.get_concept_sources(concept_id)
        )
