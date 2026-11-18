from collections import Counter

import networkx as nx

from eduagent_kg.ontology import relationship_is_allowed
from eduagent_kg.schemas.enums import RelationshipType, Severity
from eduagent_kg.schemas.graph import CanonicalGraph
from eduagent_kg.schemas.review import ValidationIssue, ValidationReport


class GraphValidator:
    VERSION = "1.0"

    def validate(self, graph: CanonicalGraph) -> ValidationReport:
        issues: list[ValidationIssue] = []
        node_ids = [node.canonical_id for node in graph.nodes]
        node_map = {node.canonical_id: node for node in graph.nodes}
        if len(node_ids) != len(node_map):
            issues.append(ValidationIssue(
                code="duplicate_node_id", severity=Severity.ERROR,
                message="Canonical node IDs must be unique.",
            ))
        for node in graph.nodes:
            if not node.canonical_id or ":" not in node.canonical_id:
                issues.append(ValidationIssue(
                    code="unstable_node_id", severity=Severity.ERROR,
                    message="Canonical node ID does not use the stable typed ID format.",
                    target_id=node.canonical_id,
                ))
            if not node.provenance:
                issues.append(ValidationIssue(
                    code="missing_node_provenance", severity=Severity.ERROR,
                    message="Canonical node has no provenance.", target_id=node.canonical_id,
                ))

        seen_edges: set[tuple] = set()
        all_relationships = graph.relationships + graph.candidate_relationships
        for edge in all_relationships:
            source = node_map.get(edge.source_canonical_id)
            target = node_map.get(edge.target_canonical_id)
            if source is None or target is None:
                issues.append(ValidationIssue(
                    code="missing_endpoint", severity=Severity.ERROR,
                    message="Relationship references a missing source or target node.",
                    target_id=edge.canonical_id,
                ))
                continue
            if edge.source_canonical_id == edge.target_canonical_id:
                issues.append(ValidationIssue(
                    code="self_relation", severity=Severity.ERROR,
                    message="Self-relationships are invalid.", target_id=edge.canonical_id,
                ))
            if not relationship_is_allowed(edge.relationship_type, source.node_type, target.node_type):
                issues.append(ValidationIssue(
                    code="invalid_ontology_edge", severity=Severity.ERROR,
                    message=(f"{edge.relationship_type.value} does not allow "
                             f"{source.node_type.value} -> {target.node_type.value}"),
                    target_id=edge.canonical_id,
                ))
            key = (edge.relationship_type, edge.source_canonical_id, edge.target_canonical_id)
            if key in seen_edges:
                issues.append(ValidationIssue(
                    code="duplicate_edge", severity=Severity.ERROR,
                    message="Duplicate canonical edge detected.", target_id=edge.canonical_id,
                ))
            seen_edges.add(key)
            if not edge.provenance:
                issues.append(ValidationIssue(
                    code="missing_edge_provenance", severity=Severity.ERROR,
                    message="Canonical relationship has no provenance.", target_id=edge.canonical_id,
                ))

        cycles_by_type: dict[str, list[list[str]]] = {}
        # Candidates are excluded: an unreviewed inferred prerequisite is not an approved fact.
        for relationship_type in (RelationshipType.PREREQUISITE_FOR, RelationshipType.IS_A):
            typed_graph = nx.DiGraph()
            typed_graph.add_nodes_from(node_map)
            typed_graph.add_edges_from(
                (edge.source_canonical_id, edge.target_canonical_id)
                for edge in graph.relationships
                if edge.relationship_type == relationship_type
            )
            if not nx.is_directed_acyclic_graph(typed_graph):
                cycles = [list(cycle) for cycle in nx.simple_cycles(typed_graph)]
                cycles_by_type[relationship_type.value] = cycles
                for cycle in cycles:
                    issues.append(ValidationIssue(
                        code=f"cycle_{relationship_type.value.lower()}",
                        severity=Severity.ERROR,
                        message=f"{relationship_type.value} cycle detected: {' -> '.join(cycle)}",
                        target_id=cycle[0] if cycle else None,
                    ))

        counts = Counter(edge.relationship_type.value for edge in graph.relationships)
        return ValidationReport(
            graph_id=graph.graph_id, validator_version=self.VERSION,
            is_valid=not any(issue.severity == Severity.ERROR for issue in issues),
            issues=issues, checked_node_count=len(graph.nodes),
            checked_relationship_count=len(all_relationships),
            relationship_counts_by_type=dict(sorted(counts.items())),
            cycles_by_type=cycles_by_type,
        )
