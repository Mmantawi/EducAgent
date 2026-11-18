import argparse
import json
import logging
import os
import tempfile
from collections import Counter
from pathlib import Path

from eduagent_kg.schemas.documents import StructuredTextbook
from eduagent_kg.schemas.enums import ReviewStatus
from eduagent_kg.schemas.review import ReviewItem
from eduagent_kg.validation import GraphValidator

from .merger import HierarchicalGraphMerger, load_fragments


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Resolve and validate Phase 3 graph fragments.")
    parser.add_argument("fragments", type=Path, help="Directory containing GraphFragment JSON files")
    parser.add_argument("--textbook", type=Path, required=True, help="Phase 2 sections/textbook.json")
    parser.add_argument("--output", type=Path, default=Path("data/canonical"))
    parser.add_argument("--fuzzy-threshold", type=float, default=0.88)
    parser.add_argument("--verbose", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO)
    textbook = StructuredTextbook.model_validate_json(args.textbook.read_text(encoding="utf-8"))
    fragments = load_fragments(args.fragments)
    merger = HierarchicalGraphMerger()
    merger.resolver.fuzzy_threshold = args.fuzzy_threshold
    graph, queue, stats = merger.merge(fragments, textbook)
    report = GraphValidator().validate(graph)
    for issue in report.issues:
        queue.items.append(ReviewItem(
            review_id=f"review:validation:{issue.code}:{issue.target_id or 'graph'}",
            category="validation_failure", target_id=issue.target_id or graph.graph_id,
            reason=issue.message, payload=issue.model_dump(mode="json"),
        ))
    stats = stats.model_copy(update={
        "invalid_edges": sum(issue.code in {"missing_endpoint", "invalid_ontology_edge", "self_relation", "duplicate_edge"} for issue in report.issues),
        "detected_cycles": sum(len(cycles) for cycles in report.cycles_by_type.values()),
        "pending_reviews": sum(item.status == ReviewStatus.CANDIDATE for item in queue.items),
        "relationship_counts_by_type": dict(Counter(edge.relationship_type.value for edge in graph.relationships)),
    })
    root = args.output / _safe(textbook.document_id)
    _write(root / "canonical-graph.json", graph.model_dump(mode="json"))
    _write(root / "review-queue.json", queue.model_dump(mode="json"))
    _write(root / "validation-report.json", report.model_dump(mode="json"))
    _write(root / "merge-statistics.json", stats.model_dump(mode="json"))
    print(json.dumps({
        "graph": str(root / "canonical-graph.json"),
        "review_queue": str(root / "review-queue.json"),
        "validation_report": str(root / "validation-report.json"),
        "statistics": stats.model_dump(mode="json"),
    }, ensure_ascii=False, indent=2))
    return 0 if report.is_valid else 1


def _safe(value: str) -> str:
    result = "".join(char if char.isalnum() or char in "-_." else "_" for char in value)
    if not result or result in {".", ".."}:
        raise ValueError("document ID cannot be converted to a safe path")
    return result


def _write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent, text=True)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(payload, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except Exception:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


if __name__ == "__main__":
    raise SystemExit(main())
