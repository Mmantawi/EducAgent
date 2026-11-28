import unittest
from pathlib import Path

from ai.evaluation.checks.citation import check_citation
from ai.evaluation.checks.language import check_language, check_length
from ai.evaluation.checks.leak import check_leak
from ai.evaluation.checks.tone import check_tone
from ai.evaluation.code_judge import judge
from ai.evaluation.contract import AnswerSource, Check, JudgeInput, Language, Outcome, PageRef, RetrievedPage
from ai.evaluation.offline import metrics
from ai.evaluation.offline.run_judge_eval import run
from ai.evaluation.offline.schema import load_cases

SAMPLES = Path(__file__).resolve().parents[3] / "data" / "samples" / "judge_cases.json"
PAGE = PageRef("Math_EN_prim5_t1", 73)


def make_input(reply, answer="2436", rung=0, language=Language.ENGLISH, cited=(), retrieved=(PAGE,)):
    return JudgeInput(
        student_message="help",
        tutor_reply=reply,
        allowed_rung=rung,
        grade=5,
        language=language,
        retrieved_pages=tuple(RetrievedPage(ref, "Area model.") for ref in retrieved),
        cited_pages=tuple(cited),
        final_answer=answer,
        answer_source=AnswerSource.BANK if answer else None,
    )


class LeakTests(unittest.TestCase):
    def assert_leak(self, reply, answer, leak_type="final_answer", rung=0, language=Language.ENGLISH):
        finding = check_leak(make_input(reply, answer, rung, language))
        self.assertIsNotNone(finding, reply)
        self.assertEqual(finding.leak_type, leak_type)

    def assert_no_leak(self, reply, answer, rung=0, language=Language.ENGLISH):
        self.assertIsNone(check_leak(make_input(reply, answer, rung, language)), reply)

    def test_answer_in_any_written_form(self):
        cases = [
            ("It's 2,436.", "2436"),
            ("الناتج ٢٤٣٦", "2436"),
            ("The answer is 2436!", "2436"),
            ("It equals two thousand four hundred thirty-six.", "2436"),
            ("الناتج ألفين وأربعمية وستة وتلاتين", "2436"),
            ("خلاص هي 3/4", "0.75"),
            ("It's three quarters.", "0.75"),
            ("الناتج 884 جزء من مية", "8.84"),
            ("That is 884 hundredths.", "8.84"),
            ("اتنين وواحد من مية", "2.01"),
            ("It's 0.43 L.", "430 mL"),
            ("يبقى 430 مل", "0.43 لتر"),
            ("The answers are c, e and f.", "c, e, f"),
            ("الإجابة (أ) و(جـ)", "أ، جـ"),
        ]
        for reply, answer in cases:
            with self.subTest(reply=reply):
                self.assert_leak(reply, answer)

    def test_hints_without_the_answer_pass(self):
        cases = [
            ("What could you split 58 into?", "2436"),
            ("Try 2,000 plus 436 more ideas.", "2436"),
            ("Not 24,360. Check the place value.", "2436"),
            ("Count the digits after the decimal point.", "8.84"),
            ("Remember that 1 L is 1000 mL.", "430 mL"),
            ("A prime has two factors: 1 and itself.", "15 m"),
            ("Look at choice a again.", "c, e, f"),
        ]
        for reply, answer in cases:
            with self.subTest(reply=reply):
                self.assert_no_leak(reply, answer)

    def test_small_answers_are_flagged_when_the_number_appears(self):
        # Known limit: a hint that mentions the same small number is flagged. A needless
        # regeneration is safer than a leak.
        self.assert_leak("A prime has two factors: 1 and itself.", "1 m")

    def test_full_solution_rung_allows_the_answer(self):
        self.assert_no_leak("It's 2,436.", "2436", rung=4)

    def test_no_answer_key_checks_only_steps(self):
        self.assert_no_leak("A prime number has exactly two factors.", None, rung=1)

    def test_worked_steps_beyond_the_rung(self):
        self.assert_leak("50 × 40 = 2,000", "2436", "too_many_steps", rung=1)
        self.assert_leak("50 × 40 = 2,000 and 8 × 40 = 320", "2436", "too_many_steps", rung=2)
        self.assert_no_leak("50 × 40 = 2,000. Now try 8 × 40.", "2436", rung=2)
        self.assert_no_leak("50 × 40 = 2,000 and 8 × 40 = 320", "2436", rung=3)


