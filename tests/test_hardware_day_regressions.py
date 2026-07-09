"""Regressions from the first real GPU-pod run (Radeon PRO W7900-class, gfx1100,
ROCm 7.2, CMake 3.22, lld linker — 2026-07-08).

The live run went STUCK at iteration 4 with cluster ('unknown', None) despite the
agent applying three correct patches. Root causes, each pinned here:

  1. Parser blind spots for the pod's REAL error texts (captured verbatim in
     fixtures/logs/build_err_cmake_nvcc_toolkit.txt and
     fixtures/logs/build_err_lld_undefined_main.txt).
  2. All unparsed errors shared ONE ('unknown', None) cluster, so three
     DIFFERENT errors burned a single attempt budget -> premature STUCK while
     the run was in fact progressing.
  3. The pod has no global git identity, so every `git commit` in the audit
     trail silently failed ("real commits" quietly became no commits).
"""

from __future__ import annotations

import json
import subprocess

from bridge.agent import Orchestrator, load_prompts
from bridge.agent.orchestrator import RunOutcome, _error_fingerprint
from bridge.cli import _ensure_git_repo
from bridge.config import BridgeConfig
from bridge.executor import LocalExecutor
from bridge.executor.base import ExecResult, Executor, Phase
from bridge.llm.replay import ReplayBackend
from bridge.parser import parse
from bridge.parser.model import ErrorClass
from bridge.run_state import RunRecorder, RunState
from tests.conftest import FIXTURES_DIR, REPO_ROOT


# -- 1. parser recognises the pod's real error texts --------------------------

def test_cmake_nvcc_toolkit_error_classifies_as_cmake_cuda_language():
    text = (FIXTURES_DIR / "logs" / "build_err_cmake_nvcc_toolkit.txt").read_text(encoding="utf-8")
    p = parse(text).primary
    assert p is not None, "CMake 3.22 'Failed to find nvcc' must yield a primary diagnostic"
    assert p.error_class is ErrorClass.CMAKE_CUDA_LANGUAGE
    assert "nvcc" in p.message.lower()


def test_lld_undefined_symbol_classifies_as_link_error():
    text = (FIXTURES_DIR / "logs" / "build_err_lld_undefined_main.txt").read_text(encoding="utf-8")
    p = parse(text).primary
    assert p is not None, "lld 'undefined symbol:' must yield a primary diagnostic"
    assert p.error_class is ErrorClass.LINK_UNDEFINED_REFERENCE
    assert p.symbol == "main"


def test_headerless_cmake_link_language_error_is_classified():
    # CMake's own wording when no enabled language claims a source file.
    for line in (
        'CMake Error: Cannot determine link language for target "app".',
        "CMake Error: CMake can not determine linker language for target: app",
    ):
        p = parse(line).primary
        assert p is not None
        assert p.error_class is ErrorClass.CMAKE_CUDA_LANGUAGE


def test_gnu_ld_style_still_recognised():
    p = parse("/usr/bin/ld: gemm.o: undefined reference to `hipblasCreate'").primary
    assert p is not None and p.error_class is ErrorClass.LINK_UNDEFINED_REFERENCE
    assert p.symbol == "hipblasCreate"


def test_ansi_colorized_output_still_parses():
    """Verbatim from the recorded on-pod cassette: cmake colorized its stderr, so
    every line began with an escape sequence and the whole run parsed 'unknown'."""
    colored_header = (
        "-- Configuring incomplete, errors occurred!\n"
        "\x1b[31mCMake Error at /usr/share/cmake-3.22/Modules/CMakeDetermineCUDACompiler.cmake:179 (message):\n"
        "  Failed to find nvcc.\n"
        "\n"
        "  Compiler requires the CUDA toolkit.  Please set the CUDAToolkit_ROOT\n"
        "  variable.\n"
        "Call Stack (most recent call first):\n"
        "  CMakeLists.txt:2 (project)\n"
        "\n"
        "\x1b[0m\n"
    )
    p = parse(colored_header).primary
    assert p is not None and p.error_class is ErrorClass.CMAKE_CUDA_LANGUAGE

    colored_bare = (
        '\x1b[0mCMake Error: Cannot determine link language for target "app".\x1b[0m\n'
        "\x1b[0mCMake Error: CMake can not determine linker language for target: app\x1b[0m\n"
    )
    p = parse(colored_bare).primary
    assert p is not None and p.error_class is ErrorClass.CMAKE_CUDA_LANGUAGE


# -- 2. distinct unknown errors must not share one attempt budget -------------

