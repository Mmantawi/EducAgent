"""Book-level prerequisites across lessons and chapters (plan step 4).

Each lesson is extracted on its own, so the model never sees that "Divide with a remainder"
(page 40) needs "Multiplication facts" (page 12). This pass looks at the whole book:

1. Candidates: for every concept/skill, the earlier-taught nodes closest in meaning
   (top-k by embedding similarity of "name: description"). Earlier = first taught on an
   earlier page, so links always point forward through the book.
2. Judge: one model call per lesson lists that lesson's nodes and their candidates and asks
   which are *direct* prerequisites (what a student must already know), not loose topic overlap.
3. Output: accepted pairs become inferred PREREQUISITE_FOR candidates with a rationale and
   strength, queued for human review. Links that duplicate an existing prerequisite or would
   create a cycle are skipped. Raw answers are cached per lesson, so re-runs are free.

    python -m eduagent_kg.resolution.book_prerequisites data/g3t1/kaggle_full --base-url http://localhost:8000/v1
"""

import argparse
import hashlib
import json
import logging
import re
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from eduagent_kg.console import configure_utf8_stdout
from eduagent_kg.files import write_json_atomic
from eduagent_kg.ids import make_relationship_id
from eduagent_kg.ontology import LEARNING_NODES
from eduagent_kg.schemas.enums import ClaimDisposition, RelationshipType, ReviewStatus
from eduagent_kg.schemas.graph import CanonicalEntity, CanonicalGraph, CanonicalRelationship
from eduagent_kg.schemas.review import ReviewItem, ReviewQueue

from .embedding_dedup import Embedder, _cosine_matrix, default_embedder
from .twins import fix_twin_links

PROMPT_VERSION = "book-prerequisites-v2"
MAX_PER_TARGET = 3  # the prompt asks for at most this many; extra answers are dropped
logger = logging.getLogger(__name__)


class Judge(Protocol):
    model_name: str

    def complete(self, prompt: str, schema: dict) -> str: ...


class OpenAICompatibleJudge:
    """Any OpenAI-compatible server (vLLM on Kaggle, a hosted API, ...)."""

    def __init__(self, base_url: str, model: str, api_key: str = "not-needed", *, max_tokens: int = 6000,
                 timeout: float = 300, structured_output: bool = True, disable_thinking: bool = True) -> None:
        from openai import OpenAI
        self._client = OpenAI(base_url=base_url, api_key=api_key, timeout=timeout, max_retries=2)
        self.model_name = model
        self.max_tokens = max_tokens
        self.structured_output = structured_output
        self.disable_thinking = disable_thinking

    def complete(self, prompt: str, schema: dict) -> str:
        kwargs: dict = {}
        if self.structured_output:
            kwargs["response_format"] = {"type": "json_schema",
                                         "json_schema": {"name": "Prerequisites", "schema": schema}}
        if self.disable_thinking:
            kwargs["extra_body"] = {"chat_template_kwargs": {"enable_thinking": False}}
        response = self._client.chat.completions.create(
            model=self.model_name, messages=[{"role": "user", "content": prompt}],
            max_tokens=self.max_tokens, temperature=0, **kwargs,
        )
        return response.choices[0].message.content or ""


@dataclass
class LessonBatch:
    section_id: str
    targets: list[CanonicalEntity]
    candidates: list[CanonicalEntity]
    pairs: set[tuple[str, str]]  # (earlier canonical_id, later canonical_id) the judge may accept


@dataclass
class PrerequisiteReport:
    lessons: int = 0
    candidate_pairs: int = 0
    accepted: list[dict] = field(default_factory=list)
    skipped: list[dict] = field(default_factory=list)
    failed_lessons: list[dict] = field(default_factory=list)


def first_taught(node: CanonicalEntity) -> tuple[int, str]:
    """(page, section_id) where the node first appears in the book."""
    ref = min(node.provenance, key=lambda p: (p.page_start, p.section_id))
    return ref.page_start, ref.section_id


