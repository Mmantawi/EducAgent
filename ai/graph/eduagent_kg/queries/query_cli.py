import argparse

from eduagent_kg.config import Settings
from eduagent_kg.console import configure_utf8_stdout
from eduagent_kg.storage import Neo4jGraphStore

from .neo4j import Neo4jGraphQueryRepository
from .service import GraphQueryService


def main(argv: list[str] | None = None) -> int:
    configure_utf8_stdout()
    parser = argparse.ArgumentParser(description="Query the EduAgent Neo4j graph.")
    subparsers = parser.add_subparsers(dest="command", required=True)
    search = subparsers.add_parser("search")
    search.add_argument("query")
    search.add_argument("--subject")
    search.add_argument("--grade", type=int)
    search.add_argument("--limit", type=int, default=5)
    prerequisites = subparsers.add_parser("prerequisites")
    prerequisites.add_argument("concept_id")
    prerequisites.add_argument("--max-depth", type=int, default=1)
    args = parser.parse_args(argv)
    settings = Settings()
    if not settings.neo4j_password:
        parser.error("EDUAGENT_KG_NEO4J_PASSWORD is required")
    store = Neo4jGraphStore.connect(
        settings.neo4j_uri, settings.neo4j_username, settings.neo4j_password,
        database=settings.neo4j_database,
    )
    try:
        store.verify_connectivity()
        service = GraphQueryService(
            Neo4jGraphQueryRepository(store.driver, database=store.database)
        )
        if args.command == "search":
            result = service.search_concepts(
                args.query, subject=args.subject, grade=args.grade, limit=args.limit
            )
        else:
            if service.get_concept(args.concept_id) is None:
                parser.error(f"Concept not found: {args.concept_id}")
            result = service.get_prerequisites(args.concept_id, max_depth=args.max_depth)
        print(result.model_dump_json(indent=2))
    finally:
        store.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
