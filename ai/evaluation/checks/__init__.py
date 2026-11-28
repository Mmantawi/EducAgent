"""Code checks for the judge. Each check returns a Finding, or None if the reply passes."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from ai.evaluation.contract import Check


@dataclass(frozen=True)
class Finding:
    check: Check
    reason: str
    leak_type: Optional[str] = None
