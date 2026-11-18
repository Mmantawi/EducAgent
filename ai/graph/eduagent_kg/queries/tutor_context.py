from eduagent_kg.schemas.queries import RAGSectionRequest, TutorGraphContext

from .service import GraphQueryService


def build_tutor_graph_context(
    service: GraphQueryService, query_or_id: str, *, max_prerequisite_depth: int = 1
) -> TutorGraphContext:
    concept = service.get_concept(query_or_id)
    if concept is None:
        matches = service.search_concepts(query_or_id, limit=1).results
        concept = service.get_concept(matches[0].concept_id) if matches else None
    if concept is None:
        return TutorGraphContext(query=query_or_id, found=False)
    prerequisites = service.get_prerequisites(
        concept.concept_id, max_depth=max_prerequisite_depth
    ).prerequisites
    sources = service.get_concept_sources(concept.concept_id).sources
    for prerequisite in prerequisites:
        sources.extend(
            service.get_concept_sources(prerequisite.concept.concept_id).sources
        )
    unique_sources = list({source.source_ref_id: source for source in sources}.values())
    rag_requests = [
        RAGSectionRequest(
            document_id=source.document_id, book_id=source.book_id,
            section_id=source.section_id, page_start=source.page_start,
            page_end=source.page_end,
        )
        for source in {
            (item.document_id, item.book_id, item.section_id, item.page_start, item.page_end): item
            for item in unique_sources
        }.values()
    ]
    return TutorGraphContext(
        query=query_or_id, found=True, concept=concept,
        prerequisites=prerequisites, sources=unique_sources,
        rag_section_requests=rag_requests,
    )
