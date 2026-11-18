import argparse
from pathlib import Path

from eduagent_kg.console import configure_utf8_stdout
from eduagent_kg.schemas.graph import CanonicalGraph

from .memory import InMemoryGraphRepository
from .service import GraphQueryService
from .tutor_context import build_tutor_graph_context


def main(argv: list[str] | None = None) -> int:
    configure_utf8_stdout()
    parser = argparse.ArgumentParser(description="Run the offline Tutor graph-context fixture demo.")
    parser.add_argument("--graph", type=Path, required=True)
    parser.add_argument("--topic", required=True)
    parser.add_argument("--max-depth", type=int, default=1)
    args = parser.parse_args(argv)
    graph = CanonicalGraph.model_validate_json(args.graph.read_text(encoding="utf-8"))
    repository = InMemoryGraphRepository()
    repository.import_graph(graph)
    context = build_tutor_graph_context(
        GraphQueryService(repository), args.topic,
        max_prerequisite_depth=args.max_depth,
    )
    print(context.model_dump_json(indent=2))
    return 0 if context.found else 1


if __name__ == "__main__":
    raise SystemExit(main())
