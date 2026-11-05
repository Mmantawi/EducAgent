# Evaluation

Live checks on each tutoring turn (the judge) and, later, offline scoring.

| File | Purpose |
|---|---|
| `contract.py` | Draft input and output format of the judge |
| `normalize.py` | Reads numeric answers in Egyptian Arabic and English as exact values |
| `tests/` | Unit tests, using synthetic data only |

## Run the tests

From the repository root, with Python 3.9 or newer and no extra packages:

```bash
python -m unittest discover -s ai/evaluation/tests -t .
```

## Rules

- Code checks run first. The LLM judge handles only what code cannot, and it can reject a reply that passed code but cannot approve one that failed.
- The judge never sets the help rung.
- If an answer cannot be read with confidence, return "cannot check". Never mark a child wrong because of a guess.

## Inputs and outputs

- **Input:** `JudgeInput` holds the student message, tutor reply, allowed rung, grade, language, retrieved and cited pages, and the final answer with its source when known.
- **Output:** `JudgeVerdict` holds the outcome (`pass`, `regenerate` or `fallback`), the layer that decided, the failed checks and a reason.
- **Citations:** these use `(source, page)` to match the output of `retrieve_pages` in `ai/CurriculumRAG.ipynb`.
