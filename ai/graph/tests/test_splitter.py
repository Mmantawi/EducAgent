import unittest

from eduagent_kg.parsing.splitter import HierarchicalSectionSplitter, clean_text, is_noise_line
from eduagent_kg.schemas.documents import ParsedBlock, ParsedDocument
from eduagent_kg.schemas.enums import BlockType


def _document(lines: list[tuple[int, str]]) -> ParsedDocument:
    blocks = [
        ParsedBlock(block_id=f"b{i}", block_type=BlockType.PARAGRAPH, text=text,
                    page_start=page, page_end=page, order=i)
        for i, (page, text) in enumerate(lines)
    ]
    return ParsedDocument(
        document_id="doc", book_id="book", title="Test", source_uri="test", content_hash="0" * 64,
        page_count=max(page for page, _ in lines), parser_name="test", parser_version="1",
        blocks=blocks, grade=3, subject="mathematics", original_language="en",
    )


# Layout of the Egyptian MoE Grade 3 maths book: each lesson opens on a page that repeats the
# chapter banner and an unnumbered title; later pages carry the numbered lesson heading.
BOOK = [
    (8, "Chapter 2 Time and Duration"),
    (8, "Point!"),
    (8, "Time before and after can be found on a clock."),
    (9, "2-1 Finding Time Before and After"),
    (9, "Exercise"),
    (9, "2 3 4 5 6 7 8 9 10 11 12 13 14 15 16 17 18"),
    (9, "9"),
    (10, "Chapter 2 Time and Duration"),
    (10, "Shorter Time Units"),
    (10, "Point!"),
    (10, "1 minute = 60 seconds"),
    (11, "2-2 Shorter Time Units"),
    (11, "Try"),
    (12, "Reading a Stopwatch"),
    (12, "Chapter 2 Time and Duration"),
    (12, "Point!"),
    (12, "A stopwatch shows seconds."),
    (13, "Chapter2 Review and Practice"),
    (13, "Try"),
]


class SplitterTest(unittest.TestCase):
    def setUp(self) -> None:
        self.sections = HierarchicalSectionSplitter().split(_document(BOOK))
        self.by_heading = {section.heading: section for section in self.sections}

    def test_first_lesson_gets_the_page_after_the_chapter_banner(self) -> None:
        chapter = self.by_heading["Chapter 2 Time and Duration"]
        lesson = self.by_heading["2-1 Finding Time Before and After"]
        self.assertNotIn("Point!", chapter.text)
        self.assertIn("Time before and after can be found", lesson.text)
        self.assertEqual(lesson.page_start, 8)

    def test_opening_page_moves_to_the_following_numbered_lesson(self) -> None:
        previous = self.by_heading["2-1 Finding Time Before and After"]
        lesson = self.by_heading["2-2 Shorter Time Units"]
        self.assertNotIn("1 minute = 60 seconds", previous.text)
        self.assertIn("1 minute = 60 seconds", lesson.text)
        self.assertEqual(lesson.heading_path, ["Chapter 2 Time and Duration", "2-2 Shorter Time Units"])

    def test_unnumbered_lesson_before_a_review_becomes_its_own_section(self) -> None:
        lesson = self.by_heading["Reading a Stopwatch"]
        self.assertIn("A stopwatch shows seconds.", lesson.text)
        self.assertEqual(lesson.heading_path, ["Chapter 2 Time and Duration", "Reading a Stopwatch"])
        self.assertNotIn("A stopwatch shows seconds.", self.by_heading["2-2 Shorter Time Units"].text)
        self.assertIn("Chapter2 Review and Practice", self.by_heading)

    def test_page_edge_noise_is_removed_from_section_text(self) -> None:
        lesson = self.by_heading["2-1 Finding Time Before and After"]
        self.assertNotIn("11 12 13", lesson.text)
        self.assertNotIn("\n9\n", "\n" + lesson.text + "\n")

    def test_no_content_is_lost(self) -> None:
        kept = sorted(text for _, text in BOOK if not is_noise_line(text))
        produced = sorted(line for section in self.sections for line in section.text.split("\n"))
        self.assertEqual(produced, kept)


class CleanTextTest(unittest.TestCase):
    def test_keeps_real_numbers_and_circled_digits(self) -> None:
        text = "① 1 0 x 3\n25]\n1 2 3 4 5 6 8 9 10\n3 x 4 = 12\nAnswer: 12 [OCR_ARTIFACT: run x9]"
        self.assertEqual(clean_text(text), "① 1 0 x 3\n3 x 4 = 12\nAnswer: 12")


if __name__ == "__main__":
    unittest.main()
