"""Score the answer checker on labelled answer cases.

Usage, from the repository root:
    python -m ai.evaluation.offline.run_answer_eval data/samples/answer_cases.json

Each case has an answer_key, a student_answer and the expected result. The command
prints agreement, a table of expected against actual results, and every
disagreement. It exits with 1 if agreement is below the target or if any correct
answer was marked wrong, the mistake that hurts a child most.
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path
from typing import List, Optional

from ai.evaluation.answer_checker import Result, check_answer

TARGET_AGREEMENT = 0.98
RESULTS = [result.value for result in Result]


def evaluate(cases: List[dict]) -> dict:
    ids = [case["id"] for case in cases]
    duplicates = sorted(i for i, n in Counter(ids).items() if n > 1)
    if duplicates:
        raise ValueError(f"Duplicate ids: {duplicates}")
    rows, table = [], Counter()
    for case in cases:
        if case["expected"] not in RESULTS:
            raise ValueError(f"{case['id']}: expected must be one of {RESULTS}")
        check = check_answer(case["student_answer"], case["answer_key"])
        table[(case["expected"], check.result.value)] += 1
        rows.append({**case, "got": check.result.value, "reason": check.reason})
    agreed = sum(1 for row in rows if row["got"] == row["expected"])
    return {
        "cases": len(rows),
        "agreement": agreed / len(rows) if rows else None,
        "correct_marked_wrong": [row for row in rows if row["expected"] == "correct" and row["got"] == "wrong"],
        "wrong_marked_correct": [row for row in rows if row["expected"] == "wrong" and row["got"] == "correct"],
        "table": {f"{expected}->{got}": n for (expected, got), n in sorted(table.items())},
        "disagreements": [row for row in rows if row["got"] != row["expected"]],
    }


def passes(report: dict) -> bool:
    return bool(report["cases"]) and report["agreement"] >= TARGET_AGREEMENT and not report["correct_marked_wrong"]


def format_report(report: dict) -> str:
    lines = [
        f"{report['cases']} cases | agreement {report['agreement']:.1%} (target {TARGET_AGREEMENT:.0%})",
        f"Correct answers marked wrong: {len(report['correct_marked_wrong'])} (must be 0)",
        f"Wrong answers marked correct: {len(report['wrong_marked_correct'])}",
        "",
        f"{'expected':<14}" + "".join(f"{result:>14}" for result in RESULTS),
    ]
    for expected in RESULTS:
        counts = [report["table"].get(f"{expected}->{got}", 0) for got in RESULTS]
        lines.append(f"{expected:<14}" + "".join(f"{n:>14}" for n in counts))
    if report["disagreements"]:
        lines += ["", "Disagreements"]
        for row in report["disagreements"]:
            lines.append(f"  {row['id']}: {row['student_answer']!r} vs key {row['answer_key']!r}: expected {row['expected']}, got {row['got']} ({row['reason']})")
    lines += ["", "PASS" if passes(report) else "FAIL"]
    return "\n".join(lines)


def main(argv: Optional[List[str]] = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 1:
        print(__doc__.strip())
        return 2
    report = evaluate(json.loads(Path(argv[0]).read_text(encoding="utf-8")))
    print(format_report(report))
    return 0 if passes(report) else 1


if __name__ == "__main__":
    sys.exit(main())
