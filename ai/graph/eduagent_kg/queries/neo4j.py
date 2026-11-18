import json

from eduagent_kg.resolution.normalization import normalize_text
from eduagent_kg.schemas.enums import RelationshipType
from eduagent_kg.schemas.provenance import SourceReference
from eduagent_kg.schemas.queries import (
    ConceptDetail, ConceptSummary, ExerciseSummary, RelationshipPathItem,
)

from .service import GraphQueryRepository


class Neo4jGraphQueryRepository(GraphQueryRepository):
    def __init__(self, driver, *, database: str = "neo4j") -> None:
        self.driver = driver
        self.database = database

    def search_concepts(self, query, subject, grade, limit):
        records = self._run("""
            MATCH (c:Entity:Concept)
            WHERE ($subject IS NULL OR c.subject = $subject)
              AND ($grade IS NULL OR c.grade = $grade)
              AND (
                c.normalized_name CONTAINS $normalized
                OR toLower(c.name) CONTAINS $lower_query
                OR any(alias IN coalesce(c.aliases, []) WHERE toLower(alias) CONTAINS $lower_query)
              )
            RETURN c
            ORDER BY CASE WHEN c.normalized_name = $normalized THEN 0 ELSE 1 END, c.name
            LIMIT $limit
        """, subject=subject, grade=grade, normalized=normalize_text(query),
             lower_query=query.casefold(), limit=limit)
        return [_concept_summary(_data(record)["c"]) for record in records]

    def get_concept(self, concept_id):
        records = self._run("""
            MATCH (c:Entity:Concept {canonical_id: $concept_id})
            RETURN c
        """, concept_id=concept_id)
        if not records:
            return None
        node = _data(records[0])["c"]
        return ConceptDetail(
            **_concept_summary(node).model_dump(),
            original_language=node.get("original_language", "en"),
            sources=_provenance(node.get("provenance_json")),
        )

    def get_prerequisites(self, concept_id, max_depth):
        # max_depth is validated as an integer in GraphQueryService; Cypher ranges cannot be parameters.
        records = self._run(f"""
            MATCH p=(pre:Entity:Concept)-[:PREREQUISITE_FOR*1..{max_depth}]->
                    (c:Entity:Concept {{canonical_id: $concept_id}})
            WHERE all(r IN relationships(p) WHERE r.review_status = 'approved')
            RETURN pre, length(p) AS depth,
                   [r IN relationships(p) | r.canonical_id] AS relationship_ids,
                   [r IN relationships(p) | r.provenance_json] AS provenance_jsons
            ORDER BY depth, pre.name
        """, concept_id=concept_id)
        return [RelationshipPathItem(
            concept=_concept_summary(data["pre"]), depth=data["depth"],
            relationship_type=RelationshipType.PREREQUISITE_FOR,
            direction="prerequisite_to_concept", relationship_ids=data["relationship_ids"],
            provenance=_provenance_many(data["provenance_jsons"]),
        ) for record in records for data in [_data(record)]]

    def get_dependents(self, concept_id):
        records = self._run("""
            MATCH (c:Entity:Concept {canonical_id: $concept_id})
                  -[r:PREREQUISITE_FOR]->(dependent:Entity:Concept)
            WHERE r.review_status = 'approved'
            RETURN dependent, r
            ORDER BY dependent.name
        """, concept_id=concept_id)
        return [_path_item(record, "dependent", "concept_to_dependent") for record in records]

    def get_related_concepts(self, concept_id):
        records = self._run("""
            MATCH (c:Entity:Concept {canonical_id: $concept_id})
                  -[r:IS_A|PREREQUISITE_FOR]-(other:Entity:Concept)
            WHERE r.review_status = 'approved'
            RETURN DISTINCT other, r,
                   CASE WHEN startNode(r).canonical_id = c.canonical_id
                        THEN 'outgoing' ELSE 'incoming' END AS direction
            ORDER BY other.name
        """, concept_id=concept_id)
        return [RelationshipPathItem(
            concept=_concept_summary(data["other"]), depth=1,
            relationship_type=RelationshipType(data["r"].type),
            direction=data["direction"], relationship_ids=[data["r"].get("canonical_id")],
            provenance=_provenance(data["r"].get("provenance_json")),
        ) for record in records for data in [_data(record)]]

    def get_exercises(self, concept_id):
        records = self._run("""
            MATCH (exercise:Entity:Exercise)-[r:ASSESSES]->
                  (c:Entity:Concept {canonical_id: $concept_id})
            WHERE r.review_status = 'approved'
            RETURN exercise, r
            ORDER BY exercise.name
        """, concept_id=concept_id)
        return [ExerciseSummary(
            exercise_id=data["exercise"].get("canonical_id"),
            name=data["exercise"].get("name"),
            description=data["exercise"].get("description"),
            subject=data["exercise"].get("subject"), grade=data["exercise"].get("grade"),
            relationship_id=data["r"].get("canonical_id"),
            provenance=_provenance(data["r"].get("provenance_json")),
        ) for record in records for data in [_data(record)]]

    def get_concept_sources(self, concept_id):
        records = self._run("""
            MATCH (c:Entity:Concept {canonical_id: $concept_id})
            RETURN c.provenance_json AS provenance_json
        """, concept_id=concept_id)
        return _provenance(_data(records[0])["provenance_json"]) if records else []

    def _run(self, query: str, **parameters):
        result = self.driver.execute_query(query, database_=self.database, **parameters)
        return result.records


def _data(record):
    return record.data() if hasattr(record, "data") else record


def _concept_summary(node) -> ConceptSummary:
    return ConceptSummary(
        concept_id=node.get("canonical_id"), name=node.get("name"),
        aliases=list(node.get("aliases") or []), description=node.get("description"),
        subject=node.get("subject"), grade=node.get("grade"),
    )


def _path_item(record, node_key: str, direction: str) -> RelationshipPathItem:
    data = _data(record)
    relationship = data["r"]
    return RelationshipPathItem(
        concept=_concept_summary(data[node_key]), depth=1,
        relationship_type=RelationshipType(relationship.type), direction=direction,
        relationship_ids=[relationship.get("canonical_id")],
        provenance=_provenance(relationship.get("provenance_json")),
    )


def _provenance(value: str | None) -> list[SourceReference]:
    if not value:
        return []
    return [SourceReference.model_validate(item) for item in json.loads(value)]


def _provenance_many(values: list[str]) -> list[SourceReference]:
    unique = {}
    for value in values:
        for item in _provenance(value):
            unique[item.source_ref_id] = item
    return list(unique.values())
