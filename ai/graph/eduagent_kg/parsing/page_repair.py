"""Plan source-page repairs for suspicious MinerU reconstructions.

This module never claims that OCR was repaired. It renders the original PDF
pages and records why they need a replaceable vision/OCR provider. A provider
can later return corrected ParsedBlock objects for only those pages.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from eduagent_kg.schemas.documents import ParsedBlock, ParsedDocument


@dataclass(frozen=True)
class SuspiciousPage:
    page: int
    block_ids: tuple[str, ...]
    reasons: tuple[str, ...]


def detect_suspicious_pages(document: ParsedDocument, *, operator_threshold: int = 20) -> list[SuspiciousPage]:
    """Find pages whose parsed text is likely to have lost visual layout."""
    by_page: dict[int, list[ParsedBlock]] = {}
    for block in document.blocks:
        by_page.setdefault(block.page_start, []).append(block)

    suspicious: list[SuspiciousPage] = []
    operator_re = re.compile(r"\\(?:times|div|cdot)")
    for page, blocks in sorted(by_page.items()):
        text = "\n".join(block.text for block in blocks)
        reasons: list[str] = []
        operator_count = len(operator_re.findall(text))
        if operator_count >= operator_threshold:
            reasons.append(f"operator_density:{operator_count}")
        if re.search(r"\\boxed\s*\{[^}]{24,}", text):
            reasons.append("malformed_box_expression")
        if re.search(r"(?:\\times\s+[^\s]+)(?:\s+\\times\s+[^\s]+){3,}", text) or re.search(r"(?:\\times\s+){4,}", text):
            reasons.append("repeated_operator_run")
        if reasons:
            suspicious.append(SuspiciousPage(page, tuple(block.block_id for block in blocks), tuple(reasons)))
    return suspicious


def render_source_pages(pdf_path: Path, pages: list[int], output_dir: Path, *, dpi: int = 180) -> list[Path]:
    """Render selected original PDF pages with Poppler's pdftoppm command."""
    executable = shutil.which("pdftoppm")
    if not executable:
        raise RuntimeError("pdftoppm is required to render source pages for repair")
    output_dir.mkdir(parents=True, exist_ok=True)
    rendered: list[Path] = []
    for page in sorted(set(pages)):
        prefix = output_dir / f"page-{page:04d}"
        output = prefix.with_suffix(".png")
        if not output.is_file():
            result = subprocess.run(
                [executable, "-f", str(page), "-l", str(page), "-singlefile", "-png", "-r", str(dpi), str(pdf_path), str(prefix)],
                capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120,
            )
            if result.returncode != 0 or not output.is_file():
                raise RuntimeError(f"Could not render PDF page {page}: {result.stderr.strip()}")
        rendered.append(output)
    return rendered


def write_repair_manifest(
    pdf_path: Path,
    document: ParsedDocument,
    output_dir: Path,
    *,
    operator_threshold: int = 20,
) -> Path:
    """Render suspicious pages and write an explicit pending-repair manifest."""
    issues = detect_suspicious_pages(document, operator_threshold=operator_threshold)
    pages_dir = output_dir / "source_pages"
    rendered = render_source_pages(pdf_path, [item.page for item in issues], pages_dir) if issues else []
    rendered_by_page = {int(path.stem.split("-")[-1]): str(path) for path in rendered}
    payload = {
        "contract_version": "1.0",
        "status": "needs_ocr_repair" if issues else "no_suspicious_pages",
        "source_pdf": str(pdf_path),
        "source_pdf_sha256": _sha256(pdf_path),
        "page_images": rendered_by_page,
        "pages": [
            {"page": item.page, "block_ids": list(item.block_ids), "reasons": list(item.reasons)}
            for item in issues
        ],
        "repair_provider": None,
        "note": "No corrected blocks were generated; a replaceable vision/OCR provider must review these pages.",
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = output_dir / "repair-manifest.json"
    manifest_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return manifest_path


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
