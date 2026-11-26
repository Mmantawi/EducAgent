"""Re-split an already-exported section file (JSONL) with the current splitter.

Use this when the original MinerU output is no longer available: the exported
sections are concatenated back into a line-level block stream and split again.
Each line keeps the page range of the section it came from, so page ranges of
the new sections can be slightly wider than the true ones.

    python -m eduagent_kg.parsing.resplit INPUT.jsonl OUTPUT.jsonl
"""

import argparse
import hashlib
import json
from pathlib import Path

from eduagent_kg.console import configure_utf8_stdout
from eduagent_kg.schemas.documents import ParsedBlock, ParsedDocument
from eduagent_kg.schemas.enums import BlockType

from .splitter import HierarchicalSectionSplitter


def rows_to_document(rows: list[dict]) -> ParsedDocument:
    blocks: list[ParsedBlock] = []
    for row in rows:
        for line in row["text"].split("\n"):
            blocks.append(ParsedBlock(
                block_id=f"blk:{len(blocks):05d}", block_type=BlockType.PARAGRAPH, text=line,
                page_start=row["page_start"], page_end=row["page_end"], order=len(blocks),
            ))
    first = rows[0]
    digest = hashlib.sha256("\n".join(b.text for b in blocks).encode("utf-8")).hexdigest()
    return ParsedDocument(
        document_id=first["document_id"], book_id=first["book_id"], title=first["document_id"],
        source_uri="resplit", content_hash=digest,
        page_count=max(row["page_end"] for row in rows),
        parser_name="resplit", parser_version="1.0", blocks=blocks,
        grade=first.get("grade"), subject=first.get("subject"),
        original_language=first.get("original_language"),
    )


def main(argv: list[str] | None = None) -> int:
    configure_utf8_stdout()
    parser = argparse.ArgumentParser(description="Re-split exported textbook sections.")
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args(argv)
    rows = [json.loads(line) for line in args.input.read_text(encoding="utf-8").splitlines() if line.strip()]
    sections = HierarchicalSectionSplitter().split(rows_to_document(rows))
    keep = ("section_id", "document_id", "book_id", "heading", "heading_path", "text",
            "page_start", "page_end", "original_language", "grade", "subject")
    with args.output.open("w", encoding="utf-8", newline="\n") as stream:
        for section in sections:
            row = {key: getattr(section, key) for key in keep}
            row["term"] = rows[0].get("term")
            stream.write(json.dumps(row, ensure_ascii=False) + "\n")
    print(f"{len(rows)} input sections -> {len(sections)} sections written to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
