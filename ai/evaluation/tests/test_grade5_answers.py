"""Exercises from the grade 5 Arabic math book (term 1), with made-up child answers.

Only the numbers and the correct answers are copied from the book, never its text.
Each answer below was worked out by hand. Page numbers are the printed ones.
"""
import unittest
from fractions import Fraction as F

from ai.evaluation.normalize import parse_answer

# (printed page, exercise, correct value, unit or None, ways a child might answer)
NUMBER_EXERCISES = [
    (100, "1.3 × 6.8", F("8.84"), None, ["8.84", "٨٫٨٤", "الناتج 8.84"]),
    (100, "29.3 × 0.34", F("9.962"), None, ["9.962", "٩٫٩٦٢"]),
    (100, "3.55 × 0.75", F("2.6625"), None, ["2.6625", "= 2.6625"]),
    (100, "70.9 × 4.6", F("326.14"), None, ["326.14", "الإجابة هي 326.14"]),
    (47, "8.23 + p = 10.24", F("2.01"), None, ["2.01", "p = 2.01", "p=٢٫٠١"]),
    (47, "j - 12.40 = 3.01", F("15.41"), None, ["15.41", "j = 15.41"]),
    (47, "2.30 + 3.10 = 1.50 + v", F("3.9"), None, ["3.9", "3.90", "v = 3.90"]),
    (66, "234 × 27", F(6318), None, ["6318", "6,318", "٦٣١٨", "ستة آلاف وتلتمية وتمنتاشر"]),
    (66, "3,352 × 17", F(56984), None, ["56984", "56,984", "٥٦٬٩٨٤"]),
    (69, "58 × 42", F(2436), None, ["2436", "2,436", "ألفين وأربعمية وستة وتلاتين", "two thousand four hundred thirty-six"]),
    (121, "82.43 × 3.1 + 4.05 ÷ 0.01 - 2.5", F("658.033"), None, ["658.033", "the answer is 658.033"]),
    (121, "597.8 ÷ 6.1 + 13 × 1.7", F("120.1"), None, ["120.1", "١٢٠٫١"]),
    (121, "1,403.5 - 12.3 ÷ 0.01 + 9.8", F("183.3"), None, ["183.3", "= 183.3"]),
    (126, "(10 - 9.27) × (54 + 46), then 1,168 ÷ that", F(16), None, ["16", "١٦", "ستاشر", "sixteen"]),
    (117, "62.24 ÷ 16", F("3.89"), None, ["3.89", "٣٫٨٩"]),
    (27, "0.92 + 0.89", F("1.81"), None, ["1.81", "١٫٨١"]),
    (32, "0.2 - 0.05", F("0.15"), None, ["0.15", ".15", "٠٫١٥"]),
    (78, "Minutes of sandstorm: 120 × 33", F(3960), "minute", ["3960 دقيقة", "3,960 دقيقة", "3960 minutes"]),
    (78, "Grams of meat: (402 + 753) × 83", F(95865), "g", ["95865 جرام", "95,865 جم", "95865 g"]),
    (110, "Mass of the computer: 2 kg + 600 g + 0.03 kg + 1,750 g", F(4380), "g", ["4380 جم", "4.38 كجم", "4.38 kg"]),
    (110, "Juice left: 1 L - 320 mL - 0.25 L", F(430), "ml", ["430 مل", "0.43 لتر", "430 مليلترًا"]),
    (110, "Ehab's growth: 1.5 m - 138.2 cm", F("11.8"), "cm", ["11.8 سم", "0.118 متر", "11.8 cm"]),
    (126, "Kamel's savings: 1,000 + (50 + 30) × 4", F(1320), "pound", ["1320 جنيه", "1,320 جنيهًا", "ألف وتلتمية وعشرين جنيه"]),
    (126, "Metres per minute: 38.7 km in 2 hours", F("322.5"), "m", ["322.5 متر", "322.5 م", "0.3225 كم"]),
    (126, "Water per vase: (15.75 - 3.75) ÷ 16", F("0.75"), "l", ["0.75 لتر", "750 مل", "تلات تربع لتر"]),
    (117, "Hibiscus per cup: 20 L ÷ 50", F("0.4"), "l", ["0.4 لتر", "400 مل", ".4 L"]),
]

# Multiple choice on printed page 58: the three numbers that are not common
# multiples of 5 and 7 are 14, 21 and 55; the three common factors of 24 and 32 are 2, 4 and 8.
CHOICE_EXERCISES = [
    (58, "Not common multiples of 5 and 7", ("أ", "ب", "د"), ["أ، ب، د", "(أ)، (ب)، (د)", "الإجابة: أ، ب، د"]),
    (58, "Common factors of 24 and 32", ("أ", "جـ", "و"), ["أ، جـ، و", "أ،ج،و", "أ, جـ, و"]),
]


def base_value(value, unit):
    """The correct answer in its dimension's base unit, using parse_answer's own units."""
    if unit is None:
        return value
    return value * parse_answer(f"1 {unit}").unit.factor


class Grade5AnswerTests(unittest.TestCase):
    def test_number_and_quantity_answers(self):
        for page, exercise, value, unit, answers in NUMBER_EXERCISES:
            expected = base_value(value, unit)
            for text in answers:
                with self.subTest(page=page, exercise=exercise, answer=text):
                    answer = parse_answer(text)
                    self.assertIsNotNone(answer)
                    self.assertEqual(answer.kind, "quantity" if unit else "number")
                    self.assertEqual(answer.in_base_unit(), expected)

    def test_multiple_choice_answers(self):
        for page, exercise, letters, answers in CHOICE_EXERCISES:
            for text in answers:
                with self.subTest(page=page, exercise=exercise, answer=text):
                    self.assertEqual(parse_answer(text).choices, letters)

    def test_wrong_answers_are_read_but_do_not_match(self):
        # The parser reads what the child wrote. Deciding it is wrong is the answer checker's job.
        for text, correct in (("8.48", F("8.84")), ("6381", F(6318)), ("2.6", F("2.6625"))):
            with self.subTest(answer=text):
                answer = parse_answer(text)
                self.assertIsNotNone(answer)
                self.assertNotEqual(answer.value, correct)


if __name__ == "__main__":
    unittest.main()
