"""Book-level duplicate merge with sentence embeddings (plan step 3).

Each lesson is extracted on its own, so the same idea comes back under several names
("Division with a remainder" / "Division remainder" / "Division with Remainders").
This pass embeds every Concept and Skill once, then:

- pairs at or above ``auto_threshold`` are merged automatically, unless a guard says
  they are different (different numbers, opposite operations, reversed conversions,
  or the model already linked them as distinct, e.g. A PREREQUISITE_FOR B);
- pairs between ``review_threshold`` and ``auto_threshold`` go to the review queue as
  ``embedding_merge_candidate`` items, which ``apply_review_decisions`` can merge.

Merging redirects every link to the surviving node and folds duplicate links together
the same way the lesson merger does (weight += 1, highest strength, joined descriptions).

    python -m eduagent_kg.resolution.embedding_dedup data/g3t1/kaggle_full
"""

import argparse
import json
import re
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from eduagent_kg.console import configure_utf8_stdout
from eduagent_kg.files import write_json_atomic
from eduagent_kg.ids import make_relationship_id
from eduagent_kg.ontology import LEARNING_NODES, SYMMETRIC_RELATIONSHIPS
from eduagent_kg.resolution.merger import fold_edge, fold_inferred_into_quoted
from eduagent_kg.schemas.enums import RelationshipType
from eduagent_kg.schemas.graph import CanonicalEntity, CanonicalGraph, CanonicalRelationship
from eduagent_kg.schemas.review import ReviewItem, ReviewQueue

DEFAULT_MODEL = "BAAI/bge-small-en-v1.5"
MERGE_CATEGORY = "embedding_merge_candidate"
# A direct link of one of these types means the model saw two different things.
DISTINCT_LINKS = frozenset({
    RelationshipType.PREREQUISITE_FOR, RelationshipType.IS_A, RelationshipType.COMPONENT_OF,
    RelationshipType.INVERSE_OF, RelationshipType.CONTRASTS_WITH,
})
# Opposite operations: "Add ..." vs "Subtract ..." or vs "Add and subtract ...".
# A name that mentions neither side ("Find a remainder") is not blocked.
OPPOSITES = [
    ({"add", "addition", "adding", "sum"}, {"subtract", "subtraction", "subtracting", "difference"}),
    ({"multiply", "multiplication", "multiplying", "product"}, {"divide", "division", "dividing", "quotient"}),
    ({"more", "greater", "larger", "bigger", "increase"}, {"less", "fewer", "smaller", "decrease"}),
]
# Qualifiers that must appear in both names or in neither ("with borrowing" vs "with borrowing
# mentally"; "shift left" vs "shift right"; "multiplier" vs "multiplicand").
QUALIFIERS = [
    {"mental", "mentally"}, {"vertical", "vertically", "written"}, {"left"}, {"right"},
    {"multiplier"}, {"multiplicand"}, {"dividend"}, {"divisor"}, {"even"}, {"odd"},
    {"same"}, {"different"},
]
# Number words count as numbers; "zeros" (numbers that contain zeros) is not "zero".
NUMBER_WORDS = {
    "zero": "0", "one": "1", "two": "2", "three": "3", "four": "4", "five": "5", "six": "6",
    "seven": "7", "eight": "8", "nine": "9", "ten": "10", "hundred": "100", "thousand": "1000",
    "tens": "10s", "hundreds": "100s", "thousands": "1000s",
}
FILLER = {"a", "an", "the", "of", "to", "in", "on", "for", "and", "with", "using", "by", "into", "from"}
DIRECTION_WORDS = {"to", "into", "from"}


class Embedder(Protocol):
    def embed(self, texts: list[str]) -> list[list[float]]: ...


class FastEmbedEmbedder:
    """CPU embeddings via fastembed (ONNX). Downloads the model on first use."""

    def __init__(self, model: str = DEFAULT_MODEL) -> None:
        from fastembed import TextEmbedding
        self._model = TextEmbedding(model_name=model)

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [list(map(float, v)) for v in self._model.embed(texts)]


