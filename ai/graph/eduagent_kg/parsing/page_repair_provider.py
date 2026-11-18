"""Replaceable page-image repair providers.

The repair contract is intentionally narrower than general OCR: the provider
must correct the text of the existing MinerU blocks for a flagged page. It may
not invent block IDs or silently change page ownership. This keeps section IDs
and source references stable while making the repair auditable.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path

from pydantic import Field

from eduagent_kg.schemas.common import ContractModel
from eduagent_kg.schemas.documents import ParsedBlock, ParsedDocument

from .page_repair import SuspiciousPage


class PageRepairBlock(ContractModel):
    """One corrected text value mapped to an existing parsed block."""

    block_id: str = Field(min_length=1)
    text: str


class PageRepairDraft(ContractModel):
    """Structured response expected from a page-image repair provider."""

    page: int = Field(ge=1)
    blocks: list[PageRepairBlock] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


@dataclass(frozen=True)
class PageRepairResult:
    page: int
    blocks: tuple[PageRepairBlock, ...]
    raw_text: str
    provider: str
    model: str
    notes: tuple[str, ...] = ()


class PageRepairProvider(ABC):
    @property
    @abstractmethod
    def provider_name(self) -> str: ...

    @property
    @abstractmethod
    def model_name(self) -> str: ...

    @abstractmethod
    def repair(
        self, page_image: Path, *, page: int, blocks: list[ParsedBlock]
    ) -> PageRepairResult: ...


class MockPageRepairProvider(PageRepairProvider):
    """Deterministic provider used by unit tests and local dry runs."""

    def __init__(self, replacements: dict[int, dict[str, str]]) -> None:
        self._replacements = replacements

    @property
    def provider_name(self) -> str:
        return "mock-page-repair"

    @property
    def model_name(self) -> str:
        return "fixture"

    def repair(self, page_image: Path, *, page: int, blocks: list[ParsedBlock]) -> PageRepairResult:
        del page_image
        replacements = self._replacements.get(page, {})
        corrected = tuple(
            PageRepairBlock(block_id=block.block_id, text=replacements.get(block.block_id, block.text))
            for block in blocks
        )
        return PageRepairResult(page, corrected, "", self.provider_name, self.model_name)


class GeminiPageRepairProvider(PageRepairProvider):
    """Gemini vision provider using Pydantic structured output.

    This provider is optional and never runs during ordinary tests. It sends a
    rendered source-page image plus the existing block map, then validates the
    model response before any document is changed.
    """

    def __init__(self, *, api_key: str, model: str = "gemini-2.5-flash") -> None:
        if not api_key:
            raise ValueError("Gemini API key is required")
        try:
            from google import genai
            from google.genai import types
        except ImportError as exc:
            raise RuntimeError(
                "Google GenAI SDK is not installed; install the `gemini` project extra"
            ) from exc
        self._client = genai.Client(api_key=api_key)
        self._types = types
        self._model = model

    @property
    def provider_name(self) -> str:
        return "google-genai-vision"

    @property
    def model_name(self) -> str:
        return self._model

    def repair(self, page_image: Path, *, page: int, blocks: list[ParsedBlock]) -> PageRepairResult:
        block_map = "\n".join(f"- {block.block_id}: {block.text!r}" for block in blocks)
        prompt = (
            "You are correcting a textbook page reconstructed incorrectly by a PDF parser. "
            "Read only the visible page image. Return the exact visible text for each existing "
            "block ID below, preserving Arabic, English, numbers, symbols, exercise numbering, "
            "and blanks. Do not invent text. Do not create IDs. If a block is visually blank, "
            "return an empty string. The response must contain exactly these block IDs.\n\n"
            f"Page: {page}\nExisting blocks:\n{block_map}"
        )
        try:
            response = self._client.models.generate_content(
                model=self._model,
                contents=[
                    self._types.Part.from_bytes(
                        data=page_image.read_bytes(), mime_type="image/png"
                    ),
                    prompt,
                ],
                config=self._types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_json_schema=PageRepairDraft.model_json_schema(),
                    temperature=0,
                ),
            )
        except Exception as exc:
            raise RuntimeError(f"Gemini page repair request failed: {exc}") from exc
        parsed = getattr(response, "parsed", None)
        raw_text = getattr(response, "text", None) or ""
        if parsed is None:
            raise RuntimeError("Gemini page repair returned no structured output")
        draft = parsed if isinstance(parsed, PageRepairDraft) else PageRepairDraft.model_validate(parsed)
        if draft.page != page:
            raise ValueError(f"Gemini returned page {draft.page}, expected {page}")
        return PageRepairResult(
            page=page,
            blocks=tuple(draft.blocks),
            raw_text=raw_text,
            provider=self.provider_name,
            model=self.model_name,
            notes=tuple(draft.notes),
        )


def apply_page_repairs(
    document: ParsedDocument,
    suspicious_pages: list[SuspiciousPage],
    results: list[PageRepairResult],
) -> ParsedDocument:
    """Validate and apply corrections while preserving existing block IDs."""
    expected_pages = {item.page: item for item in suspicious_pages}
    result_by_page = {result.page: result for result in results}
    if set(result_by_page) != set(expected_pages):
        raise ValueError("A repair result is required for every suspicious page")

    by_id = {block.block_id: block for block in document.blocks}
    replacements: dict[str, str] = {}
    for page, result in result_by_page.items():
        expected_ids = set(expected_pages[page].block_ids)
        seen: set[str] = set()
        for corrected in result.blocks:
            if corrected.block_id not in expected_ids or corrected.block_id not in by_id:
                raise ValueError(f"Repair returned unknown block ID: {corrected.block_id}")
            if by_id[corrected.block_id].page_start != page:
                raise ValueError(f"Repair block {corrected.block_id} is not on page {page}")
            if corrected.block_id in seen:
                raise ValueError(f"Repair returned duplicate block ID: {corrected.block_id}")
            seen.add(corrected.block_id)
            replacements[corrected.block_id] = corrected.text
        if seen != expected_ids:
            raise ValueError(f"Repair page {page} did not return exactly the existing block IDs")

    repaired_blocks = [
        block.model_copy(update={"text": replacements[block.block_id]})
        if block.block_id in replacements else block
        for block in document.blocks
    ]
    return document.model_copy(update={"blocks": repaired_blocks})
