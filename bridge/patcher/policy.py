"""The patch policy engine — the mechanical trust gate (THREAT_MODEL T1/T3/T4).

Every diff is checked here *before* it is applied, so the guardrails hold even if
the model is wrong or adversarially steered by indirect prompt injection. A diff
is rejected if it: touches a file outside the writable allowlist (checked on BOTH
sides of every hunk, so deletions and renames are policy-checked by their old path
too), touches a protected path, edits or deletes a test file (unless explicitly
allowed), introduces a forbidden construct (shell-out / network / eval), changes a
file mode or creates a non-regular file (symlinks), uses a traversal or absolute
path, exceeds the size cap, or creates too many new files. Pure and I/O-free so it
is exhaustively unit-testable, including against the poisoned fixture's payload.
"""

from __future__ import annotations

import fnmatch
import re
from dataclasses import dataclass, field

# Windows drive-letter prefix ("C:...") — an absolute path in disguise.
_DRIVE_PREFIX = re.compile(r"^[A-Za-z]:")


@dataclass
class DiffFacts:
    touched_files: list[str] = field(default_factory=list)
    new_files: list[str] = field(default_factory=list)
    added_lines: list[str] = field(default_factory=list)
    changed_line_count: int = 0
    # Extended git headers that alter a file's mode or type (symlink creation,
    # executable-bit flips). Porting fixes never need these; the gate rejects them.
    mode_lines: list[str] = field(default_factory=list)


@dataclass
class PolicyResult:
    ok: bool
    reason: str = ""
    facts: DiffFacts = field(default_factory=DiffFacts)


def parse_diff(diff: str) -> DiffFacts:
    facts = DiffFacts()
    pending_new = False

    def touch(path: str) -> None:
        if path.startswith(("a/", "b/")):
            path = path[2:]
        if path and path != "/dev/null" and path not in facts.touched_files:
            facts.touched_files.append(path)

    for line in diff.splitlines():
        if line.startswith("--- "):
            src = line[4:].strip()
            pending_new = src.endswith("/dev/null")
            if not pending_new:
                # The OLD path is policy-relevant too: a deletion hunk
                # ("+++ /dev/null") or a rename would otherwise slip past the
                # test-file / protected / allowlist checks entirely.
                touch(src)
        elif line.startswith("+++ "):
            path = line[4:].strip()
            if path.startswith("b/"):
                path = path[2:]
            if path != "/dev/null":
                if path not in facts.touched_files:
                    facts.touched_files.append(path)
                if pending_new:
                    facts.new_files.append(path)
            pending_new = False
        elif line.startswith(("rename from ", "rename to ")):
            # git rename headers carry bare paths (no a/ b/ prefix) and may
            # appear with no ---/+++ pair at all (100% similarity).
            touch(line.split(" ", 2)[2])
        elif line.startswith(("old mode ", "new mode ")) or (
            line.startswith("new file mode ") and not line.rstrip().endswith("100644")
        ):
            facts.mode_lines.append(line.strip())
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

    # Path shape first: no absolute paths, no traversal, no option-lookalikes.
    # (git apply also refuses most of these by default, but the gate must not
    # depend on another tool's defaults for a security property.)
    for path in facts.touched_files:
        norm = path.replace("\\", "/")
        if norm.startswith(("/", "-")) or ".." in norm.split("/") or _DRIVE_PREFIX.match(norm):
            return PolicyResult(False, f"suspicious path (absolute/traversal): {path}", facts)

    if facts.mode_lines:
        return PolicyResult(
            False, f"changes a file mode/type (forbidden): {facts.mode_lines[0]}", facts
        )

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
