"""ErrorParser: turn raw HIPIFY / ROCm build / ctest output into structured,
deduplicated, root-cause-ordered diagnostics.

This is the highest-leverage component: everything downstream (the diagnosis
prompt, the dashboard, the STUCK bookkeeping) consumes its output, so it is
designed to be *faithful and graceful*. Faithful: patterns are written against
real ROCm/clang diagnostics (see fixtures/logs). Graceful: unrecognised errors
are surfaced as `unknown_compile_error` rather than dropped, and malformed or
empty input yields an empty `ParseResult`, never an exception.

Root-cause ordering (the spec's "include-depth / first occurrence first"):
compilers cascade, so we rank by (phase, severity, first-occurrence) and expose
`result.primary`. Phase ordering encodes that you cannot link what will not
compile, nor test what will not build. Within an #include chain the *deepest*
file (where the fatal error actually is) is the diagnostic's location, and the
chain length is recorded as `include_depth`.
"""

from __future__ import annotations

import dataclasses
import re

from .model import (
    Category,
    Cluster,
    Diagnostic,
    ErrorClass,
    HipifyStats,
    ParseResult,
    Severity,
)

# CUDA library / API symbol prefixes. An undeclared identifier with one of these
# is a CUDA API HIPIFY missed; anything else is a generic (often cascade) error.
_CUDA_PREFIXES = (
    "cublas", "cusparse", "cufft", "cudnn", "curand", "cusolver", "cutensor",
    "cuda", "cuStream", "cuMem", "nvtx", "nvToolsExt", "nppi", "__nv", "__half",
)

# -- line patterns (anchored on real ROCm/clang/cmake/ctest output) -----------
_INCLUDE_FROM = re.compile(r"^In file included from (?P<file>\S+?):(?P<line>\d+)[,:]")
_CMAKE_HEADER = re.compile(r"^CMake Error at (?P<file>\S+):(?P<line>\d+) \((?P<cmd>\w+)\)")
_ARCH_FLAG = re.compile(r"clang(?:\+\+)?: error: unsupported option '(?P<opt>[^']+)'")
_FATAL_HEADER = re.compile(
    r"^(?P<file>\S+):(?P<line>\d+):(?P<col>\d+): fatal error: '(?P<hdr>[^']+)' file not found"
)
_UNDECLARED = re.compile(
    r"^(?P<file>\S+):(?P<line>\d+):(?P<col>\d+): error: use of undeclared identifier '(?P<sym>[^']+)'"
)
_NO_MATCH = re.compile(
    r"^(?P<file>\S+):(?P<line>\d+):(?P<col>\d+): error: no matching function for call to '(?P<sym>[^']+)'"
)
_EXPECTED_EXPR = re.compile(
    r"^(?P<file>\S+):(?P<line>\d+):(?P<col>\d+): error: expected expression"
)
_GENERIC_DIAG = re.compile(
    r"^(?P<file>\S+):(?P<line>\d+):(?P<col>\d+): (?P<sev>error|warning): (?P<msg>.*)"
)
# GNU ld says "undefined reference to `sym'"; LLVM lld (the ROCm 7.x default)
# says "ld.lld: error: undefined symbol: sym" — cover both (hardware-day find).
_UNDEF_REF = re.compile(r"undefined (?:reference to|symbol:) [`']?(?P<sym>[A-Za-z_][\w:@.]*)")
# CMake also emits headerless errors ("CMake Error: <msg>", no file:line) — e.g.
# "CMake Error: Cannot determine link language for target" when a .cu source is
# not claimed by any enabled language (hardware-day find).
_CMAKE_BARE = re.compile(r"^CMake Error: (?P<msg>.+)")
_HIPIFY_WARN = re.compile(r"^\s*warning: (?P<file>\S+):(?P<line>\d+): (?P<msg>.*)")
_CTEST_SUMMARY = re.compile(
    r"(?P<pct>\d+)% tests passed, (?P<failed>\d+) tests failed out of (?P<total>\d+)"
)
_CTEST_FAILED = re.compile(
    r"^\s*\d+/\d+ Test\s+#\d+:\s+(?P<name>\S+)\s+\.*\**Failed"
)
_WARP_HINT = re.compile(r"__shfl|warpSize|warp[- ]?size|\b32[- ]lane|64[- ]lane", re.IGNORECASE)
_TOLERANCE_HINT = re.compile(r"rtol|atol|abs err|tolerance|exceeds", re.IGNORECASE)


