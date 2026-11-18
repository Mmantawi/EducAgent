import argparse
import logging
from pathlib import Path

from eduagent_kg.ingestion import IngestionService
from eduagent_kg.parsing import FixtureParser, MinerUParser, ParserError


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Parse an educational PDF into EduAgent artifacts.")
    parser.add_argument("pdf", type=Path)
    parser.add_argument("--document-id", required=True)
    parser.add_argument("--book-id", required=True)
    parser.add_argument("--title", required=True)
    parser.add_argument("--grade", required=True, type=int)
    parser.add_argument("--subject", required=True)
    parser.add_argument("--language", required=True, dest="original_language")
    parser.add_argument("--edition")
    parser.add_argument("--output", type=Path, default=Path("data/ingestions"))
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--parser", choices=("mineru", "fixture"), default="mineru")
    parser.add_argument("--fixture", type=Path, help="Required only with --parser fixture")
    parser.add_argument("--verbose", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO)
    if args.parser == "fixture":
        if args.fixture is None:
            build_parser().error("--fixture is required when --parser fixture is selected")
        adapter = FixtureParser(args.fixture)
    else:
        adapter = MinerUParser()
    try:
        result = IngestionService(adapter, args.output).ingest(
            args.pdf, document_id=args.document_id, book_id=args.book_id, title=args.title,
            grade=args.grade, subject=args.subject, original_language=args.original_language,
            edition=args.edition, force=args.force,
        )
    except (OSError, ValueError, ParserError) as exc:
        logging.error("%s", exc)
        return 2
    action = "reused" if result.reused else "created"
    print(f"Ingestion {action}: {result.manifest.model_dump_json(indent=2)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
