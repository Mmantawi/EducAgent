"""Load a canonical graph JSON into Neo4j (connection settings come from .env / EDUAGENT_KG_*).

    python -m eduagent_kg.storage.import_cli data/g3t1/kaggle_step4/canonical-graph.final.json
    python -m eduagent_kg.storage.import_cli <graph.json> --include-unreviewed   # preview only

By default only approved relationships are written. --include-unreviewed writes every
relationship with its review_status so the graph can be explored before review; queries the
tutor relies on must then filter ``WHERE r.review_status = 'approved'``.
"""

import argparse
from pathlib import Path

from eduagent_kg.config import Settings
from eduagent_kg.console import configure_utf8_stdout
from eduagent_kg.schemas.graph import CanonicalGraph

from .neo4j import Neo4jGraphStore


def main(argv: list[str] | None = None) -> int:
    configure_utf8_stdout()
    parser = argparse.ArgumentParser(description="Import a canonical graph into Neo4j.")
    parser.add_argument("graph", type=Path)
    parser.add_argument("--include-unreviewed", action="store_true",
                        help="Preview: also write unreviewed and candidate relationships")
    args = parser.parse_args(argv)
    settings = Settings()
    if not settings.neo4j_password:
        parser.error("Set EDUAGENT_KG_NEO4J_PASSWORD in .env")
    graph = CanonicalGraph.model_validate_json(args.graph.read_text(encoding="utf-8"))
    store = Neo4jGraphStore.connect(settings.neo4j_uri, settings.neo4j_username, settings.neo4j_password,
                                    database=settings.neo4j_database)
    try:
        store.verify_connectivity()
        store.initialize_schema()
        stats = store.import_graph(graph, include_unreviewed=args.include_unreviewed)
    finally:
        store.close()
    mode = "preview (all relationships)" if args.include_unreviewed else "approved relationships only"
    print(f"Imported {stats.nodes_submitted} nodes into {settings.neo4j_uri} [{mode}]; "
          f"{stats.approved_relationships_submitted} approved relationships, "
          f"{stats.relationships_excluded} not imported")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