def build_batches(graph: CanonicalGraph, embedder: Embedder, *, top_k: int = 6,
                  min_similarity: float = 0.5) -> list[LessonBatch]:
    knowledge = [n for n in graph.nodes if n.node_type in LEARNING_NODES]
    if len(knowledge) < 2:
        return []
    texts = [f"{n.name}: {n.description}" if n.description else n.name for n in knowledge]
    scores = _cosine_matrix(embedder.embed(texts))
    position = [first_taught(n) for n in knowledge]
    by_lesson: dict[str, list[int]] = defaultdict(list)
    for index, (_, section) in enumerate(position):
        by_lesson[section].append(index)

    batches = []
    for section, targets in sorted(by_lesson.items(), key=lambda item: position[item[1][0]][0]):
        pairs, candidates = set(), {}
        for t in targets:
            earlier = [i for i in range(len(knowledge)) if position[i][0] < position[t][0]]
            earlier.sort(key=lambda i: -float(scores[t, i]))
            for i in earlier[:top_k]:
                if float(scores[t, i]) < min_similarity:
                    break
                pairs.add((knowledge[i].canonical_id, knowledge[t].canonical_id))
                candidates[i] = knowledge[i]
        if pairs:
            batches.append(LessonBatch(
                section_id=section, targets=[knowledge[t] for t in targets],
                candidates=sorted(candidates.values(), key=first_taught), pairs=pairs,
            ))
    return batches


def build_prompt(batch: LessonBatch, grade: int | None) -> tuple[str, dict, dict[str, str]]:
    """Prompt, JSON schema and short-id -> canonical_id map for one lesson."""
    ids: dict[str, str] = {}
    later_lines, earlier_lines = [], []
    for n, node in enumerate(batch.targets, 1):
        ids[f"L{n}"] = node.canonical_id
        later_lines.append(f"L{n}. [{node.node_type.value}] {node.name} - {node.description or ''}")
    for n, node in enumerate(batch.candidates, 1):
        ids[f"E{n}"] = node.canonical_id
        earlier_lines.append(f"E{n}. [{node.node_type.value}] {node.name} - {node.description or ''} "
                             f"(page {first_taught(node)[0]})")
    later_ids = [k for k in ids if k.startswith("L")]
    earlier_ids = [k for k in ids if k.startswith("E")]
    prompt = f"""You are mapping prerequisites in a grade {grade or ''} primary maths textbook.

A LATER lesson teaches these concepts and skills:
{chr(10).join(later_lines)}

EARLIER lessons in the same book taught these:
{chr(10).join(earlier_lines)}

For each L node, list the E nodes a student must ALREADY know before they can learn it.
- At most 3 E nodes per L node: the most direct ones. Skip an L node if nothing above is needed.
- Only DIRECT prerequisites: if E1 is needed for E2 and E2 for L1, list only E2 -> L1.
- Not generic vocabulary: "Multiplier" is not a prerequisite of every multiplication skill.
- Not loose topic overlap: "Bar graph" is not a prerequisite for "Divide by 10".
- Strength 1-10: 9-10 = impossible without it; 4-7 = usually needed; 1-3 = helpful.
- reason: one sentence a teacher would accept.
- It is fine to return few or no links.

Return JSON: {{"prerequisites": [{{"earlier": "E3", "later": "L1", "strength": 7, "reason": "..."}}]}}"""
    schema = {
        "type": "object", "additionalProperties": False, "required": ["prerequisites"],
        "properties": {"prerequisites": {"type": "array", "items": {
            "type": "object", "additionalProperties": False,
            "required": ["earlier", "later", "strength", "reason"],
            "properties": {
                "earlier": {"type": "string", "enum": earlier_ids},
                "later": {"type": "string", "enum": later_ids},
                "strength": {"type": "integer", "minimum": 1, "maximum": 10},
                "reason": {"type": "string"},
            },
        }}},
    }
    return prompt, schema, ids


def parse_answer(raw: str) -> list[dict]:
    text = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL).strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text)
    data = json.loads(text)
    items = data.get("prerequisites") if isinstance(data, dict) else None
    if not isinstance(items, list):
        raise ValueError("answer has no 'prerequisites' list")
    return [i for i in items if isinstance(i, dict)]


def _ask(judge: Judge, batch: LessonBatch, grade: int | None, cache_dir: Path | None) -> list[dict]:
    prompt, schema, _ = build_prompt(batch, grade)
    key = hashlib.sha256(f"{PROMPT_VERSION}|{judge.model_name}|{prompt}".encode()).hexdigest()
    cache = cache_dir / f"{re.sub(r'[^A-Za-z0-9_-]', '_', batch.section_id)}.json" if cache_dir else None
    if cache and cache.is_file():
        saved = json.loads(cache.read_text(encoding="utf-8"))
        if saved.get("cache_key") == key:
            return parse_answer(saved["raw"])
    raw = judge.complete(prompt, schema)
    if cache:
        write_json_atomic(cache, {"cache_key": key, "section_id": batch.section_id, "raw": raw})
    return parse_answer(raw)


