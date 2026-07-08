"""Patcher: the mechanical gate + apply step for LLM-generated diffs.

    check_diff(diff, config) -> PolicyResult      the trust gate (pure)
    apply_patch(executor, diff, config) -> PatchResult
"""

from __future__ import annotations

from .apply import PatchResult, apply_patch
from .policy import DiffFacts, PolicyResult, check_diff, parse_diff

__all__ = [
    "check_diff",
    "parse_diff",
    "apply_patch",
    "PolicyResult",
    "PatchResult",
    "DiffFacts",
]
