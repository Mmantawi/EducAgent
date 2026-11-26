"""Reference-free quality report for a canonical graph.

Measures the problems found in the first Qwen graph without needing a hand-labelled
gold set: isolated nodes, star-shaped graphs, near-duplicate names, missing descriptions,
prerequisites that only link a skill to its own concept, and the size of the review queue.

    python -m eduagent_kg.evaluation.quality --graph old=path/old.json --graph new=path/new.json
"""

import argparse
import json
import re
from collections import Counter, defaultdict
from difflib import SequenceMatcher
from itertools import combinations
from pathlib import Path

from eduagent_kg.console import configure_utf8_stdout
from eduagent_kg.ontology import LEARNING_NODES, STRUCTURAL_RELATIONSHIPS, SYMMETRIC_RELATIONSHIPS
from eduagent_kg.schemas.enums import NodeType, RelationshipType, ReviewStatus
from eduagent_kg.schemas.graph import CanonicalGraph

# Generic verbs and filler that make "Perform division" and "Division" look different.
STOPWORDS = {
    "a", "an", "the", "of", "for", "to", "in", "on", "by", "with", "and", "using", "use",
    "perform", "calculate", "compute", "find", "solve", "do", "apply", "basic", "method",
    "operation", "problems", "problem", "numbers", "number",
}
LINK_TYPES_EXCLUDED = STRUCTURAL_RELATIONSHIPS | {RelationshipType.TEACHES}


def _tokens(name: str) -> frozenset[str]:
    words = re.findall(r"[a-z0-9]+", name.casefold())
    stems = {w[:-1] if len(w) > 4 and w.endswith("s") else w for w in words}
    return frozenset(stems - STOPWORDS)


def _similar(a: str, b: str) -> bool:
    """Likely the same node: same content words, and never different numbers (by 10 vs by 0)."""
    ta, tb = _tokens(a), _tokens(b)
    if {t for t in ta if t.isdigit()} != {t for t in tb if t.isdigit()}:
        return False
    if ta and ta == tb:
        return True
    jaccard = len(ta & tb) / len(ta | tb) if ta | tb else 0.0
    return jaccard >= 0.67 or SequenceMatcher(None, a.casefold(), b.casefold()).ratio() >= 0.93


def _names_itself(skill: str, concept: str) -> bool:
    """A skill whose name just wraps the concept ("Calculate Elapsed Time" / "Elapsed Time")."""
    prefix = lambda name: {t[:5] for t in _tokens(name)}  # convert/conversion -> "conve"
    concept_stems = prefix(concept)
    return bool(concept_stems) and concept_stems <= prefix(skill)


def _same_thing(a, b) -> bool:
    """Similar names that the duplicate-merge guards do not call different
    ("Convert kilometers to meters" vs "Convert meters to kilometers" are different)."""
    from eduagent_kg.resolution.embedding_dedup import block_reason  # avoids an import cycle
    return _similar(a.name, b.name) and block_reason(a, b) is None


