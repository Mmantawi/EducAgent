import math
import unittest

from eduagent_kg.resolution.embedding_dedup import MERGE_CATEGORY, block_reason, deduplicate
from eduagent_kg.resolution.merger import HierarchicalGraphMerger
from eduagent_kg.schemas.enums import DecisionType, NodeType, RelationshipType
from eduagent_kg.schemas.extraction import ExtractedEntity, ExtractedRelationship, GraphFragment
from eduagent_kg.schemas.review import ReviewDecision
from eduagent_kg.validation import GraphValidator
from eduagent_kg.validation.review import apply_review_decisions

from test_merge import _metadata, _source, _textbook


def _unit(angle_degrees: float) -> list[float]:
    angle = math.radians(angle_degrees)
    return [math.cos(angle), math.sin(angle), 0.0]


# Cosine similarity of two vectors = cos(angle between them).
VECTORS = {
    "Division with a remainder": _unit(0),
    "Division with Remainders": _unit(5),          # cos 5deg = 0.996 -> auto merge
    "Remainder": _unit(60),
    "Convert kilometers to meters": _unit(120),
    "Convert meters to kilometers": _unit(121),    # very close, but a reversed conversion
    "Unit of length": _unit(200),
    "Length unit": _unit(222),                     # cos 22deg = 0.927 -> review, not auto
    "Multiply by 10": _unit(300),
    "Multiply by 100": _unit(301),                 # different numbers
}


class FakeEmbedder:
    def embed(self, texts):
        return [VECTORS[t] for t in texts]


def _fragment(section_id: str, names: list[tuple[str, NodeType]], links=()) -> GraphFragment:
    entities = [
        ExtractedEntity(local_id=f"n{i}", node_type=kind, name=name, description=f"{name} desc",
                        aliases=[], provenance=[_source(section_id)], extraction=_metadata())
        for i, (name, kind) in enumerate(names)
    ]
    entities.append(ExtractedEntity(
        local_id="section", node_type=NodeType.SOURCE_SECTION, name=section_id, aliases=[],
        provenance=[_source(section_id)], extraction=_metadata(), attributes={"section_id": section_id},
    ))
    kinds = {e.local_id: e.node_type for e in entities}
    relationships = [
        ExtractedRelationship(
            local_id=f"r{i}", relationship_type=kind, source_local_id=src, target_local_id=dst,
            source_type=kinds[src], target_type=kinds[dst], provenance=[_source(section_id)],
            extraction=_metadata(), description=f"{section_id} link", strength=strength,
        )
        for i, (kind, src, dst, strength) in enumerate(links)
    ]
    return GraphFragment(fragment_id=f"fragment:{section_id}", document_id="doc", book_id="book",
                         section_id=section_id, entities=entities, relationships=relationships)


C, S = NodeType.CONCEPT, NodeType.SKILL


