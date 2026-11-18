import json
from collections import defaultdict

from eduagent_kg.schemas.enums import NodeType, RelationshipType, ReviewStatus
from eduagent_kg.schemas.graph import CanonicalGraph
from eduagent_kg.schemas.queries import ImportStatistics
from eduagent_kg.validation import GraphValidator

NODE_LABELS = {node_type: node_type.value for node_type in NodeType}
RELATIONSHIP_TYPES = {kind: kind.value for kind in RelationshipType}


class GraphImportError(RuntimeError):
    pass


class Neo4jGraphStore:
    def __init__(self, driver, *, database: str = "neo4j") -> None:
        self.driver = driver
        self.database = database

    @classmethod
    def connect(cls, uri: str, username: str, password: str, *, database: str = "neo4j"):
        from neo4j import GraphDatabase

        driver = GraphDatabase.driver(uri, auth=(username, password))
        return cls(driver, database=database)

    def close(self) -> None:
        self.driver.close()

    def verify_connectivity(self) -> None:
        self.driver.verify_connectivity()

    def initialize_schema(self) -> None:
        statements = [
            "CREATE CONSTRAINT entity_canonical_id IF NOT EXISTS "
            "FOR (n:Entity) REQUIRE n.canonical_id IS UNIQUE",
            "CREATE INDEX concept_normalized_name IF NOT EXISTS "
            "FOR (n:Concept) ON (n.normalized_name)",
            "CREATE INDEX concept_subject_grade IF NOT EXISTS "
            "FOR (n:Concept) ON (n.subject, n.grade)",
            "CREATE INDEX source_section_id IF NOT EXISTS "
            "FOR (n:SourceSection) ON (n.section_id)",
            "CREATE INDEX book_reference_id IF NOT EXISTS "
            "FOR (n:Book) ON (n.book_id)",
        ]
        statements.extend(
            f"CREATE CONSTRAINT rel_{kind.value.lower()}_id IF NOT EXISTS "
            f"FOR ()-[r:{kind.value}]-() REQUIRE r.canonical_id IS UNIQUE"
            for kind in RelationshipType
        )
        for statement in statements:
            self.driver.execute_query(statement, database_=self.database)

    def import_graph(self, graph: CanonicalGraph) -> ImportStatistics:
        report = GraphValidator().validate(graph)
        if not report.is_valid:
            codes = ", ".join(issue.code for issue in report.issues)
            raise GraphImportError(f"Canonical graph failed validation before import: {codes}")
        approved = [
            edge for edge in graph.relationships
            if edge.review_status == ReviewStatus.APPROVED
        ]
        missing_review = [edge.canonical_id for edge in approved if not edge.review_history]
        if missing_review:
            raise GraphImportError(
                "Approved relationships are missing review history: " + ", ".join(missing_review)
            )
        excluded = len(graph.relationships) - len(approved) + len(graph.candidate_relationships)
        self.driver.execute_query(
            """
            MATCH ()-[r]->()
            WHERE r.graph_id = $graph_id AND NOT r.canonical_id IN $approved_ids
            DELETE r
            """,
            graph_id=graph.graph_id,
            approved_ids=[edge.canonical_id for edge in approved],
            database_=self.database,
        )
        nodes_by_type: dict[NodeType, list[dict]] = defaultdict(list)
        for node in graph.nodes:
            nodes_by_type[node.node_type].append(_node_row(node, graph.graph_id))
        for node_type, rows in nodes_by_type.items():
            label = NODE_LABELS[node_type]
            query = f"""
            UNWIND $rows AS row
            MERGE (n:Entity:{label} {{canonical_id: row.canonical_id}})
            SET n += row.properties
            """
            self.driver.execute_query(query, rows=rows, database_=self.database)

        edges_by_type: dict[RelationshipType, list[dict]] = defaultdict(list)
        for edge in approved:
            edges_by_type[edge.relationship_type].append(_relationship_row(edge, graph.graph_id))
        for relationship_type, rows in edges_by_type.items():
            cypher_type = RELATIONSHIP_TYPES[relationship_type]
            query = f"""
            UNWIND $rows AS row
            MATCH (source:Entity {{canonical_id: row.source_id}})
            MATCH (target:Entity {{canonical_id: row.target_id}})
            MERGE (source)-[r:{cypher_type} {{canonical_id: row.canonical_id}}]->(target)
            SET r += row.properties
            """
            self.driver.execute_query(query, rows=rows, database_=self.database)
        return ImportStatistics(
            graph_id=graph.graph_id, nodes_submitted=len(graph.nodes),
            approved_relationships_submitted=len(approved), relationships_excluded=excluded,
        )


def _node_row(node, graph_id: str) -> dict:
    attributes = dict(node.attributes)
    return {
        "canonical_id": node.canonical_id,
        "properties": {
            "canonical_id": node.canonical_id, "node_type": node.node_type.value,
            "name": node.name, "normalized_name": node.normalized_name,
            "description": node.description, "aliases": node.aliases,
            "subject": node.subject, "grade": node.grade,
            "original_language": node.original_language,
            "review_status": node.review_status.value,
            "source_local_ids": node.source_local_ids,
            "provenance_json": json.dumps(
                [item.model_dump(mode="json") for item in node.provenance], ensure_ascii=False
            ),
            "attributes_json": json.dumps(attributes, ensure_ascii=False),
            "section_id": attributes.get("section_id"),
            "book_id": attributes.get("book_id"), "graph_id": graph_id,
        },
    }


def _relationship_row(edge, graph_id: str) -> dict:
    return {
        "canonical_id": edge.canonical_id,
        "source_id": edge.source_canonical_id, "target_id": edge.target_canonical_id,
        "properties": {
            "canonical_id": edge.canonical_id,
            "relationship_type": edge.relationship_type.value,
            "disposition": edge.disposition.value,
            "review_status": edge.review_status.value,
            "rationale": edge.rationale,
            "review_history_json": json.dumps(
                [item.model_dump(mode="json") for item in edge.review_history], ensure_ascii=False
            ),
            "provenance_json": json.dumps(
                [item.model_dump(mode="json") for item in edge.provenance], ensure_ascii=False
            ),
            "graph_id": graph_id,
        },
    }
