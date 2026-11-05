import unittest

from ai.evaluation.contract import (
    AnswerSource,
    Check,
    JudgeInput,
    JudgeVerdict,
    Language,
    Layer,
    Outcome,
)


def make_input(**overrides):
    values = {
        "student_message": "How much is 5 + 3?",
        "tutor_reply": "What do you get if you count 3 more after 5?",
        "allowed_rung": 0,
        "grade": 4,
        "language": Language.ENGLISH,
    }
    values.update(overrides)
    return JudgeInput(**values)


class JudgeInputTests(unittest.TestCase):
    def test_accepts_every_rung_from_0_to_4(self):
        for rung in range(5):
            with self.subTest(rung=rung):
                self.assertEqual(make_input(allowed_rung=rung).allowed_rung, rung)

    def test_rejects_rungs_outside_the_range(self):
        for rung in (-1, 5):
            with self.subTest(rung=rung), self.assertRaises(ValueError):
                make_input(allowed_rung=rung)

    def test_answer_and_its_source_must_be_set_together(self):
        make_input(final_answer="8", answer_source=AnswerSource.BANK)
        with self.assertRaises(ValueError):
            make_input(final_answer="8")
        with self.assertRaises(ValueError):
            make_input(answer_source=AnswerSource.BANK)


class JudgeVerdictTests(unittest.TestCase):
    def test_pass_has_no_failed_checks(self):
        JudgeVerdict(Outcome.PASS, Layer.CODE)
        with self.assertRaises(ValueError):
            JudgeVerdict(Outcome.PASS, Layer.CODE, failed_checks=(Check.LEAK,))

    def test_failure_must_name_a_check(self):
        JudgeVerdict(Outcome.REGENERATE, Layer.LLM, failed_checks=(Check.GROUNDING,))
        for outcome in (Outcome.REGENERATE, Outcome.FALLBACK):
            with self.subTest(outcome=outcome), self.assertRaises(ValueError):
                JudgeVerdict(outcome, Layer.CODE)


if __name__ == "__main__":
    unittest.main()
