"""Reject citations of pages that were not retrieved for this turn.

A reply that cites nothing passes. Whether every reply must cite a page is still a
team decision, and whether a cited page supports the claim is the grounding check.
"""
from __future__ import annotations

from typing import Optional

from ai.evaluation.checks import Finding
from ai.evaluation.contract import Check, JudgeInput


def check_citation(judge_input: JudgeInput) -> Optional[Finding]:
    retrieved = {page.ref for page in judge_input.retrieved_pages}
    unknown = [ref for ref in judge_input.cited_pages if ref not in retrieved]
    if not unknown:
        return None
    listed = ", ".join(f"{ref.source} p.{ref.page}" for ref in unknown)
    return Finding(Check.CITATION, f"Cites pages that were not retrieved: {listed}.")
