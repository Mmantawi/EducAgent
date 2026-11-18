import json
import shutil
import subprocess
from pathlib import Path

from eduagent_kg.schemas.documents import ParsedBlock, ParsedDocument
from eduagent_kg.schemas.enums import BlockType

from .base import DocumentParser, ParserError, ParserUnavailableError


TYPE_MAP = {
    "text": BlockType.PARAGRAPH,
    "paragraph": BlockType.PARAGRAPH,
    "title": BlockType.HEADING,
    "heading": BlockType.HEADING,
    "table": BlockType.TABLE,
    "image": BlockType.IMAGE,
    "equation": BlockType.EQUATION,
    "interline_equation": BlockType.EQUATION,
    "list": BlockType.LIST,
    "doc_title": BlockType.HEADING,
    "paragraph_title": BlockType.HEADING,
    "index": BlockType.LIST,
    "aside_text": BlockType.PARAGRAPH,
    "header": BlockType.PARAGRAPH,
    "footer": BlockType.PARAGRAPH,
    "page_number": BlockType.PARAGRAPH,
    "chart": BlockType.IMAGE,
}


class MinerUParser(DocumentParser):
    """Adapter for the official stateless MinerU CLI structured output."""

    def __init__(self, executable: str = "mineru-kit", *, tier: str = "basic") -> None:
        if tier not in {"flash", "basic", "standard", "advanced"}:
            raise ValueError(f"Unsupported MinerU tier: {tier}")
        self.executable = executable
        self.tier = tier
        self._path = shutil.which(executable)
        self._version: str | None = None

    @property
    def name(self) -> str:
        return "mineru-kit"

    @property
    def version(self) -> str:
        self._ensure_available()
        if self._version is None:
            result = subprocess.run(
                [self._path, "--version"], capture_output=True, text=True,
                encoding="utf-8", errors="replace", timeout=30
            )
            self._version = (result.stdout or result.stderr).strip() or "unknown"
        return self._version

    def _ensure_available(self) -> None:
        if not self._path:
            raise ParserUnavailableError(
                "MinerU executable 'mineru-kit' is unavailable. Install a compatible "
                "MinerU runtime and verify `mineru-kit parse --help`; no fallback parser was used."
            )

    def _verify_cli_contract(self) -> None:
        self._ensure_available()
        result = subprocess.run(
            [self._path, "parse", "--help"], capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=30
        )
        help_text = result.stdout + result.stderr
        if result.returncode != 0 or "--format" not in help_text or "middle_json" not in help_text:
            raise ParserUnavailableError(
                "Installed MinerU does not advertise `parse --format middle_json`; "
                "refusing to assume an unsupported CLI contract."
            )

    def parse(
        self, pdf_path: Path, *, artifact_dir: Path, reuse_artifact: bool = False, **metadata
    ) -> ParsedDocument:
        artifact_dir.mkdir(parents=True, exist_ok=True)
        output_path = artifact_dir / "middle.json"
        if reuse_artifact and output_path.is_file():
            return self._read_and_convert(output_path, pdf_path=pdf_path, **metadata)
        self._verify_cli_contract()
        result = subprocess.run(
            [
                self._path, "parse", str(pdf_path), "-o", str(output_path),
                "--format", "middle_json", "--tier", self.tier,
            ],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=3600,
        )
        if result.returncode != 0:
            raise ParserError(f"MinerU failed with exit code {result.returncode}: {result.stderr.strip()}")
        if not output_path.is_file():
            raise ParserError(f"MinerU completed without the expected artifact: {output_path}")
        return self._read_and_convert(output_path, pdf_path=pdf_path, **metadata)

    def _read_and_convert(self, output_path: Path, *, pdf_path: Path, **metadata) -> ParsedDocument:
        try:
            payload = json.loads(output_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ParserError(f"Cannot read MinerU middle_json artifact: {exc}") from exc
        return self._convert(payload, pdf_path=pdf_path, **metadata)

    def _convert(self, payload: dict, *, pdf_path: Path, **metadata) -> ParsedDocument:
        pages = payload.get("pdf_info")
        if not isinstance(pages, list) and payload.get("schema") == "docvortex.middle":
            return self._convert_docvortex(payload, pdf_path=pdf_path, **metadata)
        if not isinstance(pages, list):
            raise ParserError(
                "MinerU middle_json is neither legacy `pdf_info` nor "
                "supported `docvortex.middle` output"
            )
        blocks: list[ParsedBlock] = []
        order = 0
        for page_index, page in enumerate(pages, start=1):
            page_no = int(page.get("page_idx", page_index - 1)) + 1
            for raw in page.get("para_blocks", []):
                raw_type = str(raw.get("type", "text")).lower()
                block_type = TYPE_MAP.get(raw_type, BlockType.PARAGRAPH)
                text = _collect_text(raw)
                blocks.append(ParsedBlock(
                    block_id=f"block:p{page_no}:{order}",
                    block_type=block_type,
                    text=text,
                    page_start=page_no,
                    page_end=page_no,
                    order=order,
                    bounding_box=_bbox(raw.get("bbox")),
                    heading_level=int(raw.get("level", 1)) if block_type == BlockType.HEADING else None,
                    asset_path=raw.get("img_path"),
                    structured_content=raw.get("table_body") or raw.get("latex"),
                ))
                order += 1
        if not blocks:
            raise ParserError("MinerU middle_json contained no convertible content blocks")
        return ParsedDocument(
            **metadata,
            source_uri=str(pdf_path),
            page_count=max(block.page_end for block in blocks),
            parser_name=self.name,
            parser_version=self.version,
            blocks=blocks,
        )

    def _convert_docvortex(self, payload: dict, *, pdf_path: Path, **metadata) -> ParsedDocument:
        schema_version = str(payload.get("schema_version", ""))
        if not schema_version.startswith("2."):
            raise ParserError(
                f"Unsupported docvortex.middle schema version: {schema_version or 'missing'}"
            )
        pages = payload.get("pages")
        if not isinstance(pages, list):
            raise ParserError("docvortex.middle output is missing the `pages` list")

        blocks: list[ParsedBlock] = []
        order = 0
        used_ids: set[str] = set()
        for page_position, page in enumerate(pages):
            if not isinstance(page, dict):
                raise ParserError(f"docvortex.middle page {page_position} is not an object")
            page_no = int(page.get("page_idx", page_position)) + 1
            raw_blocks = page.get("blocks", [])
            if not isinstance(raw_blocks, list):
                raise ParserError(f"docvortex.middle page {page_no} has invalid `blocks`")
            for raw_position, raw in enumerate(raw_blocks):
                if not isinstance(raw, dict):
                    continue
                raw_type = str(raw.get("type", "text")).lower()
                block_type = TYPE_MAP.get(raw_type, BlockType.PARAGRAPH)
                raw_index = raw.get("index", raw_position)
                block_id = f"block:p{page_no}:{raw_index}"
                if block_id in used_ids:
                    block_id = f"{block_id}:{raw_position}"
                used_ids.add(block_id)
                text = _collect_text(raw.get("content", ""))
                structured_content = None
                if block_type in {BlockType.TABLE, BlockType.EQUATION}:
                    structured_content = text or None
                blocks.append(ParsedBlock(
                    block_id=block_id,
                    block_type=block_type,
                    text=text,
                    page_start=page_no,
                    page_end=page_no,
                    order=order,
                    bounding_box=_bbox(raw.get("bbox")),
                    heading_level=(
                        max(1, min(6, int(raw.get("level", 1))))
                        if block_type == BlockType.HEADING else None
                    ),
                    asset_path=_find_asset_path(raw),
                    structured_content=structured_content,
                ))
                order += 1

        if not blocks:
            raise ParserError("docvortex.middle output contained no convertible content blocks")
        declared_page_count = (
            payload.get("metadata", {}).get("document", {}).get("page_count")
            if isinstance(payload.get("metadata"), dict) else None
        )
        page_count = int(declared_page_count) if declared_page_count else max(
            block.page_end for block in blocks
        )
        return ParsedDocument(
            **metadata,
            source_uri=str(pdf_path),
            page_count=page_count,
            parser_name=self.name,
            parser_version=self.version,
            blocks=blocks,
        )


def _collect_text(value) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "".join(_collect_text(item) for item in value)
    if isinstance(value, dict):
        if isinstance(value.get("content"), str):
            return value["content"]
        return "".join(_collect_text(value.get(key, [])) for key in ("lines", "spans", "blocks"))
    return ""


def _bbox(value):
    if isinstance(value, list) and len(value) == 4:
        return tuple(float(item) for item in value)
    return None


def _find_asset_path(value) -> str | None:
    if isinstance(value, dict):
        for key in ("img_path", "image_path", "asset_path", "uri"):
            candidate = value.get(key)
            if isinstance(candidate, str) and candidate.strip():
                return candidate
        for child in value.get("content", []):
            found = _find_asset_path(child)
            if found:
                return found
    elif isinstance(value, list):
        for child in value:
            found = _find_asset_path(child)
            if found:
                return found
    return None
