"""The smooth-journey commands.

`bridge init` must never write a config that `bridge run` would then reject —
every path through the wizard round-trips the file through the schema. And
`bridge demo` is the one-command replacement for the two-terminal native demo,
so its headless core must complete the same replayed migration `run` does.
"""

from __future__ import annotations

import json

import yaml

from bridge.cli import main
from bridge.config import BridgeConfig
from bridge.setup_wizard import detect_commands, find_cuda_roots, pick_arch_from_output
from tests.conftest import REPO_ROOT


def _cuda_repo(tmp_path, build_system="cmake"):
    repo = tmp_path / "proj"
    (repo / "src").mkdir(parents=True)
    (repo / "src" / "kernel.cu").write_text("__global__ void k() {}\n", encoding="utf-8")
    if build_system == "cmake":
        (repo / "CMakeLists.txt").write_text("project(x LANGUAGES CXX CUDA)\n", encoding="utf-8")
    elif build_system == "make":
        (repo / "Makefile").write_text("all:\n\ttrue\n", encoding="utf-8")
    return repo


def test_init_yes_writes_a_config_that_validates(tmp_path):
    repo = _cuda_repo(tmp_path)
    out = tmp_path / "config.yaml"
    rc = main(["init", "--yes", "--repo", str(repo), "--arch", "gfx1100", "--out", str(out)])
    assert rc == 0
    cfg = BridgeConfig.load(str(out))  # the wizard's own round-trip, re-checked
    assert cfg.executor.kind == "local"
    assert cfg.repo.offload_arch == "gfx1100"
    assert cfg.repo.path == str(repo)
    assert cfg.commands.configure and "hipcc" in cfg.commands.configure
    assert "cmake --build" in cfg.commands.build
    assert "src" in cfg.commands.hipify  # the detected .cu sweep root
    assert cfg.llm.backend == "openai"


def test_init_detects_makefile_build(tmp_path):
    repo = _cuda_repo(tmp_path, build_system="make")
    out = tmp_path / "config.yaml"
    assert main(["init", "--yes", "--repo", str(repo), "--out", str(out)]) == 0
    cfg = BridgeConfig.load(str(out))
    assert cfg.commands.configure is None
    assert cfg.commands.build.startswith("make")


def test_init_refuses_to_overwrite_without_force(tmp_path):
    repo = _cuda_repo(tmp_path)
    out = tmp_path / "config.yaml"
    out.write_text("precious: true\n", encoding="utf-8")
    assert main(["init", "--yes", "--repo", str(repo), "--out", str(out)]) == 2
    assert out.read_text(encoding="utf-8") == "precious: true\n"
    assert main(["init", "--yes", "--repo", str(repo), "--out", str(out), "--force"]) == 0
    assert "precious" not in out.read_text(encoding="utf-8")


def test_init_rejects_missing_repo_path(tmp_path):
    rc = main(["init", "--yes", "--repo", str(tmp_path / "nope"), "--out", str(tmp_path / "c.yaml")])
    assert rc == 2


def test_pick_arch_from_output():
    # rocm_agent_enumerator: one id per line, incl. the gfx000 CPU agent.
    assert pick_arch_from_output("gfx000\ngfx942\n") == "gfx942"
    # rocminfo: ids buried in Name: lines.
    assert pick_arch_from_output("  Name:                    gfx1100\n  Uuid: GPU-x\n") == "gfx1100"
    assert pick_arch_from_output("no gpus here") is None


def test_find_cuda_roots_and_detect_commands(tmp_path):
    repo = _cuda_repo(tmp_path)
    (repo / "lib").mkdir()
    (repo / "lib" / "util.cuh").write_text("#pragma once\n", encoding="utf-8")
    assert find_cuda_roots(str(repo)) == ["lib", "src"]
    det = detect_commands(str(repo))
    assert det["build_system"] == "cmake"
    assert "lib src" in det["hipify"]
    # a .cu at the repo root collapses the sweep to '.'
    (repo / "top.cu").write_text("", encoding="utf-8")
    assert find_cuda_roots(str(repo)) == ["."]


def test_demo_headless_completes_the_replayed_migration(tmp_path):
    cfg = {
        "executor": {"kind": "mock", "mock": {"scenario": str(REPO_ROOT / "fixtures/scenarios/success.yaml")}},
        "commands": {"hipify": "hipify-perl", "build": "cmake --build build", "test": "ctest"},
        "repo": {"path": str(tmp_path / "scratch")},
        "llm": {"backend": "replay", "replay": {"cassette": str(REPO_ROOT / "fixtures/cassettes/success.json")}},
        "prompts_dir": str(REPO_ROOT / "prompts"),
        "runs_dir": str(tmp_path / "runs"),
    }
    cfg_path = tmp_path / "c.yaml"
    cfg_path.write_text(yaml.safe_dump(cfg), encoding="utf-8")

    assert main(["demo", "--headless", "--delay", "0", "--config", str(cfg_path)]) == 0
    state = json.loads((tmp_path / "runs" / "current.json").read_text(encoding="utf-8"))
    assert state["status"] == "SUCCESS"


def test_demo_without_a_clone_fails_gracefully(tmp_path):
    assert main(["demo", "--headless", "--config", str(tmp_path / "missing.yaml")]) == 2
