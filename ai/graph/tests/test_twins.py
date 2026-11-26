import unittest

from eduagent_kg.resolution.merger import HierarchicalGraphMerger
from eduagent_kg.resolution.twins import fix_twin_links
from eduagent_kg.schemas.enums import DecisionType, NodeType, RelationshipType
from eduagent_kg.schemas.review import ReviewDecision
from eduagent_kg.validation import GraphValidator
from eduagent_kg.validation.review import apply_review_decisions

from test_dedup import _fragment
from test_merge import _textbook

C, S, P = NodeType.CONCEPT, NodeType.SKILL, RelationshipType.PREREQUISITE_FOR


class TwinLinksTest(unittest.TestCase):
    def setUp(self):
        names = [("Multiply by 10", S), ("Multiply by 10", C),
                 ("Include unit in final answer", S), ("Include units in answers", S),
                 ("Convert kilometers to meters", S), ("Convert meters to kilometers", S),
                 ("Bar graph", C), ("Create a bar graph", S)]
        links = [(P, "n0", "n1", 9), (P, "n2", "n3", 9), (P, "n4", "n5", 7), (P, "n6", "n7", 9)]
        graph, queue, _ = HierarchicalGraphMerger().merge([_fragment("s1", names, links)], _textbook())
        self.graph, self.queue, self.report = fix_twin_links(graph, queue)
        self.names = {n.canonical_id: (n.name, n.node_type) for n in self.graph.nodes}

    def _links(self, kind):
        return {(self.names[e.source_canonical_id][0], self.names[e.target_canonical_id][0])
                for e in self.graph.relationships + self.graph.candidate_relationships
                if e.relationship_type == kind}

    def test_skill_pointing_at_its_own_concept_becomes_uses(self):
        self.assertIn(("Multiply by 10", "Multiply by 10"), self._links(RelationshipType.USES))
        self.assertNotIn(("Multiply by 10", "Multiply by 10"), self._links(P))
        self.assertTrue(GraphValidator().validate(self.graph).is_valid)

    def test_near_duplicates_lose_the_prerequisite_and_go_to_merge_review(self):
        self.assertNotIn(("Include unit in final answer", "Include units in answers"), self._links(P))
        item = next(i for i in self.queue.items if i.category == "embedding_merge_candidate")
        decision = ReviewDecision(target_id=item.review_id, reviewer_id="teacher",
                                  decision=DecisionType.APPROVE, reason="same skill")
        merged, _ = apply_review_decisions(self.graph, self.queue, [decision])
        self.assertEqual(len(merged.nodes), len(self.graph.nodes) - 1)

    def test_real_prerequisites_and_reversed_conversions_are_kept(self):
        kept = self._links(P)
        self.assertIn(("Bar graph", "Create a bar graph"), kept)
        self.assertIn(("Convert kilometers to meters", "Convert meters to kilometers"), kept)
        self.assertEqual(len(self.report.turned_into_uses), 1)
        self.assertEqual(len(self.report.sent_to_merge_review), 1)

    def test_no_review_item_points_at_a_removed_link(self):
        ids = {e.canonical_id for e in self.graph.relationships + self.graph.candidate_relationships}
        ids |= {n.canonical_id for n in self.graph.nodes}
        for item in self.queue.items:
            self.assertTrue(all(part in ids for part in item.target_id.split("|")), item.review_id)


if __name__ == "__main__":
    unittest.main()
