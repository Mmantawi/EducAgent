"""The code layer of the judge: every check that runs without a model.

judge() runs all code checks and returns one verdict. A reply that fails any check
gets REGENERATE with every failed check listed. The LLM layer (step 7) will run only
on replies that pass here, and can only add failures, never remove them.

Score it with:
    python -m ai.evaluation.offline.run_judge_eval data/samples/judge_cases.json --judge ai.evaluation.code_judge:judge
"""
from __future__ import annotations

from typing import Callable, List, Optional

from ai.evaluation.checks import Finding
from ai.evaluation.checks.citation import check_citation
from ai.evaluation.checks.language import check_language, check_length
from ai.evaluation.checks.leak import check_leak
from ai.evaluation.checks.tone import check_tone
from ai.evaluation.contract import JudgeInput, JudgeVerdict, Layer, Outcome

CHECKS: List[Callable[[JudgeInput], Optional[Finding]]] = [
    check_leak,
    check_citation,
    check_language,
    check_length,
    check_tone,
]


def findings(judge_input: JudgeInput) -> List[Finding]:
    return [finding for finding in (check(judge_input) for check in CHECKS) if finding]


def judge(judge_input: JudgeInput) -> JudgeVerdict:
    found = findings(judge_input)
    if not found:
        return JudgeVerdict(Outcome.PASS, Layer.CODE)
    return JudgeVerdict(
        Outcome.REGENERATE,
        Layer.CODE,
        tuple(finding.check for finding in found),
        " ".join(finding.reason for finding in found),
    )
