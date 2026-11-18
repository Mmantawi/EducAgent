from collections import deque

from eduagent_kg.resolution.normalization import normalize_text
from eduagent_kg.schemas.enums import NodeType, RelationshipType, ReviewStatus
from eduagent_kg.schemas.graph import CanonicalGraph
from eduagent_kg.schemas.queries import (
    ConceptDetail, ConceptSummary, ExerciseSummary, ImportStatistics, RelationshipPathItem,
)
from eduagent_kg.validation import GraphValidator

from .service import GraphQueryRepository


class InMemoryGraphRepository(GraphQueryRepository):
    """Deterministic graph repository for unit tests; it executes real graph traversal in memory."""

    def __init__(self) -> None:
        self.nodes = {}
        self.edges = {}
        self.edge_graph_ids = {}

    def import_graph(self, graph: CanonicalGraph) -> ImportStatistics:
        report = GraphValidator().validate(graph)
        if not report.is_valid:
            raise ValueError("Canonical graph is invalid: " + ", ".join(i.code for i in report.issues))
        self.nodes.update({node.canonical_id: node.model_copy(deep=True) for node in graph.nodes})
        approved = [edge for edge in graph.relationships if edge.review_status == ReviewStatus.APPROVED]
        if any(not edge.review_history for edge in approved):
            raise ValueError("Approved relationships require review history")
        approved_ids = {edge.canonical_id for edge in approved}
        for edge_id in [
            edge_id for edge_id, graph_id in self.edge_graph_ids.items()
            if graph_id == graph.graph_id and edge_id not in approved_ids
        ]:
            self.edges.pop(edge_id, None)
            self.edge_graph_ids.pop(edge_id, None)
        self.edges.update({edge.canonical_id: edge.model_copy(deep=True) for edge in approved})
        self.edge_graph_ids.update({edge.canonical_id: graph.graph_id for edge in approved})
        return ImportStatistics(
            graph_id=graph.graph_id, nodes_submitted=len(graph.nodes),
            approved_relationships_submitted=len(approved),
            relationships_excluded=(len(graph.relationships) - len(approved) + len(graph.candidate_relationships)),
        )

    def search_concepts(self, query, subject, grade, limit):
        needle = normalize_text(query)
        matches = []
        for node in self.nodes.values():
            if node.node_type != NodeType.CONCEPT:
                continue
            if subject is not None and node.subject != subject:
                continue
            if grade is not None and node.grade != grade:
                continue
            variants = [node.name, node.normalized_name, *node.aliases]
            if any(needle in normalize_text(value) for value in variants):
                matches.append(node)
        matches.sort(key=lambda node: (node.normalized_name != needle, node.name))
        return [_summary(node) for node in matches[:limit]]

    def get_concept(self, concept_id):
        node = self.nodes.get(concept_id)
        if not node or node.node_type != NodeType.CONCEPT:
            return None
        return ConceptDetail(
            **_summary(node).model_dump(), original_language=node.original_language,
            sources=node.provenance,
        )

    def get_prerequisites(self, concept_id, max_depth):
        if concept_id not in self.nodes:
            return []
        incoming = {}
        for edge in self.edges.values():
            if edge.relationship_type == RelationshipType.PREREQUISITE_FOR:
                incoming.setdefault(edge.target_canonical_id, []).append(edge)
        results = {}
        queue = deque([(concept_id, 0, [], [])])
        best_depth = {concept_id: 0}
        while queue:
            current, depth, relationship_ids, provenance = queue.popleft()
            if depth >= max_depth:
                continue
            for edge in incoming.get(current, []):
                source = edge.source_canonical_id
                next_depth = depth + 1
                next_ids = [edge.canonical_id, *relationship_ids]
                next_provenance = _unique_provenance(provenance + edge.provenance)
                if source not in results or next_depth < results[source].depth:
                    results[source] = RelationshipPathItem(
                        concept=_summary(self.nodes[source]), depth=next_depth,
                        relationship_type=RelationshipType.PREREQUISITE_FOR,
                        direction="prerequisite_to_concept", relationship_ids=next_ids,
                        provenance=next_provenance,
                    )
                if source not in best_depth or next_depth < best_depth[source]:
                    best_depth[source] = next_depth
                    queue.append((source, next_depth, next_ids, next_provenance))
        return sorted(results.values(), key=lambda item: (item.depth, item.concept.name))

    def get_dependents(self, concept_id):
        return sorted([
            _path(self.nodes[edge.target_canonical_id], edge, "concept_to_dependent")
            for edge in self.edges.values()
            if edge.relationship_type == RelationshipType.PREREQUISITE_FOR
            and edge.source_canonical_id == concept_id
        ], key=lambda item: item.concept.name)

    def get_related_concepts(self, concept_id):
        found = {}
        for edge in self.edges.values():
            if edge.relationship_type not in {RelationshipType.IS_A, RelationshipType.PREREQUISITE_FOR}:
                continue
            if edge.source_canonical_id == concept_id:
                other, direction = edge.target_canonical_id, "outgoing"
            elif edge.target_canonical_id == concept_id:
                other, direction = edge.source_canonical_id, "incoming"
            else:
                continue
            node = self.nodes.get(other)
            if node and node.node_type == NodeType.CONCEPT:
                found[(other, edge.relationship_type)] = _path(node, edge, direction)
        return sorted(found.values(), key=lambda item: item.concept.name)

    def get_exercises(self, concept_id):
        results = []
        for edge in self.edges.values():
            if edge.relationship_type != RelationshipType.ASSESSES or edge.target_canonical_id != concept_id:
                continue
            node = self.nodes.get(edge.source_canonical_id)
            if not node or node.node_type != NodeType.EXERCISE:
                continue
            results.append(ExerciseSummary(
                exercise_id=node.canonical_id, name=node.name, description=node.description,
                subject=node.subject, grade=node.grade, relationship_id=edge.canonical_id,
                provenance=edge.provenance,
            ))
        return sorted(results, key=lambda item: item.name)

    def get_concept_sources(self, concept_id):
        node = self.nodes.get(concept_id)
        return list(node.provenance) if node and node.node_type == NodeType.CONCEPT else []


def _summary(node) -> ConceptSummary:
    return ConceptSummary(
        concept_id=node.canonical_id, name=node.name, aliases=node.aliases,
        description=node.description, subject=node.subject, grade=node.grade,
    )


def _path(node, edge, direction) -> RelationshipPathItem:
    return RelationshipPathItem(
        concept=_summary(node), depth=1, relationship_type=edge.relationship_type,
        direction=direction, relationship_ids=[edge.canonical_id], provenance=edge.provenance,
    )


def _unique_provenance(values):
    return list({item.source_ref_id: item for item in values}.values())
