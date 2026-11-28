# Evaluation

Live checks on each tutoring turn (the judge) and, later, offline scoring.

| File | Purpose |
|---|---|
| `contract.py` | Draft input and output format of the judge |
| `normalize.py` | Reads a child's answer in Egyptian Arabic or English: numbers, number words up to the thousands, units, and multiple-choice letters |
| `offline/schema.py` | Format, loading and validation for judge test cases |
| `offline/summary.py` | Shows what a set of test cases covers |
| `offline/LABEL_GUIDE.md` | How to label a case: help rungs, checks and leak types |
| `tests/` | Unit tests, using synthetic data only |

Sample test cases are in `data/samples/judge_cases.json`. To check a case file and see its coverage:

```bash
python -m ai.evaluation.offline.summary data/samples/judge_cases.json
```

## Run the tests

From the repository root, with Python 3.9 or newer and no extra packages:

```bash
python -m unittest discover -s ai/evaluation/tests -t .
```

## Rules

- Code checks run first. The LLM judge handles only what code cannot, and it can reject a reply that passed code but cannot approve one that failed.
- The judge never sets the help rung.
- If an answer cannot be read with confidence, return "cannot check". Never mark a child wrong because of a guess.

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
