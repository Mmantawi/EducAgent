from abc import ABC, abstractmethod
from pathlib import Path

from eduagent_kg.schemas.documents import ParsedDocument


class ParserError(RuntimeError):
    """A document parser failed with an actionable error."""


class ParserUnavailableError(ParserError):
    """The requested parser runtime is not installed or usable."""


class DocumentParser(ABC):
    @property
    @abstractmethod
    def name(self) -> str: ...

    @property
    @abstractmethod
    def version(self) -> str: ...

    @abstractmethod
    def parse(
        self,
        pdf_path: Path,
        *,
        document_id: str,
        book_id: str,
        title: str,
        grade: int,
        subject: str,
        original_language: str,
        edition: str | None,
        content_hash: str,
        artifact_dir: Path,
        reuse_artifact: bool = False,
    ) -> ParsedDocument: ...
