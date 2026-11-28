"""Score a judge on labelled test cases and save a report.

Usage, from the repository root:
    python -m ai.evaluation.offline.run_judge_eval data/samples/judge_cases.json --judge naive_answer_match

--judge takes a baseline name (always_pass, naive_answer_match) or "package.module:function".
--split defaults to dev. Score the held-back test cases only for final results.
Reports are saved to artifacts/judge_eval/, which Git ignores.
"""
from __future__ import annotations

import argparse
import importlib
import json
import sys
import time
from datetime import datetime
from pathlib import Path
from statistics import mean
from typing import Callable, List, Optional, Sequence

from ai.evaluation.contract import JudgeInput, JudgeVerdict
from ai.evaluation.offline import metrics
from ai.evaluation.offline.baselines import JUDGES
from ai.evaluation.offline.schema import Case, load_cases

Judge = Callable[[JudgeInput], JudgeVerdict]
DEFAULT_OUTPUT = Path("artifacts") / "judge_eval"


def resolve_judge(name: str) -> Judge:
    if name in JUDGES:
        return JUDGES[name]
    if ":" not in name:
        raise ValueError(f"Unknown judge {name!r}. Use one of {sorted(JUDGES)} or 'package.module:function'.")
    module_name, attribute = name.split(":", 1)
    return getattr(importlib.import_module(module_name), attribute)


def run(cases: Sequence[Case], judge: Judge) -> List[metrics.Scored]:
    scored = []
    for case in cases:
        started = time.perf_counter()
        verdict: Optional[JudgeVerdict] = None
        error = None
        try:
            verdict = judge(case.to_judge_input())
            if not isinstance(verdict, JudgeVerdict):
                error, verdict = f"judge returned {type(verdict).__name__}, not JudgeVerdict", None
        except Exception as exc:  # A crash is a result to report, not a reason to stop.
            error = f"{type(exc).__name__}: {exc}"
        scored.append(metrics.Scored(case, verdict, time.perf_counter() - started, error))
    return scored


def _section(scored: Sequence[metrics.Scored]) -> dict:
    return {
        "cases": len(scored),
        "overall": metrics.overall(scored).as_dict(),
        "by_check": {name: counts.as_dict() for name, counts in metrics.by_check(scored).items()},
    }


def build_report(scored: Sequence[metrics.Scored], judge_name: str, split: str, source: str) -> dict:
    seconds = [item.seconds for item in scored]
    return {
        "judge": judge_name,
        "cases_file": source,
        "split": split,
        "created": datetime.now().isoformat(timespec="seconds"),
        **_section(scored),
        "by_language": {key: _section(group) for key, group in metrics.group_by(scored, lambda c: c.language.value).items()},
        "by_category": {key: metrics.overall(group).as_dict() for key, group in metrics.group_by(scored, lambda c: c.category).items()},
        "by_leak_type": {key: counts.as_dict() for key, counts in metrics.by_leak_type(scored).items()},
        "errors": sum(1 for item in scored if item.error),
        "seconds": {"mean": mean(seconds) if seconds else None, "max": max(seconds, default=None)},
        "label_status": sorted({item.case.label_status for item in scored}),
        "mistakes": metrics.mistakes(scored),
    }


def _rate(value: Optional[float]) -> str:
    return "-" if value is None else f"{value:.0%}"


def format_report(report: dict) -> str:
    def row(name: str, counts: dict) -> str:
        return (
            f"{name:<16}{counts['caught']:>4}/{counts['caught'] + counts['missed']:<4}{_rate(counts['catch_rate']):>7}"
            f"{counts['wrongly_rejected']:>6}/{counts['wrongly_rejected'] + counts['correctly_passed']:<4}"
            f"{_rate(counts['wrong_rejection_rate']):>7}"
        )

    header = f"{'':<16}{'caught':>9}{'rate':>7}{'wrongly rejected':>17}"
    lines = [
        f"Judge: {report['judge']} | split: {report['split']} | cases: {report['cases']} | errors: {report['errors']}",
        f"Labels: {', '.join(report['label_status'])}",
        "",
        header,
        row("any check", report["overall"]),
    ]
    lines += [row(name, counts) for name, counts in report["by_check"].items()]
    for language, section in report["by_language"].items():
        lines += ["", f"{language} ({section['cases']} cases)", header, row("any check", section["overall"])]
        lines += [row(name, counts) for name, counts in section["by_check"].items() if counts["caught"] + counts["missed"]]
    if report["by_leak_type"]:
        lines += ["", "Leaks by type", header]
        lines += [row(name, counts) for name, counts in report["by_leak_type"].items()]
    lines += ["", f"Disagreements: {len(report['mistakes'])} (listed in the saved report)"]
    return "\n".join(lines)


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Score a judge on labelled test cases.")
    parser.add_argument("cases", help="JSON file of test cases")
    parser.add_argument("--judge", default="always_pass")
    parser.add_argument("--split", choices=("dev", "test", "all"), default="dev")
    parser.add_argument("--out", default=str(DEFAULT_OUTPUT), help="folder for the saved report")
    parser.add_argument("--no-save", action="store_true")
    args = parser.parse_args(argv)

    cases = load_cases(args.cases)
    if args.split != "all":
        cases = [case for case in cases if case.split == args.split]
    if args.split != "dev":
        print("Scoring held-back test cases. Do not tune the judge on these results.\n")
    if not cases:
        print(f"No {args.split} cases in {args.cases}.")
        return 1

    report = build_report(run(cases, resolve_judge(args.judge)), args.judge, args.split, args.cases)
    print(format_report(report))
    if not args.no_save:
        folder = Path(args.out)
        folder.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        safe_name = args.judge.replace(":", "-").replace(".", "-")
        path = folder / f"{stamp}_{safe_name}_{args.split}.json"
        path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\nSaved {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
