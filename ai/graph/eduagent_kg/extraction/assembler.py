import unicodedata
from datetime import datetime, timezone

from eduagent_kg.ids import make_source_ref_id, normalize_identity
from eduagent_kg.ontology import assert_relationship_allowed
from eduagent_kg.schemas.documents import TextbookSection
from eduagent_kg.schemas.enums import (
    ClaimDisposition, ExtractionMethod, NodeType, RelationshipType, ReviewStatus,
)
from eduagent_kg.schemas.extraction import ExtractedEntity, ExtractedRelationship, GraphFragment
from eduagent_kg.schemas.llm import SectionExtractionDraft
from eduagent_kg.schemas.provenance import ExtractionMetadata, SourceReference

from .prompt import PROMPT_VERSION
from .provider import ModelOutputError


class GraphFragmentAssembler:
    def assemble(
        self, section: TextbookSection, draft: SectionExtractionDraft, *, provider: str, model: str
    ) -> GraphFragment:
        self._validate_evidence(section, draft)
        source_cache: dict[str | None, SourceReference] = {}

        def source(evidence: str | None) -> SourceReference:
            if evidence not in source_cache:
                source_cache[evidence] = SourceReference(
                    source_ref_id=make_source_ref_id(
                        book_id=section.book_id, section_id=section.section_id,
                        page_start=section.page_start, page_end=section.page_end, evidence=evidence,
                    ),
                    book_id=section.book_id, document_id=section.document_id,
                    section_id=section.section_id, page_start=section.page_start,
                    page_end=section.page_end, evidence_text=evidence, block_ids=section.block_ids,
                )
            return source_cache[evidence]

        llm_metadata = ExtractionMetadata(
            grade=section.grade, subject=section.subject,
            original_language=section.original_language, extraction_method=ExtractionMethod.LLM,
            disposition=ClaimDisposition.EXTRACTED, review_status=ReviewStatus.UNREVIEWED,
            extractor_name=provider, extractor_version="1", model_name=model,
            prompt_version=PROMPT_VERSION, extracted_at=datetime.now(timezone.utc),
        )
        entities: list[ExtractedEntity] = []
        id_map: dict[str, str] = {}
        entity_by_key: dict[tuple[NodeType, str], ExtractedEntity] = {}
        reserved = {"section", "lesson"}
        for item in draft.entities:
            if item.local_id in reserved:
                raise ModelOutputError(f"Entity local_id `{item.local_id}` is reserved")
            key = (NodeType(item.node_type), normalize_identity(item.name))
            if key in entity_by_key:
                existing = entity_by_key[key]
                id_map[item.local_id] = existing.local_id
                existing.aliases = sorted(set(existing.aliases + item.aliases))
                if source(item.evidence_text) not in existing.provenance:
                    existing.provenance.append(source(item.evidence_text))
                continue
            entity = ExtractedEntity(
                local_id=item.local_id, node_type=NodeType(item.node_type), name=item.name,
                description=item.description, aliases=item.aliases,
                provenance=[source(item.evidence_text)], extraction=llm_metadata,
            )
            entities.append(entity)
            entity_by_key[key] = entity
            id_map[item.local_id] = item.local_id

        section_evidence = section.heading if section.heading in section.text else None
        rule_metadata = llm_metadata.model_copy(update={
            "extraction_method": ExtractionMethod.RULE,
            "extractor_name": "eduagent-structure",
            "model_name": None,
            "confidence": 1.0,
        })
        section_entity = ExtractedEntity(
            local_id="section", node_type=NodeType.SOURCE_SECTION, name=section.heading,
            description=None, aliases=[], attributes={"section_id": section.section_id},
            provenance=[source(section_evidence)], extraction=rule_metadata,
        )
        entities.append(section_entity)
        id_map["section"] = "section"

        lesson_name = _lesson_name(section.heading_path)
        if lesson_name:
            lesson_entity = ExtractedEntity(
                local_id="lesson", node_type=NodeType.LESSON, name=lesson_name,
                description=None, aliases=[], attributes={}, provenance=[source(section_evidence)],
                extraction=rule_metadata,
            )
            entities.append(lesson_entity)
            id_map["lesson"] = "lesson"

        types = {entity.local_id: entity.node_type for entity in entities}
        relationships: list[ExtractedRelationship] = []
        seen: set[tuple] = set()
        for item in draft.relationships:
            source_id = id_map.get(item.source_local_id)
            target_id = id_map.get(item.target_local_id)
            if source_id is None or target_id is None:
                raise ModelOutputError(
                    f"Relationship {item.local_id} references an unknown endpoint"
                )
            disposition = ClaimDisposition.INFERRED if item.inferred else ClaimDisposition.EXTRACTED
            status = ReviewStatus.CANDIDATE if item.inferred else ReviewStatus.UNREVIEWED
            assert_relationship_allowed(item.relationship_type, types[source_id], types[target_id])
            key = (item.relationship_type, source_id, target_id, disposition)
            if key in seen:
                continue
            seen.add(key)
            metadata = llm_metadata.model_copy(update={
                "disposition": disposition, "review_status": status,
            })
            relationships.append(ExtractedRelationship(
                local_id=item.local_id, relationship_type=item.relationship_type,
                source_local_id=source_id, target_local_id=target_id,
                source_type=types[source_id], target_type=types[target_id],
                provenance=[source(item.evidence_text)], extraction=metadata,
                rationale=item.rationale,
            ))

        for entity in list(entities):
            if entity.node_type in {NodeType.SOURCE_SECTION, NodeType.LESSON}:
                continue
            key = (RelationshipType.SUPPORTED_BY, entity.local_id, "section", ClaimDisposition.EXTRACTED)
            if key not in seen:
                seen.add(key)
                relationships.append(ExtractedRelationship(
                    local_id=f"support:{entity.local_id}",
                    relationship_type=RelationshipType.SUPPORTED_BY,
                    source_local_id=entity.local_id, target_local_id="section",
                    source_type=entity.node_type, target_type=NodeType.SOURCE_SECTION,
                    provenance=entity.provenance, extraction=rule_metadata,
                ))
        if lesson_name:
            key = (RelationshipType.PART_OF, "section", "lesson", ClaimDisposition.EXTRACTED)
            if key not in seen:
                relationships.append(ExtractedRelationship(
                    local_id="structure:section-part-of-lesson",
                    relationship_type=RelationshipType.PART_OF,
                    source_local_id="section", target_local_id="lesson",
                    source_type=NodeType.SOURCE_SECTION, target_type=NodeType.LESSON,
                    provenance=[source(section_evidence)], extraction=rule_metadata,
                ))
        return GraphFragment(
            fragment_id=f"fragment:{section.section_id}", document_id=section.document_id,
            book_id=section.book_id, section_id=section.section_id,
            entities=entities, relationships=relationships,
        )

    def _validate_evidence(self, section: TextbookSection, draft: SectionExtractionDraft) -> None:
        for entity in draft.entities:
            matched = _exact_source_span(section.text, entity.evidence_text)
            if matched is None:
                raise ModelOutputError(
                    f"Entity {entity.local_id} evidence is not an exact section substring"
                )
            entity.evidence_text = matched
        for relationship in draft.relationships:
            if relationship.evidence_text:
                matched = _exact_source_span(section.text, relationship.evidence_text)
                if matched is None:
                    raise ModelOutputError(
                        f"Relationship {relationship.local_id} evidence is not an exact section substring"
                    )
                relationship.evidence_text = matched


