from datetime import datetime, timezone

from pydantic import Field

from .common import ContractModel


class SectionExtractionResult(ContractModel):
    section_id: str
    status: str
    attempts: int = Field(ge=0)
    cached: bool = False
    fragment_path: str | None = None
    raw_response_path: str | None = None
    error_path: str | None = None
    error: str | None = None


class ExtractionRunReport(ContractModel):
    document_id: str
    provider: str
    model: str
    started_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    completed_at: datetime | None = None
    results: list[SectionExtractionResult] = Field(default_factory=list)

    @property
    def succeeded(self) -> int:
        return sum(item.status == "succeeded" for item in self.results)

    @property
    def failed(self) -> int:
        return sum(item.status == "failed" for item in self.results)