def _reaches(adjacency: dict[str, set[str]], start: str, goal: str) -> bool:
    stack, seen = [start], {start}
    while stack:
        current = stack.pop()
        if current == goal:
            return True
        for nxt in adjacency.get(current, ()):
            if nxt not in seen:
                seen.add(nxt)
                stack.append(nxt)
    return False


def propose_prerequisites(
    graph: CanonicalGraph, queue: ReviewQueue, embedder: Embedder, judge: Judge, *,
    top_k: int = 6, min_similarity: float = 0.5, concurrency: int = 4, cache_dir: Path | None = None,
    min_strength: int = 8,
) -> tuple[CanonicalGraph, ReviewQueue, PrerequisiteReport]:
    """min_strength: on the full book, links the model rated 7 or lower were mostly topic overlap
    ("Kilometer -> Tables"); 8+ were mostly real prerequisites. Weaker ones stay in the report."""
    graph = graph.model_copy(deep=True)
    nodes = {n.canonical_id: n for n in graph.nodes}
    batches = build_batches(graph, embedder, top_k=top_k, min_similarity=min_similarity)
    grade = graph.grades[0] if graph.grades else None
    report = PrerequisiteReport(lessons=len(batches), candidate_pairs=sum(len(b.pairs) for b in batches))

    def run(batch):
        try:
            return batch, _ask(judge, batch, grade, cache_dir), None
        except Exception as error:  # one bad lesson must not stop the book
            logger.warning("Prerequisite pass failed for %s: %s", batch.section_id, error)
            return batch, [], str(error)

    with ThreadPoolExecutor(max_workers=max(1, concurrency)) as pool:
        results = list(pool.map(run, batches))

    edges = list(graph.relationships) + list(graph.candidate_relationships)
    adjacency: dict[str, set[str]] = defaultdict(set)
    linked = set()
    for e in edges:
        if e.relationship_type == RelationshipType.PREREQUISITE_FOR:
            adjacency[e.source_canonical_id].add(e.target_canonical_id)
            linked.add(frozenset((e.source_canonical_id, e.target_canonical_id)))

    existing_items = {item.review_id for item in queue.items}
    new_items = []
    for batch, answers, error in results:
        if error:
            report.failed_lessons.append({"section_id": batch.section_id, "error": error[:300]})
            continue
        _, _, ids = build_prompt(batch, grade)
        per_target: dict[str, int] = defaultdict(int)
        for answer in answers:
            earlier, later = str(answer.get("earlier")), str(answer.get("later"))
            source = ids.get(earlier) if earlier.startswith("E") else None
            target = ids.get(later) if later.startswith("L") else None
            label = {"earlier": nodes[source].name if source else earlier,
                     "later": nodes[target].name if target else later}
            reason = str(answer.get("reason") or "").strip()
            # Any listed earlier node may be chosen for any node of the lesson, as long as it
            # really comes first in the book; the top-k lists only decide what is shown.
            if not source or not target or first_taught(nodes[source])[0] >= first_taught(nodes[target])[0]:
                report.skipped.append({**label, "why": "not an earlier -> later pair from the prompt"})
                continue
            if per_target[target] >= MAX_PER_TARGET:
                report.skipped.append({**label, "why": f"more than {MAX_PER_TARGET} for one node"})
                continue
            if frozenset((source, target)) in linked:
                report.skipped.append({**label, "why": "already linked as a prerequisite"})
                continue
            if _reaches(adjacency, target, source):
                report.skipped.append({**label, "why": "would create a cycle"})
                continue
            try:
                strength = min(10, max(1, int(answer.get("strength") or 5)))
            except (TypeError, ValueError):
                strength = 5
            if strength < min_strength:
                report.skipped.append({**label, "strength": strength, "reason": reason,
                                       "why": f"strength below {min_strength}"})
                continue
            edge = CanonicalRelationship(
                canonical_id=make_relationship_id(RelationshipType.PREREQUISITE_FOR.value, source, target),
                relationship_type=RelationshipType.PREREQUISITE_FOR,
                source_canonical_id=source, target_canonical_id=target,
                source_type=nodes[source].node_type, target_type=nodes[target].node_type,
                disposition=ClaimDisposition.INFERRED, review_status=ReviewStatus.CANDIDATE,
                provenance=list({p.source_ref_id: p for p in (min(nodes[source].provenance, key=lambda p: p.page_start),
                                                               min(nodes[target].provenance, key=lambda p: p.page_start))}.values()),
                rationale=reason or "Proposed by the book-level prerequisite pass.",
                description=reason or None, strength=strength,
            )
            graph.candidate_relationships.append(edge)
            per_target[target] += 1
            adjacency[source].add(target)
            linked.add(frozenset((source, target)))
            report.accepted.append({**label, "strength": strength, "reason": reason})
            review_id = f"review:relationship:{edge.canonical_id}"
            if review_id not in existing_items:
                new_items.append(ReviewItem(
                    review_id=review_id, category="inferred_prerequisite", target_id=edge.canonical_id,
                    reason=f"Book-level pass: '{label['earlier']}' before '{label['later']}'. {reason}",
                    payload=edge.model_dump(mode="json"),
                ))
    graph.candidate_relationships.sort(key=lambda e: e.canonical_id)
    return graph, queue.model_copy(update={"items": list(queue.items) + new_items}), report