def _lesson_name(path: list[str]) -> str | None:
    for title in reversed(path):
        normalized = unicodedata.normalize("NFKC", title).casefold().strip()
        if normalized.startswith("lesson") or normalized.startswith("الدرس"):
            return title
    return None


def _exact_source_span(source: str, evidence: str) -> str | None:
    """Return the original unique source span, tolerating only whitespace/JSON escape damage."""
    if evidence in source:
        return evidence
    repaired = (
        evidence.replace("\times", "\\times")
        .replace("\text", "\\text")
        .replace("\boxed", "\\boxed")
        .replace("\frac", "\\frac")
        .replace("\rightarrow", "\\rightarrow")
    )
    normalized_source, starts, ends = _collapse_whitespace_with_offsets(source)
    normalized_evidence, _, _ = _collapse_whitespace_with_offsets(repaired)
    if not normalized_evidence:
        return None
    position = normalized_source.find(normalized_evidence)
    if position < 0 or normalized_source.find(normalized_evidence, position + 1) >= 0:
        return None
    last = position + len(normalized_evidence) - 1
    return source[starts[position]:ends[last]]


def _collapse_whitespace_with_offsets(text: str) -> tuple[str, list[int], list[int]]:
    characters: list[str] = []
    starts: list[int] = []
    ends: list[int] = []
    for index, character in enumerate(text):
        if character.isspace():
            if not characters or characters[-1] == " ":
                if characters:
                    ends[-1] = index + 1
                continue
            characters.append(" ")
            starts.append(index)
            ends.append(index + 1)
        else:
            characters.append(character)
            starts.append(index)
            ends.append(index + 1)
    if characters and characters[-1] == " ":
        characters.pop()
        starts.pop()
        ends.pop()
    return "".join(characters), starts, ends
