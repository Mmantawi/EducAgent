import unittest
from fractions import Fraction as F

from ai.evaluation.normalize import normalize_text, parse_number


class ParseNumberTests(unittest.TestCase):
    def assert_parses(self, cases):
        for text, expected in cases:
            with self.subTest(text=text):
                self.assertEqual(parse_number(text), expected)

    def test_western_and_arabic_digits(self):
        self.assert_parses([
            ("5", F(5)),
            ("٥", F(5)),
            ("۵", F(5)),
            ("-3", F(-3)),
            ("−٣", F(-3)),
            ("  12  ", F(12)),
        ])

    def test_decimals(self):
        self.assert_parses([
            ("0.5", F(1, 2)),
            ("٠٫٥", F(1, 2)),
            (".75", F(3, 4)),
            ("-.5", F(-1, 2)),
            ("12.40", F(62, 5)),
        ])

    def test_comma_that_is_not_thousands_returns_none(self):
        # "2,4" could be a list or the decimal 2.4, so it is not guessed.
        for text in ("2,4", "3,5", "٣،٥", "0,125", "1,23", "12,3456"):
            with self.subTest(text=text):
                self.assertIsNone(parse_number(text))

    def test_thousands(self):
        self.assert_parses([
            ("5,328", F(5328)),
            ("٥٬٣٢٨", F(5328)),
            ("1,234,567", F(1234567)),
            ("1,234.5", F(2469, 2)),
        ])

    def test_fractions(self):
        self.assert_parses([
            ("1/2", F(1, 2)),
            ("٣/٤", F(3, 4)),
            ("3 / 4", F(3, 4)),
            ("½", F(1, 2)),
            ("-1/2", F(-1, 2)),
        ])

    def test_mixed_numbers_are_added_not_multiplied(self):
        self.assert_parses([
            ("2 1/2", F(5, 2)),
            ("٢ ١/٢", F(5, 2)),
            ("2½", F(5, 2)),
            ("-2 1/2", F(-5, 2)),
        ])

    def test_invisible_direction_marks_are_ignored(self):
        self.assertEqual(parse_number("‏٥‎"), F(5))

    def test_egyptian_arabic_whole_numbers(self):
        self.assert_parses([
            ("خمسة", F(5)),
            ("خمسه", F(5)),
            ("خَمْسَة", F(5)),
            ("أربعة", F(4)),
            ("اتنين", F(2)),
            ("تلاتة", F(3)),
            ("حداشر", F(11)),
            ("عشرين", F(20)),
            ("خمسة وعشرين", F(25)),
            ("خمسة و عشرين", F(25)),
        ])

    def test_egyptian_arabic_fractions(self):
        self.assert_parses([
            ("نص", F(1, 2)),
            ("نصف", F(1, 2)),
            ("تلت", F(1, 3)),
            ("ربع", F(1, 4)),
            ("تلتين", F(2, 3)),
            ("تلات تربع", F(3, 4)),
            ("اتنين ونص", F(5, 2)),
            ("2 ونص", F(5, 2)),
        ])

    def test_similar_arabic_words_stay_distinct(self):
        self.assert_parses([
            ("ربع", F(1, 4)),
            ("أربع", F(4)),
            ("تلت", F(1, 3)),
            ("تلات", F(3)),
        ])

    def test_english_words(self):
        self.assert_parses([
            ("five", F(5)),
            ("Five", F(5)),
            ("twenty five", F(25)),
            ("twenty-five", F(25)),
            ("half", F(1, 2)),
            ("a half", F(1, 2)),
            ("one half", F(1, 2)),
            ("three quarters", F(3, 4)),
            ("two thirds", F(2, 3)),
            ("two and a half", F(5, 2)),
            ("2 and a half", F(5, 2)),
            ("2 and 1/2", F(5, 2)),
        ])

    def test_large_numbers_in_words(self):
        self.assert_parses([
            ("مية", F(100)),
            ("مائة", F(100)),
            ("مية وخمسة وعشرين", F(125)),
            ("ميتين", F(200)),
            ("تلتمية", F(300)),
            ("ثلاثمائة", F(300)),
            ("تلات مية", F(300)),
            ("تمنمية تمانية وتمانين", F(888)),
            ("ألف", F(1000)),
            ("ألف وتلتمية", F(1300)),
            ("ألفين وأربعمية وستة وتلاتين", F(2436)),
            ("تلات تلاف", F(3000)),
            ("عشرة آلاف", F(10000)),
            ("مية ونص", F(201, 2)),
            ("one hundred", F(100)),
            ("a hundred", F(100)),
            ("three hundred and five", F(305)),
            ("two thousand four hundred thirty-six", F(2436)),
            ("one thousand and twenty", F(1020)),
        ])

    def test_badly_ordered_number_words_return_none(self):
        for text in ("خمسة وخمسة", "عشرين وتلاتين", "مية ومية", "خمسة وألف", "ten hundred", "hundred hundred"):
            with self.subTest(text=text):
                self.assertIsNone(parse_number(text))

    def test_same_value_in_every_form(self):
        for text in ("1/2", "0.5", "٠٫٥", "½", "نص", "half", "one half"):
            with self.subTest(text=text):
                self.assertEqual(parse_number(text), F(1, 2))

    def test_unclear_answers_return_none_instead_of_a_guess(self):
        for text in (
            "",
            "   ",
            "abc",
            "1/0",
            "5 cm",
            "the answer is 5",
            "حوالي خمسة",
            "five three",
            "twenty three five",
            "two half",
            "واحد واتنين",
            "1.2.3",
            "5.",
        ):
            with self.subTest(text=text):
                self.assertIsNone(parse_number(text))


class NormalizeTextTests(unittest.TestCase):
    def test_unifies_arabic_spelling(self):
        self.assertEqual(normalize_text("أَرْبَعَة"), "اربعه")

    def test_removes_elongation(self):
        self.assertEqual(normalize_text("خمـــسة"), "خمسه")

    def test_converts_digits_inside_text(self):
        self.assertEqual(normalize_text("Answer ٣"), "answer 3")


if __name__ == "__main__":
    unittest.main()