class _ShapeShiftingFailure(Executor):
    """Every build fails with a DIFFERENT unparseable error (as the pod did:
    nvcc-detect, then link-language, then undefined-main...)."""

    def __init__(self):
        self.builds = 0

    def run(self, command, *, cwd=None, timeout=None, phase=Phase.OTHER):
        if phase == Phase.BUILD:
            self.builds += 1
            return ExecResult(command, 1, "", f"mystery failure variant #{self.builds}\n", 0.0, phase)
        return ExecResult(command, 0, "", "", 0.0, phase)

    def read_file(self, path):  # pragma: no cover - context builder fallback
        raise FileNotFoundError(path)

    def write_file(self, path, content):
        pass

    def exists(self, path):
        return False


def test_distinct_unknown_errors_get_distinct_clusters(tmp_path):
    a = _error_fingerprint("mystery failure variant #1")
    b = _error_fingerprint("mystery failure variant #2")
    assert a != b
    assert _error_fingerprint("mystery failure variant #1") == a  # stable

    diag = {"error_class": "unknown", "root_cause": "?", "files_to_touch": [], "fix_summary": "try"}
    entries = []
    for k in range(12):
        entries.append({"response": {"text": json.dumps(diag), "prompt_tokens": 1, "completion_tokens": 1}})
        entries.append({"response": {"text": (
            f"diff --git a/src/f{k}.hip b/src/f{k}.hip\nnew file mode 100644\n"
            f"--- /dev/null\n+++ b/src/f{k}.hip\n@@ -0,0 +1 @@\n+// {k}\n"
        ), "prompt_tokens": 1, "completion_tokens": 1}})
    cassette = tmp_path / "c.json"
    cassette.write_text(json.dumps(entries), encoding="utf-8")

    cfg = BridgeConfig.model_validate({
        "executor": {"kind": "mock", "mock": {"scenario": str(REPO_ROOT / "fixtures/scenarios/stuck_build.yaml")}},
        "commands": {"hipify": "true", "build": "true", "test": "true"},
        "repo": {"path": str(tmp_path / "repo")},
        "llm": {"backend": "replay", "replay": {"cassette": str(cassette)}},
        "prompts_dir": str(REPO_ROOT / "prompts"),
        "caps": {"max_iterations": 6, "max_attempts_per_cluster": 3},
    })
    rec = RunRecorder(str(tmp_path / "s.json"), RunState(run_id="t", scenario="-", executor="fake"))
    orch = Orchestrator(cfg, _ShapeShiftingFailure(), ReplayBackend(str(cassette)),
                        load_prompts(cfg.prompts_dir), rec)
    outcome = orch.run()
    # Before the fix this died STUCK at iteration 4 (3 attempts + cap check on
    # one shared cluster). Distinct fingerprints -> runs the full budget.
    assert outcome is RunOutcome.EXHAUSTED
    assert len(rec.state.iterations) == 6


# -- 3. audit-trail commits must work on boxes with no git identity -----------

def test_agent_commits_succeed_without_global_git_identity(tmp_path):
    repo = tmp_path / "repo"
    _ensure_git_repo(str(repo))
    (tmp_path / "empty_gitconfig").write_text("", encoding="utf-8")
    # Hide any host-level identity: point global/system config at an empty file.
    ex = LocalExecutor(str(repo), env={
        "GIT_CONFIG_GLOBAL": str(tmp_path / "empty_gitconfig"),
        "GIT_CONFIG_SYSTEM": str(tmp_path / "empty_gitconfig"),
    })
    cfg = BridgeConfig.model_validate({
        "executor": {"kind": "local"},
        "commands": {"hipify": "true", "build": "true", "test": "true"},
        "repo": {"path": str(repo)},
        "llm": {"backend": "replay", "replay": {"cassette": str(tmp_path / "c.json")}},
        "prompts_dir": str(REPO_ROOT / "prompts"),
    })
    (tmp_path / "c.json").write_text("[]", encoding="utf-8")
    rec = RunRecorder(str(tmp_path / "s.json"), RunState(run_id="t", scenario="-", executor="local"))
    orch = Orchestrator(cfg, ex, ReplayBackend(str(tmp_path / "c.json")),
                        load_prompts(cfg.prompts_dir), rec)

    ex.write_file("src/fix.hip", "// ported\n")
    assert orch._commit(1, None, {"fix_summary": "port fix"}, ["src/fix.hip"])

    log = subprocess.run(["git", "-C", str(repo), "log", "--pretty=%an %s"],
                         capture_output=True, text=True).stdout
    assert "bridge(iter 1" in log, f"commit missing; git log was: {log!r}"
    assert "bridge-agent" in log
