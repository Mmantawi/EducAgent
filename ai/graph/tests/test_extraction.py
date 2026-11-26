import json
import shutil
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

from eduagent_kg.extraction.assembler import GraphFragmentAssembler
from eduagent_kg.extraction.cli import main as extraction_main
from eduagent_kg.extraction.openai_compatible import (
    OpenAICompatibleExtractionProvider, draft_json_schema, parse_draft,
)
from eduagent_kg.extraction.prompt import build_extraction_prompt
from eduagent_kg.extraction.provider import ModelOutputError
from eduagent_kg.schemas.documents import TextbookSection
from eduagent_kg.schemas.enums import NodeType

SECTION_TEXT = (
    "2-3 Shorter Time Units\nPoint!\nA second is a unit of time shorter than a minute.\n"
    "1 minute = 60 seconds\nTry\n1 minute 5 seconds = 60 seconds + 5 seconds\n1 minute = 60 seconds"
)

MODEL_OUTPUT = {
    "entities": [
        {"local_id": "second", "node_type": "Concept", "name": "Second (unit of time)",
         "description": "A second is a very short unit of time.",
         "evidence_text": "A second is a unit of time shorter than a minute."},
        {"local_id": "convert", "node_type": "Skill", "name": "Convert minutes and seconds",
         "description": "Change a time in minutes into seconds and back.",
         # Appears twice in the section: must still be accepted.
         "evidence_text": "1 minute = 60 seconds"},
        {"local_id": "ex1", "node_type": "Exercise", "name": "Stopwatch reading",
         "evidence_text": "Try"},
        {"local_id": "made_up", "node_type": "Concept", "name": "Hour",
         "evidence_text": "An hour has 60 minutes."},
    ],
    "relationships": [
        {"local_id": "t1", "relationship_type": "TEACHES", "source_local_id": "section",
         "target_local_id": "second", "evidence_text": "Point!"},
        {"local_id": "p1", "relationship_type": "PREREQUISITE_FOR", "source_local_id": "second",
         "target_local_id": "convert", "inferred": True,
         "rationale": "You must know what a second is before converting."},
        # Invalid: inferred without a rationale -> dropped by the parser, not the whole draft.
        {"local_id": "p2", "relationship_type": "PREREQUISITE_FOR", "source_local_id": "convert",
         "target_local_id": "second", "inferred": True},
        # Points at the dropped made-up concept -> dropped by the assembler.
        {"local_id": "p3", "relationship_type": "IS_A", "source_local_id": "made_up",
         "target_local_id": "second", "evidence_text": "Point!"},
    ],
}


def _section(section_id: str = "sec:1") -> TextbookSection:
    return TextbookSection(
        section_id=section_id, document_id="doc", book_id="book", heading="2-3 Shorter Time Units",
        heading_path=["Chapter 2 Time and Duration", "2-3 Shorter Time Units"], page_start=27,
        page_end=30, text=SECTION_TEXT, grade=3, subject="mathematics", original_language="en",
    )


class _FakeServer(BaseHTTPRequestHandler):
    requests: list[dict] = []
    reply: dict = {"content": json.dumps(MODEL_OUTPUT), "finish_reason": "stop"}
    queued: list[dict] = []  # replies used first, in order, before falling back to `reply`

    def do_POST(self):  # noqa: N802
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        type(self).requests.append(body)
        reply = type(self).queued.pop(0) if type(self).queued else self.reply
        payload = json.dumps({
            "id": "x", "object": "chat.completion", "created": 0, "model": body["model"],
            "choices": [{"index": 0, "finish_reason": reply["finish_reason"],
                         "message": {"role": "assistant", "content": reply["content"]}}],
        }).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *args):
        pass


class OpenAICompatibleProviderTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = HTTPServer(("127.0.0.1", 0), _FakeServer)
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.base_url = f"http://127.0.0.1:{cls.server.server_port}/v1"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()

    def setUp(self):
        _FakeServer.requests = []
        _FakeServer.queued = []
        _FakeServer.reply = {"content": json.dumps(MODEL_OUTPUT), "finish_reason": "stop"}
        self.provider = OpenAICompatibleExtractionProvider(base_url=self.base_url, model="qwen-test")

    def test_gleaning_round_adds_missing_nodes_and_sibling_links(self):
        gleaned = {
            "entities": [
                # Repeats an existing node under a new id: must map onto the original.
                {"local_id": "sec2", "node_type": "Concept", "name": "Second (unit of time)",
                 "description": "dup", "evidence_text": "A second is a unit of time shorter than a minute."},
                {"local_id": "minute", "node_type": "Concept", "name": "Minute",
                 "description": "A minute is 60 seconds.", "evidence_text": "1 minute = 60 seconds"},
            ],
            "relationships": [
                {"local_id": "r1", "relationship_type": "COMPONENT_OF", "source_local_id": "sec2",
                 "target_local_id": "minute", "evidence_text": "1 minute = 60 seconds",
                 "description": "Sixty seconds make one minute.", "strength": 8},
                {"local_id": "r2", "relationship_type": "USES", "source_local_id": "convert",
                 "target_local_id": "minute", "inferred": True,
                 "rationale": "Converting needs the size of a minute.", "strength": 9},
            ],
        }
        _FakeServer.queued = [
            {"content": json.dumps(MODEL_OUTPUT), "finish_reason": "stop"},
            {"content": json.dumps(gleaned), "finish_reason": "stop"},
            {"content": json.dumps({"entities": [], "relationships": []}), "finish_reason": "stop"},
        ]
        provider = OpenAICompatibleExtractionProvider(base_url=self.base_url, model="qwen-test", gleanings=2)
        result = provider.extract(_section())
        self.assertEqual(len(_FakeServer.requests), 3)  # stops after an empty gleaning round
        second_request = _FakeServer.requests[1]["messages"]
        self.assertEqual(second_request[-2]["role"], "assistant")
        self.assertIn("MANY nodes and relationships were missed", second_request[-1]["content"])
        names = [entity.name for entity in result.parsed.entities]
        self.assertEqual(names.count("Second (unit of time)"), 1)
        self.assertIn("Minute", names)
        fragment = GraphFragmentAssembler().assemble(
            _section(), result.parsed, provider="openai-compatible", model="qwen-test"
        )
        links = {(r.relationship_type.value, r.source_local_id, r.target_local_id): r for r in fragment.relationships}
        component = links[("COMPONENT_OF", "second", "minute")]
        self.assertEqual((component.description, component.strength), ("Sixty seconds make one minute.", 8))
        self.assertIn(("USES", "convert", "minute"), links)

    def test_gleaning_failure_keeps_first_round(self):
        _FakeServer.queued = [
            {"content": json.dumps(MODEL_OUTPUT), "finish_reason": "stop"},
            {"content": '{"entities": [', "finish_reason": "length"},
        ]
        result = self.provider.extract(_section())
        # All four first-round entities survive the failed gleaning round (the assembler
        # drops the Exercise and the misquoted one later).
        self.assertEqual(len(result.parsed.entities), 4)

    def test_request_uses_json_schema_and_disables_thinking(self):
        self.provider.extract(_section())
        request = _FakeServer.requests[0]
        self.assertEqual(request["response_format"]["type"], "json_schema")
        self.assertEqual(request["chat_template_kwargs"], {"enable_thinking": False})
        self.assertEqual(request["temperature"], 0.0)

    def test_truncated_output_is_reported_not_parsed(self):
        _FakeServer.reply = {"content": '{"entities": [{"local_id": "a', "finish_reason": "length"}
        with self.assertRaisesRegex(ModelOutputError, "max_tokens"):
            self.provider.extract(_section())

    def test_bad_items_are_dropped_and_good_ones_kept(self):
        result = self.provider.extract(_section())
        fragment = GraphFragmentAssembler().assemble(
            _section(), result.parsed, provider="openai-compatible", model="qwen-test"
        )
        nodes = {e.name: e for e in fragment.entities if e.node_type in {NodeType.CONCEPT, NodeType.SKILL}}
        # The Exercise is dropped; the node with an unfindable quote is KEPT but marked unverified,
        # so the links pointing at it survive for review instead of disappearing with it.
        self.assertEqual(set(nodes), {"Second (unit of time)", "Convert minutes and seconds", "Hour"})
        self.assertEqual(nodes["Hour"].attributes, {"evidence_verified": False})
        self.assertIsNone(nodes["Hour"].provenance[0].evidence_text)
        self.assertEqual(nodes["Second (unit of time)"].attributes, {})
        kinds = sorted(rel.relationship_type.value for rel in fragment.relationships)
        for kind in ("PREREQUISITE_FOR", "TEACHES", "IS_A"):
            self.assertIn(kind, kinds)
        self.assertEqual(len(fragment.warnings), 2)  # exercise dropped, Hour kept unverified

    def test_ocr_noisy_quote_matches_approximately_and_unquoted_link_becomes_inferred(self):
        draft = parse_draft(json.dumps({"entities": [
            {"local_id": "second", "node_type": "Concept", "name": "Second", "description": "d",
             # OCR dropped "a" and changed punctuation: still the same sentence.
             "evidence_text": "A second is unit of time shorter than a minute!"},
            {"local_id": "minute", "node_type": "Concept", "name": "Minute", "description": "d",
             "evidence_text": "1 minute = 60 seconds"},
        ], "relationships": [
            {"local_id": "r", "relationship_type": "USES", "source_local_id": "minute", "target_local_id": "second",
             "description": "A minute is counted in seconds.", "strength": 7, "inferred": False,
             "evidence_text": "a quote that is nowhere in the lesson at all", "rationale": ""},
        ]}))
        fragment = GraphFragmentAssembler().assemble(_section(), draft, provider="p", model="m")
        second = next(e for e in fragment.entities if e.local_id == "second")
        self.assertEqual(second.provenance[0].evidence_text, "A second is a unit of time shorter than a minute")
        link = next(r for r in fragment.relationships if r.relationship_type.value == "USES")  # Concept -> Concept
        self.assertEqual(link.extraction.disposition.value, "inferred")
        self.assertEqual(link.rationale, "A minute is counted in seconds.")

    def test_cli_runs_end_to_end_and_resumes_from_cache(self):
        with tempfile.TemporaryDirectory() as tmp:
            sections = Path(tmp) / "sections.jsonl"
            sections.write_text(
                "\n".join(_section(f"sec:{i}").model_dump_json() for i in range(2)), encoding="utf-8"
            )
            out = Path(tmp) / "out"
            args = [str(sections), "--output", str(out), "--base-url", self.base_url, "--model", "qwen-test"]
            self.assertEqual(extraction_main(args), 0)
            # 2 sections x (extraction + 1 gleaning round that finds nothing new)
            self.assertEqual(len(_FakeServer.requests), 4)
            self.assertEqual(extraction_main(args), 0)
            self.assertEqual(len(_FakeServer.requests), 4)  # second run served from cache

            # A saved answer produced by an older prompt must NOT be reused (Kaggle run 2 bug).
            root = next(out.glob("*/"))
            shutil.rmtree(root / "cache")
            for raw in (root / "raw").glob("*.json"):
                payload = json.loads(raw.read_text(encoding="utf-8"))
                payload["cache_key"] = "from-an-older-prompt"
                raw.write_text(json.dumps(payload), encoding="utf-8")
            self.assertEqual(extraction_main(args), 0)
            self.assertEqual(len(_FakeServer.requests), 8)