def evaluate_graph(graph: CanonicalGraph, extraction: dict | None = None) -> dict:
    nodes = {node.canonical_id: node for node in graph.nodes}
    edges = list(graph.relationships) + list(graph.candidate_relationships)
    knowledge = {cid for cid, node in nodes.items() if node.node_type in LEARNING_NODES}

    # Where each knowledge node is taught: section -> lesson/chapter via PART_OF.
    parent = {e.source_canonical_id: e.target_canonical_id for e in edges
              if e.relationship_type == RelationshipType.PART_OF}

    def chapter_of(section_id: str) -> str | None:
        current, seen = section_id, set()
        while current in parent and current not in seen:
            seen.add(current)
            current = parent[current]
            if nodes.get(current) and nodes[current].node_type == NodeType.CHAPTER:
                return current
        return None

    sections_of: dict[str, set[str]] = defaultdict(set)
    for e in edges:
        if e.relationship_type == RelationshipType.SUPPORTED_BY and e.source_canonical_id in knowledge:
            sections_of[e.source_canonical_id].add(e.target_canonical_id)
    chapters_of = {cid: {c for s in secs if (c := chapter_of(s))} for cid, secs in sections_of.items()}

    links = [e for e in edges if e.relationship_type not in LINK_TYPES_EXCLUDED
             and e.source_canonical_id in knowledge and e.target_canonical_id in knowledge]
    degree = Counter()
    for e in links:
        degree[e.source_canonical_id] += 1
        degree[e.target_canonical_id] += 1
    isolated = sorted(nodes[cid].name for cid in knowledge if degree[cid] == 0)

    # Largest connected group of knowledge nodes (undirected).
    neighbours = defaultdict(set)
    for e in links:
        neighbours[e.source_canonical_id].add(e.target_canonical_id)
        neighbours[e.target_canonical_id].add(e.source_canonical_id)
    largest, seen = 0, set()
    for start in knowledge:
        if start in seen:
            continue
        stack, size = [start], 0
        seen.add(start)
        while stack:
            current = stack.pop()
            size += 1
            for nxt in neighbours[current] - seen:
                seen.add(nxt)
                stack.append(nxt)
        largest = max(largest, size)

    prereqs = [e for e in links if e.relationship_type == RelationshipType.PREREQUISITE_FOR]
    cross_lesson = [e for e in prereqs if not (sections_of[e.source_canonical_id] & sections_of[e.target_canonical_id])]
    cross_chapter = [e for e in prereqs if chapters_of.get(e.source_canonical_id) and chapters_of.get(e.target_canonical_id)
                     and not (chapters_of[e.source_canonical_id] & chapters_of[e.target_canonical_id])]
    def is_self_link(edge) -> bool:
        source, target = nodes[edge.source_canonical_id], nodes[edge.target_canonical_id]
        if source.node_type == target.node_type:
            return _same_thing(source, target)
        # "Bar graph -> Create a bar graph" (concept first) is a real prerequisite; only the
        # reverse, a skill pointing at its own concept, is backwards.
        return source.node_type == NodeType.SKILL and _names_itself(source.name, target.name)

    self_links = [
        f"{nodes[e.source_canonical_id].name} -> {nodes[e.target_canonical_id].name}"
        for e in prereqs if is_self_link(e)
    ]
    duplicates = [
        f"{nodes[a].name} | {nodes[b].name}"
        for a, b in combinations(sorted(knowledge), 2)
        if nodes[a].node_type == nodes[b].node_type and _same_thing(nodes[a], nodes[b])
    ]
    needs_review = [e for e in edges if e.review_status != ReviewStatus.APPROVED
                    and e.relationship_type not in STRUCTURAL_RELATIONSHIPS]
    described_links = [e for e in links if getattr(e, "description", None)]
    strengths = [e.strength for e in links if getattr(e, "strength", None)]
    directed = {(e.relationship_type, e.source_canonical_id, e.target_canonical_id) for e in links
                if e.relationship_type not in SYMMETRIC_RELATIONSHIPS}
    two_way = sum(1 for kind, a, b in directed if (kind, b, a) in directed) // 2
    spread = (
        round((sum((s - sum(strengths) / len(strengths)) ** 2 for s in strengths) / len(strengths)) ** 0.5, 2)
        if strengths else None
    )

    report = {
        "nodes_by_type": dict(sorted(Counter(n.node_type.value for n in nodes.values()).items())),
        "knowledge_nodes": len(knowledge),
        "links_by_type": dict(sorted(Counter(e.relationship_type.value for e in links).items())),
        "knowledge_links": len(links),
        "links_per_knowledge_node": round(2 * len(links) / len(knowledge), 2) if knowledge else 0.0,
        "isolated_knowledge_nodes": len(isolated),
        "isolated_share": round(len(isolated) / len(knowledge), 2) if knowledge else 0.0,
        "largest_connected_group": largest,
        "prerequisites": len(prereqs),
        "cross_lesson_prerequisites": len(cross_lesson),
        "cross_chapter_prerequisites": len(cross_chapter),
        "self_link_prerequisites": len(self_links),
        "likely_duplicate_pairs": len(duplicates),
        "nodes_without_description": sum(not nodes[c].description for c in knowledge),
        "links_with_description": len(described_links),
        "mean_link_strength": round(sum(strengths) / len(strengths), 1) if strengths else None,
        "link_strength_spread": spread,
        "distinct_link_types": len({e.relationship_type for e in links}),
        "two_way_directed_pairs": two_way,
        "relationships_needing_review": len(needs_review),
        "approved_relationships": sum(e.review_status == ReviewStatus.APPROVED for e in edges),
        "examples": {
            "isolated": isolated[:15],
            "self_link_prerequisites": self_links[:10],
            "likely_duplicates": duplicates[:15],
        },
    }
    if extraction:
        report.update(extraction)
    return report


