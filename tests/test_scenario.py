"""Scenario loader: bundles are self-contained and validated at load time."""

from __future__ import annotations

import pytest

from bridge.executor.scenario import Scenario


def test_success_scenario_shape(scenarios_dir):
    s = Scenario.load(str(scenarios_dir / "success.yaml"))
    assert s.name == "success"
    assert s.hipify.ok
    assert len(s.stages) == 8
    # first stage is a failing build; last stage is a sticky green all-pass
    assert not s.stages[0].build.ok
    assert s.stages[-1].sticky
    assert s.stages[-1].test is not None and s.stages[-1].test.ok
    assert s.stages[-1].test.passed == 5 and s.stages[-1].test.total == 5


def test_partial_scenario_ends_sticky_below_100(scenarios_dir):
    s = Scenario.load(str(scenarios_dir / "partial.yaml"))
    last = s.stages[-1]
    assert last.sticky
    assert last.test is not None
    assert not last.test.ok
    assert last.test.passed == 4 and last.test.total == 5


def test_stuck_build_never_reaches_tests(scenarios_dir):
    s = Scenario.load(str(scenarios_dir / "stuck_build.yaml"))
    assert s.stages[-1].sticky
    assert not s.stages[-1].build.ok
    # a build-stuck scenario has no test specs at all
    assert all(st.test is None for st in s.stages)


def test_fixture_logs_are_nonempty(scenarios_dir):
    s = Scenario.load(str(scenarios_dir / "success.yaml"))
    assert s.hipify.text.strip()
    for st in s.stages:
        assert st.build.text.strip()


def test_missing_log_fails_loudly(tmp_path):
    bad = tmp_path / "bad.yaml"
    bad.write_text(
        "name: bad\nhipify:\n  log: nope.txt\nstages:\n"
        "  - name: s\n    build: { log: nope.txt }\n",
        encoding="utf-8",
    )
    with pytest.raises(FileNotFoundError):
        Scenario.load(str(bad))


def test_empty_stages_rejected(tmp_path, scenarios_dir):
    # reference a real hipify log so we get past that check, then fail on stages
    hip = scenarios_dir / ".." / "logs" / "hipify_run.txt"
    bad = tmp_path / "bad.yaml"
    bad.write_text(
        f"name: bad\nhipify:\n  log: {hip.resolve().as_posix()}\nstages: []\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError):
        Scenario.load(str(bad))