class EmbeddingDedupTest(unittest.TestCase):
    def setUp(self):
        s1 = _fragment("s1", [("Division with a remainder", C), ("Remainder", C), ("Unit of length", C),
                              ("Multiply by 10", S)],
                       [(RelationshipType.COMPONENT_OF, "n1", "n0", 5)])
        s2 = _fragment("s2", [("Division with Remainders", C), ("Remainder", C), ("Length unit", C),
                              ("Convert kilometers to meters", S), ("Convert meters to kilometers", S),
                              ("Multiply by 100", S)],
                       [(RelationshipType.COMPONENT_OF, "n1", "n0", 8)])
        self.graph, self.queue, _ = HierarchicalGraphMerger().merge([s1, s2], _textbook())
        self.merged, self.new_queue, self.report = deduplicate(self.graph, self.queue, FakeEmbedder())
        self.names = {n.name: n for n in self.merged.nodes}

    def test_near_identical_names_merge_and_links_fold_together(self):
        self.assertEqual(len(self.report.merged), 1)
        survivor = self.names.get("Division with a remainder") or self.names["Division with Remainders"]
        self.assertTrue({"Division with a remainder", "Division with Remainders"}
                        - {survivor.name} <= set(survivor.aliases))
        links = [e for e in self.merged.relationships if e.relationship_type == RelationshipType.COMPONENT_OF]
        self.assertEqual(len(links), 1)                       # the same link from both lessons
        self.assertEqual(links[0].weight, 2)
        self.assertEqual(links[0].strength, 8)
        self.assertEqual(links[0].target_canonical_id, survivor.canonical_id)
        self.assertTrue(GraphValidator().validate(self.merged).is_valid)

    def test_guards_block_reversed_conversions_and_different_numbers(self):
        self.assertIn("Convert kilometers to meters", self.names)
        self.assertIn("Convert meters to kilometers", self.names)
        self.assertIn("Multiply by 10", self.names)
        self.assertIn("Multiply by 100", self.names)
        reasons = {b["reason"] for b in self.report.blocked}
        self.assertIn("different numbers", reasons)
        self.assertTrue(any("different order" in r for r in reasons))

    def test_borderline_pair_goes_to_review_and_approval_merges_it(self):
        items = [i for i in self.new_queue.items if i.category == MERGE_CATEGORY]
        self.assertEqual(len(items), 1)
        self.assertIn("Length unit", items[0].reason)
        decision = ReviewDecision(target_id=items[0].review_id, reviewer_id="teacher",
                                  decision=DecisionType.APPROVE, reason="same idea")
        graph, _ = apply_review_decisions(self.merged, self.new_queue, [decision])
        names = {n.name for n in graph.nodes}
        self.assertEqual(len({"Unit of length", "Length unit"} & names), 1)

    def test_rejecting_a_merge_keeps_both_nodes(self):
        item = next(i for i in self.new_queue.items if i.category == MERGE_CATEGORY)
        decision = ReviewDecision(target_id=item.review_id, reviewer_id="teacher",
                                  decision=DecisionType.REJECT, reason="different")
        graph, queue = apply_review_decisions(self.merged, self.new_queue, [decision])
        self.assertEqual(len(graph.nodes), len(self.merged.nodes))

    def test_link_quoted_in_one_lesson_and_inferred_in_another_is_one_edge(self):
        s1 = _fragment("s1", [("Remainder", C), ("Division with a remainder", C)],
                       [(RelationshipType.COMPONENT_OF, "n0", "n1", 5)])
        s2 = _fragment("s2", [("Remainder", C), ("Division with a remainder", C)],
                       [(RelationshipType.COMPONENT_OF, "n0", "n1", 7)])
        inferred = s2.relationships[0].model_copy(update={
            "rationale": "implied", "extraction": s2.relationships[0].extraction.model_copy(
                update={"disposition": "inferred", "review_status": "candidate"})})
        s2 = s2.model_copy(update={"relationships": [inferred]})
        graph, queue, _ = HierarchicalGraphMerger().merge([s1, s2], _textbook())
        self.assertTrue(GraphValidator().validate(graph).is_valid)
        links = [e for e in graph.relationships if e.relationship_type == RelationshipType.COMPONENT_OF]
        self.assertEqual((len(links), links[0].weight, links[0].strength), (1, 2, 7))
        self.assertFalse(graph.candidate_relationships)
        self.assertFalse([i for i in queue.items if i.category == "inferred_prerequisite"])

    def test_opposite_operations_never_merge(self):
        def node(name):
            return next(n for n in self.graph.nodes if n.name == name).model_copy(update={"name": name})
        base = node("Remainder")
        add = base.model_copy(update={"name": "Add large numbers mentally"})
        sub = base.model_copy(update={"name": "Subtract large numbers mentally"})
        self.assertEqual(block_reason(add, sub), "opposite operations")
        # Wrong merges seen on the full book before these guards existed.
        wrong = [
            ("Break up the multiplier to multiply", "Break up the multiplicand to multiply"),
            ("Place value shifts left", "Place value shifts right"),
            ("Multiply numbers with zeros", "Multiply by zero"),
            ("Multiply by hundreds", "Multiply by tens and hundreds"),
            ("Subtract large numbers", "Add and subtract large numbers"),
            ("Subtract numbers with borrowing", "Subtract numbers with borrowing mentally"),
        ]
        for left, right in wrong:
            with self.subTest(left=left):
                self.assertIsNotNone(block_reason(base.model_copy(update={"name": left}),
                                                  base.model_copy(update={"name": right})))
        right_merges = [
            ("Add numbers mentally", "Add numbers with ones mentally"),
            ("Find a remainder", "Find the remainder in division"),
            ("Length unit", "Unit of Length"),
        ]
        for left, right in right_merges:
            with self.subTest(left=left):
                self.assertIsNone(block_reason(base.model_copy(update={"name": left}),
                                               base.model_copy(update={"name": right})))
        self.assertIsNone(block_reason(base.model_copy(update={"name": "Time units"}),
                                       base.model_copy(update={"name": "Time Unit"})))


if __name__ == "__main__":
    unittest.main()