def summarize_extraction(path: Path) -> dict:
    """Section success counts from this repo's extraction report or the old Kaggle run manifest."""
    data = json.loads(path.read_text(encoding="utf-8"))
    if "results" in data:
        total = len(data["results"])
        failed = sum(r.get("status") != "succeeded" for r in data["results"])
    else:
        total = data.get("raw_sections", 0)
        failed = len(data.get("skipped_sections", []))
    return {"sections_total": total, "sections_failed": failed}


ROWS = [
    ("sections_total", "Sections"), ("sections_failed", "Sections failed"),
    ("knowledge_nodes", "Concepts + skills"), ("knowledge_links", "Links between concepts/skills"),
    ("links_per_knowledge_node", "Links per concept/skill"),
    ("isolated_knowledge_nodes", "Concepts/skills with no links"), ("isolated_share", "  share"),
    ("largest_connected_group", "Largest connected group"),
    ("prerequisites", "Prerequisites"), ("cross_lesson_prerequisites", "  across lessons"),
    ("cross_chapter_prerequisites", "  across chapters"),
    ("self_link_prerequisites", "  skill -> own concept (bad)"),
    ("likely_duplicate_pairs", "Likely duplicate pairs"),
    ("nodes_without_description", "Concepts/skills without description"),
    ("links_with_description", "Links with description"), ("mean_link_strength", "Mean link strength"),
    ("link_strength_spread", "  strength spread (std dev; 0 = all the same)"),
    ("distinct_link_types", "Distinct link types used"),
    ("two_way_directed_pairs", "Two-way directed links (bad)"),
    ("relationships_needing_review", "Relationships needing human review"),
    ("approved_relationships", "Approved relationships"),
]


def render_markdown(reports: dict[str, dict]) -> str:
    labels = list(reports)
    lines = ["| Metric | " + " | ".join(labels) + " |", "|---|" + "---|" * len(labels)]
    for key, title in ROWS:
        if any(key in r for r in reports.values()):
            lines.append(f"| {title} | " + " | ".join(str(reports[l].get(key, "-")) for l in labels) + " |")
    kinds = sorted({k for r in reports.values() for k in r["links_by_type"]})
    for kind in kinds:
        lines.append(f"| `{kind}` links | " + " | ".join(str(reports[l]["links_by_type"].get(kind, 0)) for l in labels) + " |")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    configure_utf8_stdout()
    parser = argparse.ArgumentParser(description="Reference-free quality report for canonical graphs.")
    parser.add_argument("--graph", action="append", required=True, metavar="LABEL=PATH",
                        help="Graph to score; repeat to compare (e.g. old=a.json new=b.json)")
    parser.add_argument("--extraction", action="append", default=[], metavar="LABEL=PATH",
                        help="Optional extraction report / run manifest for the same label")
    parser.add_argument("--json", type=Path, help="Also write the full reports as JSON")
    args = parser.parse_args(argv)
    extraction = {label: summarize_extraction(Path(p)) for label, p in (x.split("=", 1) for x in args.extraction)}
    reports = {}
    for item in args.graph:
        label, path = item.split("=", 1) if "=" in item else (Path(item).stem, item)
        graph = CanonicalGraph.model_validate_json(Path(path).read_text(encoding="utf-8"))
        reports[label] = evaluate_graph(graph, extraction.get(label))
    print(render_markdown(reports))
    for label, report in reports.items():
        print(f"\n[{label}] examples")
        for name, values in report["examples"].items():
            print(f"  {name}: {values[:8]}")
    if args.json:
        args.json.write_text(json.dumps(reports, indent=2, ensure_ascii=False), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
