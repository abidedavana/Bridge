"""Error parser: tested against every real fixture log, plus dedup, root-cause
ordering, include-depth, and injection-safety.

This is the component the whole loop's quality hangs on, so the bar is a skeptical
judge: correct classification on authentic ROCm/clang/ctest text, the root cause
ranked first, duplicates collapsed, and the prompt-injection payload never
promoted out of raw source into a structured field.
"""

from __future__ import annotations

import pytest

from bridge.parser import ErrorClass, Category, parse
from tests.conftest import FIXTURES_DIR

LOGS = FIXTURES_DIR / "logs"


def log(name: str) -> str:
    return (LOGS / name).read_text(encoding="utf-8")


# -- per-fixture classification (the >=8 real error classes) ------------------

def test_cmake_cuda_language():
    r = parse(log("build_err_cmake_cuda_lang.txt"))
    assert r.primary.error_class == ErrorClass.CMAKE_CUDA_LANGUAGE
    assert r.primary.category == Category.CMAKE
    assert r.primary.file == "CMakeLists.txt" and r.primary.line == 3


def test_cmake_no_cuda_reports_both_language_and_toolkit():
    r = parse(log("build_cmake_no_cuda.txt"))
    assert r.primary.error_class == ErrorClass.CMAKE_CUDA_LANGUAGE  # root: fix language first
    assert ErrorClass.CMAKE_CUDA_TOOLKIT in r.error_classes


def test_arch_flag_unsupported():
    r = parse(log("build_err_arch_flag.txt"))
    assert r.primary.error_class == ErrorClass.ARCH_FLAG_UNSUPPORTED
    syms = [d.symbol for d in r.diagnostics]
    assert "-arch=sm_70" in syms
    assert any("generate-code" in (s or "") for s in syms)


def test_missing_cuda_header_with_include_depth():
    r = parse(log("build_err_missing_cublas_header.txt"))
    assert r.primary.error_class == ErrorClass.MISSING_CUDA_HEADER
    assert r.primary.symbol == "cublas_v2.h"
    assert r.primary.file == "/workspace/repo/src/gemm.hpp"
    assert r.primary.include_depth == 1  # included from gemm.cpp


def test_undeclared_cublas_clusters_four_symbols_one_file():
    r = parse(log("build_err_undeclared_cublas.txt"))
    assert r.primary.error_class == ErrorClass.UNDECLARED_CUDA_IDENTIFIER
    assert len(r.diagnostics) == 4
    assert len(r.clusters) == 1
    c = r.clusters[0]
    assert c.file == "/workspace/repo/src/gemm.cpp"
    assert set(c.symbols) == {"cublasHandle_t", "cublasCreate", "cublasSgemm", "cublasDestroy"}


def test_link_undefined_reference():
    r = parse(log("build_err_link_hipblas.txt"))
    assert r.primary.error_class == ErrorClass.LINK_UNDEFINED_REFERENCE
    assert r.primary.category == Category.LINK
    assert "hipblasCreate" in r.clusters[0].symbols


def test_kernel_launch_syntax_ranks_above_its_cascade():
    r = parse(log("build_err_kernel_launch_syntax.txt"))
    # the "expected expression" at <<<...>>> is the root; "undeclared saxpy" is a
    # cascade and must not outrank it.
    assert r.primary.error_class == ErrorClass.KERNEL_LAUNCH_SYNTAX
    assert r.error_classes[0] == ErrorClass.KERNEL_LAUNCH_SYNTAX


def test_no_matching_function():
    r = parse(log("build_err_no_matching_function.txt"))
    assert r.primary.error_class == ErrorClass.NO_MATCHING_FUNCTION
    assert r.primary.symbol == "hipMemcpy"


def test_hipify_stats_and_warnings():
    r = parse(log("hipify_run.txt"))
    assert r.hipify is not None
    assert r.hipify.conversion_pct == 84
    assert r.hipify.warnings == 7
    classes = r.error_classes
    assert ErrorClass.HIPIFY_UNCONVERTED in classes
    assert ErrorClass.WARP_SIZE_ASSUMPTION in classes


def test_ctest_pass_rate_and_warp_failure():
    r = parse(log("test_partial_60.txt"))
    assert (r.passed, r.total) == (3, 5)
    assert r.pass_rate == pytest.approx(0.6)
    # warp_reduce fails on a 64-lane assumption; classified as such, ranked first
    assert r.primary.error_class == ErrorClass.WARP_SIZE_ASSUMPTION


