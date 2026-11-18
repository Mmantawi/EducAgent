import hashlib
import json
import logging
import os
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

from eduagent_kg.parsing.base import DocumentParser, ParserError
from eduagent_kg.parsing.splitter import HierarchicalSectionSplitter
from eduagent_kg.schemas.documents import ParsedDocument, StructuredTextbook
from eduagent_kg.schemas.enums import IngestionStatus
from eduagent_kg.schemas.ingestion import IngestionManifest

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class IngestionResult:
    manifest: IngestionManifest
    parsed_document: ParsedDocument | None
    structured_textbook: StructuredTextbook | None
    reused: bool


class IngestionService:
    def __init__(self, parser: DocumentParser, output_root: Path) -> None:
        self.parser = parser
        self.output_root = output_root
        self.splitter = HierarchicalSectionSplitter()

    def ingest(
        self, pdf_path: Path, *, document_id: str, book_id: str, title: str, grade: int,
        subject: str, original_language: str, edition: str | None = None, force: bool = False,
    ) -> IngestionResult:
        pdf_path = pdf_path.resolve()
        if not pdf_path.is_file():
            raise FileNotFoundError(f"Textbook PDF does not exist: {pdf_path}")
        if pdf_path.suffix.casefold() != ".pdf":
            raise ValueError(f"Expected a .pdf textbook, received: {pdf_path.name}")
        content_hash = _sha256(pdf_path)
        document_dir = self.output_root.resolve() / _safe_component(document_id)
        parsed_dir = document_dir / "parsed"
        sections_dir = document_dir / "sections"
        artifacts_dir = document_dir / "parser_artifacts"
        manifest_path = document_dir / "manifest.json"
        parsed_path = parsed_dir / "document.json"
        sections_path = sections_dir / "textbook.json"

        existing = None
        if manifest_path.is_file():
            existing = IngestionManifest.model_validate_json(manifest_path.read_text(encoding="utf-8"))
        if not force and existing and parsed_path.is_file() and sections_path.is_file():
            if existing.content_hash == content_hash and existing.status == IngestionStatus.SUCCEEDED:
                LOGGER.info("Reusing unchanged ingestion for %s", document_id)
                return IngestionResult(
                    existing,
                    ParsedDocument.model_validate_json(parsed_path.read_text(encoding="utf-8")),
                    StructuredTextbook.model_validate_json(sections_path.read_text(encoding="utf-8")),
                    True,
                )

        document_dir.mkdir(parents=True, exist_ok=True)
        ingestion_id = f"ingestion:{uuid5(NAMESPACE_URL, document_id + '|' + content_hash)}"
        manifest = IngestionManifest(
            ingestion_id=ingestion_id, document_id=document_id, book_id=book_id,
            source_uri=str(pdf_path), content_hash=content_hash, grade=grade, subject=subject,
            original_language=original_language, status=IngestionStatus.PROCESSING,
            parser_name=self.parser.name,
            parsed_document_path=str(parsed_path), sections_path=str(sections_path),
            parser_artifact_path=str(artifacts_dir),
        )
        _write_model(manifest_path, manifest)
        try:
            parsed = self.parser.parse(
                pdf_path, document_id=document_id, book_id=book_id, title=title, grade=grade,
                subject=subject, original_language=original_language, edition=edition,
                content_hash=content_hash, artifact_dir=artifacts_dir,
                reuse_artifact=(
                    not force and existing is not None
                    and existing.content_hash == content_hash
                    and (artifacts_dir / "middle.json").is_file()
                ),
            )
            sections = self.splitter.split(parsed)
            warnings = [warning for section in sections for warning in section.warnings]
            textbook = StructuredTextbook(
                document_id=document_id, book_id=book_id, title=title, grade=grade,
                subject=subject, original_language=original_language, edition=edition,
                source_uri=str(pdf_path), content_hash=content_hash, sections=sections,
            )
            _write_model(parsed_path, parsed)
            _write_model(sections_path, textbook)
            manifest = manifest.model_copy(update={
                "status": IngestionStatus.SUCCEEDED,
                "completed_at": datetime.now(timezone.utc),
                "parser_version": parsed.parser_version,
                "section_ids": [section.section_id for section in sections],
                "warnings": warnings,
            })
            _write_model(manifest_path, manifest)
            return IngestionResult(manifest, parsed, textbook, False)
        except Exception as exc:
            LOGGER.exception("Ingestion failed for %s", pdf_path)
            manifest = manifest.model_copy(update={
                "status": IngestionStatus.FAILED,
                "completed_at": datetime.now(timezone.utc),
                "error_message": str(exc),
            })
            _write_model(manifest_path, manifest)
            if isinstance(exc, (ParserError, ValueError)):
                raise
            raise ParserError(f"Ingestion failed: {exc}") from exc


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_component(value: str) -> str:
    safe = "".join(char if char.isalnum() or char in "-_." else "_" for char in value)
    if not safe or safe in {".", ".."}:
        raise ValueError("document_id cannot be converted to a safe output directory")
    return safe


def _write_model(path: Path, model) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    content = model.model_dump_json(indent=2) + "\n"
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent, text=True)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except Exception:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise
