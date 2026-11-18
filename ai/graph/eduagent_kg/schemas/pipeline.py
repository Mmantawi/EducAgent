from datetime import datetime, timezone
from enum import StrEnum

from pydantic import Field

from .common import ContractModel, CurriculumMetadata


class StageStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    PARTIAL = "partial"
    FAILED = "failed"
    SKIPPED = "skipped"
    AWAITING_REVIEW = "awaiting_review"


class PipelineBookInput(CurriculumMetadata):
    pdf_path: str
    document_id: str
    book_id: str
    title: str
    edition: str | None = None
    section_ids: list[str] | None = None


class StageRecord(ContractModel):
    stage: str
    status: StageStatus = StageStatus.PENDING
    started_at: datetime | None = None
    completed_at: datetime | None = None
    artifacts: list[str] = Field(default_factory=list)
    message: str | None = None
    attempts: int = Field(default=0, ge=0)


class PipelineRunManifest(ContractModel):
    run_id: str
    status: StageStatus = StageStatus.PENDING
    inputs: list[PipelineBookInput]
    stages: list[StageRecord] = Field(default_factory=list)
    started_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    completed_at: datetime | None = None
