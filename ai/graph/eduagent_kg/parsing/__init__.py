"""Replaceable PDF parsing and section splitting boundary."""

from .base import DocumentParser, ParserError, ParserUnavailableError
from .fixture import FixtureParser
from .mineru import MinerUParser
from .page_repair import SuspiciousPage, detect_suspicious_pages, render_source_pages, write_repair_manifest
from .page_repair_provider import (
    GeminiPageRepairProvider,
    MockPageRepairProvider,
    PageRepairBlock,
    PageRepairDraft,
    PageRepairProvider,
    PageRepairResult,
    apply_page_repairs,
)

__all__ = [
    "DocumentParser", "ParserError", "ParserUnavailableError", "FixtureParser", "MinerUParser",
    "SuspiciousPage", "detect_suspicious_pages", "render_source_pages", "write_repair_manifest",
    "PageRepairBlock", "PageRepairDraft", "PageRepairProvider", "PageRepairResult",
    "MockPageRepairProvider", "GeminiPageRepairProvider", "apply_page_repairs",
]
