import json
import math
import re
import tempfile
import unittest
from pathlib import Path

from eduagent_kg.evaluation.quality import evaluate_graph
from eduagent_kg.resolution.book_prerequisites import _reaches, build_batches, propose_prerequisites
from eduagent_kg.resolution.merger import HierarchicalGraphMerger
from eduagent_kg.schemas.documents import StructuredTextbook, TextbookSection
from eduagent_kg.schemas.enums import NodeType, RelationshipType, ReviewStatus
from eduagent_kg.schemas.extraction import ExtractedEntity, ExtractedRelationship, GraphFragment
from eduagent_kg.schemas.provenance import SourceReference
from eduagent_kg.validation import GraphValidator

from test_merge import META, _metadata

PAGES = {"s1": 3, "s2": 10}
ANGLES = {"Multiplication": 0, "Bar graph": 170, "Divide with a remainder": 20, "Remainder": 30}


def _source(section_id: str) -> SourceReference:
    page = PAGES[section_id]
    return SourceReference(source_ref_id=f"ref:{section_id}", book_id="book", document_id="doc",
                           section_id=section_id, page_start=page, page_end=page, evidence_text="x")


def _fragment(section_id, names):
    entities = [ExtractedEntity(local_id=f"n{i}", node_type=kind, name=name, description=f"{name} desc",
                                provenance=[_source(section_id)], extraction=_metadata())
                for i, (name, kind) in enumerate(names)]
    entities.append(ExtractedEntity(local_id="section", node_type=NodeType.SOURCE_SECTION, name=section_id,
                                    provenance=[_source(section_id)], extraction=_metadata(),
                                    attributes={"section_id": section_id}))
    supported_by = [  # "taught in this section" links, as the real assembler adds them
        ExtractedRelationship(local_id=f"support:{e.local_id}", relationship_type=RelationshipType.SUPPORTED_BY,
                              source_local_id=e.local_id, target_local_id="section", source_type=e.node_type,
                              target_type=NodeType.SOURCE_SECTION, provenance=e.provenance, extraction=_metadata())
        for e in entities if e.local_id != "section"
    ]
    return GraphFragment(fragment_id=f"fragment:{section_id}", document_id="doc", book_id="book",
                         section_id=section_id, entities=entities, relationships=supported_by)


def _textbook():
    sections = [TextbookSection(section_id=s, document_id="doc", book_id="book", heading=s,
                                heading_path=[f"Chapter {i} X", s], page_start=PAGES[s], page_end=PAGES[s],
                                text="x", **META) for i, s in enumerate(PAGES, 1)]
    return StructuredTextbook(document_id="doc", book_id="book", title="Book", source_uri="x",
                              content_hash="0" * 64, sections=sections, **META)


class FakeEmbedder:
    def embed(self, texts):
        out = []
        for text in texts:
            angle = math.radians(ANGLES[text.split(":")[0]])
            out.append([math.cos(angle), math.sin(angle)])
        return out


class FakeJudge:
    """Says 'Multiplication' is a prerequisite of 'Divide with a remainder'; also tries a bad id."""
    model_name = "fake"

    def __init__(self):
        self.calls = 0

    def complete(self, prompt, schema):
        self.calls += 1
        ids = dict(re.findall(r"^([EL]\d+)\. \[\w+\] ([^-]+?) -", prompt, flags=re.MULTILINE))
        by_name = {name: short for short, name in ids.items()}
        return json.dumps({"prerequisites": [
            {"earlier": by_name["Multiplication"], "later": by_name["Divide with a remainder"],
             "strength": 8, "reason": "Division facts come from multiplication facts."},
            {"earlier": "E99", "later": "L1", "strength": 5, "reason": "made up"},
        ]})


class BrokenJudge:
    model_name = "fake"

    def complete(self, prompt, schema):
        raise RuntimeError("server down")


class BookPrerequisitesTest(unittest.TestCase):
    def setUp(self):
        fragments = [
            _fragment("s1", [("Multiplication", NodeType.CONCEPT), ("Bar graph", NodeType.CONCEPT)]),
            _fragment("s2", [("Divide with a remainder", NodeType.SKILL), ("Remainder", NodeType.CONCEPT)]),
        ]
        self.graph, self.queue, _ = HierarchicalGraphMerger().merge(fragments, _textbook())

    def test_candidates_only_point_forward_and_skip_unrelated_topics(self):
        batches = build_batches(self.graph, FakeEmbedder(), top_k=3, min_similarity=0.5)
        self.assertEqual(len(batches), 1)                     # only the later lesson has earlier nodes
        names = {n.canonical_id: n.name for n in self.graph.nodes}
        pairs = {(names[a], names[b]) for a, b in batches[0].pairs}
        self.assertIn(("Multiplication", "Divide with a remainder"), pairs)
        self.assertNotIn(("Bar graph", "Divide with a remainder"), pairs)   # cos 150deg < 0.5

    def test_accepted_pairs_become_reviewable_cross_lesson_prerequisites(self):
        with tempfile.TemporaryDirectory() as tmp:
            graph, queue, report = propose_prerequisites(
                self.graph, self.queue, FakeEmbedder(), FakeJudge(), cache_dir=Path(tmp))
        self.assertEqual([(a["earlier"], a["later"]) for a in report.accepted],
                         [("Multiplication", "Divide with a remainder")])
        self.assertTrue(any(s["why"].startswith("not an earlier") for s in report.skipped))
        edge = next(e for e in graph.candidate_relationships if e.relationship_type == RelationshipType.PREREQUISITE_FOR)
        self.assertEqual(edge.review_status, ReviewStatus.CANDIDATE)
        self.assertEqual(edge.strength, 8)
        self.assertIn(edge.canonical_id, {i.target_id for i in queue.items if i.category == "inferred_prerequisite"})
        self.assertTrue(GraphValidator().validate(graph).is_valid)
        self.assertEqual(evaluate_graph(graph)["cross_lesson_prerequisites"], 1)
        self.assertEqual(evaluate_graph(graph)["cross_chapter_prerequisites"], 1)

    def test_rerun_uses_cache_and_never_duplicates_links(self):
        with tempfile.TemporaryDirectory() as tmp:
            judge = FakeJudge()
            graph, queue, _ = propose_prerequisites(self.graph, self.queue, FakeEmbedder(), judge, cache_dir=Path(tmp))
            again, _, report = propose_prerequisites(graph, queue, FakeEmbedder(), judge, cache_dir=Path(tmp))
        self.assertEqual(judge.calls, 1)
        self.assertEqual(report.accepted, [])
        self.assertTrue(any(s["why"] == "already linked as a prerequisite" for s in report.skipped))
        self.assertEqual(len(again.candidate_relationships), len(graph.candidate_relationships))

    def test_failed_lesson_is_reported_not_fatal(self):
        graph, _, report = propose_prerequisites(self.graph, self.queue, FakeEmbedder(), BrokenJudge())
        self.assertEqual(len(report.failed_lessons), 1)
        self.assertEqual(len(graph.candidate_relationships), len(self.graph.candidate_relationships))

    def test_cycle_check(self):
        self.assertTrue(_reaches({"a": {"b"}, "b": {"c"}}, "a", "c"))
        self.assertFalse(_reaches({"a": {"b"}}, "b", "a"))


if __name__ == "__main__":
    unittest.main()
