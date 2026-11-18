import argparse
import json
import logging
import os
from pathlib import Path

from eduagent_kg.config import Settings
from eduagent_kg.console import configure_utf8_stdout
from eduagent_kg.extraction import GeminiExtractionProvider, MockExtractionProvider
from eduagent_kg.parsing import FixtureParser, MinerUParser
from eduagent_kg.schemas.llm import SectionExtractionDraft
from eduagent_kg.schemas.pipeline import PipelineBookInput, StageStatus
from eduagent_kg.schemas.review import ReviewDecision
from eduagent_kg.storage import Neo4jGraphStore

from .orchestrator import PipelineOrchestrator


def main(argv: list[str] | None = None) -> int:
    configure_utf8_stdout()
    parser = argparse.ArgumentParser(description="Run the resumable EduAgent KG pipeline.")
    parser.add_argument("--books", type=Path, required=True, help="JSON array of PipelineBookInput")
    parser.add_argument("--output", type=Path, default=Path("data/pipeline"))
    parser.add_argument("--parser", choices=("mineru", "fixture"), default="mineru")
    parser.add_argument("--parser-fixture", type=Path)
    parser.add_argument("--provider", choices=("gemini", "mock"), default="gemini")
    parser.add_argument("--mock-responses", type=Path)
    parser.add_argument("--decisions", type=Path)
    parser.add_argument("--rerun-stage", action="append", default=[])
    parser.add_argument("--import-approved", action="store_true")
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO)
    settings = Settings()
    inputs = [
        PipelineBookInput.model_validate(item)
        for item in json.loads(args.books.read_text(encoding="utf-8"))
    ]
    if args.parser == "fixture":
        if not args.parser_fixture:
            parser.error("--parser-fixture is required with the fixture parser")
        parser_factory = lambda _: FixtureParser(args.parser_fixture)
    else:
        parser_factory = lambda _: MinerUParser()

    if args.provider == "mock":
        if not args.mock_responses:
            parser.error("--mock-responses is required with the mock provider")
        response_payload = json.loads(args.mock_responses.read_text(encoding="utf-8"))

        def provider_factory(_):
            return MockExtractionProvider({
                section_id: [SectionExtractionDraft.model_validate(draft)]
                for section_id, draft in response_payload.items()
            })
    else:
        live_enabled = os.getenv("EDUAGENT_KG_ENABLE_LIVE_GEMINI", "").casefold() == "true"
        if not args.live or not live_enabled or not settings.gemini_api_key:
            parser.error(
                "Gemini requires --live, EDUAGENT_KG_ENABLE_LIVE_GEMINI=true, and API credentials"
            )
        provider_factory = lambda _: GeminiExtractionProvider(
            api_key=settings.gemini_api_key, model=settings.gemini_model
        )

    decisions = None
    if args.decisions:
        decisions = [
            ReviewDecision.model_validate(item)
            for item in json.loads(args.decisions.read_text(encoding="utf-8"))
        ]
    store = None
    if args.import_approved:
        if not settings.neo4j_password:
            parser.error("Neo4j password is required with --import-approved")
        store = Neo4jGraphStore.connect(
            settings.neo4j_uri, settings.neo4j_username, settings.neo4j_password,
            database=settings.neo4j_database,
        )
        store.verify_connectivity()
        store.initialize_schema()
    try:
        manifest = PipelineOrchestrator(
            parser_factory=parser_factory, provider_factory=provider_factory,
            output_root=args.output, graph_store=store,
            max_concurrency=settings.extraction_max_concurrency,
            rate_limit_per_minute=settings.extraction_rate_limit_per_minute,
            max_retries=settings.extraction_max_retries,
        ).run(
            inputs, decisions=decisions, auto_import=args.import_approved,
            rerun_stages=set(args.rerun_stage),
        )
        print(manifest.model_dump_json(indent=2))
    finally:
        if store:
            store.close()
    if manifest.status == StageStatus.SUCCEEDED:
        return 0
    if manifest.status == StageStatus.AWAITING_REVIEW:
        return 2
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
