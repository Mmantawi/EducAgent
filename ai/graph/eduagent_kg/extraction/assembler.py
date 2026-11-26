import re
import unicodedata
from datetime import datetime, timezone
from difflib import SequenceMatcher

from eduagent_kg.ids import make_source_ref_id, normalize_identity
from eduagent_kg.ontology import (
    KNOWLEDGE_NODE_TYPES, SYMMETRIC_RELATIONSHIPS, relationship_is_allowed,
)
from eduagent_kg.schemas.documents import TextbookSection
from eduagent_kg.schemas.enums import (
    ClaimDisposition, ExtractionMethod, NodeType, RelationshipType, ReviewStatus,
)
from eduagent_kg.schemas.extraction import ExtractedEntity, ExtractedRelationship, GraphFragment
from eduagent_kg.schemas.llm import SectionExtractionDraft
from eduagent_kg.schemas.provenance import ExtractionMetadata, SourceReference

from .prompt import PROMPT_VERSION


class GraphFragmentAssembler:
    """Turns one model draft into a graph fragment.

    Invalid items (unverifiable evidence, unknown endpoints, disallowed node or relationship
    types) are dropped one by one and recorded in ``fragment.warnings``; one bad item no
    longer discards the whole section.
    """

    def __init__(self, allowed_node_types: frozenset[NodeType] = KNOWLEDGE_NODE_TYPES) -> None:
        self.allowed_node_types = allowed_node_types

    def assemble(
        self, section: TextbookSection, draft: SectionExtractionDraft, *, provider: str, model: str,
        extra_warnings: tuple[str, ...] | list[str] = (),
    ) -> GraphFragment:
        draft = draft.model_copy(deep=True)
        filter_warnings, unverified = self._filter_draft(section, draft)
        warnings = list(extra_warnings) + filter_warnings
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
            key =(NodeType(item.node_type), normalize_identity(item.name))
            if key in entity_by_key:
                existing = entity_by_key[key]
                id_map[item.local_id] = existing.local_id
                existing.aliases = sorted(set(existing.aliases + item.aliases))
                if source(item.evidence_text) not in existing.provenance:
                    existing.provenance.append(source(item.evidence_text))
                continue
            verified = item.local_id not in unverified
            entity = ExtractedEntity(
                local_id=item.local_id, node_type=NodeType(item.node_type), name=item.name,
                description=item.description, aliases=item.aliases,
                attributes={} if verified else {"evidence_verified": False},
                provenance=[source(item.evidence_text if verified else None)], extraction=llm_metadata,
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
        used_ids: set[str] = set()
        for item in draft.relationships:
            source_id = id_map.get(item.source_local_id)
            target_id = id_map.get(item.target_local_id)
            if source_id is None or target_id is None:
                warnings.append(f"Dropped relationship {item.local_id}: unknown endpoint")
                continue
            if source_id == target_id:
                warnings.append(f"Dropped relationship {item.local_id}: endpoints merged into one entity")
                continue
            if not relationship_is_allowed(item.relationship_type, types[source_id], types[target_id]):
                warnings.append(
                    f"Dropped relationship {item.local_id}: {item.relationship_type.value} does not allow "
                    f"{types[source_id].value} -> {types[target_id].value}"
                )
                continue
            disposition = ClaimDisposition.INFERRED if item.inferred else ClaimDisposition.EXTRACTED
            status = ReviewStatus.CANDIDATE if item.inferred else ReviewStatus.UNREVIEWED
            if item.relationship_type in SYMMETRIC_RELATIONSHIPS and target_id < source_id:
                source_id, target_id = target_id, source_id
            key = (item.relationship_type, source_id, target_id, disposition)
            if key in seen:
                continue
            seen.add(key)
            metadata = llm_metadata.model_copy(update={
                "disposition": disposition, "review_status": status,
            })
            # The model sometimes reuses a relationship id (often across gleaning rounds);
            # a repeated id would make the whole fragment invalid, so rename it instead.
            local_id, suffix = item.local_id, 2
            while local_id in used_ids:
                local_id, suffix = f"{item.local_id}_{suffix}", suffix + 1
            used_ids.add(local_id)
            relationships.append(ExtractedRelationship(
                local_id=local_id, relationship_type=item.relationship_type,
                source_local_id=source_id, target_local_id=target_id,
                source_type=types[source_id], target_type=types[target_id],
                provenance=[source(item.evidence_text)], extraction=metadata,
                rationale=item.rationale, description=item.description, strength=item.strength,
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
            entities=entities, relationships=relationships, warnings=warnings,
        )

    def _filter_draft(
        self, section: TextbookSection, draft: SectionExtractionDraft
    ) -> tuple[list[str], set[str]]:
        """Check quotes and types. Returns warnings and the ids of nodes kept without a verified quote.

        A node whose quote cannot be found (even approximately) is kept but marked
        ``evidence_verified=False`` instead of being deleted: deleting it also deleted every
        link that pointed at it. Unquoted direct links become inferred candidates for review.
        """
        warnings: list[str] = []
        unverified: set[str] = set()
        kept_entities = []
        seen_ids: set[str] = set()
        for entity in draft.entities:
            if entity.local_id in {"section", "lesson"} or entity.local_id in seen_ids:
                warnings.append(f"Dropped entity {entity.local_id}: reserved or duplicate local_id")
                continue
            if NodeType(entity.node_type) not in self.allowed_node_types:
                warnings.append(f"Dropped entity {entity.local_id}: {entity.node_type} nodes are not extracted")
                continue
            matched = _exact_source_span(section.text, entity.evidence_text) or _approximate_span(
                section.text, entity.evidence_text
            )
            if matched is None:
                unverified.add(entity.local_id)
                warnings.append(f"Kept entity {entity.local_id} without a verified quote (needs review)")
            else:
                entity.evidence_text = matched
            kept_entities.append(entity)
            seen_ids.add(entity.local_id)
        draft.entities = kept_entities

        kept_relationships = []
        for relationship in draft.relationships:
            if relationship.evidence_text:
                matched = _exact_source_span(section.text, relationship.evidence_text) or _approximate_span(
                    section.text, relationship.evidence_text
                )
                if matched is None and not relationship.inferred:
                    # model_copy skips per-field validation, so both fields change together.
                    relationship = relationship.model_copy(update={
                        "inferred": True, "evidence_text": None,
                        "rationale": relationship.rationale or relationship.description
                        or "Quote not found in the section text; check before approving.",
                    })
                    warnings.append(
                        f"Relationship {relationship.local_id}: quote not found, kept as inferred (needs review)"
                    )
                else:
                    relationship = relationship.model_copy(update={"evidence_text": matched})
            kept_relationships.append(relationship)
        draft.relationships = _collapse_two_way_uses(kept_relationships, warnings)
        return warnings, unverified


def _lesson_name(path: list[str]) -> str | None:
    for title in reversed(path):
        normalized = unicodedata.normalize("NFKC", title).casefold().strip()
        if normalized.startswith("lesson") or normalized.startswith("الدرس"):
            return title
    return None


def _exact_source_span(source: str, evidence: str) -> str | None:
    """Return the original source span, tolerating only whitespace/JSON escape damage.

    A quote that occurs more than once (``1 minute = 60 seconds``) is valid evidence;
    the first occurrence is used.
    """
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
    folded_source = normalized_source.casefold()
    if position < 0 and len(folded_source) == len(normalized_source):
        position = folded_source.find(normalized_evidence.casefold())
    if position < 0:
        return None
    last = position + len(normalized_evidence) - 1
    return source[starts[position]:ends[last]]


def _collapse_two_way_uses(relationships: list, warnings: list[str]) -> list:
    """"A USES B" plus "B USES A" means the two depend on each other: keep one RELATED_TO."""
    uses = {(r.source_local_id, r.target_local_id): r for r in relationships
            if r.relationship_type == RelationshipType.USES}
    collapsed: set[tuple[str, str]] = set()
    result = []
    for relationship in relationships:
        pair = (relationship.source_local_id, relationship.target_local_id)
        reverse = uses.get(pair[::-1]) if relationship.relationship_type == RelationshipType.USES else None
        if reverse is None:
            result.append(relationship)
            continue
        key = tuple(sorted(pair))
        if key in collapsed:
            continue
        collapsed.add(key)
        description = " / ".join(dict.fromkeys(d for d in (relationship.description, reverse.description) if d))
        result.append(relationship.model_copy(update={
            "relationship_type": RelationshipType.RELATED_TO,
            "description": description or relationship.description,
            "strength": max(relationship.strength or 0, reverse.strength or 0) or None,
            "inferred": relationship.inferred and reverse.inferred,
            "evidence_text": relationship.evidence_text or reverse.evidence_text,
            "rationale": relationship.rationale or reverse.rationale,
        }))
        warnings.append(f"Merged two-way USES {key[0]} <-> {key[1]} into one RELATED_TO")
    return result


WORD_RE = re.compile(r"\w+")


def _approximate_span(source: str, evidence: str, threshold: float = 0.8) -> str | None:
    """Best source span whose words closely match the quote (tolerates OCR and paraphrase noise)."""
    quote = [m.group().casefold() for m in WORD_RE.finditer(evidence)]
    if len(quote) < 3:
        return None
    words = list(WORD_RE.finditer(source))
    folded = [m.group().casefold() for m in words]
    best_ratio, best = 0.0, None
    for size in {len(quote) - 1, len(quote), len(quote) + 1}:
        for start in range(0, max(len(words) - size + 1, 0)):
            ratio = SequenceMatcher(None, quote, folded[start:start + size], autojunk=False).ratio()
            if ratio > best_ratio:
                best_ratio, best = ratio, (words[start].start(), words[start + size - 1].end())
    if best is None or best_ratio < threshold:
        return None
    return source[best[0]:best[1]]


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
