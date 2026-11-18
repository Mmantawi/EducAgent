import argparse
import json
import logging
import os
from pathlib import Path

from eduagent_kg.config import Settings
from eduagent_kg.schemas.llm import SectionExtractionDraft

from .gemini import GeminiExtractionProvider
from .mock import MockExtractionProvider
from .runner import ExtractionRunner


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Extract validated graph fragments from Phase 2 sections.")
    parser.add_argument("textbook", type=Path, help="Phase 2 sections/textbook.json")
    parser.add_argument("--output", type=Path, default=Path("data/extractions"))
    parser.add_argument("--provider", choices=("gemini", "mock"), default="gemini")
    parser.add_argument("--mock-responses", type=Path, help="Section-to-draft JSON used only by mock provider")
    parser.add_argument("--model")
    parser.add_argument("--max-sections", type=int)
    parser.add_argument("--section-id", action="append", dest="section_ids")
    parser.add_argument("--max-concurrency", type=int)
    parser.add_argument("--rate-limit", type=int)
    parser.add_argument("--max-retries", type=int)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--live", action="store_true", help="Required acknowledgment for a live Gemini call")
    parser.add_argument("--verbose", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO)
    settings = Settings()
    if args.provider == "mock":
        if not args.mock_responses:
            parser.error("--mock-responses is required with --provider mock")
        payload = json.loads(args.mock_responses.read_text(encoding="utf-8"))
        responses = {
            section_id: [SectionExtractionDraft.model_validate(draft)]
            for section_id, draft in payload.items()
        }
        provider = MockExtractionProvider(responses)
    else:
        live_enabled = os.getenv("EDUAGENT_KG_ENABLE_LIVE_GEMINI", "").casefold() == "true"
        if not args.live or not live_enabled:
            logging.error(
                "Live Gemini extraction requires both --live and EDUAGENT_KG_ENABLE_LIVE_GEMINI=true"
            )
            return 2
        if not settings.gemini_api_key:
            logging.error("EDUAGENT_KG_GEMINI_API_KEY is not configured")
            return 2
        provider = GeminiExtractionProvider(
            api_key=settings.gemini_api_key, model=args.model or settings.gemini_model
        )
    runner = ExtractionRunner(
        provider, args.output,
        max_concurrency=args.max_concurrency or settings.extraction_max_concurrency,
        rate_limit_per_minute=args.rate_limit or settings.extraction_rate_limit_per_minute,
        max_retries=(args.max_retries if args.max_retries is not None else settings.extraction_max_retries),
    )
    report = runner.run(
        args.textbook, max_sections=args.max_sections,
        section_ids=set(args.section_ids) if args.section_ids else None, force=args.force,
    )
    print(report.model_dump_json(indent=2))
    return 1 if report.failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
