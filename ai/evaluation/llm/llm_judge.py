"""The LLM layer of the judge.

make_llm_judge wraps a provider. It asks the model for a JSON verdict, retries once if
the call fails or the output cannot be read, and then fails closed: the verdict is
FALLBACK with judge_unavailable, never a pass.
"""
from __future__ import annotations

import json
import re
from typing import Callable, Optional, Tuple

from ai.evaluation.contract import Check, JudgeInput, JudgeVerdict, Layer, Outcome
from ai.evaluation.llm.prompt import PROMPT_VERSION, SYSTEM, build_user_prompt
from ai.evaluation.llm.providers import Provider, ProviderError

# Citations are checked in code only.
LLM_CHECKS = (Check.LEAK, Check.GROUNDING, Check.LANGUAGE, Check.READING_LEVEL, Check.SAFETY)
LEAK_TYPES = ("final_answer", "too_many_steps")
_TRUE = {True, "true", "yes", 1}
_FALSE = {False, "false", "no", 0, None}


def parse_verdict(text: str) -> Tuple[Tuple[Check, ...], Optional[str], str]:
    """Read the model's JSON. Raises ValueError if it is missing or malformed."""
    match = re.search(r"\{.*\}", text, flags=re.S)
    if not match:
        raise ValueError("No JSON object in the model output.")
    data = json.loads(match.group())
    if not isinstance(data, dict):
        raise ValueError("The model output is not a JSON object.")
    failed = []
    for check in LLM_CHECKS:
        value = data.get(check.value, False)
        if isinstance(value, str):
            value = value.strip().lower()
        if value in _TRUE:
            failed.append(check)
        elif value not in _FALSE:
            raise ValueError(f"{check.value} must be true or false, got {value!r}.")
    leak_type = data.get("leak_type")
    if Check.LEAK in failed and leak_type not in LEAK_TYPES:
        leak_type = "final_answer"
    reason = str(data.get("reason") or "").strip()
    return tuple(failed), leak_type if Check.LEAK in failed else None, reason


def make_llm_judge(provider: Provider, retries: int = 1) -> Callable[[JudgeInput], JudgeVerdict]:
    def judge(judge_input: JudgeInput) -> JudgeVerdict:
        user = build_user_prompt(judge_input)
        problem = ""
        for _ in range(retries + 1):
            try:
                failed, leak_type, reason = parse_verdict(provider.complete(SYSTEM, user))
            except (ProviderError, ValueError) as error:
                problem = f"{type(error).__name__}: {error}"
                continue
            if not failed:
                return JudgeVerdict(Outcome.PASS, Layer.LLM)
            detail = f" ({leak_type})" if leak_type else ""
            return JudgeVerdict(Outcome.REGENERATE, Layer.LLM, failed, f"{reason}{detail} [{provider.name}, {PROMPT_VERSION}]")
        return JudgeVerdict(
            Outcome.FALLBACK,
            Layer.LLM,
            (Check.JUDGE_UNAVAILABLE,),
            f"The LLM judge could not give a verdict: {problem} [{provider.name}]",
        )

    return judge
