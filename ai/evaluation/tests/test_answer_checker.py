import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from ai.evaluation.answer_checker import Result, check_answer
from ai.evaluation.normalize import parse_answer
from ai.evaluation.offline.run_answer_eval import evaluate, main, passes

SAMPLES = Path(__file__).resolve().parents[3] / "data" / "samples" / "answer_cases.json"


class NumberTests(unittest.TestCase):
    def assert_result(self, student, key, result):
        self.assertEqual(check_answer(student, key).result, result, f"{student!r} vs {key!r}")

    def test_same_value_in_any_form_is_correct(self):
        for student in ("0.5", ".5", "1/2", "٠٫٥", "نص", "half", "the answer is 0.5"):
            with self.subTest(student=student):
                self.assert_result(student, "0.5", Result.CORRECT)

    def test_different_value_is_wrong(self):
        self.assert_result("0.6", "0.5", Result.WRONG)
        self.assert_result("884", "8.84", Result.WRONG)

    def test_unreadable_answers_are_never_wrong(self):
        for student in ("", "مش عارف", "2,4", "5 or 6", "كيلو 5"):
            with self.subTest(student=student):
                self.assert_result(student, "2.4", Result.CANNOT_CHECK)

    def test_unreadable_key_cannot_be_checked(self):
        self.assert_result("5", "؟؟", Result.CANNOT_CHECK)

    def test_unit_given_for_a_plain_number_is_ignored(self):
        self.assert_result("6318 سم", "6318", Result.CORRECT)

    def test_choice_letters_for_a_value_cannot_be_checked(self):
        self.assert_result("ب", "12", Result.CANNOT_CHECK)

    def test_key_can_be_a_parsed_answer(self):
        self.assert_result("12", parse_answer("12"), Result.CORRECT)


class QuantityTests(unittest.TestCase):
    def assert_result(self, student, key, result):
        self.assertEqual(check_answer(student, key).result, result, f"{student!r} vs {key!r}")

    def test_same_amount_in_another_unit_is_correct(self):
        for student, key in (("150 سم", "1.5 م"), ("4380 جم", "4.38 كجم"), ("0.43 لتر", "430 مل"), ("66 ساعة", "3960 دقيقة")):
            with self.subTest(student=student):
                self.assert_result(student, key, Result.CORRECT)

    def test_different_amount_is_wrong(self):
        self.assert_result("140 سم", "1.5 م", Result.WRONG)

    def test_wrong_kind_of_unit_is_wrong(self):
        check = check_answer("1.5 كجم", "1.5 م")
        self.assertEqual(check.result, Result.WRONG)
        self.assertIn("mass", check.reason)

    def test_right_number_without_unit_is_partial(self):
        self.assert_result("1.5", "1.5 م", Result.PARTIAL)

    def test_number_right_in_another_unit_without_unit_cannot_be_checked(self):
        check = check_answer("150", "1.5 م")
        self.assertEqual(check.result, Result.CANNOT_CHECK)
        self.assertIn("cm", check.reason)

    def test_wrong_number_without_unit_is_wrong(self):
        self.assert_result("7", "1.5 م", Result.WRONG)


class ChoiceTests(unittest.TestCase):
    def assert_result(self, student, key, result):
        self.assertEqual(check_answer(student, key).result, result, f"{student!r} vs {key!r}")

    def test_same_choices_in_any_order_are_correct(self):
        self.assert_result("د، أ، ب", "أ، ب، د", Result.CORRECT)
        self.assert_result("c, a", "a, c", Result.CORRECT)

    def test_some_right_choices_and_none_wrong_is_partial(self):
        check = check_answer("أ", "أ، ب، د")
        self.assertEqual(check.result, Result.PARTIAL)
        self.assertIn("2 choice", check.reason)

    def test_any_wrong_choice_is_wrong(self):
        self.assert_result("أ، جـ", "أ، ب، د", Result.WRONG)

    def test_mixed_alphabets_cannot_be_checked(self):
        self.assert_result("a", "أ", Result.CANNOT_CHECK)

    def test_value_for_a_choice_question_cannot_be_checked(self):
        self.assert_result("14", "أ، ب، د", Result.CANNOT_CHECK)


class AnswerEvalTests(unittest.TestCase):
    def test_book_cases_meet_the_target(self):
        cases = json.loads(SAMPLES.read_text(encoding="utf-8"))
        report = evaluate(cases)
        self.assertGreaterEqual(len(cases), 75)
        self.assertEqual(report["correct_marked_wrong"], [])
        self.assertTrue(passes(report))
        self.assertEqual({case["expected"] for case in cases}, {r.value for r in Result})

    def test_a_correct_answer_marked_wrong_fails_the_run(self):
        cases = [{"id": "x", "answer_key": "5", "student_answer": "6", "expected": "correct"}]
        report = evaluate(cases)
        self.assertEqual(len(report["correct_marked_wrong"]), 1)
        self.assertFalse(passes(report))

    def test_bad_case_files_are_rejected(self):
        with self.assertRaises(ValueError):
            evaluate([{"id": "x", "answer_key": "5", "student_answer": "5", "expected": "maybe"}])
        with self.assertRaises(ValueError):
            evaluate([{"id": "x", "answer_key": "5", "student_answer": "5", "expected": "correct"}] * 2)

    def test_command_exit_code(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "cases.json"
            path.write_text(json.dumps([{"id": "x", "answer_key": "5", "student_answer": "6", "expected": "correct"}]), encoding="utf-8")
            with redirect_stdout(io.StringIO()) as output:
                self.assertEqual(main([str(path)]), 1)
            self.assertIn("FAIL", output.getvalue())
        with redirect_stdout(io.StringIO()):
            self.assertEqual(main([str(SAMPLES)]), 0)


if __name__ == "__main__":
    unittest.main()