def _is_cuda_symbol(sym: str) -> bool:
    return any(sym.startswith(p) for p in _CUDA_PREFIXES)


class ErrorParser:
    def parse(self, text: str) -> ParseResult:
        lines = text.splitlines()
        diags: list[Diagnostic] = []
        include_chain: list[tuple[str, int]] = []
        passed = total = None

        i = 0
        n = len(lines)
        while i < n:
            line = lines[i]

            m = _INCLUDE_FROM.match(line)
            if m:
                include_chain.append((m.group("file"), int(m.group("line"))))
                i += 1
                continue

            diag, consumed = self._detect(lines, i, include_chain)
            if diag is not None:
                diags.append(dataclasses.replace(diag, first_index=i))
                include_chain = []
                i += max(1, consumed)
                continue

            m = _CTEST_SUMMARY.search(line)
            if m:
                total = int(m.group("total"))
                passed = total - int(m.group("failed"))

            # Any other meaningful line breaks an include chain.
            if line.strip():
                include_chain = []
            i += 1

        result = ParseResult(passed=passed, total=total, hipify=self._hipify_stats(lines))
        self._dedupe_and_order(diags, result)
        return result

    # -- per-line detectors --------------------------------------------------

    def _detect(self, lines, i, include_chain):
        """Return (Diagnostic|None, lines_consumed). Ordered specific -> generic."""
        line = lines[i]

        m = _CMAKE_HEADER.match(line)
        if m:
            return self._cmake(lines, i, m)

        m = _CMAKE_BARE.match(line)
        if m:
            msg = m.group("msg").strip()
            low = msg.lower()
            # "Cannot determine link language for target" = the ported source is
            # not claimed by any enabled language: a build-language wiring issue.
            klass = (
                ErrorClass.CMAKE_CUDA_LANGUAGE
                if ("link language" in low or "linker language" in low)
                else ErrorClass.UNKNOWN_COMPILE_ERROR
            )
            return (
                Diagnostic(
                    error_class=klass,
                    category=Category.CMAKE,
                    severity=Severity.ERROR,
                    message=msg,
                    raw=line.strip(),
                ),
                1,
            )

        m = _ARCH_FLAG.search(line)
        if m:
            opt = m.group("opt")
            return (
                Diagnostic(
                    error_class=ErrorClass.ARCH_FLAG_UNSUPPORTED,
                    category=Category.COMPILE,
                    severity=Severity.ERROR,
                    message=f"unsupported option '{opt}'",
                    symbol=opt,
                    raw=line.strip(),
                ),
                1,
            )

        m = _FATAL_HEADER.match(line)
        if m:
            includer = include_chain[0][0] if include_chain else None
            note = f" (included from {includer})" if includer else ""
            return (
                Diagnostic(
                    error_class=ErrorClass.MISSING_CUDA_HEADER,
                    category=Category.COMPILE,
                    severity=Severity.FATAL,
                    message=f"'{m.group('hdr')}' file not found{note}",
                    file=m.group("file"),
                    line=int(m.group("line")),
                    column=int(m.group("col")),
                    symbol=m.group("hdr"),
                    include_depth=len(include_chain),
                    raw=line.strip(),
                ),
                1,
            )

        m = _UNDECLARED.match(line)
        if m:
            sym = m.group("sym")
            klass = (
                ErrorClass.UNDECLARED_CUDA_IDENTIFIER
                if _is_cuda_symbol(sym)
                else ErrorClass.UNKNOWN_COMPILE_ERROR
            )
            return (
                Diagnostic(
                    error_class=klass,
                    category=Category.COMPILE,
                    severity=Severity.ERROR,
                    message=f"use of undeclared identifier '{sym}'",
                    file=m.group("file"),
                    line=int(m.group("line")),
                    column=int(m.group("col")),
                    symbol=sym,
                    raw=line.strip(),
                ),
                1,
            )

        m = _NO_MATCH.match(line)
        if m:
            return (
                Diagnostic(
                    error_class=ErrorClass.NO_MATCHING_FUNCTION,
                    category=Category.COMPILE,
                    severity=Severity.ERROR,
                    message=f"no matching function for call to '{m.group('sym')}'",
                    file=m.group("file"),
                    line=int(m.group("line")),
                    column=int(m.group("col")),
                    symbol=m.group("sym"),
                    raw=line.strip(),
                ),
                1,
            )

        m = _EXPECTED_EXPR.match(line)
        if m:
            # `<<<grid, block>>>` left un-lowered shows as "expected expression"
            # on the launch site; confirm via the echoed source line.
            echoed = " ".join(lines[i + 1 : i + 3])
            if "<<<" in echoed:
                return (
                    Diagnostic(
                        error_class=ErrorClass.KERNEL_LAUNCH_SYNTAX,
                        category=Category.COMPILE,
                        severity=Severity.ERROR,
                        message="CUDA kernel-launch syntax '<<<...>>>' not lowered to hipLaunchKernelGGL",
                        file=m.group("file"),
                        line=int(m.group("line")),
                        column=int(m.group("col")),
                        raw=line.strip(),
                    ),
                    1,
                )

        m = _GENERIC_DIAG.match(line)
        if m:
            sev = Severity.ERROR if m.group("sev") == "error" else Severity.WARNING
            # A generic warning we don't otherwise classify is noise; skip it.
            if sev == Severity.WARNING:
                return (None, 1)
            return (
                Diagnostic(
                    error_class=ErrorClass.UNKNOWN_COMPILE_ERROR,
                    category=Category.COMPILE,
                    severity=Severity.ERROR,
                    message=m.group("msg").strip(),
                    file=m.group("file"),
                    line=int(m.group("line")),
                    column=int(m.group("col")),
                    raw=line.strip(),
                ),
                1,
            )

        m = _UNDEF_REF.search(line)
        if m:
            return (
                Diagnostic(
                    error_class=ErrorClass.LINK_UNDEFINED_REFERENCE,
                    category=Category.LINK,
                    severity=Severity.ERROR,
                    message=f"undefined reference to {m.group('sym')}",
                    symbol=m.group("sym"),
                    raw=line.strip(),
                ),
                1,
            )

        m = _HIPIFY_WARN.match(line)
        if m:
            msg = m.group("msg")
            if _WARP_HINT.search(msg):
                klass, category = ErrorClass.WARP_SIZE_ASSUMPTION, Category.HIPIFY
            elif "unconverted" in msg:
                klass, category = ErrorClass.HIPIFY_UNCONVERTED, Category.HIPIFY
            else:
                return (None, 1)
            sym = None
            sm = re.search(r"'([^']+)'", msg)
            if sm:
                sym = sm.group(1)
            return (
                Diagnostic(
                    error_class=klass,
                    category=category,
                    severity=Severity.WARNING,
                    message=msg.strip(),
                    file=m.group("file"),
                    line=int(m.group("line")),
                    symbol=sym,
                    raw=line.strip(),
                ),
                1,
            )

        m = _CTEST_FAILED.match(line)
        if m:
            return self._ctest_failure(lines, i, m)

        return (None, 0)

    def _cmake(self, lines, i, m):
        # Read the whole indented body (blank lines separate paragraphs of ONE
        # error; a non-indented line such as "Call Stack ..." ends it). The old
        # stop-at-first-blank version missed CMake 3.22's second paragraph, where
        # the actionable text lives (hardware-day find).
        body: list[str] = []
        j = i + 1
        while j < len(lines):
            ln = lines[j]
            if ln.startswith(" "):
                if ln.strip():
                    body.append(ln.strip())
            elif ln.strip():
                break
            j += 1
        blob = " ".join(body)
        low = blob.lower()
        if (
            "No CMAKE_CUDA_COMPILER" in blob
            or "failed to find nvcc" in low
            or "requires the cuda toolkit" in low
        ):
            # CUDA is still an enabled language on a box with no nvcc — the real
            # CMake 3.22 wording is "Failed to find nvcc." (ROCm pod, 2026-07-08).
            klass, msg = ErrorClass.CMAKE_CUDA_LANGUAGE, (body[0] if body else "CUDA language enabled but no CUDA toolchain")
        elif "CUDAToolkit" in blob or "CUDAToolkitConfig" in blob:
            klass, msg = ErrorClass.CMAKE_CUDA_TOOLKIT, "CUDAToolkit package not found"
        else:
            klass, msg = ErrorClass.UNKNOWN_COMPILE_ERROR, (body[0] if body else "CMake error")
        return (
            Diagnostic(
                error_class=klass,
                category=Category.CMAKE,
                severity=Severity.ERROR,
                message=msg,
                file=m.group("file"),
                line=int(m.group("line")),
                raw=lines[i].strip(),
            ),
            max(1, j - i),
        )

    def _ctest_failure(self, lines, i, m):
        name = m.group("name")
        body = " ".join(lines[i + 1 : i + 4])
        if _WARP_HINT.search(body):
            klass = ErrorClass.WARP_SIZE_ASSUMPTION
        elif _TOLERANCE_HINT.search(body):
            klass = ErrorClass.TEST_TOLERANCE_FAILURE
        else:
            klass = ErrorClass.TEST_FAILURE
        return (
            Diagnostic(
                error_class=klass,
                category=Category.TEST,
                severity=Severity.ERROR,
                message=f"test '{name}' failed",
                symbol=name,
                raw=lines[i].strip(),
            ),
            1,
        )

    # -- HIPIFY totals + dedup/order -----------------------------------------

    def _hipify_stats(self, lines) -> HipifyStats | None:
        idx = next((k for k, ln in enumerate(lines) if "TOTAL statistics" in ln), None)
        scope = lines[idx:] if idx is not None else lines
        if not any("HIPIFY" in ln or "CONVERSION %" in ln for ln in lines):
            return None

        def grab(key):
            pat = re.compile(rf"{re.escape(key)}:\s*(\d+)")
            for ln in scope:
                mm = pat.search(ln)
                if mm:
                    return int(mm.group(1))
            return None

        return HipifyStats(
            conversion_pct=grab("CONVERSION %"),
            unconverted=grab("UNCONVERTED refs count"),
            warnings=grab("WARNINGS"),
            files=grab("FILES"),
        )

    def _dedupe_and_order(self, diags, result: ParseResult) -> None:
        by_key: dict[tuple, Diagnostic] = {}
        order: list[tuple] = []
        for d in diags:
            k = d.dedup_key
            if k in by_key:
                prev = by_key[k]
                by_key[k] = dataclasses.replace(prev, occurrences=prev.occurrences + 1)
            else:
                by_key[k] = d
                order.append(k)
        deduped = sorted((by_key[k] for k in order), key=lambda d: d.sort_key)
        result.diagnostics = deduped

        clusters: dict[tuple, Cluster] = {}
        corder: list[tuple] = []
        for d in deduped:
            ck = (d.error_class, d.file)
            if ck not in clusters:
                clusters[ck] = Cluster(error_class=d.error_class, category=d.category, file=d.file)
                corder.append(ck)
            clusters[ck].diagnostics.append(d)
        result.clusters = sorted((clusters[k] for k in corder), key=lambda c: c.sort_key)


_DEFAULT = ErrorParser()


def parse(text: str) -> ParseResult:
    """Parse raw command output into a `ParseResult` (module-level convenience)."""
    return _DEFAULT.parse(text)
