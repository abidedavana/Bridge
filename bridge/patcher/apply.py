"""Apply a validated diff to the target repo — mechanically, never leaving mess.

Order: (1) the policy gate rejects anything out of bounds; (2) the diff is staged
*inside* `.git/` so it never dirties the work tree; (3) `git apply --check` proves
it applies before we touch anything; (4) the real apply is atomic. On any failure
the working tree is left clean, and the reason is returned (never raised) so the
orchestrator can retry once or mark the cluster STUCK.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from .policy import check_diff

# Inside .git/ → not part of the tracked work tree, so staging the patch here
# cannot dirty the repo or get swept into a commit.
_PATCH_FILE = ".git/bridge_patch.diff"


@dataclass
class PatchResult:
    applied: bool
    reason: str
    touched_files: list = field(default_factory=list)
    rejected_by: str = ""  # "policy" | "apply" | ""

    @property
    def ok(self) -> bool:
        return self.applied


def apply_patch(executor, diff: str, config, *, repo_cwd: Optional[str] = None) -> PatchResult:
    pol = check_diff(diff, config)
    if not pol.ok:
        return PatchResult(False, pol.reason, pol.facts.touched_files, "policy")

    executor.write_file(_PATCH_FILE, diff if diff.endswith("\n") else diff + "\n")

    # --recount: LLM-authored diffs are often semantically right but miscount the
    # @@ hunk headers; let git infer the counts from the patch body instead of
    # rejecting good fixes over arithmetic (observed on the first live run).
    _FLAGS = "--whitespace=nowarn --recount"

    chk = executor.run(f"git apply --check {_FLAGS} {_PATCH_FILE}", cwd=repo_cwd)
    if not chk.ok:
        return PatchResult(
            False,
            f"git apply --check failed: {chk.combined_output.strip()[:200]}",
            pol.facts.touched_files,
            "apply",
        )

    res = executor.run(f"git apply {_FLAGS} {_PATCH_FILE}", cwd=repo_cwd)
    if not res.ok:
        executor.run("git checkout -- .", cwd=repo_cwd)  # defensive: keep tree clean
        return PatchResult(
            False,
            f"git apply failed: {res.combined_output.strip()[:200]}",
            pol.facts.touched_files,
            "apply",
        )
    return PatchResult(True, "applied", pol.facts.touched_files, "")
