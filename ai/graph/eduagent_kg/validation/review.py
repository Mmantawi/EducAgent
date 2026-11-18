from eduagent_kg.ids import make_relationship_id
from eduagent_kg.schemas.enums import DecisionType, ReviewStatus
from eduagent_kg.schemas.graph import CanonicalGraph, CanonicalRelationship
from eduagent_kg.schemas.review import ReviewDecision, ReviewQueue


def apply_review_decisions(
    graph: CanonicalGraph, queue: ReviewQueue, decisions: list[ReviewDecision]
) -> tuple[CanonicalGraph, ReviewQueue]:
    graph = graph.model_copy(deep=True)
    queue = queue.model_copy(deep=True)
    item_lookup = {item.review_id: item for item in queue.items}
    item_lookup.update({item.target_id: item for item in queue.items})
    for decision in decisions:
        item = item_lookup.get(decision.target_id)
        if item is None:
            raise ValueError(f"Review target not found: {decision.target_id}")
        item.history.append(decision)
        if decision.decision == DecisionType.APPROVE:
            item.status = ReviewStatus.APPROVED
            if item.category == "inferred_prerequisite":
                _approve_candidate_relationship(graph, item.target_id, decision)
            elif item.category == "relationship_approval":
                _approve_existing_relationship(graph, item.target_id, decision)
            elif item.category in {"fuzzy_merge_candidate", "semantic_candidate"}:
                _approve_entity_merge(graph, item.payload)
        elif decision.decision == DecisionType.REJECT:
            item.status = ReviewStatus.REJECTED
            if item.category == "relationship_approval":
                _reject_existing_relationship(graph, item.target_id, decision)
            else:
                _reject_candidate_relationship(graph, item.target_id, decision)
        else:
            item.status = ReviewStatus.CANDIDATE
    return graph, queue


def _approve_candidate_relationship(
    graph: CanonicalGraph, relationship_id: str, decision: ReviewDecision
) -> None:
    for index, edge in enumerate(graph.candidate_relationships):
        if edge.canonical_id == relationship_id:
            approved = edge.model_copy(update={
                "review_status": ReviewStatus.APPROVED,
                "review_history": [*edge.review_history, decision],
            })
            graph.relationships.append(approved)
            del graph.candidate_relationships[index]
            return
    raise ValueError(f"Candidate relationship not found: {relationship_id}")


def _reject_candidate_relationship(
    graph: CanonicalGraph, relationship_id: str, decision: ReviewDecision
) -> None:
    for index, edge in enumerate(graph.candidate_relationships):
        if edge.canonical_id == relationship_id:
            graph.candidate_relationships[index] = edge.model_copy(
                update={
                    "review_status": ReviewStatus.REJECTED,
                    "review_history": [*edge.review_history, decision],
                }
            )
            return


def _approve_existing_relationship(
    graph: CanonicalGraph, relationship_id: str, decision: ReviewDecision
) -> None:
    for index, edge in enumerate(graph.relationships):
        if edge.canonical_id == relationship_id:
            graph.relationships[index] = edge.model_copy(update={
                "review_status": ReviewStatus.APPROVED,
                "disposition": edge.disposition,
                "review_history": [*edge.review_history, decision],
            })
            return
    raise ValueError(f"Relationship not found: {relationship_id}")


def _reject_existing_relationship(
    graph: CanonicalGraph, relationship_id: str, decision: ReviewDecision
) -> None:
    for index, edge in enumerate(graph.relationships):
        if edge.canonical_id == relationship_id:
            rejected = edge.model_copy(update={
                "review_status": ReviewStatus.REJECTED,
                "review_history": [*edge.review_history, decision],
            })
            del graph.relationships[index]
            graph.candidate_relationships.append(rejected)
            return
    raise ValueError(f"Relationship not found: {relationship_id}")


def _approve_entity_merge(graph: CanonicalGraph, payload: dict) -> None:
    left_id = payload["left_canonical_id"]
    right_id = payload["right_canonical_id"]
    survivor_id, removed_id = sorted((left_id, right_id))
    nodes = {node.canonical_id: node for node in graph.nodes}
    survivor = nodes.get(survivor_id)
    removed = nodes.get(removed_id)
    if survivor is None or removed is None:
        raise ValueError("Merge candidate references a missing canonical entity")
    if survivor.node_type != removed.node_type or survivor.subject != removed.subject or survivor.grade != removed.grade:
        raise ValueError("Review cannot merge entities across type, subject, or grade scope")
    survivor.aliases = sorted(set(survivor.aliases + removed.aliases + [removed.name]))
    survivor.source_local_ids = sorted(set(survivor.source_local_ids + removed.source_local_ids))
    survivor.provenance = list({p.source_ref_id: p for p in survivor.provenance + removed.provenance}.values())
    graph.nodes = [node for node in graph.nodes if node.canonical_id != removed_id]
    graph.relationships = _remap_edges(graph.relationships, removed_id, survivor)
    graph.candidate_relationships = _remap_edges(graph.candidate_relationships, removed_id, survivor)


def _remap_edges(edges, removed_id: str, survivor) -> list[CanonicalRelationship]:
    merged: dict[tuple, CanonicalRelationship] = {}
    for edge in edges:
        source = survivor.canonical_id if edge.source_canonical_id == removed_id else edge.source_canonical_id
        target = survivor.canonical_id if edge.target_canonical_id == removed_id else edge.target_canonical_id
        if source == target:
            continue
        updated = edge.model_copy(update={
            "source_canonical_id": source, "target_canonical_id": target,
            "source_type": survivor.node_type if source == survivor.canonical_id else edge.source_type,
            "target_type": survivor.node_type if target == survivor.canonical_id else edge.target_type,
            "canonical_id": make_relationship_id(edge.relationship_type.value, source, target),
        })
        key = (updated.relationship_type, source, target)
        if key in merged:
            merged[key].provenance = list({
                p.source_ref_id: p for p in merged[key].provenance + updated.provenance
            }.values())
        else:
            merged[key] = updated
    return list(merged.values())
