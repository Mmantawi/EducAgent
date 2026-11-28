import unittest
from fractions import Fraction as F

from ai.evaluation.normalize import parse_answer


class LeadInTests(unittest.TestCase):
    def test_short_lead_ins_are_removed(self):
        for text in (
            "8.84",
            "8.84.",
            "the answer is 8.84",
            "The answer is 8.84.",
            "answer: 8.84",
            "= 8.84",
            "الإجابة 8.84",
            "الإجابة هي 8.84",
            "الناتج: ٨٫٨٤",
            "هي 8.84",
        ):
            with self.subTest(text=text):
                answer = parse_answer(text)
                self.assertEqual((answer.kind, answer.value), ("number", F(221, 25)))

    def test_variable_name_before_equals_is_removed(self):
        for text in ("p = 2.01", "P=2.01", "س = 2.01"):
            with self.subTest(text=text):
                self.assertEqual(parse_answer(text).value, F(201, 100))

    def test_longer_sentences_return_none(self):
        for text in ("I think it might be 5 or 6", "مش عارف بس ممكن 5", "5 or 6", "", "   "):
            with self.subTest(text=text):
                self.assertIsNone(parse_answer(text))


class QuantityTests(unittest.TestCase):
    def assert_quantity(self, text, value, unit):
        answer = parse_answer(text)
        self.assertIsNotNone(answer, text)
        self.assertEqual((answer.kind, answer.value, answer.unit.name), ("quantity", value, unit))

    def test_units_in_both_languages(self):
        cases = [
            ("5 سم", F(5), "cm"),
            ("٥ سم", F(5), "cm"),
            ("5cm", F(5), "cm"),
            ("5 cm", F(5), "cm"),
            ("11.8 سنتيمتر", F(59, 5), "cm"),
            ("15 كيلومترًا", F(15), "km"),
            ("3.26 km", F(163, 50), "km"),
            ("322.5 متر", F(645, 2), "m"),
            ("4.38 كجم", F(219, 50), "kg"),
            ("4380 جم", F(4380), "g"),
            ("430 مل", F(430), "ml"),
            ("0.4 لتر", F(2, 5), "l"),
            ("1,320 جنيهًا", F(1320), "pound"),
            ("66 ساعة", F(66), "hour"),
            ("3960 دقيقة", F(3960), "minute"),
            ("خمسة سم", F(5), "cm"),
            ("الإجابة 9180 جرام", F(9180), "g"),
        ]
        for text, value, unit in cases:
            with self.subTest(text=text):
                self.assert_quantity(text, value, unit)

    def test_same_amount_in_different_units_compares_equal(self):
        pairs = [("1.5 م", "150 سم"), ("4.38 كجم", "4380 جم"), ("0.43 لتر", "430 مل"), ("1 ساعة", "60 دقيقة")]
        for first, second in pairs:
            with self.subTest(first=first, second=second):
                a, b = parse_answer(first), parse_answer(second)
                self.assertEqual(a.unit.dimension, b.unit.dimension)
                self.assertEqual(a.in_base_unit(), b.in_base_unit())

    def test_unclear_units_return_none(self):
        # "كيلو" alone can mean kilogram or kilometre.
        for text in ("5 كيلو", "كيلو 5", "5 صناديق", "5 xyz"):
            with self.subTest(text=text):
                self.assertIsNone(parse_answer(text))


class ChoiceTests(unittest.TestCase):
    def test_single_letters(self):
        for text, letter in (("أ", "أ"), ("(ب)", "ب"), ("جـ)", "جـ"), ("ج", "جـ"), ("د.", "د"), ("هـ", "هـ"), ("b", "b"), ("(C)", "c")):
            with self.subTest(text=text):
                answer = parse_answer(text)
                self.assertEqual((answer.kind, answer.choices), ("choice", (letter,)))

    def test_lists_of_letters(self):
        for text, letters in (
            ("أ، ب، د", ("أ", "ب", "د")),
            ("أ،جـ،و", ("أ", "جـ", "و")),
            ("الإجابة: أ، جـ، و", ("أ", "جـ", "و")),
            ("a, c, d", ("a", "c", "d")),
        ):
            with self.subTest(text=text):
                self.assertEqual(parse_answer(text).choices, letters)

    def test_unclear_letter_lists_return_none(self):
        # Without commas, "أ و جـ" could be "a and c" or three letters.
        for text in ("أ و جـ", "أ، أ", "a, ب", "ز"):
            with self.subTest(text=text):
                self.assertIsNone(parse_answer(text))


if __name__ == "__main__":
    unittest.main()
