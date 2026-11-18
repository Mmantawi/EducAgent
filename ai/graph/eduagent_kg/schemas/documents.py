from pydantic import Field, model_validator

from .common import ContractModel, CurriculumMetadata
from .enums import BlockType


class ParsedBlock(ContractModel):
    block_id: str = Field(min_length=1)
    block_type: BlockType
    text: str = ""
    page_start: int = Field(ge=1)
    page_end: int = Field(ge=1)
    order: int = Field(ge=0)
    bounding_box: tuple[float, float, float, float] | None = None
    heading_level: int | None = Field(default=None, ge=1, le=6)
    asset_path: str | None = None
    structured_content: dict | list | str | None = None
    boundary_uncertain: bool = False

    @model_validator(mode="after")
    def valid_pages(self):
        if self.page_end < self.page_start:
            raise ValueError("page_end must be greater than or equal to page_start")
        return self


class ParsedDocument(CurriculumMetadata):
    contract_version: str = "1.0"
    document_id: str = Field(min_length=1)
    book_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    edition: str | None = None
    source_uri: str = Field(min_length=1)
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    page_count: int = Field(ge=1)
    parser_name: str = Field(min_length=1)
    parser_version: str = Field(min_length=1)
    blocks: list[ParsedBlock] = Field(default_factory=list)


class TextbookSection(CurriculumMetadata):
    contract_version: str = "1.0"
    section_id: str = Field(min_length=1)
    document_id: str = Field(min_length=1)
    book_id: str = Field(min_length=1)
    parent_section_id: str | None = None
    heading: str = Field(min_length=1)
    heading_path: list[str] = Field(min_length=1)
    page_start: int = Field(ge=1)
    page_end: int = Field(ge=1)
    text: str
    block_ids: list[str] = Field(default_factory=list)
    table_block_ids: list[str] = Field(default_factory=list)
    image_block_ids: list[str] = Field(default_factory=list)
    boundary_uncertain: bool = False
    warnings: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def valid_pages(self):
        if self.page_end < self.page_start:
            raise ValueError("page_end must be greater than or equal to page_start")
        return self


class StructuredTextbook(CurriculumMetadata):
    contract_version: str = "1.0"
    document_id: str = Field(min_length=1)
    book_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    edition: str | None = None
    source_uri: str = Field(min_length=1)
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    sections: list[TextbookSection]

