from collections import Counter
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

from eduagent_kg.ids import make_canonical_id, make_relationship_id
from eduagent_kg.schemas.documents import StructuredTextbook
from eduagent_kg.schemas.enums import (
    ClaimDisposition, NodeType, RelationshipType, ReviewStatus,
)
from eduagent_kg.schemas.extraction import GraphFragment
from eduagent_kg.schemas.graph import CanonicalEntity, CanonicalGraph, CanonicalRelationship
from eduagent_kg.schemas.merge import MergeStatistics
from eduagent_kg.schemas.review import ReviewItem, ReviewQueue

from .normalization import normalize_text
from .resolver import EntityResolver


class HierarchicalGraphMerger:
    """Merge in section → lesson → book → subject → global scope order."""

    def __init__(self, resolver: EntityResolver | None = None) -> None:
        self.resolver = resolver or EntityResolver()

    def merge(
        self, fragments: list[GraphFragment], textbook: StructuredTextbook
    ) -> tuple[CanonicalGraph, ReviewQueue, MergeStatistics]:
        return self.merge_many([(fragments, textbook)])

    def merge_many(
        self, datasets: list[tuple[list[GraphFragment], StructuredTextbook]]
    ) -> tuple[CanonicalGraph, ReviewQueue, MergeStatistics]:
        """Merge multiple books while retaining subject and grade resolution boundaries."""
        if not datasets:
            raise ValueError("At least one textbook dataset is required")
        ordered_datasets: list[tuple[list[GraphFragment], StructuredTextbook]] = []
        for fragments, textbook in datasets:
            section_order = {section.section_id: index for index, section in enumerate(textbook.sections)}
            ordered_datasets.append((
                sorted(fragments, key=lambda item: section_order.get(item.section_id, 10**9)),
                textbook,
            ))
        fragments = [fragment for group, _ in ordered_datasets for fragment in group]
        mentions = [
            (f"{fragment.fragment_id}::{entity.local_id}", entity)
            for fragment in fragments for entity in fragment.entities
        ]
        resolution = self.resolver.resolve(mentions)
        nodes = {entity.canonical_id: entity for entity in resolution.entities}
        mention_map = resolution.mention_to_canonical
        relationships: dict[tuple, CanonicalRelationship] = {}
        candidates: dict[tuple, CanonicalRelationship] = {}
        review_items = list(resolution.review_items)

        for fragment in fragments:
            for relation in fragment.relationships:
                source_key = f"{fragment.fragment_id}::{relation.source_local_id}"
                target_key = f"{fragment.fragment_id}::{relation.target_local_id}"
                source_id = mention_map[source_key]
                target_id = mention_map[target_key]
                canonical = CanonicalRelationship(
                    canonical_id=make_relationship_id(
                        relation.relationship_type.value, source_id, target_id
                    ),
                    relationship_type=relation.relationship_type,
                    source_canonical_id=source_id, target_canonical_id=target_id,
                    source_type=nodes[source_id].node_type, target_type=nodes[target_id].node_type,
                    disposition=relation.extraction.disposition,
                    review_status=relation.extraction.review_status,
                    provenance=list(relation.provenance), rationale=relation.rationale,
                )
                target_collection = (
                    candidates if canonical.disposition == ClaimDisposition.INFERRED else relationships
                )
                self._merge_edge(target_collection, canonical)
                if canonical.disposition == ClaimDisposition.INFERRED:
                    review_items.append(ReviewItem(
                        review_id=f"review:relationship:{canonical.canonical_id}",
                        category="inferred_prerequisite",
                        target_id=canonical.canonical_id,
                        reason="LLM-inferred prerequisite requires explicit human approval.",
                        payload=canonical.model_dump(mode="json"),
                    ))

        for _, textbook in ordered_datasets:
            self._add_hierarchy(textbook, nodes, relationships)
        review_items.extend(self._relationship_reviews(relationships, candidates))
        for edge in relationships.values():
            if edge.review_status != ReviewStatus.APPROVED:
                review_items.append(ReviewItem(
                    review_id=f"review:relationship:{edge.canonical_id}",
                    category="relationship_approval", target_id=edge.canonical_id,
                    reason="Extracted relationship requires explicit review before Neo4j import.",
                    payload=edge.model_dump(mode="json"),
                ))
        textbooks = [textbook for _, textbook in ordered_datasets]
        book_ids = sorted({textbook.book_id for textbook in textbooks})
        graph_id = f"graph:{uuid5(NAMESPACE_URL, '|'.join(book_ids))}"
        graph = CanonicalGraph(
            graph_id=graph_id,
            subjects=sorted({textbook.subject for textbook in textbooks}),
            grades=sorted({textbook.grade for textbook in textbooks}),
            book_ids=book_ids, nodes=sorted(nodes.values(), key=lambda n: n.canonical_id),
            relationships=sorted(relationships.values(), key=lambda r: r.canonical_id),
            candidate_relationships=sorted(candidates.values(), key=lambda r: r.canonical_id),
        )
        queue = ReviewQueue(graph_id=graph_id, items=_dedupe_review_items(review_items))
        counts = Counter(item.relationship_type.value for item in graph.relationships)
        stats = MergeStatistics(
            total_extracted_entities=len(mentions), total_canonical_entities=len(graph.nodes),
            duplicate_candidates=sum(item.category.endswith("merge_candidate") for item in queue.items),
            confirmed_merges=resolution.confirmed_merges,
            relationship_counts_by_type=dict(sorted(counts.items())), invalid_edges=0,
            detected_cycles=0,
            pending_reviews=sum(item.status == ReviewStatus.CANDIDATE for item in queue.items),
            approved_relationships=sum(r.review_status == ReviewStatus.APPROVED for r in graph.relationships),
            rejected_relationships=sum(r.review_status == ReviewStatus.REJECTED for r in graph.candidate_relationships),
        )
        return graph, queue, stats

    def _add_hierarchy(
        self, textbook: StructuredTextbook, nodes: dict[str, CanonicalEntity],
        relationships: dict[tuple, CanonicalRelationship],
    ) -> None:
        section_nodes = {
            str(node.attributes.get("section_id")): node
            for node in nodes.values()
            if (
                node.node_type == NodeType.SOURCE_SECTION and node.attributes.get("section_id")
                and any(ref.book_id == textbook.book_id for ref in node.provenance)
            )
        }
        available_provenance = [
            ref for node in nodes.values() for ref in node.provenance
            if ref.book_id == textbook.book_id
        ]
        if not available_provenance:
            return
        book_id = make_canonical_id(NodeType.BOOK, book_id=textbook.book_id, identity=textbook.book_id)
        book = CanonicalEntity(
            canonical_id=book_id, node_type=NodeType.BOOK, name=textbook.title,
            normalized_name=normalize_text(textbook.title), aliases=[],
            attributes={"book_id": textbook.book_id}, source_local_ids=[f"book:{textbook.book_id}"],
            provenance=_unique_provenance(available_provenance), grade=textbook.grade,
            subject=textbook.subject, original_language=textbook.original_language,
        )
        _merge_node(nodes, book)
        for section in textbook.sections:
            section_node = section_nodes.get(section.section_id)
            if not section_node:
                continue
            chapter_name = next((x for x in section.heading_path if _is_chapter(x)), None)
            lesson_name = next((x for x in reversed(section.heading_path) if _is_lesson(x)), None)
            chapter = self._structural_node(NodeType.CHAPTER, chapter_name, textbook, section_node) if chapter_name else None
            lesson = self._structural_node(NodeType.LESSON, lesson_name, textbook, section_node) if lesson_name else None
            if chapter:
                _merge_node(nodes, chapter)
            if lesson:
                _merge_node(nodes, lesson)
            parent = lesson or chapter or book
            self._add_structural_edge(section_node, parent, relationships)
            if lesson:
                self._add_structural_edge(lesson, chapter or book, relationships)
            if chapter:
                self._add_structural_edge(chapter, book, relationships)

    def _structural_node(
        self, node_type: NodeType, name: str, textbook: StructuredTextbook,
        evidence_node: CanonicalEntity,
    ) -> CanonicalEntity:
        return CanonicalEntity(
            canonical_id=make_canonical_id(node_type, book_id=textbook.book_id, identity=name),
            node_type=node_type, name=name, normalized_name=normalize_text(name), aliases=[],
            attributes={}, source_local_ids=[f"structure:{evidence_node.canonical_id}:{node_type.value}"],
            provenance=list(evidence_node.provenance), grade=textbook.grade, subject=textbook.subject,
            original_language=textbook.original_language,
        )

    def _add_structural_edge(self, source, target, edges) -> None:
        edge = CanonicalRelationship(
            canonical_id=make_relationship_id(RelationshipType.PART_OF.value, source.canonical_id, target.canonical_id),
            relationship_type=RelationshipType.PART_OF,
            source_canonical_id=source.canonical_id, target_canonical_id=target.canonical_id,
            source_type=source.node_type, target_type=target.node_type,
            disposition=ClaimDisposition.EXTRACTED, review_status=ReviewStatus.UNREVIEWED,
            provenance=_unique_provenance(source.provenance),
        )
        self._merge_edge(edges, edge)

    def _merge_edge(self, collection, edge: CanonicalRelationship) -> None:
        key = (edge.relationship_type, edge.source_canonical_id, edge.target_canonical_id)
        if key in collection:
            collection[key].provenance = _unique_provenance(
                collection[key].provenance + edge.provenance
            )
        else:
            collection[key] = edge

    def _relationship_reviews(self, relationships, candidates) -> list[ReviewItem]:
        items: list[ReviewItem] = []
        all_edges = list(relationships.values()) + list(candidates.values())
        keys = {(e.relationship_type, e.source_canonical_id, e.target_canonical_id): e for e in all_edges}
        for edge in all_edges:
            if edge.relationship_type not in {RelationshipType.PREREQUISITE_FOR, RelationshipType.IS_A}:
                continue
            reverse = keys.get((edge.relationship_type, edge.target_canonical_id, edge.source_canonical_id))
            if reverse and edge.canonical_id < reverse.canonical_id:
                items.append(ReviewItem(
                    review_id=f"review:contradiction:{edge.canonical_id}:{reverse.canonical_id}",
                    category="contradictory_relationships", target_id=edge.canonical_id,
                    reason="Opposing directed relationships require review.",
                    payload={"relationship_ids": [edge.canonical_id, reverse.canonical_id]},
                ))
            if edge.relationship_type != RelationshipType.PART_OF and not any(
                ref.evidence_text for ref in edge.provenance
            ):
                items.append(ReviewItem(
                    review_id=f"review:missing-evidence:{edge.canonical_id}",
                    category="missing_evidence", target_id=edge.canonical_id,
                    reason="Relationship has provenance coordinates but no textual evidence.",
                    payload=edge.model_dump(mode="json"),
                ))
        return items


