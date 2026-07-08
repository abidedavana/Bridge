"""RunState: the single serialisable record of a run, and what the dashboard reads.

The orchestrator (and, today, the mock-demo driver) writes a `RunState` to a JSON
file after every iteration via `RunRecorder`. The dashboard process reads that
file and renders it. This file *is* the contract between the loop and the UI, and
it doubles as the persisted run log the spec requires ("every error, diagnosis,
diff, timing, token count").

Decoupling through a file (rather than a shared object) is deliberate: the run and
the dashboard are separate processes — `python -m bridge dashboard` in one
terminal, `python -m bridge mock-demo` in another — and neither needs to import
the other. Writes are atomic (temp + os.replace) so the dashboard never reads a
half-written file.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import asdict, dataclass, field
from typing import Optional


@dataclass
class IterationRecord:
    iteration: int
    phase: str                       # hipify | build | test
    outcome: str                     # ok | fail
    error_class: Optional[str] = None      # primary diagnostic's class this iter
    location: Optional[str] = None         # file:line of the primary diagnostic
    message: Optional[str] = None
    error_classes: list[str] = field(default_factory=list)  # all classes seen
    passed: Optional[int] = None
    total: Optional[int] = None
    diff: Optional[str] = None        # M3 fills this; None in mock-demo
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost: float = 0.0
    duration_s: float = 0.0


@dataclass
class RunState:
    run_id: str
    scenario: str
    executor: str                    # mock | ssh
    status: str = "RUNNING"          # RUNNING | SUCCESS | PARTIAL | STUCK
    # endpoint badge — proves where the brain runs
    llm_backend: str = ""
    llm_model: str = ""
    llm_host: str = ""
    cost_mode: str = "priced"        # priced | self_hosted
    cost_currency: str = "USD"
    simulated_cost: bool = False     # true while no real LLM is in the loop
    # HIPIFY headline ("converted X%")
    hipify_conversion_pct: Optional[int] = None
    hipify_warnings: Optional[int] = None
    # cumulative counters
    total_prompt_tokens: int = 0
    total_completion_tokens: int = 0
    total_cost: float = 0.0
    # timeline
    current: Optional[IterationRecord] = None
    iterations: list[IterationRecord] = field(default_factory=list)
    started_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return asdict(self)


class RunRecorder:
    """Owns a RunState and flushes it to JSON after every change."""

    def __init__(self, path: str, state: RunState):
        self.path = os.path.abspath(path)
        self.state = state
        os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
        self._flush()

    def add(self, rec: IterationRecord) -> None:
        self.state.iterations.append(rec)
        self.state.current = rec
        self.state.total_prompt_tokens += rec.prompt_tokens
        self.state.total_completion_tokens += rec.completion_tokens
        self.state.total_cost += rec.cost
        self._flush()

    def set_hipify(self, conversion_pct: Optional[int], warnings: Optional[int]) -> None:
        self.state.hipify_conversion_pct = conversion_pct
        self.state.hipify_warnings = warnings
        self._flush()

    def finish(self, status: str) -> None:
        self.state.status = status
        self._flush()

    def _flush(self) -> None:
        self.state.updated_at = time.time()
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(self.state.to_dict(), fh, indent=2)
        os.replace(tmp, self.path)  # atomic on the same filesystem


def load_state(path: str) -> Optional[dict]:
    """Read a run-state JSON file, or None if no run has started."""
    if not os.path.exists(path):
        return None
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)
