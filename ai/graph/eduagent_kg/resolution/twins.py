"""Fix prerequisites between "twins": two nodes that name the same idea.

Lessons are extracted separately, so one idea can come back as a Skill in one lesson and a
Concept in another ("Multiply by 10" / "Multiply by 10"), or as two near-identical names that
the duplicate merge left for review. A PREREQUISITE_FOR between twins is wrong either way:

- Skill -> its own Concept ("Subtract using the vertical method" -> "Vertical subtraction")
  is backwards; it becomes "Skill USES Concept", which is what the link means.
- Same-type near-duplicates ("Include unit in final answer" -> "Include units in answers")
  are not prerequisites of each other; the link is removed and the pair is queued as an
  ``embedding_merge_candidate``, so a reviewer approving it merges the two nodes.

Pairs the duplicate guards call different ("Convert kilometers to meters" vs "Convert meters
to kilometers") are left alone, and so is Concept -> Skill ("Bar graph" -> "Create a bar
graph"), which is a real prerequisite.
"""

from dataclasses import dataclass, field

from eduagent_kg.evaluation.quality import _names_itself, _similar
from eduagent_kg.ids import make_relationship_id
from eduagent_kg.schemas.enums import NodeType, RelationshipType
from eduagent_kg.schemas.graph import CanonicalGraph
from eduagent_kg.schemas.review import ReviewItem, ReviewQueue

from .embedding_dedup import MERGE_CATEGORY, block_reason
from .merger import fold_edge


@dataclass
class TwinReport:
    turned_into_uses: list[str] = field(default_factory=list)
    sent_to_merge_review: list[str] = field(default_factory=list)


def fix_twin_links(graph: CanonicalGraph, queue: ReviewQueue) -> tuple[CanonicalGraph, ReviewQueue, TwinReport]:
    graph = graph.model_copy(deep=True)
    nodes = {n.canonical_id: n for n in graph.nodes}
    report = TwinReport()
    removed: set[str] = set()
    new_items: list[ReviewItem] = []
    uses_edges = []

    for edge in list(graph.relationships) + list(graph.candidate_relationships):
        if edge.relationship_type != RelationshipType.PREREQUISITE_FOR:
            continue
        source, target = nodes[edge.source_canonical_id], nodes[edge.target_canonical_id]
        label = f"{source.name} -> {target.name}"
        if (source.node_type == NodeType.SKILL and target.node_type == NodeType.CONCEPT
                and _names_itself(source.name, target.name)):
            removed.add(edge.canonical_id)
            uses_edges.append(edge.model_copy(update={
                "relationship_type": RelationshipType.USES,
                "canonical_id": make_relationship_id(RelationshipType.USES.value,
                                                     source.canonical_id, target.canonical_id),
                "description": edge.description or f"{source.name} applies {target.name}.",
            }))
            report.turned_into_uses.append(label)
        elif (source.node_type == target.node_type and _similar(source.name, target.name)
              and block_reason(source, target) is None):
            removed.add(edge.canonical_id)
            left, right = sorted((source.canonical_id, target.canonical_id))
            new_items.append(ReviewItem(
                review_id=f"review:merge:{left}:{right}", category=MERGE_CATEGORY,
                target_id=f"{left}|{right}",
                reason=f"'{source.name}' and '{target.name}' look like the same {source.node_type.value}; "
                       "a prerequisite between them was removed. Merge them?",
                payload={"left_canonical_id": left, "right_canonical_id": right, "score": None},
            ))
            report.sent_to_merge_review.append(label)

    graph.relationships = [e for e in graph.relationships if e.canonical_id not in removed]
    graph.candidate_relationships = [e for e in graph.candidate_relationships if e.canonical_id not in removed]
    # A USES link keeps the review state of the prerequisite it replaces; fold into an existing one.
    for edge in uses_edges:
        target_list = graph.candidate_relationships if edge.review_status.value == "candidate" else graph.relationships
        existing = next((e for e in graph.relationships + graph.candidate_relationships
                         if e.canonical_id == edge.canonical_id), None)
        if existing:
            fold_edge(existing, edge)
        else:
            target_list.append(edge)

    by_id = {}
    for item in queue.items:
        if item.target_id in removed:
            continue  # the review item of a removed prerequisite
        by_id[item.review_id] = item
    for edge in uses_edges:  # re-point the review item to the new USES link
        review_id = f"review:relationship:{edge.canonical_id}"
        if review_id not in by_id and edge.review_status.value != "approved":
            by_id[review_id] = ReviewItem(
                review_id=review_id,
                category="inferred_prerequisite" if edge.review_status.value == "candidate" else "relationship_approval",
                target_id=edge.canonical_id,
                reason="Skill USES its own concept (was a backwards prerequisite).",
                payload=edge.model_dump(mode="json"),
            )
    for item in new_items:
        by_id.setdefault(item.review_id, item)
    return graph, queue.model_copy(update={"items": list(by_id.values())}), report
