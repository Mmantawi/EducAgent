"""The full judge: code checks first, then the LLM layer.

Rules:
- If any code check fails, that verdict stands. The LLM is not asked, so it can never
  overrule a code failure.
- If code passes, the LLM may add failures. If the LLM cannot answer, the verdict is
  FALLBACK, never a pass.

For the scoring command, env_judge builds the LLM provider from environment variables
(see llm/providers.py), and env_llm_only scores the LLM layer on its own:
    LLM_PROVIDER=ollama LLM_MODEL=qwen2.5:7b-instruct \\
        python -m ai.evaluation.offline.run_judge_eval data/samples/judge_cases.json --judge ai.evaluation.judge:env_judge
"""
from __future__ import annotations

from typing import Callable, Optional

from ai.evaluation import code_judge
from ai.evaluation.contract import JudgeInput, JudgeVerdict, Outcome
from ai.evaluation.llm.llm_judge import make_llm_judge
from ai.evaluation.llm.providers import provider_from_env

Judge = Callable[[JudgeInput], JudgeVerdict]


def make_layered_judge(llm_judge: Optional[Judge] = None) -> Judge:
    def judge(judge_input: JudgeInput) -> JudgeVerdict:
        verdict = code_judge.judge(judge_input)
        if verdict.outcome is not Outcome.PASS or llm_judge is None:
            return verdict
        return llm_judge(judge_input)

    return judge


_from_env = {}


def _cached(key: str, build: Callable[[], Judge]) -> Judge:
    if key not in _from_env:
        _from_env[key] = build()
    return _from_env[key]


def env_judge(judge_input: JudgeInput) -> JudgeVerdict:
    return _cached("layered", lambda: make_layered_judge(make_llm_judge(provider_from_env())))(judge_input)


def env_llm_only(judge_input: JudgeInput) -> JudgeVerdict:
    return _cached("llm", lambda: make_llm_judge(provider_from_env()))(judge_input)
