"""The patch policy engine — the mechanical trust gate (THREAT_MODEL T1/T3/T4).

Every diff is checked here *before* it is applied, so the guardrails hold even if
the model is wrong or adversarially steered by indirect prompt injection. A diff
is rejected if it: touches a file outside the writable allowlist, touches a
protected path, edits a test file (unless explicitly allowed), introduces a
forbidden construct (shell-out / network / eval), exceeds the size cap, or creates
too many new files. Pure and I/O-free so it is exhaustively unit-testable,
including against the poisoned fixture's payload.
"""

from __future__ import annotations

import fnmatch
from dataclasses import dataclass, field


@dataclass
class DiffFacts:
    touched_files: list[str] = field(default_factory=list)
    new_files: list[str] = field(default_factory=list)
    added_lines: list[str] = field(default_factory=list)
    changed_line_count: int = 0


@dataclass
class PolicyResult:
    ok: bool
    reason: str = ""
    facts: DiffFacts = field(default_factory=DiffFacts)


def parse_diff(diff: str) -> DiffFacts:
    facts = DiffFacts()
    pending_new = False
    for line in diff.splitlines():
        if line.startswith("--- "):
            src = line[4:].strip()
            pending_new = src.endswith("/dev/null")
        elif line.startswith("+++ "):
            path = line[4:].strip()
            if path.startswith("b/"):
                path = path[2:]
            if path != "/dev/null":
                facts.touched_files.append(path)
                if pending_new:
                    facts.new_files.append(path)
            pending_new = False
        elif line.startswith("+") and not line.startswith("+++"):
            facts.added_lines.append(line[1:])
            facts.changed_line_count += 1
        elif line.startswith("-") and not line.startswith("---"):
            facts.changed_line_count += 1
    return facts


def _matches_any(path: str, globs: list[str]) -> bool:
    for g in globs:
        if fnmatch.fnmatch(path, g):
            return True
        # fnmatch has no globstar: '**/foo' never matches a root-level 'foo'
        # (no '/'). Treat '**/' as "any depth, including zero" — without this
        # the gate rejected perfect root-level CMakeLists.txt fixes on the
        # first live run.
        if g.startswith("**/") and fnmatch.fnmatch(path, g[3:]):
            return True
    return False


def check_diff(diff: str, config) -> PolicyResult:
    """Mechanically vet a unified diff against config policy + security."""
    facts = parse_diff(diff)
    if not facts.touched_files:
        return PolicyResult(False, "diff touches no files", facts)

    sec = config.security
    pol = config.policy

    for path in facts.touched_files:
        if _matches_any(path, sec.protected_globs):
            return PolicyResult(False, f"edits protected path: {path}", facts)
        if not pol.patch_test_files and _matches_any(path, pol.test_globs):
            return PolicyResult(False, f"edits a test file (forbidden): {path}", facts)
        if sec.writable_globs and not _matches_any(path, sec.writable_globs):
            return PolicyResult(False, f"edits outside writable allowlist: {path}", facts)

    low_forbidden = [t.lower() for t in sec.forbidden_insertions]
    for added in facts.added_lines:
        al = added.lower()
        for tok, raw in zip(low_forbidden, sec.forbidden_insertions):
            if tok in al:
                return PolicyResult(False, f"introduces forbidden construct '{raw}'", facts)

    if facts.changed_line_count > config.caps.max_patch_lines:
        return PolicyResult(
            False,
            f"diff too large: {facts.changed_line_count} > {config.caps.max_patch_lines} lines",
            facts,
        )
    if len(facts.new_files) > sec.max_new_files:
        return PolicyResult(
            False, f"creates too many new files: {len(facts.new_files)} > {sec.max_new_files}", facts
        )

    return PolicyResult(True, "ok", facts)