class SchemaAndParsingTest(unittest.TestCase):
    def test_schema_only_allows_knowledge_nodes(self):
        schema = draft_json_schema()
        self.assertEqual(schema["$defs"]["DraftEntity"]["properties"]["node_type"]["enum"], ["Concept", "Skill"])
        kinds = schema["$defs"]["RelationshipType"]["enum"]
        self.assertNotIn("ASSESSES", kinds)
        for kind in ("USES", "COMPONENT_OF", "INVERSE_OF", "CONTRASTS_WITH", "RELATED_TO", "PREREQUISITE_FOR"):
            self.assertIn(kind, kinds)
        relationship = schema["$defs"]["DraftRelationship"]["properties"]
        self.assertIn("strength", relationship)
        self.assertIn("description", relationship)

    def test_prompt_explains_every_relationship_type(self):
        prompt = build_extraction_prompt(_section())
        for kind in ("USES", "COMPONENT_OF", "INVERSE_OF", "CONTRASTS_WITH", "RELATED_TO"):
            self.assertIn(f"- {kind} (", prompt)
        self.assertIn("every pair of nodes", prompt)

    def test_parse_strips_thinking_and_code_fences(self):
        raw = "<think>plan</think>\n```json\n{\"entities\": [], \"relationships\": []}\n```"
        self.assertEqual(parse_draft(raw).entities, [])

    def test_schema_requires_every_field_the_model_must_fill(self):
        schema = draft_json_schema()
        self.assertEqual(schema["required"], ["entities", "relationships"])
        relationship = schema["$defs"]["DraftRelationship"]
        for field in ("description", "strength", "inferred", "evidence_text", "rationale"):
            self.assertIn(field, relationship["required"])
        self.assertEqual(relationship["properties"]["evidence_text"], {"type": "string"})

    def test_first_kaggle_run_output_is_reported_not_silently_empty(self):
        # Real Qwen3-14B output from the first Kaggle run: relationships only, no entities, no quotes.
        raw = (Path(__file__).parent / "fixtures" / "qwen_run1_no_entities.json").read_text(encoding="utf-8")
        warnings: list[str] = []
        draft = parse_draft(raw, warnings)
        self.assertEqual(draft.entities, [])
        self.assertIn("Model output has no `entities` list", warnings)
        self.assertEqual(sum(w.startswith("Dropped relationship") for w in warnings), 4)
        fragment = GraphFragmentAssembler().assemble(
            _section(), draft, provider="p", model="m", extra_warnings=warnings
        )
        self.assertEqual(fragment.warnings[: len(warnings)], warnings)

    def test_empty_strings_mean_not_applicable(self):
        raw = json.dumps({"entities": [], "relationships": [
            {"local_id": "a", "relationship_type": "USES", "source_local_id": "x", "target_local_id": "y",
             "description": "d", "strength": 5, "inferred": True, "evidence_text": "", "rationale": "implied"},
            {"local_id": "b", "relationship_type": "USES", "source_local_id": "x", "target_local_id": "y",
             "description": "d", "strength": 5, "inferred": False, "evidence_text": "", "rationale": "implied too"},
        ]})
        warnings: list[str] = []
        draft = parse_draft(raw, warnings)
        self.assertEqual([r.evidence_text for r in draft.relationships], [None, None])
        self.assertTrue(all(r.inferred for r in draft.relationships))
        self.assertEqual(len(warnings), 1)  # the second one was promoted to inferred

    def test_two_way_uses_collapses_into_one_related_to(self):
        # Kaggle run 2: "Multiplier Addition Rule USES Subtraction Rule" and the reverse.
        def link(local_id, source, target, strength):
            return {"local_id": local_id, "relationship_type": "USES", "source_local_id": source,
                    "target_local_id": target, "description": f"{source} with {target}", "strength": strength,
                    "inferred": False, "evidence_text": "1 minute = 60 seconds", "rationale": ""}
        draft = parse_draft(json.dumps({"entities": [
            {"local_id": "a", "node_type": "Concept", "name": "Second", "description": "d",
             "evidence_text": "1 minute = 60 seconds"},
            {"local_id": "b", "node_type": "Concept", "name": "Minute", "description": "d",
             "evidence_text": "1 minute = 60 seconds"},
        ], "relationships": [link("r1", "a", "b", 6), link("r2", "b", "a", 9)]}))
        fragment = GraphFragmentAssembler().assemble(_section(), draft, provider="p", model="m")
        links = [r for r in fragment.relationships if r.relationship_type.value in ("USES", "RELATED_TO")]
        self.assertEqual(len(links), 1)
        self.assertEqual(links[0].relationship_type.value, "RELATED_TO")
        self.assertEqual(links[0].strength, 9)
        self.assertIn("Merged two-way USES a <-> b into one RELATED_TO", fragment.warnings)

    def test_repeated_relationship_id_is_renamed_not_fatal(self):
        # Full-book Kaggle run: one lesson failed because the model reused a relationship id.
        def link(source, target, kind):
            return {"local_id": "r1", "relationship_type": kind, "source_local_id": source,
                    "target_local_id": target, "description": "d", "strength": 5,
                    "inferred": False, "evidence_text": "1 minute = 60 seconds", "rationale": ""}
        draft = parse_draft(json.dumps({"entities": [
            {"local_id": "a", "node_type": "Concept", "name": "Second", "description": "d",
             "evidence_text": "1 minute = 60 seconds"},
            {"local_id": "b", "node_type": "Concept", "name": "Minute", "description": "d",
             "evidence_text": "1 minute = 60 seconds"},
        ], "relationships": [link("a", "b", "COMPONENT_OF"), link("a", "b", "RELATED_TO")]}))
        fragment = GraphFragmentAssembler().assemble(_section(), draft, provider="p", model="m")
        ids = [r.local_id for r in fragment.relationships]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertIn("r1", ids)
        self.assertIn("r1_2", ids)

    def test_prompt_asks_for_varied_types_and_strengths(self):
        prompt = build_extraction_prompt(_section())
        self.assertIn("never emit both", prompt)
        self.assertIn("WHOLE 1-10 scale", prompt)
        self.assertIn("Never create a skill that only wraps a concept", prompt)  # Kaggle v7 twins

    def test_parse_rejects_non_json(self):
        with self.assertRaises(ModelOutputError):
            parse_draft("Sorry, I cannot help with that.")


if __name__ == "__main__":
    unittest.main()