def load_fragments(directory: Path) -> list[GraphFragment]:
    paths = sorted(directory.glob("*.json"))
    if not paths:
        raise FileNotFoundError(f"No graph fragment JSON files found in {directory}")
    return [GraphFragment.model_validate_json(path.read_text(encoding="utf-8")) for path in paths]


def _merge_node(nodes: dict[str, CanonicalEntity], incoming: CanonicalEntity) -> None:
    current = nodes.get(incoming.canonical_id)
    if current is None:
        nodes[incoming.canonical_id] = incoming
        return
    current.aliases = sorted(set(current.aliases + incoming.aliases))
    current.source_local_ids = sorted(set(current.source_local_ids + incoming.source_local_ids))
    current.provenance = _unique_provenance(current.provenance + incoming.provenance)
    current.attributes.update(incoming.attributes)


def _unique_provenance(values):
    return list({item.source_ref_id: item for item in values}.values())


def _is_chapter(value: str) -> bool:
    normalized = normalize_text(value)
    return normalized.startswith(("chapter", "unit", "الفصل", "الوحدة"))


def _is_lesson(value: str) -> bool:
    normalized = normalize_text(value)
    return normalized.startswith(("lesson", "الدرس"))


def _dedupe_review_items(items: list[ReviewItem]) -> list[ReviewItem]:
    return sorted({item.review_id: item for item in items}.values(), key=lambda item: item.review_id)
