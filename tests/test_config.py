"""Config schema: validation is strict and fails early with clear messages."""

from __future__ import annotations

import os

import pytest
import yaml
from pydantic import ValidationError

from bridge.config import BridgeConfig
from tests.conftest import REPO_ROOT


def test_example_config_loads_and_resolves_scenario():
    cfg = BridgeConfig.load(str(REPO_ROOT / "config.example.yaml"))
    assert cfg.executor.kind == "mock"
    # scenario path is resolved to an absolute path relative to the config file
    assert os.path.isabs(cfg.executor.mock.scenario)
    assert os.path.exists(cfg.executor.mock.scenario)
    assert cfg.repo.offload_arch == "gfx942"


def test_llm_display_host_derived_from_base_url():
    cfg = BridgeConfig.load(str(REPO_ROOT / "config.example.yaml"))
    assert cfg.llm.resolved_display_host() == "api.fireworks.ai"


def test_ssh_kind_requires_ssh_section(tmp_path):
    bad = {
        "executor": {"kind": "ssh"},  # no ssh section
        "commands": {"hipify": "h", "build": "b", "test": "t"},
        "repo": {"path": "x"},
    }
    p = tmp_path / "c.yaml"
    p.write_text(yaml.safe_dump(bad), encoding="utf-8")
    with pytest.raises(ValidationError):
        BridgeConfig.load(str(p))


def test_mock_kind_requires_mock_section(tmp_path):
    bad = {
        "executor": {"kind": "mock"},  # no mock section
        "commands": {"hipify": "h", "build": "b", "test": "t"},
        "repo": {"path": "x"},
    }
    p = tmp_path / "c.yaml"
    p.write_text(yaml.safe_dump(bad), encoding="utf-8")
    with pytest.raises(ValidationError):
        BridgeConfig.load(str(p))


def test_caps_must_be_positive(tmp_path):
    bad = {
        "executor": {"kind": "mock", "mock": {"scenario": "s.yaml"}},
        "commands": {"hipify": "h", "build": "b", "test": "t"},
        "repo": {"path": "x"},
        "caps": {"max_iterations": 0},
    }
    p = tmp_path / "c.yaml"
    p.write_text(yaml.safe_dump(bad), encoding="utf-8")
    with pytest.raises(ValidationError):
        BridgeConfig.load(str(p))


def test_defaults_are_conservative(tmp_path):
    minimal = {
        "executor": {"kind": "mock", "mock": {"scenario": "s.yaml"}},
        "commands": {"hipify": "h", "build": "b", "test": "t"},
        "repo": {"path": "x"},
    }
    p = tmp_path / "c.yaml"
    p.write_text(yaml.safe_dump(minimal), encoding="utf-8")
    cfg = BridgeConfig.load(str(p))
    assert cfg.policy.patch_test_files is False
    assert cfg.policy.allow_tolerance_relaxation is False
    assert cfg.caps.max_iterations == 40
    assert cfg.caps.max_attempts_per_cluster == 3
    # security guardrails exist by default (defence-in-depth, not opt-in)
    assert cfg.security.writable_globs and cfg.security.protected_globs
    assert "system(" in cfg.security.forbidden_insertions
    # default brain is a live OpenAI-compatible endpoint priced per token
    assert cfg.llm.backend == "openai"
    assert cfg.llm.cost.mode == "priced"


def test_replay_backend_requires_cassette(tmp_path):
    bad = {
        "executor": {"kind": "mock", "mock": {"scenario": "s.yaml"}},
        "commands": {"hipify": "h", "build": "b", "test": "t"},
        "repo": {"path": "x"},
        "llm": {"backend": "replay"},  # no replay section
    }
    p = tmp_path / "c.yaml"
    p.write_text(yaml.safe_dump(bad), encoding="utf-8")
    with pytest.raises(ValidationError):
        BridgeConfig.load(str(p))


def test_replay_cassette_path_resolved_relative_to_config(tmp_path):
    (tmp_path / "cas.yaml").write_text("[]\n", encoding="utf-8")
    good = {
        "executor": {"kind": "mock", "mock": {"scenario": "s.yaml"}},
        "commands": {"hipify": "h", "build": "b", "test": "t"},
        "repo": {"path": "x"},
        "llm": {"backend": "replay", "replay": {"cassette": "cas.yaml"}},
    }
    p = tmp_path / "c.yaml"
    p.write_text(yaml.safe_dump(good), encoding="utf-8")
    cfg = BridgeConfig.load(str(p))
    assert os.path.isabs(cfg.llm.replay.cassette)
    assert os.path.exists(cfg.llm.replay.cassette)


def test_cost_priced_vs_self_hosted():
    from bridge.config import CostConfig

    priced = CostConfig(mode="priced", input_per_mtok=0.20, output_per_mtok=0.60)
    # 1M input @ $0.20 + 0.5M output @ $0.60 = 0.20 + 0.30 = $0.50
    assert priced.token_cost(1_000_000, 500_000) == pytest.approx(0.50)
    # self-hosted vLLM on the MI300X: zero marginal token cost
    self_hosted = CostConfig(mode="self_hosted")
    assert self_hosted.token_cost(1_000_000, 500_000) == 0.0
