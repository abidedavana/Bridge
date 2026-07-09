"""`bridge run` must be repeatable — a judge (or you) will run the offline demo
more than once. Regression for the STUCK-on-second-run bug where stale files from
a prior run collided with the cassette's new-file patches.

Also pins the report wording: a class whose cluster ended STUCK is never listed
under "fixed autonomously", even when attempts on it applied diffs."""

from __future__ import annotations

import ast
import json

import yaml

from bridge.cli import main
from tests.conftest import REPO_ROOT


def test_bridge_run_is_repeatable(tmp_path):
    cfg = {
        "executor": {"kind": "mock", "mock": {"scenario": str(REPO_ROOT / "fixtures/scenarios/success.yaml")}},
        "commands": {"hipify": "hipify-perl", "build": "cmake --build build", "test": "ctest"},
        "repo": {"path": str(tmp_path / "scratch")},
        "llm": {"backend": "replay", "replay": {"cassette": str(REPO_ROOT / "fixtures/cassettes/success.json")}},
        "prompts_dir": str(REPO_ROOT / "prompts"),
        "runs_dir": str(tmp_path / "runs"),
        "caps": {"max_iterations": 40, "max_attempts_per_cluster": 3},
    }
    cfg_path = tmp_path / "c.yaml"
    cfg_path.write_text(yaml.safe_dump(cfg), encoding="utf-8")
    state_path = tmp_path / "runs" / "current.json"

    for attempt in range(2):
        assert main(["run", "--config", str(cfg_path)]) == 0
        state = json.loads(state_path.read_text(encoding="utf-8"))
        assert state["status"] == "SUCCESS", f"run {attempt + 1} was {state['status']}"
        assert any(it["diff"] for it in state["iterations"])  # diffs really applied


def test_run_refuses_to_reset_a_non_bridge_directory(tmp_path):
    """The mock-mode scratch reset must never delete a directory Bridge did not
    itself create: a mock config whose repo.path points at a real folder is
    protected by the provenance-marker check."""
    import pytest

    victim = tmp_path / "important"
    victim.mkdir()
    (victim / "thesis.txt").write_text("do not delete", encoding="utf-8")
    cfg = {
        "executor": {"kind": "mock", "mock": {"scenario": str(REPO_ROOT / "fixtures/scenarios/success.yaml")}},
        "commands": {"hipify": "hipify-perl", "build": "cmake --build build", "test": "ctest"},
        "repo": {"path": str(victim)},
        "llm": {"backend": "replay", "replay": {"cassette": str(REPO_ROOT / "fixtures/cassettes/success.json")}},
        "prompts_dir": str(REPO_ROOT / "prompts"),
        "runs_dir": str(tmp_path / "runs"),
    }
    cfg_path = tmp_path / "c.yaml"
    cfg_path.write_text(yaml.safe_dump(cfg), encoding="utf-8")

    with pytest.raises(SystemExit) as exc:
        main(["run", "--config", str(cfg_path)])
    assert exc.value.code == 2
    assert (victim / "thesis.txt").exists()  # nothing was deleted


def test_partial_report_never_lists_a_class_as_both_fixed_and_stuck(tmp_path, capsys):
    from tests.test_orchestrator import write_cassette

    cfg = {
        "executor": {"kind": "mock", "mock": {"scenario": str(REPO_ROOT / "fixtures/scenarios/partial.yaml")}},
        "commands": {"hipify": "hipify-perl", "build": "cmake --build build", "test": "ctest"},
        "repo": {"path": str(tmp_path / "scratch")},
        "llm": {"backend": "replay", "replay": {"cassette": write_cassette(tmp_path / "c.json")}},
        "prompts_dir": str(REPO_ROOT / "prompts"),
        "runs_dir": str(tmp_path / "runs"),
        "caps": {"max_iterations": 40, "max_attempts_per_cluster": 3},
    }
    cfg_path = tmp_path / "c.yaml"
    cfg_path.write_text(yaml.safe_dump(cfg), encoding="utf-8")

    assert main(["run", "--config", str(cfg_path)]) == 0
    state = json.loads((tmp_path / "runs" / "current.json").read_text(encoding="utf-8"))
    assert state["status"] == "PARTIAL"

    report = {}
    for line in capsys.readouterr().out.splitlines():
        if ":" in line and line.lstrip().startswith(("error classes fixed autonomously", "STUCK clusters")):
            key, _, value = line.partition(":")
            report[key.strip()] = ast.literal_eval(value.strip())
    fixed = set(report["error classes fixed autonomously"])
    stuck = set(report["STUCK clusters"])
    assert stuck, "PARTIAL run must report its stuck cluster"
    assert not fixed & stuck, f"classes listed as both fixed and stuck: {fixed & stuck}"
    # The stuck class DID have applied diffs along the way — without the filter it
    # would have been double-listed, so this pins the actual regression.
    assert any(it["diff"] and it["error_class"] in stuck for it in state["iterations"])
