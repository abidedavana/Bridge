"""The error parser's data model and taxonomy.

The taxonomy (`ErrorClass`) is a **public contract**: the M3 diagnosis prompt
looks up its CUDA->ROCm cheat-sheet by error class, and the dashboard groups the
iteration timeline by it. So these string keys are stable and additive-only.

A `Diagnostic` is one parsed compiler/linker/test/HIPIFY finding. A `Cluster`
groups diagnostics the agent should fix together (same class, same file) so the
orchestrator can cap *attempts per cluster*. A `ParseResult` is what one call to
the parser returns for one command's output.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


class Category:
    """Coarse phase a diagnostic belongs to. Drives root-cause ordering: you fix
    configure errors before compile errors before link errors before tests."""

    CMAKE = "cmake"
    COMPILE = "compile"
    LINK = "link"
    HIPIFY = "hipify"
    TEST = "test"


class Severity:
    FATAL = "fatal"
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


class ErrorClass:
    """Stable taxonomy keys. Additive-only — never renumber or the M3 cheat-sheet
    and the dashboard drift out of sync with the parser."""

    CMAKE_CUDA_LANGUAGE = "cmake_cuda_language"          # enable_language(CUDA)/CUDACXX
    CMAKE_CUDA_TOOLKIT = "cmake_cuda_toolkit"            # find_package(CUDAToolkit)
    ARCH_FLAG_UNSUPPORTED = "arch_flag_unsupported"      # -arch=sm_XX / --generate-code
    MISSING_CUDA_HEADER = "missing_cuda_header"          # 'cublas_v2.h' file not found
    UNDECLARED_CUDA_IDENTIFIER = "undeclared_cuda_identifier"  # cublas*/nvtx*/cuda*
    NO_MATCHING_FUNCTION = "no_matching_function"        # hipMemcpy arg-count mismatch
    KERNEL_LAUNCH_SYNTAX = "kernel_launch_syntax"        # <<<grid,block>>> not lowered
    LINK_UNDEFINED_REFERENCE = "link_undefined_reference"  # undefined reference to hipblas*
    HIPIFY_UNCONVERTED = "hipify_unconverted"            # HIPIFY left an API unmapped
    WARP_SIZE_ASSUMPTION = "warp_size_assumption"        # 32- vs 64-lane warp / __shfl
    TEST_TOLERANCE_FAILURE = "test_tolerance_failure"    # fp mismatch within rtol/atol
    TEST_FAILURE = "test_failure"                        # other ctest failure
    UNKNOWN_COMPILE_ERROR = "unknown_compile_error"      # a real error we didn't classify


# Lower rank = closer to the root cause = sorted earlier.
_PHASE_RANK = {
    Category.CMAKE: 0,
    Category.COMPILE: 1,
    Category.LINK: 2,
    Category.TEST: 3,
    Category.HIPIFY: 4,
}
_SEVERITY_RANK = {
    Severity.FATAL: 0,
    Severity.ERROR: 1,
    Severity.WARNING: 2,
    Severity.INFO: 3,
}


@dataclass(frozen=True)
class Diagnostic:
    error_class: str
    category: str
    severity: str
    message: str
    file: Optional[str] = None
    line: Optional[int] = None
    column: Optional[int] = None
    symbol: Optional[str] = None
    # Depth in the #include chain (0 = the error is in the file being compiled).
    include_depth: int = 0
    # 0-based position of the diagnostic's first line in the log (ordering tiebreak).
    first_index: int = 0
    # How many identical diagnostics were collapsed into this one.
    occurrences: int = 1
    # The single raw diagnostic line, kept for display. Deliberately does NOT
    # include the echoed source line: that is where indirect-prompt-injection
    # payloads ride, and it is fetched separately (and delimited as untrusted) by
    # the context builder. The parser extracts *structure*, not instructions.
    raw: str = ""

    @property
    def dedup_key(self) -> tuple:
        return (self.error_class, self.file, self.line, self.column, self.symbol, self.message)

    @property
    def sort_key(self) -> tuple:
        return (
            _PHASE_RANK.get(self.category, 9),
            _SEVERITY_RANK.get(self.severity, 9),
            self.first_index,
        )

    @property
    def location(self) -> str:
        if self.file and self.line:
            return f"{self.file}:{self.line}"
        return self.file or "<unknown>"


@dataclass
class Cluster:
    """Diagnostics to fix as a unit (same class + file). The orchestrator caps
    attempts per cluster, so this is the granularity a STUCK verdict applies to."""

    error_class: str
    category: str
    file: Optional[str]
    diagnostics: list[Diagnostic] = field(default_factory=list)

    @property
    def root(self) -> Diagnostic:
        return self.diagnostics[0]

    @property
    def symbols(self) -> list[str]:
        seen: list[str] = []
        for d in self.diagnostics:
            if d.symbol and d.symbol not in seen:
                seen.append(d.symbol)
        return seen

    @property
    def sort_key(self) -> tuple:
        return self.root.sort_key


@dataclass
class HipifyStats:
    conversion_pct: Optional[int] = None
    unconverted: Optional[int] = None
    warnings: Optional[int] = None
    files: Optional[int] = None


@dataclass
class ParseResult:
    diagnostics: list[Diagnostic] = field(default_factory=list)  # deduped, root-first
    clusters: list[Cluster] = field(default_factory=list)        # root-first
    passed: Optional[int] = None
    total: Optional[int] = None
    hipify: Optional[HipifyStats] = None

    @property
    def primary(self) -> Optional[Diagnostic]:
        """The root-cause diagnostic: earliest phase, highest severity, first seen."""
        return self.diagnostics[0] if self.diagnostics else None

    @property
    def pass_rate(self) -> Optional[float]:
        if self.total:
            return (self.passed or 0) / self.total
        return None

    @property
    def error_classes(self) -> list[str]:
        seen: list[str] = []
        for d in self.diagnostics:
            if d.error_class not in seen:
                seen.append(d.error_class)
        return seen
