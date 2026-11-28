# Evaluation

Live checks on each tutoring turn (the judge) and, later, offline scoring.

| File | Purpose |
|---|---|
| `contract.py` | Draft input and output format of the judge |
| `normalize.py` | Reads a child's answer in Egyptian Arabic or English: numbers, number words up to the thousands, units, and multiple-choice letters |
| `answer_checker.py` | Marks a math answer as correct, wrong, partly right or cannot check, against the answer key |
| `offline/run_answer_eval.py` | Scores the answer checker on labelled answer cases |
| `offline/schema.py` | Format, loading and validation for judge test cases |
| `offline/summary.py` | Shows what a set of test cases covers |
| `offline/LABEL_GUIDE.md` | How to label a case: help rungs, checks and leak types |
| `offline/run_judge_eval.py` | Scores a judge on the test cases and saves a report |
| `offline/metrics.py` | Catch rate and wrong rejections, per check, language and leak type |
| `offline/baselines.py` | Two simple judges to compare real ones against |
| `tests/` | Unit tests, using synthetic data only |

Sample test cases are in `data/samples/judge_cases.json`. To check a case file and see its coverage:

```bash
python -m ai.evaluation.offline.summary data/samples/judge_cases.json
```

To score a judge on the `dev` cases and save a report to `artifacts/judge_eval/`, which Git ignores:

```bash
python -m ai.evaluation.offline.run_judge_eval data/samples/judge_cases.json --judge naive_answer_match
```

`--judge` takes `always_pass`, `naive_answer_match`, or `package.module:function` for any function that takes a `JudgeInput` and returns a `JudgeVerdict`. Add `--split test` only for final results, and never tune the judge on them.

The two numbers to read together:

- **Catch rate:** of the replies a check should fail, the share it does fail.
- **Wrong rejections:** of the replies a check should pass, the share it fails anyway.

A judge that crashes on a case is reported as an error and never counts as a pass.

## Run the tests

From the repository root, with Python 3.9 or newer and no extra packages:

```bash
python -m unittest discover -s ai/evaluation/tests -t .
```

## Rules

- Code checks run first. The LLM judge handles only what code cannot, and it can reject a reply that passed code but cannot approve one that failed.
- The judge never sets the help rung.
- If an answer cannot be read with confidence, return "cannot check". Never mark a child wrong because of a guess.

## Checking answers

`check_answer(student_text, answer_key)` returns one of:

| Result | When |
|---|---|
| `correct` | The same value in any form or unit, such as `0.43 لتر` for `430 مل` |
| `wrong` | A readable answer with a different value, or a unit of the wrong kind |
| `partial` | The right number with its unit missing, or some right choices with nothing wrong added |
| `cannot_check` | The answer or key could not be read, or a bare number is only right in another unit (`4380` for `4.38 كجم`) |

There is no rounding tolerance yet. To score the checker on the answer cases from the grade 5 book:

```bash
python -m ai.evaluation.offline.run_answer_eval data/samples/answer_cases.json
```

It fails if agreement is below 98% or if any correct answer is marked wrong.

## Reading answers

- `parse_number` reads one bare number, such as `٣/٤`, `.75`, `2 1/2` or `خمسة وعشرين`.
- `parse_answer` also accepts a short lead-in (`الإجابة هي`, `the answer is`, `p =`), a unit (`5 سم`, `4.38 كجم`), or choice letters (`أ، جـ، و`).
- Quantities compare across units with `in_base_unit()`, so `1.5 م` equals `150 سم`.
- Unclear answers return `None`: `2,4` could be a list or a decimal, `كيلو` alone could be kilograms or kilometres, and `أ و جـ` without commas could mean "a and c".
- Not handled yet: clock times (`3:15`), remainders (`11 الباقي 8`), and units written before the number.

## Inputs and outputs

- **Input:** `JudgeInput` holds the student message, tutor reply, allowed rung, grade, language, retrieved and cited pages, and the final answer with its source when known.
- **Output:** `JudgeVerdict` holds the outcome (`pass`, `regenerate` or `fallback`), the layer that decided, the failed checks and a reason.
- **Citations:** these use `(source, page)` to match the output of `retrieve_pages` in `ai/CurriculumRAG.ipynb`.
