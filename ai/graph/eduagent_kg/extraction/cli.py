"""Run concept/skill extraction over a sections JSONL file (no PDF parsing needed).

    python -m eduagent_kg.extraction.cli data/g3t1/sections_v2.jsonl \
        --output data/g3t1/extraction --base-url http://localhost:8080/v1 --model qwen3-14b

Results are cached per section, so an interrupted run resumes where it stopped.
"""

import argparse
import hashlib
import json
import logging
from pathlib import Path

from eduagent_kg.config import Settings
from eduagent_kg.console import configure_utf8_stdout
from eduagent_kg.ontology import KNOWLEDGE_NODE_TYPES
from eduagent_kg.schemas.documents import StructuredTextbook, TextbookSection
from eduagent_kg.schemas.extraction import GraphFragment

from .openai_compatible import OpenAICompatibleExtractionProvider
from .runner import ExtractionRunner


def sections_to_textbook(path: Path) -> StructuredTextbook:
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    fields = set(TextbookSection.model_fields)
    sections = [TextbookSection.model_validate({k: v for k, v in row.items() if k in fields}) for row in rows]
    first = sections[0]
    return StructuredTextbook(
        document_id=first.document_id, book_id=first.book_id, title=first.document_id,
        source_uri=str(path), content_hash=hashlib.sha256(path.read_bytes()).hexdigest(),
        sections=sections, grade=first.grade, subject=first.subject,
        original_language=first.original_language,
    )


def main(argv: list[str] | None = None) -> int:
    configure_utf8_stdout()
    settings = Settings()
    parser = argparse.ArgumentParser(description="Extract concepts and skills from textbook sections.")
    parser.add_argument("sections", type=Path, help="Sections JSONL (one TextbookSection per line)")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--base-url", default=settings.llm_base_url)
    parser.add_argument("--model", default=settings.llm_model)
    parser.add_argument("--max-tokens", type=int, default=settings.llm_max_tokens)
    parser.add_argument("--concurrency", type=int, default=settings.extraction_max_concurrency)
    parser.add_argument("--gleanings", type=int, default=1,
                        help="Extra 'what did you miss?' rounds per section (GraphRAG); 0 disables")
    parser.add_argument("--max-sections", type=int, help="Only the first N sections (for a quick test)")
    parser.add_argument("--no-structured-output", action="store_true",
                        help="For servers without JSON-schema support")
    parser.add_argument("--force", action="store_true", help="Ignore cached results")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    args.output.mkdir(parents=True, exist_ok=True)
    textbook_path = args.output / "textbook.json"
    textbook_path.write_text(sections_to_textbook(args.sections).model_dump_json(indent=2), encoding="utf-8")
    provider = OpenAICompatibleExtractionProvider(
        base_url=args.base_url, model=args.model, api_key=settings.llm_api_key,
        max_tokens=args.max_tokens, structured_output=not args.no_structured_output,
        gleanings=args.gleanings,
    )
    report = ExtractionRunner(
        provider, args.output, max_concurrency=args.concurrency,
        rate_limit_per_minute=0, max_retries=settings.extraction_max_retries,
    ).run(textbook_path, max_sections=args.max_sections, force=args.force)
    (args.output / "extraction-report.json").write_text(report.model_dump_json(indent=2), encoding="utf-8")
    failed = [result for result in report.results if result.status != "succeeded"]
    print(f"{len(report.results) - len(failed)}/{len(report.results)} sections succeeded")
    for result in failed:
        print(f"  FAILED {result.section_id}: {result.error}")
    empty, total_nodes = summarize_fragments(report)
    print(f"{total_nodes} concepts/skills extracted")
    if empty:
        print(f"WARNING: {len(empty)} section(s) produced no concepts or skills:")
        for section_id, reasons in empty:
            print(f"  {section_id}: {'; '.join(reasons[:3]) or 'model returned none'}")
    if failed:
        return 1
    return 2 if report.results and total_nodes == 0 else 0


def summarize_fragments(report) -> tuple[list[tuple[str, list[str]]], int]:
    """Sections whose fragment has no concept/skill (with the drop reasons), and the node total."""
    empty, total = [], 0
    for result in report.results:
        if not result.fragment_path or not Path(result.fragment_path).is_file():
            continue
        fragment = GraphFragment.model_validate_json(Path(result.fragment_path).read_text(encoding="utf-8"))
        count = sum(entity.node_type in KNOWLEDGE_NODE_TYPES for entity in fragment.entities)
        total += count
        if count == 0:
            empty.append((result.section_id, fragment.warnings))
    return empty, total


if __name__ == "__main__":
    raise SystemExit(main())
