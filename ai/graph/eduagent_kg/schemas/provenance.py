from datetime import datetime, timezone

from pydantic import Field, model_validator

from .common import ContractModel, CurriculumMetadata
from .enums import ClaimDisposition, ExtractionMethod, ReviewStatus


class SourceReference(ContractModel):
    source_ref_id: str = Field(min_length=1)
    book_id: str = Field(min_length=1)
    document_id: str = Field(min_length=1)
    section_id: str = Field(min_length=1)
    page_start: int = Field(ge=1)
    page_end: int = Field(ge=1)
    evidence_text: str | None = None
    block_ids: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def valid_page_range(self):
        if self.page_end < self.page_start:
            raise ValueError("page_end must be greater than or equal to page_start")
        return self


class ExtractionMetadata(CurriculumMetadata):
    extraction_method: ExtractionMethod
    disposition: ClaimDisposition = ClaimDisposition.EXTRACTED
    review_status: ReviewStatus = ReviewStatus.UNREVIEWED
    extractor_name: str = Field(min_length=1)
    extractor_version: str = Field(min_length=1)
    model_name: str | None = None
    prompt_version: str | None = None
    extracted_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    confidence: float | None = Field(default=None, ge=0, le=1)