class SentenceTransformerEmbedder:
    """Embeddings via sentence-transformers (preinstalled on Kaggle).

    CPU by default: a few hundred short names take seconds, and on Kaggle the GPUs are
    usually full with the vLLM server.
    """

    def __init__(self, model: str = DEFAULT_MODEL, device: str = "cpu") -> None:
        from sentence_transformers import SentenceTransformer
        self._model = SentenceTransformer(model, device=device)

    def embed(self, texts: list[str]) -> list[list[float]]:
        return self._model.encode(texts, normalize_embeddings=True).tolist()


def default_embedder(model: str = DEFAULT_MODEL) -> Embedder:
    try:
        return FastEmbedEmbedder(model)
    except ImportError:
        pass
    try:
        return SentenceTransformerEmbedder(model)
    except ImportError as error:
        raise ImportError("Install fastembed or sentence-transformers to run the embedding merge") from error


@dataclass
class DedupReport:
    merged: list[dict] = field(default_factory=list)       # {"survivor", "removed": [...], "score"}
    candidates: list[dict] = field(default_factory=list)   # {"left", "right", "score"}
    blocked: list[dict] = field(default_factory=list)      # {"left", "right", "score", "reason"}


def _words(name: str) -> list[str]:
    words = re.findall(r"[a-z0-9]+", name.casefold())
    keep = set(NUMBER_WORDS) | {"zeros", "ones"}  # "ones place" is not the number 1
    return [w[:-1] if w not in keep and len(w) > 3 and w.endswith("s") and not w.endswith("ss") else w
            for w in words]


def _numbers(words: set[str]) -> set[str]:
    return {NUMBER_WORDS.get(w, w) for w in words if w.isdigit() or w in NUMBER_WORDS}


def block_reason(a: CanonicalEntity, b: CanonicalEntity) -> str | None:
    """Why two similar-looking nodes must NOT be merged, or None if merging is safe."""
    if a.node_type != b.node_type:
        return "different node types"
    if a.subject != b.subject or a.grade != b.grade:
        return "different subject or grade"
    wa, wb = _words(a.name), _words(b.name)
    sa, sb = set(wa), set(wb)
    if _numbers(sa) != _numbers(sb):
        return "different numbers"
    for left, right in OPPOSITES:
        sides_a = {side for side, words in (("l", left), ("r", right)) if sa & words}
        sides_b = {side for side, words in (("l", left), ("r", right)) if sb & words}
        if sides_a and sides_b and sides_a != sides_b:
            return "opposite operations"
    for qualifier in QUALIFIERS:
        if bool(sa & qualifier) != bool(sb & qualifier):
            return f"only one says '{sorted(qualifier)[0]}'"
    # "Convert kilometers to meters" vs "Convert meters to kilometers": order only matters when
    # the name has a direction ("Unit of length" and "Length unit" are the same thing).
    directional = DIRECTION_WORDS & sa and DIRECTION_WORDS & sb
    content_a = [w for w in wa if w not in FILLER]
    content_b = [w for w in wb if w not in FILLER]
    if directional and set(content_a) == set(content_b) and content_a != content_b:
        return "same words in a different order (e.g. a reversed conversion)"
    return None


def _cosine_matrix(vectors: list[list[float]]):
    import numpy as np
    matrix = np.asarray(vectors, dtype=np.float32)
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    matrix = matrix / np.where(norms == 0, 1, norms)
    return matrix @ matrix.T


def _node_text(node: CanonicalEntity) -> str:
    return node.name


