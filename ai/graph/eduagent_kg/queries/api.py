from contextlib import asynccontextmanager

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Query, Request

from eduagent_kg.config import Settings
from eduagent_kg.schemas.queries import (
    ConceptDetail, ConceptSearchResponse, ConceptSourcesResponse, DependentsResponse,
    ExercisesResponse, PrerequisiteResponse, RelatedConceptsResponse,
)
from eduagent_kg.storage import Neo4jGraphStore

from .neo4j import Neo4jGraphQueryRepository
from .service import GraphQueryService


def get_graph_service(request: Request) -> GraphQueryService:
    return request.app.state.graph_service


def create_router() -> APIRouter:
    router = APIRouter(prefix="/graph", tags=["knowledge-graph"])

    @router.get("/concepts/search", response_model=ConceptSearchResponse)
    def search_concepts(
        q: str = Query(min_length=1), subject: str | None = None,
        grade: int | None = Query(default=None, ge=1, le=12),
        limit: int = Query(default=5, ge=1, le=100),
        service: GraphQueryService = Depends(get_graph_service),
    ):
        return service.search_concepts(q, subject=subject, grade=grade, limit=limit)

    @router.get("/concepts/{concept_id}", response_model=ConceptDetail)
    def get_concept(concept_id: str, service: GraphQueryService = Depends(get_graph_service)):
        return _require_concept(service, concept_id)

    @router.get("/concepts/{concept_id}/prerequisites", response_model=PrerequisiteResponse)
    def get_prerequisites(
        concept_id: str, max_depth: int = Query(default=1, ge=1, le=10),
        service: GraphQueryService = Depends(get_graph_service),
    ):
        _require_concept(service, concept_id)
        return service.get_prerequisites(concept_id, max_depth=max_depth)

    @router.get("/concepts/{concept_id}/dependents", response_model=DependentsResponse)
    def get_dependents(
        concept_id: str, service: GraphQueryService = Depends(get_graph_service),
    ):
        _require_concept(service, concept_id)
        return service.get_dependents(concept_id)

    @router.get("/concepts/{concept_id}/related", response_model=RelatedConceptsResponse)
    def get_related(
        concept_id: str, service: GraphQueryService = Depends(get_graph_service),
    ):
        _require_concept(service, concept_id)
        return service.get_related_concepts(concept_id)

    @router.get("/concepts/{concept_id}/exercises", response_model=ExercisesResponse)
    def get_exercises(
        concept_id: str, service: GraphQueryService = Depends(get_graph_service),
    ):
        _require_concept(service, concept_id)
        return service.get_exercises(concept_id)

    @router.get("/concepts/{concept_id}/sources", response_model=ConceptSourcesResponse)
    def get_sources(
        concept_id: str, service: GraphQueryService = Depends(get_graph_service),
    ):
        _require_concept(service, concept_id)
        return service.get_concept_sources(concept_id)

    return router


def create_app(
    *, service: GraphQueryService | None = None, settings: Settings | None = None
) -> FastAPI:
    configured_settings = settings or Settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        store = None
        if service is not None:
            app.state.graph_service = service
        else:
            if not configured_settings.neo4j_password:
                raise RuntimeError("EDUAGENT_KG_NEO4J_PASSWORD is required to start the graph API")
            store = Neo4jGraphStore.connect(
                configured_settings.neo4j_uri, configured_settings.neo4j_username,
                configured_settings.neo4j_password, database=configured_settings.neo4j_database,
            )
            store.verify_connectivity()
            app.state.graph_service = GraphQueryService(
                Neo4jGraphQueryRepository(store.driver, database=store.database)
            )
        yield
        if store is not None:
            store.close()

    app = FastAPI(title="EduAgent Knowledge Graph API", version="0.1.0", lifespan=lifespan)
    router = create_router()
    app.state.graph_router = router
    app.include_router(router)
    return app


def _require_concept(service: GraphQueryService, concept_id: str) -> ConceptDetail:
    concept = service.get_concept(concept_id)
    if concept is None:
        raise HTTPException(status_code=404, detail=f"Concept not found: {concept_id}")
    return concept


app = create_app()