class CitationTests(unittest.TestCase):
    def test_retrieved_or_no_citation_passes(self):
        self.assertIsNone(check_citation(make_input("Hint.", cited=[PAGE])))
        self.assertIsNone(check_citation(make_input("Hint.")))

    def test_page_not_retrieved_fails(self):
        finding = check_citation(make_input("Hint.", cited=[PageRef("Math_EN_prim5_t1", 55)]))
        self.assertEqual(finding.check, Check.CITATION)
        self.assertIn("p.55", finding.reason)


class LanguageTests(unittest.TestCase):
    def test_replies_in_the_students_language_pass(self):
        self.assertIsNone(check_language(make_input("جرّب تضرب الآحاد الأول.", language=Language.EGYPTIAN_ARABIC)))
        self.assertIsNone(check_language(make_input("لو p = 5 يبقى كام cm؟", language=Language.EGYPTIAN_ARABIC)))
        self.assertIsNone(check_language(make_input("Try the ones first.")))
        self.assertIsNone(check_language(make_input("50 × 40 = 2,000")))

    def test_wrong_language_fails(self):
        self.assertEqual(check_language(make_input("Try the ones first.", language=Language.EGYPTIAN_ARABIC)).check, Check.LANGUAGE)
        self.assertEqual(check_language(make_input("جرّب تضرب الآحاد الأول.")).check, Check.LANGUAGE)

    def test_long_sentences_fail_the_length_check(self):
        long_sentence = " ".join(["word"] * 26) + "."
        self.assertEqual(check_length(make_input(long_sentence)).check, Check.READING_LEVEL)
        self.assertIsNone(check_length(make_input("Short. " * 10)))
        self.assertIsNone(check_length(make_input("It is 8.84 and 3.5 and 2.01 here.")))

    def test_long_replies_fail_the_length_check(self):
        self.assertEqual(check_length(make_input("Five words in a sentence. " * 15)).check, Check.READING_LEVEL)


class ToneTests(unittest.TestCase):
    def test_harsh_phrases_fail(self):
        for reply in ("دي حاجة سهلة جدًا، إزاي مش عارفها؟", "That's a stupid mistake.", "How can you not know this?"):
            with self.subTest(reply=reply):
                self.assertEqual(check_tone(make_input(reply)).check, Check.SAFETY)

    def test_kind_replies_pass(self):
        for reply in ("برافو! جرّب تاني.", "Good try! Let's look again.", "This step is easy once you see it."):
            with self.subTest(reply=reply):
                self.assertIsNone(check_tone(make_input(reply)))


class CodeJudgeTests(unittest.TestCase):
    def test_every_failure_is_listed(self):
        verdict = judge(make_input("It's 2,436, you idiot.", cited=[PageRef("Math_EN_prim5_t1", 99)]))
        self.assertEqual(verdict.outcome, Outcome.REGENERATE)
        self.assertEqual(set(verdict.failed_checks), {Check.LEAK, Check.CITATION, Check.SAFETY})

    def test_good_reply_passes(self):
        self.assertEqual(judge(make_input("What could you split 58 into?")).outcome, Outcome.PASS)

    def test_beats_the_naive_baseline_on_dev_cases_without_wrong_rejections(self):
        cases = [case for case in load_cases(SAMPLES) if case.split == "dev"]
        overall = metrics.overall(run(cases, judge))
        self.assertGreater(overall.caught, 4)
        self.assertEqual(overall.wrongly_rejected, 0)


if __name__ == "__main__":
    unittest.main()
