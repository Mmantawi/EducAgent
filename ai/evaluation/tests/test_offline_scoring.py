import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from ai.evaluation.contract import Check, JudgeVerdict, Layer, Outcome
from ai.evaluation.offline import metrics
from ai.evaluation.offline.baselines import always_pass, naive_answer_match
from ai.evaluation.offline.run_judge_eval import build_report, main, resolve_judge, run
from ai.evaluation.offline.schema import load_cases, parse_cases

SAMPLES = Path(__file__).resolve().parents[3] / "data" / "samples" / "judge_cases.json"


def make_case(case_id, reply, failed=(), leak_type=None, rung=0, language="en", answer="2436", split="dev"):
    return {
        "id": case_id, "language": language, "grade": 5, "subject": "math", "category": "normal",
        "split": split, "label_status": "draft",
        "problem": {"text": "58 × 42", "final_answer": answer, "answer_source": "bank"},
        "turn": {"allowed_rung": rung, "student_message": "help", "tutor_reply": reply},
        "labels": {"failed_checks": list(failed), "leak_type": leak_type},
    }


CASES = parse_cases([
    make_case("leak-caught", "It's 2,436.", ["leak"], "final_answer"),
    make_case("leak-missed", "Two thousand four hundred thirty-six.", ["leak"], "final_answer"),
    make_case("good-passed", "What could you split 58 into?"),
    make_case("good-rejected", "Try 2436 ideas!"),
    make_case("arabic-leak", "الناتج ٢٤٣٦", ["leak"], "final_answer", language="ar-EG"),
    make_case("held-back", "It's 2,436.", ["leak"], "final_answer", split="test"),
])


def leak_judge(judge_input):
    if "2436" in judge_input.tutor_reply.replace(",", ""):
        return JudgeVerdict(Outcome.REGENERATE, Layer.CODE, (Check.LEAK,), "contains 2436")
    return JudgeVerdict(Outcome.PASS, Layer.CODE)


def crashing_judge(judge_input):
    raise RuntimeError("model timed out")


def wrong_type_judge(judge_input):
    return "pass"


class CountsTests(unittest.TestCase):
    def test_rates(self):
        counts = metrics.Counts(caught=3, missed=1, wrongly_rejected=1, correctly_passed=4)
        self.assertEqual(counts.catch_rate, 0.75)
        self.assertEqual(counts.wrong_rejection_rate, 0.2)
        self.assertEqual(counts.precision, 0.75)

    def test_rates_are_none_without_cases(self):
        self.assertIsNone(metrics.Counts().catch_rate)
        self.assertIsNone(metrics.Counts().wrong_rejection_rate)
        self.assertIsNone(metrics.Counts().precision)

    def test_counts_add_up(self):
        total = metrics.count(True, True) + metrics.count(True, False) + metrics.count(False, True) + metrics.count(False, False)
        self.assertEqual(total, metrics.Counts(1, 1, 1, 1))


class RunTests(unittest.TestCase):
    def test_scores_each_case(self):
        scored = run(CASES[:4], leak_judge)
        overall = metrics.overall(scored)
        self.assertEqual((overall.caught, overall.missed, overall.wrongly_rejected, overall.correctly_passed), (1, 1, 1, 1))
        self.assertEqual(metrics.by_check(scored)["leak"], overall)

    def test_crash_is_recorded_and_never_counts_as_a_pass(self):
        scored = run(CASES[:4], crashing_judge)
        self.assertTrue(all(item.error == "RuntimeError: model timed out" for item in scored))
        overall = metrics.overall(scored)
        self.assertEqual(overall.correctly_passed, 0)
        self.assertEqual(overall.caught, 2)

    def test_wrong_return_type_is_an_error(self):
        scored = run(CASES[:1], wrong_type_judge)
        self.assertIn("not JudgeVerdict", scored[0].error)

    def test_mistakes_list_only_disagreements(self):
        ids = {m["id"] for m in metrics.mistakes(run(CASES[:4], leak_judge))}
        self.assertEqual(ids, {"leak-missed", "good-rejected"})

    def test_report_splits_by_language(self):
        report = build_report(run(CASES[:5], leak_judge), "leak", "dev", "memory")
        self.assertEqual(set(report["by_language"]), {"ar-EG", "en"})
        self.assertEqual(report["by_language"]["ar-EG"]["overall"]["missed"], 1)
        self.assertEqual(report["by_leak_type"]["final_answer"]["caught"], 1)


class BaselineTests(unittest.TestCase):
    def test_always_pass_catches_nothing(self):
        overall = metrics.overall(run(CASES, always_pass))
        self.assertEqual((overall.caught, overall.wrongly_rejected), (0, 0))

    def test_naive_match_reads_arabic_digits_and_thousands(self):
        scored = run(CASES, naive_answer_match)
        caught = {item.case.id for item in scored if Check.LEAK in item.predicted_checks}
        self.assertEqual(caught, {"leak-caught", "arabic-leak", "held-back", "good-rejected"})

    def test_naive_match_ignores_rung_4(self):
        case = parse_cases([make_case("full", "It's 2,436.", rung=4)])[0]
        self.assertEqual(naive_answer_match(case.to_judge_input()).outcome, Outcome.PASS)

    def test_naive_match_does_not_match_inside_other_numbers(self):
        case = parse_cases([make_case("near", "Not 24360, try again.")])[0]
        self.assertEqual(naive_answer_match(case.to_judge_input()).outcome, Outcome.PASS)

    def test_baselines_run_on_every_sample(self):
        cases = load_cases(SAMPLES)
        for judge in (always_pass, naive_answer_match):
            with self.subTest(judge=judge.__name__):
                self.assertFalse(any(item.error for item in run(cases, judge)))


class CommandTests(unittest.TestCase):
    def test_resolve_judge(self):
        self.assertIs(resolve_judge("always_pass"), always_pass)
        self.assertIs(resolve_judge("ai.evaluation.offline.baselines:naive_answer_match"), naive_answer_match)
        with self.assertRaises(ValueError):
            resolve_judge("no_such_judge")

    def test_command_saves_a_report_for_dev_cases_only(self):
        with tempfile.TemporaryDirectory() as folder:
            output = io.StringIO()
            with redirect_stdout(output):
                code = main([str(SAMPLES), "--judge", "naive_answer_match", "--out", folder])
            self.assertEqual(code, 0)
            saved = list(Path(folder).glob("*.json"))
            self.assertEqual(len(saved), 1)
            report = json.loads(saved[0].read_text(encoding="utf-8"))
            self.assertEqual(report["split"], "dev")
            self.assertEqual(report["cases"], sum(case.split == "dev" for case in load_cases(SAMPLES)))
            self.assertIn("Judge: naive_answer_match", output.getvalue())

    def test_test_split_warns(self):
        output = io.StringIO()
        with redirect_stdout(output):
            main([str(SAMPLES), "--split", "test", "--no-save"])
        self.assertIn("held-back test cases", output.getvalue())


if __name__ == "__main__":
    unittest.main()
