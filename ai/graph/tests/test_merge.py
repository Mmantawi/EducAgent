import unittest
from datetime import datetime, timezone

from eduagent_kg.evaluation.quality import _names_itself, _similar, evaluate_graph
from eduagent_kg.resolution.merger import HierarchicalGraphMerger
from eduagent_kg.schemas.documents import StructuredTextbook, TextbookSection
from eduagent_kg.schemas.enums import (
    ClaimDisposition, ExtractionMethod, NodeType, RelationshipType, ReviewStatus,
)
from eduagent_kg.schemas.extraction import ExtractedEntity, ExtractedRelationship, GraphFragment
from eduagent_kg.schemas.provenance import ExtractionMetadata, SourceReference
from eduagent_kg.validation import GraphValidator

META = dict(grade=3, subject="mathematics", original_language="en")


def _metadata() -> ExtractionMetadata:
    return ExtractionMetadata(
        **META, extraction_method=ExtractionMethod.LLM, disposition=ClaimDisposition.EXTRACTED,
        review_status=ReviewStatus.UNREVIEWED, extractor_name="test", extractor_version="1",
        model_name="m", prompt_version="v", extracted_at=datetime.now(timezone.utc),
    )


def _source(section_id: str) -> SourceReference:
    return SourceReference(
        source_ref_id=f"ref:{section_id}", book_id="book", document_id="doc", section_id=section_id,
        page_start=1, page_end=1, evidence_text="Multiplication and division", block_ids=[],
    )


def _fragment(section_id: str, inverse_source: str) -> GraphFragment:
    def entity(local_id, name, node_type=NodeType.CONCEPT):
        return ExtractedEntity(local_id=local_id, node_type=node_type, name=name, description=None,
                               aliases=[], provenance=[_source(section_id)], extraction=_metadata())

    other = "div" if inverse_source == "mul" else "mul"
    return GraphFragment(
        fragment_id=f"fragment:{section_id}", document_id="doc", book_id="book", section_id=section_id,
        entities=[
            entity("mul", "Multiplication"), entity("div", "Division"),
            entity("section", f"Lesson {section_id}", NodeType.SOURCE_SECTION).model_copy(
                update={"attributes": {"section_id": section_id}}),
        ],
        relationships=[ExtractedRelationship(
            local_id="r", relationship_type=RelationshipType.INVERSE_OF,
            source_local_id=inverse_source, target_local_id=other,
            source_type=NodeType.CONCEPT, target_type=NodeType.CONCEPT,
            provenance=[_source(section_id)], extraction=_metadata(),
            description=f"described in {section_id}", strength=6 if section_id == "s1" else 9,
        )],
    )


def _textbook() -> StructuredTextbook:
    sections = [
        TextbookSection(section_id=sid, document_id="doc", book_id="book", heading=sid,
                        heading_path=["Chapter 1 Numbers", sid], page_start=1, page_end=1,
                        text="Multiplication and division", **META)
        for sid in ("s1", "s2")
    ]
    return StructuredTextbook(document_id="doc", book_id="book", title="Book", source_uri="x",
                              content_hash="0" * 64, sections=sections, **META)


class MergeTest(unittest.TestCase):
    def setUp(self):
        # The two lessons state the same link in opposite directions.
        self.fragments = [_fragment("s1", "mul"), _fragment("s2", "div")]
        self.graph, self.queue, _ = HierarchicalGraphMerger().merge(self.fragments, _textbook())

    def test_structural_links_are_auto_approved_with_an_audit_record(self):
        structural = [r for r in self.graph.relationships if r.relationship_type == RelationshipType.PART_OF]
        self.assertTrue(structural)
        for edge in structural:
            self.assertEqual(edge.review_status, ReviewStatus.APPROVED)
            self.assertEqual(edge.review_history[0].reviewer_id, "system:textbook-structure")
        queued = {item.target_id for item in self.queue.items if item.category == "relationship_approval"}
        self.assertFalse(queued & {edge.canonical_id for edge in structural})
        inverse = next(r for r in self.graph.relationships if r.relationship_type == RelationshipType.INVERSE_OF)
        self.assertEqual(inverse.review_status, ReviewStatus.UNREVIEWED)  # model claims still need a person
        self.assertIn(inverse.canonical_id, queued)

    def test_structural_auto_approval_can_be_turned_off(self):
        graph, _, _ = HierarchicalGraphMerger(auto_approve_structural=False).merge(self.fragments, _textbook())
        self.assertFalse(any(r.review_status == ReviewStatus.APPROVED for r in graph.relationships))

    def test_quality_report_counts_links_between_knowledge_nodes(self):
        report = evaluate_graph(self.graph)
        self.assertEqual(report["knowledge_nodes"], 2)
        self.assertEqual(report["knowledge_links"], 1)
        self.assertEqual(report["isolated_knowledge_nodes"], 0)
        self.assertEqual(report["largest_connected_group"], 2)
        self.assertEqual(report["links_with_description"], 1)
        self.assertEqual(report["relationships_needing_review"], 1)

    def test_symmetric_links_from_two_lessons_merge_into_one_weighted_edge(self):
        graph = self.graph
        inverse = [r for r in graph.relationships if r.relationship_type == RelationshipType.INVERSE_OF]
        self.assertEqual(len(inverse), 1)
        edge = inverse[0]
        self.assertEqual(edge.weight, 2)
        self.assertEqual(edge.strength, 9)
        self.assertEqual(edge.description, "described in s1 | described in s2")
        self.assertTrue(GraphValidator().validate(graph).is_valid)


class QualityHeuristicsTest(unittest.TestCase):
    def test_duplicate_names(self):
        self.assertTrue(_similar("Division with a Remainder", "Division with Remainders"))
        self.assertTrue(_similar("Interpret Table Data", "Interpret Data Table"))
        self.assertFalse(_similar("Multiplication By 10", "Multiplication By 0"))
        self.assertFalse(_similar("Breaking Up the Multiplier", "Breaking Up the Multiplicand"))

    def test_skill_that_only_names_its_concept(self):
        self.assertTrue(_names_itself("Calculate Elapsed Time", "Elapsed Time"))
        self.assertTrue(_names_itself("Convert Time Units", "Time Conversion"))
        self.assertFalse(_names_itself("Divide with a remainder", "Multiplication"))


if __name__ == "__main__":
    unittest.main()