def test_ctest_tolerance_failure_is_distinct_from_generic():
    r = parse(log("test_stuck_tolerance.txt"))
    assert (r.passed, r.total) == (4, 5)
    assert r.primary.error_class == ErrorClass.TEST_TOLERANCE_FAILURE


def test_all_tests_pass_yields_no_diagnostics():
    r = parse(log("test_all_pass.txt"))
    assert (r.passed, r.total) == (5, 5)
    assert r.diagnostics == []


# -- security: indirect prompt injection stays contained ----------------------

def test_injection_payload_never_promoted_into_structured_fields():
    r = parse(log("build_err_injection.txt"))
    # the real error is extracted...
    assert r.primary.error_class == ErrorClass.UNDECLARED_CUDA_IDENTIFIER
    assert r.primary.symbol == "nvtxRangePushA"
    # ...and the injected instruction (which rides in the echoed source line) is
    # NOT lifted into any diagnostic's message or raw field.
    for d in r.diagnostics:
        assert "system(" not in d.message and "system(" not in d.raw
        assert "curl" not in d.raw.lower()
        assert "| sh" not in d.raw


# -- dedup, ordering, robustness ---------------------------------------------

def test_identical_diagnostics_are_deduped_with_occurrence_count():
    line = "/repo/x.cpp:10:3: error: use of undeclared identifier 'cudaMalloc'"
    r = parse("\n".join([line, line, line]))
    assert len(r.diagnostics) == 1
    assert r.diagnostics[0].occurrences == 3
    assert r.diagnostics[0].error_class == ErrorClass.UNDECLARED_CUDA_IDENTIFIER


def test_cross_phase_ordering_configure_before_compile_before_link():
    blob = (
        "CMake Error at CMakeLists.txt:3 (enable_language):\n"
        "  No CMAKE_CUDA_COMPILER could be found.\n"
        "\n"
        "/repo/a.cpp:5:3: error: use of undeclared identifier 'cublasCreate'\n"
        "/usr/bin/ld: undefined reference to `hipblasSgemm'\n"
    )
    r = parse(blob)
    ordered = [d.category for d in r.diagnostics]
    assert ordered == [Category.CMAKE, Category.COMPILE, Category.LINK]
    assert r.primary.error_class == ErrorClass.CMAKE_CUDA_LANGUAGE


def test_unrecognised_error_is_surfaced_not_dropped():
    r = parse("/repo/z.cpp:9:1: error: something we have no rule for yet\n")
    assert len(r.diagnostics) == 1
    assert r.diagnostics[0].error_class == ErrorClass.UNKNOWN_COMPILE_ERROR


def test_empty_and_noise_input_is_graceful():
    assert parse("").primary is None
    assert parse("[ 50%] Building CXX object foo.o\nmake: *** [all] Error 2\n").diagnostics == []


def test_taxonomy_coverage_across_fixtures_is_at_least_eight_classes():
    names = [
        "build_err_cmake_cuda_lang.txt", "build_cmake_no_cuda.txt",
        "build_err_arch_flag.txt", "build_err_missing_cublas_header.txt",
        "build_err_undeclared_cublas.txt", "build_err_link_hipblas.txt",
        "build_err_kernel_launch_syntax.txt", "build_err_no_matching_function.txt",
        "hipify_run.txt", "test_partial_60.txt", "test_stuck_tolerance.txt",
    ]
    seen = set()
    for nm in names:
        seen.update(parse(log(nm)).error_classes)
    assert len(seen) >= 8, seen


@pytest.mark.parametrize(
    "name",
    [
        "hipify_run.txt", "hipify_poisoned.txt", "build_ok.txt",
        "build_err_cmake_cuda_lang.txt", "build_cmake_no_cuda.txt",
        "build_err_arch_flag.txt", "build_err_missing_cublas_header.txt",
        "build_err_undeclared_cublas.txt", "build_err_link_hipblas.txt",
        "build_err_kernel_launch_syntax.txt", "build_err_no_matching_function.txt",
        "build_err_injection.txt", "test_all_pass.txt", "test_partial_60.txt",
        "test_partial_80.txt", "test_stuck_tolerance.txt",
    ],
)
def test_every_fixture_parses_without_error(name):
    r = parse(log(name))
    assert isinstance(r.error_classes, list)  # never raises; always structured
