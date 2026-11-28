"""Print what a set of judge test cases covers.

Usage, from the repository root:
    python -m ai.evaluation.offline.summary data/samples/judge_cases.json
"""
from __future__ import annotations

import sys
from collections import Counter
from typing import List

from ai.evaluation.offline.schema import LABELLED_CHECKS, Case, load_cases


def summarize(cases: List[Case]) -> str:
    languages = sorted({case.language.value for case in cases})
    lines = [f"{len(cases)} cases"]

    def table(title, keys, count):
        lines.append(f"\n{title}")
        lines.append(f"{'':<16}" + "".join(f"{language:>8}" for language in languages) + f"{'total':>8}")
        for key in keys:
            counts = [count(key, language) for language in languages]
            lines.append(f"{str(key):<16}" + "".join(f"{c:>8}" for c in counts) + f"{sum(counts):>8}")

    table("Rung", range(5), lambda rung, lang: sum(c.allowed_rung == rung and c.language.value == lang for c in cases))
    table("Result", ("pass", "fail"), lambda result, lang: sum(
        (c.labels.passes == (result == "pass")) and c.language.value == lang for c in cases
    ))
    table("Failed check", [check.value for check in LABELLED_CHECKS], lambda check, lang: sum(
        check in {f.value for f in c.labels.failed_checks} and c.language.value == lang for c in cases
    ))
    table("Leak type", ("final_answer", "too_many_steps"), lambda kind, lang: sum(
        c.labels.leak_type == kind and c.language.value == lang for c in cases
    ))
    table("Category", ("normal", "attack"), lambda kind, lang: sum(c.category == kind and c.language.value == lang for c in cases))
    table("Split", ("dev", "test"), lambda split, lang: sum(c.split == split and c.language.value == lang for c in cases))

    status = Counter(case.label_status for case in cases)
    lines.append(f"\nLabel status: {dict(status)}")
    missing = [check.value for check in LABELLED_CHECKS if not any(check in c.labels.failed_checks for c in cases)]
    if missing:
        lines.append(f"No failing example yet for: {', '.join(missing)}")
    return "\n".join(lines)


def main(argv: List[str]) -> int:
    if len(argv) != 2:
        print(__doc__.strip())
        return 2
    print(summarize(load_cases(argv[1])))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