def main(argv: list[str] | None = None) -> int:
    configure_utf8_stdout()
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description="Propose prerequisites across lessons and chapters.")
    parser.add_argument("run_dir", type=Path)
    parser.add_argument("--input-suffix", default=".dedup", help="Reads canonical-graph<suffix>.json")
    parser.add_argument("--output-suffix", default=".prereq")
    parser.add_argument("--base-url", default="http://localhost:8000/v1")
    parser.add_argument("--model", default="qwen3-14b")
    parser.add_argument("--api-key", default="not-needed")
    parser.add_argument("--top-k", type=int, default=6, help="Earlier candidates per concept/skill")
    parser.add_argument("--min-similarity", type=float, default=0.5)
    parser.add_argument("--concurrency", type=int, default=4)
    parser.add_argument("--min-strength", type=int, default=8,
                        help="Drop proposed links the model rated below this (they stay in the report)")
    parser.add_argument("--no-structured-output", action="store_true")
    parser.add_argument("--dry-run", action="store_true", help="Only count candidates; no model calls")
    args = parser.parse_args(argv)

    graph = CanonicalGraph.model_validate_json(
        (args.run_dir / f"canonical-graph{args.input_suffix}.json").read_text(encoding="utf-8"))
    queue_path = args.run_dir / f"review-queue{args.input_suffix}.json"
    queue = (ReviewQueue.model_validate_json(queue_path.read_text(encoding="utf-8")) if queue_path.is_file()
             else ReviewQueue(graph_id=graph.graph_id))
    embedder = default_embedder()
    if args.dry_run:
        batches = build_batches(graph, embedder, top_k=args.top_k, min_similarity=args.min_similarity)
        print(f"{len(batches)} lessons, {sum(len(b.pairs) for b in batches)} candidate pairs")
        for batch in batches[:3]:
            print("\n" + build_prompt(batch, graph.grades[0] if graph.grades else None)[0])
        return 0
    judge = OpenAICompatibleJudge(args.base_url, args.model, args.api_key,
                                  structured_output=not args.no_structured_output)
    new_graph, new_queue, report = propose_prerequisites(
        graph, queue, embedder, judge, top_k=args.top_k, min_similarity=args.min_similarity,
        concurrency=args.concurrency, cache_dir=args.run_dir / "prerequisites-raw",
        min_strength=args.min_strength,
    )
    new_graph, new_queue, twins = fix_twin_links(new_graph, new_queue)
    print(f"Twin links: {len(twins.turned_into_uses)} skill->own-concept prerequisites turned into USES, "
          f"{len(twins.sent_to_merge_review)} near-duplicate pairs sent to merge review")
    write_json_atomic(args.run_dir / f"canonical-graph{args.output_suffix}.json", new_graph.model_dump(mode="json"))
    write_json_atomic(args.run_dir / f"review-queue{args.output_suffix}.json", new_queue.model_dump(mode="json"))
    write_json_atomic(args.run_dir / f"prerequisites-report{args.output_suffix}.json", report.__dict__)
    print(f"{report.lessons} lessons, {report.candidate_pairs} candidate pairs -> "
          f"{len(report.accepted)} prerequisites proposed, {len(report.skipped)} skipped, "
          f"{len(report.failed_lessons)} lessons failed")
    for item in report.accepted[:40]:
        print(f"  {item['earlier']!r} -> {item['later']!r} ({item['strength']}): {item['reason']}")
    for item in report.failed_lessons:
        print(f"  FAILED {item['section_id']}: {item['error']}")
    return 1 if report.failed_lessons else 0


if __name__ == "__main__":
    raise SystemExit(main())
