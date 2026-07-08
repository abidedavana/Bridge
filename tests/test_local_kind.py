"""executor.kind: local — Bridge running ON the GPU box itself (the hackathon's
Jupyter pod path, where there is no SSH hop because Bridge lives on the host).

Found on hardware day: LocalExecutor existed but was not selectable from config,
so `kind: local` failed validation on the pod. These tests pin the wiring."""

from __future__ import annotations

import json
import subprocess

from bridge.agent import Orchestrator, load_prompts
from bridge.agent.orchestrator import RunOutcome
from bridge.cli import _ensure_git_repo
from bridge.config import BridgeConfig
from bridge.executor import LocalExecutor, create_executor
from bridge.llm.replay import ReplayBackend
from bridge.run_state import RunRecorder, RunState
from tests.conftest import REPO_ROOT


def _cfg(tmp_path, **overrides):
    raw = {
        "executor": {"kind": "local"},
        "commands": {
            "hipify": "echo hipify-ok",
            "build": "echo build-ok",
            "test": "echo tests-ok",
        },
        "repo": {"path": str(tmp_path / "repo"), "offload_arch": "gfx1100"},
        "llm": {"backend": "replay", "replay": {"cassette": overrides.pop("cassette")}},
        "prompts_dir": str(REPO_ROOT / "prompts"),
        "runs_dir": str(tmp_path / "runs"),
    }
    raw.update(overrides)
    return BridgeConfig.model_validate(raw)


def _empty_cassette(tmp_path):
    p = tmp_path / "empty.json"
    p.write_text(json.dumps([]), encoding="utf-8")
    return str(p)


def test_local_kind_validates_and_builds_local_executor(tmp_path):
    cfg = _cfg(tmp_path, cassette=_empty_cassette(tmp_path))
    ex = create_executor(cfg)
    assert isinstance(ex, LocalExecutor)
    assert ex.workdir  # bound to repo.path


def test_local_kind_runs_the_loop_for_real_on_this_machine(tmp_path):
    """Green build + green tests on a real local shell -> SUCCESS with zero LLM
    calls (the empty cassette proves the brain was never needed)."""
    cassette = _empty_cassette(tmp_path)
    cfg = _cfg(tmp_path, cassette=cassette)
    _ensure_git_repo(cfg.repo.path)
    ex = create_executor(cfg)
    rec = RunRecorder(str(tmp_path / "state.json"),
                      RunState(run_id="t", scenario="-", executor="local"))
    orch = Orchestrator(cfg, ex, ReplayBackend(cassette), load_prompts(cfg.prompts_dir), rec)
    assert orch.run() is RunOutcome.SUCCESS
    assert rec.state.status == "SUCCESS"


def test_local_executor_really_executes_in_the_repo(tmp_path):
    cfg = _cfg(tmp_path, cassette=_empty_cassette(tmp_path))
    _ensure_git_repo(cfg.repo.path)
    ex = create_executor(cfg)
    res = ex.run("git rev-parse --is-inside-work-tree")
    assert res.ok and "true" in res.stdout
