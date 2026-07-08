"""The agent: context builder, LLM stages, and the orchestrator state machine.

    build_context(...)          assemble the bounded evidence the LLM sees
    diagnose / propose_edit     the two LLM stages (single-retry hardened)
    Orchestrator                the explicit parse->diagnose->patch->commit loop
"""

from __future__ import annotations

from .context import ContextBundle, build_context, resolve_repo_path
from .orchestrator import Orchestrator, RunOutcome
from .stages import diagnose, load_prompts, propose_edit

__all__ = [
    "build_context",
    "resolve_repo_path",
    "ContextBundle",
    "diagnose",
    "propose_edit",
    "load_prompts",
    "Orchestrator",
    "RunOutcome",
]
