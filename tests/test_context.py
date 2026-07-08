"""Context builder: path resolution, provably includes the error site, budget."""

from __future__ import annotations

from bridge.agent.context import build_context, resolve_repo_path
from bridge.config import BridgeConfig
from bridge.executor.local import LocalExecutor
from bridge.parser import parse


def _cfg(budget=16000):
    return BridgeConfig.model_validate({
        "executor": {"kind": "mock", "mock": {"scenario": "s.yaml"}},
        "commands": {"hipify": "h", "build": "b", "test": "t"},
        "repo": {"path": "x"},
        "caps": {"token_budget_per_iteration": budget},
    })


def test_resolve_strips_leading_components(git_repo):
    (git_repo / "src").mkdir()
    (git_repo / "src" / "gemm.cpp").write_text("x\n", encoding="utf-8")
    ex = LocalExecutor(str(git_repo))
    assert resolve_repo_path(ex, "/workspace/repo/src/gemm.cpp") == "src/gemm.cpp"
    assert resolve_repo_path(ex, "/nope/missing.cpp") is None
    assert resolve_repo_path(ex, None) is None


def test_context_includes_error_site(git_repo):
    (git_repo / "src").mkdir()
    (git_repo / "src" / "gemm.cpp").write_text(
        "\n".join(f"code_{i}" for i in range(100)) + "\n", encoding="utf-8"
    )
    ex = LocalExecutor(str(git_repo))
    log = "/workspace/repo/src/gemm.cpp:50:3: error: use of undeclared identifier 'cublasCreate'\n"
    b = build_context(parse(log), log, ex, _cfg())
    assert b.source_path == "src/gemm.cpp"
    assert "code_49" in b.source_window  # 1-indexed line 50 -> content code_49


def test_context_stays_within_budget(git_repo):
    (git_repo / "src").mkdir()
    (git_repo / "src" / "big.cpp").write_text(
        "\n".join(f"a_very_long_source_line_number_{i}" * 4 for i in range(2000)) + "\n",
        encoding="utf-8",
    )
    ex = LocalExecutor(str(git_repo))
    log = "/workspace/repo/src/big.cpp:1000:3: error: no matching function for call to 'hipMemcpy'\n" * 60
    cfg = _cfg(budget=1600)
    b = build_context(parse(log), log, ex, cfg)
    assert b.est_tokens <= cfg.caps.token_budget_per_iteration


def test_refresh_source_fills_window_from_diagnosed_file(git_repo):
    """Linker/build errors carry no file:line -> empty window -> honest NO_PATCH
    (live run 5). The diagnosis's files_to_touch must be able to supply the
    window instead."""
    from bridge.agent.context import refresh_source

    (git_repo / "CMakeLists.txt").write_text(
        "cmake_minimum_required(VERSION 3.18)\nadd_compile_options(-arch=sm_70)\n",
        encoding="utf-8",
    )
    ex = LocalExecutor(str(git_repo))
    log = "clang++: error: unsupported option '-arch=sm_70'\n"  # no file:line
    b = build_context(parse(log), log, ex, _cfg())
    assert b.source_window == ""  # nothing to show yet
    refresh_source(b, ex, "CMakeLists.txt")
    assert b.source_path == "CMakeLists.txt"
    assert "-arch=sm_70" in b.source_window  # now the model can see the flag


def test_stale_line_number_recenters_on_symbol(git_repo):
    """Regression (live run 7): fixture/log line numbers can exceed the actual
    file (or drift after edits) — the window centered past EOF and showed the
    model only the file tail, so it honestly NO_PATCHed. Center on the symbol."""
    (git_repo / "src").mkdir()
    (git_repo / "src" / "gemm.cpp").write_text(
        "#include \"gemm.hpp\"\nvoid gemm(int n) {\n  cublasHandle_t handle;\n"
        "  cublasCreate(&handle);\n  cublasDestroy(handle);\n}\n",
        encoding="utf-8",
    )
    ex = LocalExecutor(str(git_repo))
    # log claims line 31 in a 6-line file
    log = "/workspace/repo/src/gemm.cpp:31:3: error: use of undeclared identifier 'cublasCreate'\n"
    b = build_context(parse(log), log, ex, _cfg())
    assert "cublasCreate" in b.source_window  # the model can now see the call site


def test_missing_source_is_graceful(git_repo):
    ex = LocalExecutor(str(git_repo))
    log = "/workspace/repo/src/gone.cpp:5:1: error: use of undeclared identifier 'cudaFree'\n"
    b = build_context(parse(log), log, ex, _cfg())
    assert b.source_path is None and b.source_window == ""  # no crash, empty window
