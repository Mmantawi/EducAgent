import re
import unicodedata
from collections import Counter

from eduagent_kg.ids import make_section_id
from eduagent_kg.schemas.documents import ParsedBlock, ParsedDocument, TextbookSection
from eduagent_kg.schemas.enums import BlockType

CHAPTER_RE = re.compile(
    r"^(chapter\s*\d+|unit\s*\d+|الفصل\s*[\d١-٩]|الوحدة\s*[\d١-٩])\b", re.IGNORECASE
)
REVIEW_RE = re.compile(
    r"^(chapter\s*\d*\s*review|power\s*up\s*chapter|power\s*up\s*review)", re.IGNORECASE
)
LESSON_RE = re.compile(
    r"^(lesson\s*\d+|الدرس\s*[\d١-٩]|\d{1,2}\s*-\s*\d{1,2}[\.\s:]*[A-Za-z\u0600-\u06FF]|chapter\s*\d*\s*review|power\s*up\s*chapter|power\s*up\s*review)",
    re.IGNORECASE,
)
SECTION_RE = re.compile(
    r"^(section\s*\d+|activity\s*[\d١-٩]|نشاط\s*[\d١-٩])\b", re.IGNORECASE
)
EXERCISE_PREFIX_RE = re.compile(
    r"^\d{1,2}\s*-\s*\d{1,2}\s*[\(①②③④⑤\d]|write the missing|find the missing|let's calculate|let's do|the table below|rode on|if the answer",
    re.IGNORECASE,
)
MATH_EQUATION_RE = re.compile(r"(=|\\times|\\div|<|>|\\leq|\\geq)")

MICRO_PROMPTS = {
    "point!",
    "warm up",
    "how to solve",
    "try",
    "exercise",
    "example",
    "power up",
    "let's learn together!",
}


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", text)).strip().lower()


class HierarchicalSectionSplitter:
    """Heading-driven splitter that identifies chapter and lesson boundaries while keeping lesson content unified."""

    def split(self, document: ParsedDocument) -> list[TextbookSection]:
        blocks = sorted(document.blocks, key=lambda item: item.order)
        if not blocks:
            return []
        groups = self._groups(blocks)
        stack: dict[int, tuple[str, str]] = {}
        occurrences: Counter[tuple[str, ...]] = Counter()
        sections: list[TextbookSection] = []
        for heading, content, uncertain in groups:
            level = self._level(heading) if heading else 1
            title = heading.text.strip() if heading and heading.text.strip() else "Unresolved content"
            for old_level in [key for key in stack if key >= level]:
                del stack[old_level]
            parent = stack[max(stack)][0] if stack else None
            heading_path = [stack[key][1] for key in sorted(stack)] + [title]
            path_key = tuple(heading_path)
            occurrences[path_key] += 1
            section_id = make_section_id(document.document_id, heading_path, occurrences[path_key])
            all_blocks = ([heading] if heading else []) + content
            page_start = min(block.page_start for block in all_blocks)
            page_end = max(block.page_end for block in all_blocks)
            warnings = []
            if uncertain:
                warnings.append("No reliable heading boundary; content was preserved in an unresolved section.")
            section = TextbookSection(
                section_id=section_id,
                document_id=document.document_id,
                book_id=document.book_id,
                parent_section_id=parent,
                heading=title,
                heading_path=heading_path,
                page_start=page_start,
                page_end=page_end,
                text="\n".join(block.text for block in all_blocks if block.text),
                block_ids=[block.block_id for block in all_blocks],
                table_block_ids=[block.block_id for block in all_blocks if block.block_type == BlockType.TABLE],
                image_block_ids=[block.block_id for block in all_blocks if block.block_type == BlockType.IMAGE],
                boundary_uncertain=uncertain or any(block.boundary_uncertain for block in all_blocks),
                warnings=warnings,
                grade=document.grade,
                subject=document.subject,
                original_language=document.original_language,
            )
            sections.append(section)
            stack[level] = (section_id, title)
        return sections

    def _groups(self, blocks: list[ParsedBlock]):
        has_curriculum = any(
            CHAPTER_RE.match(b.text.strip())
            or (LESSON_RE.match(b.text.strip()) and not EXERCISE_PREFIX_RE.search(b.text.strip()))
            for b in blocks
            if b.text
        )
        groups: list[tuple[ParsedBlock | None, list[ParsedBlock], bool]] = []
        heading: ParsedBlock | None = None
        content: list[ParsedBlock] = []
        active_chapter: str | None = None
        active_lesson: str | None = None

        for b in blocks:
            t = b.text.strip()
            if not t:
                content.append(b)
                continue

            is_heading = False
            heading_kind: str | None = None

            if has_curriculum:
                if _norm(t) in MICRO_PROMPTS:
                    is_heading = False
                elif CHAPTER_RE.match(t):
                    if REVIEW_RE.match(t):
                        heading_kind = "review"
                        is_heading = (active_lesson != _norm(t))
                    else:
                        heading_kind = "chapter"
                        parts = t.split()
                        ch_key = parts[0].lower() + " " + (parts[1].lower() if len(parts) > 1 else "")
                        is_heading = (active_chapter != ch_key)
                elif REVIEW_RE.match(t):
                    heading_kind = "review"
                    is_heading = (active_lesson != _norm(t))
                elif LESSON_RE.match(t) and not EXERCISE_PREFIX_RE.search(t) and not MATH_EQUATION_RE.search(t):
                    heading_kind = "lesson"
                    is_heading = (active_lesson != _norm(t))
                elif SECTION_RE.match(t):
                    heading_kind = "section"
                    is_heading = True
                elif b.block_type == BlockType.HEADING and b.heading_level == 1:
                    heading_kind = "heading"
                    is_heading = True
            else:
                if b.block_type == BlockType.HEADING and t:
                    is_heading = True

            if is_heading:
                if heading_kind == "chapter":
                    parts = t.split()
                    active_chapter = parts[0].lower() + " " + (parts[1].lower() if len(parts) > 1 else "")
                    active_lesson = None
                elif heading_kind in ("lesson", "review"):
                    active_lesson = _norm(t)

                if heading is not None or content:
                    groups.append((heading, content, heading is None))
                heading = b
                content = []
            else:
                content.append(b)

        if heading is not None or content:
            groups.append((heading, content, heading is None))
        return groups

    def _level(self, heading: ParsedBlock) -> int:
        if heading.heading_level is not None:
            return heading.heading_level
        text = heading.text.strip()
        if CHAPTER_RE.match(text) and not REVIEW_RE.match(text):
            return 1
        if LESSON_RE.match(text) or REVIEW_RE.match(text):
            return 2
        if SECTION_RE.match(text):
            return 3
        return 2