def find_duplicates(
    graph: CanonicalGraph, embedder: Embedder, *, auto_threshold: float = 0.93, review_threshold: float = 0.86,
) -> tuple[list[list[str]], DedupReport]:
    """Return groups of canonical ids to merge (first id survives) and a report."""
    knowledge = [n for n in graph.nodes if n.node_type in LEARNING_NODES]
    if len(knowledge) < 2:
        return [], DedupReport()
    scores = _cosine_matrix(embedder.embed([_node_text(n) for n in knowledge]))
    linked_distinct = {
        frozenset((e.source_canonical_id, e.target_canonical_id))
        for e in list(graph.relationships) + list(graph.candidate_relationships)
        if e.relationship_type in DISTINCT_LINKS
    }
    report = DedupReport()
    pairs = []
    for i in range(len(knowledge)):
        for j in range(i + 1, len(knowledge)):
            score = float(scores[i, j])
            if score < review_threshold:
                continue
            a, b = knowledge[i], knowledge[j]
            reason = block_reason(a, b)
            if reason is None and frozenset((a.canonical_id, b.canonical_id)) in linked_distinct:
                reason = "the model linked them as different things"
            if reason == "different node types":
                continue
            entry = {"left": a.name, "right": b.name, "score": round(score, 3)}
            if reason:
                report.blocked.append({**entry, "reason": reason})
            elif score >= auto_threshold:
                pairs.append((score, i, j))
            else:
                report.candidates.append({**entry, "left_id": a.canonical_id, "right_id": b.canonical_id})

    # Complete linkage: a node joins a group only if it is close enough to every member,
    # so "A ~ B" and "B ~ C" never pulls in an unrelated C.
    group_of: dict[int, int] = {}
    groups: dict[int, list[int]] = {}
    for score, i, j in sorted(pairs, reverse=True):
        gi, gj = group_of.get(i), group_of.get(j)
        if gi is not None and gi == gj:
            continue
        members = (groups[gi] if gi is not None else [i]) + (groups[gj] if gj is not None else [j])
        if any(scores[x, y] < auto_threshold for x in members for y in members if x < y):
            report.candidates.append({
                "left": knowledge[i].name, "right": knowledge[j].name, "score": round(score, 3),
                "left_id": knowledge[i].canonical_id, "right_id": knowledge[j].canonical_id,
            })
            continue
        target = gi if gi is not None else (gj if gj is not None else i)
        for old in {gi, gj} - {None, target}:
            groups.pop(old)
        groups[target] = members
        for m in members:
            group_of[m] = target

    result = []
    for members in groups.values():
        nodes = sorted((knowledge[m] for m in members), key=_survivor_rank)
        result.append([n.canonical_id for n in nodes])
        best = max(float(scores[x, y]) for x in members for y in members if x < y)
        report.merged.append({
            "survivor": nodes[0].name, "removed": [n.name for n in nodes[1:]], "score": round(best, 3),
        })
    report.merged.sort(key=lambda m: m["survivor"])
    return result, report


def _survivor_rank(node: CanonicalEntity):
    """Keep the node taught in the most places; then the shorter, plainer name."""
    return (-len(node.provenance), len(node.name), node.name)


def merge_groups(graph: CanonicalGraph, groups: list[list[str]]) -> CanonicalGraph:
    graph = graph.model_copy(deep=True)
    redirect = {removed: group[0] for group in groups for removed in group[1:]}
    if not redirect:
        return graph
    nodes = {n.canonical_id: n for n in graph.nodes}
    for removed_id, survivor_id in redirect.items():
        survivor, removed = nodes[survivor_id], nodes[removed_id]
        survivor.aliases = sorted(set(survivor.aliases + removed.aliases + [removed.name]) - {survivor.name})
        survivor.source_local_ids = sorted(set(survivor.source_local_ids + removed.source_local_ids))
        survivor.provenance = list({p.source_ref_id: p for p in survivor.provenance + removed.provenance}.values())
        if not survivor.description and removed.description:
            survivor.description = removed.description
    graph.nodes = [n for n in graph.nodes if n.canonical_id not in redirect]
    relationships = _remap(graph.relationships, redirect, nodes)
    candidates = _remap(graph.candidate_relationships, redirect, nodes)
    fold_inferred_into_quoted(relationships, candidates)
    graph.relationships = sorted(relationships.values(), key=lambda e: e.canonical_id)
    graph.candidate_relationships = sorted(candidates.values(), key=lambda e: e.canonical_id)
    return graph


def _remap(edges, redirect: dict[str, str], nodes) -> dict[tuple, CanonicalRelationship]:
    merged: dict[tuple, CanonicalRelationship] = {}
    for edge in edges:
        source = redirect.get(edge.source_canonical_id, edge.source_canonical_id)
        target = redirect.get(edge.target_canonical_id, edge.target_canonical_id)
        if source == target:
            continue
        if edge.relationship_type in SYMMETRIC_RELATIONSHIPS and target < source:
            source, target = target, source
        if (source, target) != (edge.source_canonical_id, edge.target_canonical_id):
            edge = edge.model_copy(update={
                "source_canonical_id": source, "target_canonical_id": target,
                "source_type": nodes[source].node_type, "target_type": nodes[target].node_type,
                "canonical_id": make_relationship_id(edge.relationship_type.value, source, target),
            })
        key = (edge.relationship_type, source, target)
        if key in merged:
            fold_edge(merged[key], edge)
        else:
            merged[key] = edge
    return merged


