from collections import Counter

from eduagent_kg.resolution.normalization import normalize_text
from eduagent_kg.schemas.evaluation import (
    EvaluationReport, GoldDataset, GraphIntegrityMetrics, PRFMetrics, RetrievalMetrics,
)
from eduagent_kg.schemas.extraction import GraphFragment
from eduagent_kg.schemas.graph import CanonicalGraph
from eduagent_kg.validation import GraphValidator


class KnowledgeGraphEvaluator:
    def evaluate(
        self,
        dataset: GoldDataset,
        *,
        fragments: list[GraphFragment],
        graph: CanonicalGraph,
        query_service=None,
    ) -> EvaluationReport:
        if dataset.annotation_status != "verified":
            return EvaluationReport(
                dataset_id=dataset.dataset_id,
                metrics_available=False,
                unavailable_reason=(
                    "Annotations are draft_unverified. Independent human verification is required "
                    "before reporting extraction or retrieval scores."
                ),
            )
        predicted_entities = {
            (entity.node_type.value, normalize_text(entity.name))
            for fragment in fragments for entity in fragment.entities
            if entity.node_type.value in {"Concept", "Skill", "Exercise", "Experiment"}
        }
        gold_entities = {
            (entity.node_type.value, normalize_text(entity.name))
            for section in dataset.sections for entity in section.entities
        }
        predicted_relationships = set()
        for fragment in fragments:
            entity_map = {entity.local_id: entity for entity in fragment.entities}
            for edge in fragment.relationships:
                source = entity_map.get(edge.source_local_id)
                target = entity_map.get(edge.target_local_id)
                if source and target:
                    predicted_relationships.add((
                        edge.relationship_type.value,
                        source.node_type.value, normalize_text(source.name),
                        target.node_type.value, normalize_text(target.name),
                    ))
        gold_relationships = set()
        for section in dataset.sections:
            entity_map = {entity.gold_id: entity for entity in section.entities}
            for edge in section.relationships:
                source = entity_map[edge.source_gold_id]
                target = entity_map[edge.target_gold_id]
                gold_relationships.add((
                    edge.relationship_type.value,
                    source.node_type.value, normalize_text(source.name),
                    target.node_type.value, normalize_text(target.name),
                ))
        return EvaluationReport(
            dataset_id=dataset.dataset_id, metrics_available=True,
            entity_metrics=_prf(predicted_entities, gold_entities),
            relationship_metrics=_prf(predicted_relationships, gold_relationships),
            graph_integrity=self.graph_integrity(graph),
            retrieval_metrics=self._retrieval(dataset, query_service) if query_service else None,
        )

    def graph_integrity(self, graph: CanonicalGraph) -> GraphIntegrityMetrics:
        report = GraphValidator().validate(graph)
        ids = [node.canonical_id for node in graph.nodes]
        missing_provenance = sum(not node.provenance for node in graph.nodes) + sum(
            not edge.provenance for edge in graph.relationships + graph.candidate_relationships
        )
        return GraphIntegrityMetrics(
            cycle_count=sum(len(cycles) for cycles in report.cycles_by_type.values()),
            invalid_edge_count=sum(
                issue.code in {"missing_endpoint", "invalid_ontology_edge", "self_relation", "duplicate_edge"}
                for issue in report.issues
            ),
            duplicate_canonical_node_count=len(ids) - len(set(ids)),
            missing_provenance_count=missing_provenance,
        )

    def _retrieval(self, dataset: GoldDataset, service) -> RetrievalMetrics:
        prerequisite_correct = prerequisite_total = 0
        source_correct = source_total = 0
        missing_correct = missing_total = 0
        for case in dataset.retrieval_cases:
            if case.expect_missing:
                missing_total += 1
                matches = service.search_concepts(case.query).results
                missing_correct += not matches
                continue
            concept = service.get_concept(case.concept_id) if case.concept_id else None
            if concept is None and case.concept_name:
                matches = service.search_concepts(case.concept_name).results
                concept = service.get_concept(matches[0].concept_id) if matches else None
            prerequisite_total += 1
            source_total += 1
            if concept is None:
                continue
            actual_prerequisites = {
                normalize_text(item.concept.name)
                for item in service.get_prerequisites(concept.concept_id, max_depth=1).prerequisites
            }
            expected_prerequisites = {
                normalize_text(name) for name in case.expected_direct_prerequisite_names
            }
            prerequisite_correct += actual_prerequisites == expected_prerequisites
            actual_sources = {
                source.section_id for source in service.get_concept_sources(concept.concept_id).sources
            }
            source_correct += set(case.expected_section_ids).issubset(actual_sources)
        return RetrievalMetrics(
            evaluated_cases=len(dataset.retrieval_cases),
            direct_prerequisite_accuracy=_ratio(prerequisite_correct, prerequisite_total),
            source_reference_accuracy=_ratio(source_correct, source_total),
            missing_concept_accuracy=_ratio(missing_correct, missing_total),
        )


def _prf(predicted: set, gold: set) -> PRFMetrics:
    true_positives = len(predicted & gold)
    false_positives = len(predicted - gold)
    false_negatives = len(gold - predicted)
    precision = _ratio(true_positives, true_positives + false_positives)
    recall = _ratio(true_positives, true_positives + false_negatives)
    f1 = _ratio(2 * precision * recall, precision + recall)
    return PRFMetrics(
        true_positives=true_positives, false_positives=false_positives,
        false_negatives=false_negatives, precision=precision, recall=recall, f1=f1,
    )


def _ratio(numerator, denominator) -> float:
    return float(numerator / denominator) if denominator else 0.0
