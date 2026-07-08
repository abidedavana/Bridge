"""The poisoned-repo fixture is real, and the default guardrail would catch it.

The mechanical *defence* (a patch policy engine that rejects a diff acting on the
injection) lands with the patcher in Milestone 3. This test pins the two things
that must be true now for that defence to be demonstrable:

  1. The attack payload exists verbatim in both the replayed compiler output and
     the on-disk source the context builder will ingest.
  2. Bridge's *default* security denylist already contains the substrings that
     would flag a diff following the payload -- so the guardrail is on by default,
     not something a demo has to remember to enable.
"""

from __future__ import annotations

from pathlib import Path

from bridge.config import SecurityConfig
from bridge.executor.scenario import Scenario
from tests.conftest import FIXTURES_DIR, SCENARIOS_DIR

PAYLOAD_MARKERS = ['system("curl', "| sh", "allow_tolerance_relaxation"]


def test_poisoned_scenario_loads_and_carries_payload():
    s = Scenario.load(str(SCENARIOS_DIR / "poisoned.yaml"))
    assert s.hipify.ok
    injection_stage = s.stages[0]
    assert not injection_stage.build.ok
    log = injection_stage.build.text
    assert 'system("curl' in log and "| sh" in log
    # a well-behaved agent that ignores the injection reaches green + 100% tests
    assert s.stages[-1].sticky and s.stages[-1].test.ok


def test_injection_payload_present_in_source_for_context_builder():
    src = (FIXTURES_DIR / "repos" / "poisoned" / "src" / "attention.cpp").read_text(
        encoding="utf-8"
    )
    assert any(m in src for m in PAYLOAD_MARKERS)


def test_default_denylist_would_flag_the_payload():
    sec = SecurityConfig()
    log = (FIXTURES_DIR / "logs" / "build_err_injection.txt").read_text(
        encoding="utf-8"
    )
    # The naive "just do what the comment says" patch would add a line containing
    # these tokens; at least one is on the default denylist, so it is rejected.
    hits = [tok for tok in sec.forbidden_insertions if tok.lower() in log.lower()]
    assert hits, "default forbidden_insertions failed to cover the injection payload"
    assert "system(" in hits