def update_queue(queue: ReviewQueue, graph: CanonicalGraph, report: DedupReport) -> ReviewQueue:
    """Drop review items that point at removed nodes or links; add the borderline merge pairs."""
    ids = {n.canonical_id for n in graph.nodes}
    ids |= {e.canonical_id for e in list(graph.relationships) + list(graph.candidate_relationships)}
    candidate_ids = {e.canonical_id for e in graph.candidate_relationships}
    kept = [item for item in queue.items
            if all(part in ids for part in item.target_id.split("|"))
            and not (item.category == "inferred_prerequisite" and item.target_id not in candidate_ids)]
    seen = {item.review_id for item in kept}
    for pair in report.candidates:
        left, right = sorted((pair["left_id"], pair["right_id"]))
        if left not in ids or right not in ids:
            continue
        review_id = f"review:merge:{left}:{right}"
        if review_id in seen:
            continue
        seen.add(review_id)
        kept.append(ReviewItem(
            review_id=review_id, category=MERGE_CATEGORY, target_id=f"{left}|{right}",
            reason=f"Embedding similarity {pair['score']}: '{pair['left']}' vs '{pair['right']}'. Same idea?",
            payload={"left_canonical_id": left, "right_canonical_id": right, "score": pair["score"]},
        ))
    return queue.model_copy(update={"items": kept})


def deduplicate(
    graph: CanonicalGraph, queue: ReviewQueue, embedder: Embedder, **thresholds
) -> tuple[CanonicalGraph, ReviewQueue, DedupReport]:
    groups, report = find_duplicates(graph, embedder, **thresholds)
    merged = merge_groups(graph, groups)
    return merged, update_queue(queue, merged, report), report


def main(argv: list[str] | None = None) -> int:
    configure_utf8_stdout()
    parser = argparse.ArgumentParser(description="Merge duplicate concepts/skills using sentence embeddings.")
    parser.add_argument("run_dir", type=Path, help="Folder with canonical-graph.json and review-queue.json")
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--auto-threshold", type=float, default=0.93)
    parser.add_argument("--review-threshold", type=float, default=0.86)
    parser.add_argument("--suffix", default=".dedup", help="Output names: canonical-graph<suffix>.json etc.")
    args = parser.parse_args(argv)

    graph = CanonicalGraph.model_validate_json((args.run_dir / "canonical-graph.json").read_text(encoding="utf-8"))
    queue_path = args.run_dir / "review-queue.json"
    queue = (ReviewQueue.model_validate_json(queue_path.read_text(encoding="utf-8")) if queue_path.is_file()
             else ReviewQueue(graph_id=graph.graph_id))
    merged, new_queue, report = deduplicate(
        graph, queue, default_embedder(args.model),
        auto_threshold=args.auto_threshold, review_threshold=args.review_threshold,
    )
    write_json_atomic(args.run_dir / f"canonical-graph{args.suffix}.json", merged.model_dump(mode="json"))
    write_json_atomic(args.run_dir / f"review-queue{args.suffix}.json", new_queue.model_dump(mode="json"))
    write_json_atomic(args.run_dir / f"dedup-report{args.suffix}.json", report.__dict__)

    before = sum(n.node_type in LEARNING_NODES for n in graph.nodes)
    after = sum(n.node_type in LEARNING_NODES for n in merged.nodes)
    print(f"Concepts/skills: {before} -> {after} ({len(report.merged)} groups merged)")
    for m in report.merged:
        print(f"  MERGED {m['survivor']!r} <- {m['removed']} ({m['score']})")
    print(f"{len(report.candidates)} borderline pairs sent to review; {len(report.blocked)} blocked by guards")
    for b in report.blocked[:20]:
        print(f"  BLOCKED {b['left']!r} / {b['right']!r} ({b['score']}): {b['reason']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
