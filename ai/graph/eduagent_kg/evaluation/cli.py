import argparse
from pathlib import Path

from eduagent_kg.console import configure_utf8_stdout
from eduagent_kg.resolution.merger import load_fragments
from eduagent_kg.schemas.evaluation import GoldDataset
from eduagent_kg.schemas.graph import CanonicalGraph

from .evaluator import KnowledgeGraphEvaluator


def main(argv: list[str] | None = None) -> int:
    configure_utf8_stdout()
    parser = argparse.ArgumentParser(description="Evaluate graph artifacts against verified annotations.")
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--fragments", type=Path, required=True)
    parser.add_argument("--graph", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    dataset = GoldDataset.model_validate_json(args.dataset.read_text(encoding="utf-8"))
    graph = CanonicalGraph.model_validate_json(args.graph.read_text(encoding="utf-8"))
    report = KnowledgeGraphEvaluator().evaluate(
        dataset, fragments=load_fragments(args.fragments), graph=graph
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(report.model_dump_json(indent=2) + "\n", encoding="utf-8")
    print(report.model_dump_json(indent=2))
    return 0 if report.metrics_available else 2


if __name__ == "__main__":
    raise SystemExit(main())
