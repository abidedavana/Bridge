"""Context builder: assemble the (bounded) evidence the LLM sees.

Turns a `ParseResult` + the raw log + the repo into the strings the diagnose and
propose-edit prompts need: the primary diagnostic, an error-log excerpt, and a
window of the offending source. Two properties the spec requires and the tests
pin: it stays within a configurable token budget, and it provably includes the
error site (the primary diagnostic's line) whenever that file is readable.

The source it embeds is UNTRUSTED (it may carry injection payloads). The prompts
delimit and label it as data; the patch policy engine is the real backstop.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from ..parser import Diagnostic, ParseResult

# rough chars-per-token; good enough for budgeting (real usage is measured).
_CHARS_PER_TOKEN = 4
_PROMPT_OVERHEAD_TOKENS = 900  # system prompt + cheat-sheet, approx


@dataclass
class ContextBundle:
    primary: Optional[Diagnostic]
    parse_result: ParseResult
    source_path: Optional[str]
    source_window: str
    error_excerpt: str
    est_tokens: int


def resolve_repo_path(executor, path: Optional[str]) -> Optional[str]:
    """Map a compiler's path (often absolute, e.g. /workspace/repo/src/x.cpp) to a
    path that exists in the working copy, by stripping leading components until it
    resolves. Returns None if nothing matches."""
    if not path:
        return None
    parts = path.replace("\\", "/").lstrip("/").split("/")
    for start in range(len(parts)):
        cand = "/".join(parts[start:])
        try:
            if cand and executor.exists(cand):
                return cand
        except Exception:
            continue
    return None


def _window(text: str, line: Optional[int], ctx: int) -> str:
    lines = text.splitlines()
    if not lines:
        return ""
    if line is None:
        lines = lines[: 2 * ctx + 1]
        start = 1
    else:
        lo = max(0, line - 1 - ctx)
        hi = min(len(lines), line + ctx)
        lines = lines[lo:hi]
        start = lo + 1
    return "\n".join(f"{start + i:>5} | {ln}" for i, ln in enumerate(lines))


def _effective_line(text: str, symbol, line):
    """Where to center the source window. The diagnostic's line number can be
    stale (the tree drifts as the agent edits; fixture logs cite other trees), so
    prefer the symbol's actual location in the file; fall back to the reported
    line only if it exists; else None (head of file)."""
    lines = text.splitlines()
    if symbol:
        for idx, ln in enumerate(lines, 1):
            if symbol in ln:
                return idx
    if line and line <= len(lines):
        return line
    return None


def refresh_source(bundle: "ContextBundle", executor, path: str, line=None, ctx_lines: int = 26) -> "ContextBundle":
    """Point the bundle's source window at `path` (e.g. the file the diagnosis
    named in files_to_touch) when the compiler gave no location. Build-system and
    linker errors carry no file:line, so the original window is empty — without
    this the model rightly answers NO_PATCH because it can't see anything to edit."""
    rp = resolve_repo_path(executor, path)
    if rp:
        try:
            bundle.source_path = rp
            bundle.source_window = _window(executor.read_file(rp), line, ctx_lines)
        except Exception:
            pass
    return bundle


def build_context(
    parse_result: ParseResult,
    raw_output: str,
    executor,
    config,
    *,
    ctx_lines: int = 20,
) -> ContextBundle:
    primary = parse_result.primary
    budget = config.caps.token_budget_per_iteration

    source_path = resolve_repo_path(executor, primary.file) if primary else None
    source_window = ""
    if source_path:
        try:
            text = executor.read_file(source_path)
            eff = _effective_line(
                text, primary.symbol if primary else None, primary.line if primary else None
            )
            source_window = _window(text, eff, ctx_lines)
        except Exception:
            source_window = ""

    # error excerpt: the tail of the log, where the errors live.
    log_lines = raw_output.splitlines()
    error_excerpt = "\n".join(log_lines[-60:])

    def est(*parts: str) -> int:
        return _PROMPT_OVERHEAD_TOKENS + sum(len(p) for p in parts) // _CHARS_PER_TOKEN

    # Trim to budget: excerpt first, then the source window — but never trim the
    # source window below the lines around the error site.
    while est(source_window, error_excerpt) > budget and error_excerpt:
        el = error_excerpt.splitlines()
        if len(el) <= 12:
            break
        error_excerpt = "\n".join(el[len(el) // 4 :])
    while est(source_window, error_excerpt) > budget and source_window:
        sw = source_window.splitlines()
        if len(sw) <= 6:
            break
        drop = max(1, len(sw) // 6)
        source_window = "\n".join(sw[drop : len(sw) - drop])

    return ContextBundle(
        primary=primary,
        parse_result=parse_result,
        source_path=source_path,
        source_window=source_window,
        error_excerpt=error_excerpt,
        est_tokens=est(source_window, error_excerpt),
    )
