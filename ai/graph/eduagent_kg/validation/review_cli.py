import argparse
import json
from pathlib import Path

from eduagent_kg.schemas.graph import CanonicalGraph
from eduagent_kg.schemas.review import ReviewDecision, ReviewQueue
from eduagent_kg.validation.graph_validator import GraphValidator
from eduagent_kg.validation.review import apply_review_decisions

from eduagent_kg.resolution.cli import _write


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Apply auditable graph review decisions.")
    parser.add_argument("--graph", type=Path, required=True)
    parser.add_argument("--queue", type=Path, required=True)
    parser.add_argument("--decisions", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    graph = CanonicalGraph.model_validate_json(args.graph.read_text(encoding="utf-8"))
    queue = ReviewQueue.model_validate_json(args.queue.read_text(encoding="utf-8"))
    decisions = [
        ReviewDecision.model_validate(item)
        for item in json.loads(args.decisions.read_text(encoding="utf-8"))
    ]
    graph, queue = apply_review_decisions(graph, queue, decisions)
    report = GraphValidator().validate(graph)
    _write(args.output / "canonical-graph.json", graph.model_dump(mode="json"))
    _write(args.output / "review-queue.json", queue.model_dump(mode="json"))
    _write(args.output / "validation-report.json", report.model_dump(mode="json"))
    print(json.dumps({"decisions_applied": len(decisions), "graph_valid": report.is_valid}, indent=2))
    return 0 if report.is_valid else 1


if __name__ == "__main__":
    raise SystemExit(main())
