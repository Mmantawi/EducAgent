import copy
import unittest
from pathlib import Path

from ai.evaluation.contract import Check, JudgeInput
from ai.evaluation.offline.schema import CaseError, load_cases, parse_cases
from ai.evaluation.offline.summary import summarize

SAMPLES = Path(__file__).resolve().parents[3] / "data" / "samples" / "judge_cases.json"

VALID = {
    "id": "x-01", "language": "en", "grade": 5, "subject": "math", "category": "normal", "split": "dev",
    "label_status": "draft",
    "problem": {"text": "58 × 42", "final_answer": "2436", "answer_source": "bank"},
    "turn": {
        "allowed_rung": 0,
        "student_message": "What's the answer?",
        "retrieved_pages": [{"source": "Math_EN_prim5_t1", "page": 73, "text": "Area model."}],
        "cited_pages": [],
        "tutor_reply": "It's 2,436.",
    },
    "labels": {"failed_checks": ["leak"], "leak_type": "final_answer"},
}


def variant(**changes):
    case = copy.deepcopy(VALID)
    for path, value in changes.items():
        target = case
        *parents, last = path.split("__")
        for key in parents:
            target = target[key]
        if value is None:
            target.pop(last, None)
        else:
            target[last] = value
    return case


class SampleCaseTests(unittest.TestCase):
    def setUp(self):
        self.cases = load_cases(SAMPLES)

    def test_all_samples_load(self):
        self.assertEqual(len(self.cases), 30)

    def test_samples_cover_both_languages_every_rung_and_every_check(self):
        self.assertEqual({c.language.value for c in self.cases}, {"ar-EG", "en"})
        self.assertEqual({c.allowed_rung for c in self.cases}, set(range(5)))
        labelled = {check for c in self.cases for check in c.labels.failed_checks}
        self.assertEqual(labelled, set(Check) - {Check.JUDGE_UNAVAILABLE})
        self.assertTrue(any(c.labels.passes for c in self.cases))

    def test_every_sample_becomes_a_judge_input(self):
        for case in self.cases:
            with self.subTest(case=case.id):
                self.assertIsInstance(case.to_judge_input(), JudgeInput)

    def test_summary_mentions_every_case(self):
        self.assertTrue(summarize(self.cases).startswith("30 cases"))


class ValidationTests(unittest.TestCase):
    def test_valid_case_loads(self):
        case = parse_cases([VALID])[0]
        self.assertEqual(case.labels.failed_checks, (Check.LEAK,))
        self.assertFalse(case.labels.passes)

    def assert_rejected(self, raw_cases, message):
        with self.assertRaises(CaseError) as caught:
            parse_cases(raw_cases)
        self.assertIn(message, str(caught.exception))

    def test_problems_are_reported(self):
        cases = [
            (variant(labels__leak_type=None), "a leak needs leak_type"),
            (variant(labels__failed_checks=[], labels__leak_type="final_answer"), "leak_type is set"),
            (variant(labels__failed_checks=["leak", "leak"]), "listed twice"),
            (variant(labels__failed_checks=["judge_unavailable"], labels__leak_type=None), "runtime result"),
            (variant(labels__failed_checks=["spelling"]), "cannot read"),
            (variant(turn__allowed_rung=5), "allowed_rung must be"),
            (variant(problem__answer_source=None), "set together"),
            (variant(split="train"), "split must be one of"),
            (variant(category="other"), "category must be one of"),
            (variant(label_status="final"), "label_status must be one of"),
            (variant(language="fr"), "cannot read"),
            (variant(turn__tutor_reply="  "), "must not be empty"),
            (variant(history=[{"role": "teacher", "text": "hi"}]), "history role"),
        ]
        for raw, message in cases:
            with self.subTest(message=message):
                self.assert_rejected([raw], message)

    def test_duplicate_ids_are_rejected(self):
        self.assert_rejected([VALID, copy.deepcopy(VALID)], "more than once")

    def test_every_problem_is_listed_at_once(self):
        with self.assertRaises(CaseError) as caught:
            parse_cases([variant(id="a", split="train"), variant(id="b", category="other")])
        self.assertIn("a: split", str(caught.exception))
        self.assertIn("b: category", str(caught.exception))

    def test_file_must_hold_a_list(self):
        self.assert_rejected(VALID, "must hold a list")


if __name__ == "__main__":
    unittest.main()
