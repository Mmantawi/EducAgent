import argparse
from pathlib import Path

from eduagent_kg.config import Settings
from eduagent_kg.schemas.graph import CanonicalGraph

from .neo4j import Neo4jGraphStore


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Import an approved canonical graph into Neo4j.")
    parser.add_argument("graph", type=Path)
    parser.add_argument("--skip-schema", action="store_true")
    args = parser.parse_args(argv)
    settings = Settings()
    if not settings.neo4j_password:
        parser.error("EDUAGENT_KG_NEO4J_PASSWORD is required")
    graph = CanonicalGraph.model_validate_json(args.graph.read_text(encoding="utf-8"))
    store = Neo4jGraphStore.connect(
        settings.neo4j_uri, settings.neo4j_username, settings.neo4j_password,
        database=settings.neo4j_database,
    )
    try:
        store.verify_connectivity()
        if not args.skip_schema:
            store.initialize_schema()
        stats = store.import_graph(graph)
        print(stats.model_dump_json(indent=2))
    finally:
        store.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
