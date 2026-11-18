from datetime import datetime, timezone

from pydantic import Field

from .common import ContractModel, CurriculumMetadata
from .enums import IngestionStatus


class IngestionManifest(CurriculumMetadata):
    ingestion_id: str = Field(min_length=1)
    document_id: str = Field(min_length=1)
    book_id: str = Field(min_length=1)
    source_uri: str = Field(min_length=1)
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    contract_version: str = "1.0"
    status: IngestionStatus = IngestionStatus.PENDING
    started_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    completed_at: datetime | None = None
    parser_name: str | None = None
    parser_version: str | None = None
    section_ids: list[str] = Field(default_factory=list)
    error_message: str | None = None
    parsed_document_path: str | None = None
    sections_path: str | None = None
    parser_artifact_path: str | None = None
    warnings: list[str] = Field(default_factory=list)

