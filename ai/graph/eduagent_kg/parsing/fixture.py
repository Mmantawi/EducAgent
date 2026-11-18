import json
from pathlib import Path

from eduagent_kg.schemas.documents import ParsedDocument

from .base import DocumentParser, ParserError


class FixtureParser(DocumentParser):
    """Explicit deterministic adapter for checked-in parser fixtures and tests."""

    def __init__(self, fixture_path: Path) -> None:
        self.fixture_path = fixture_path

    @property
    def name(self) -> str:
        return "fixture"

    @property
    def version(self) -> str:
        return "1.0"

    def parse(
        self, pdf_path: Path, *, artifact_dir: Path, reuse_artifact: bool = False, **metadata
    ) -> ParsedDocument:
        try:
            payload = json.loads(self.fixture_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ParserError(f"Cannot read parser fixture {self.fixture_path}: {exc}") from exc
        artifact_dir.mkdir(parents=True, exist_ok=True)
        artifact = artifact_dir / "fixture-parser-output.json"
        artifact.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        payload.update(
            metadata,
            source_uri=str(pdf_path),
            parser_name=self.name,
            parser_version=self.version,
        )
        try:
            return ParsedDocument.model_validate(payload)
        except Exception as exc:
            raise ParserError(f"Parser fixture does not satisfy ParsedDocument: {exc}") from exc
