"""Repo-shortlist harness: triage candidate CUDA repos on Day 1 and pick the demo.

For each candidate it clones the repo (on the MI300X box, via the executor), runs
HIPIFY and a dry build, parses the result with Bridge's own error parser, and
scores it. The ranking favours the spec's target: **closest to green, with the
most interesting residual failures** — a repo that already HIPIFY-converts cleanly
and fails on a small, varied set of error classes makes the best autonomous-fix
demo. The tool reports; the human picks.

Runs through the Executor interface, so it targets the real box over SSH; the
scoring/rendering is pure and unit-tested offline.
"""

from __future__ import annotations

import posixpath
import re
import shlex
from dataclasses import dataclass, field

from .parser import parse


@dataclass
class RepoReport:
    name: str
    url: str
    cloned: bool = True
    hipify_pct: int | None = None
    build_ok: bool = False
    num_clusters: int = 0
    error_classes: list[str] = field(default_factory=list)
    primary_class: str | None = None
    note: str = ""

    @property
    def closeness(self) -> float:
        """0–100: how close to a green build. Green = 100; otherwise HIPIFY % with
        a penalty per residual error cluster."""
        if not self.cloned:
            return 0.0
        if self.build_ok:
            return 100.0
        base = float(self.hipify_pct if self.hipify_pct is not None else 50.0)
        return max(0.0, base - 6.0 * self.num_clusters)

    @property
    def interest(self) -> int:
        """Distinct error classes = variety of autonomous fixes to show off."""
        return len(self.error_classes)

    @property
    def score(self) -> float:
        return round(self.closeness + 4.0 * self.interest, 1)


_NAME_OK = re.compile(r"^[A-Za-z0-9._-]+$")


def evaluate_repo(executor, name: str, url: str, workdir: str, commands) -> RepoReport:
    # The candidates file is user-authored, but names/urls still get interpolated
    # into a shell command with `rm -rf` in it — validate and quote, always.
    if not _NAME_OK.match(name) or name in (".", ".."):
        return RepoReport(name, url, cloned=False, note="invalid repo name (letters/digits/._- only)")
    dest = posixpath.join(workdir, name)
    clone = executor.run(
        f"rm -rf {shlex.quote(dest)} && git clone --depth 1 {shlex.quote(url)} {shlex.quote(dest)}"
    )
    if not clone.ok:
        return RepoReport(name, url, cloned=False, note="clone failed")
    hip = executor.run(commands.hipify, cwd=dest)
    hstats = parse(hip.combined_output).hipify
    if commands.configure:
        executor.run(commands.configure, cwd=dest)
    build = executor.run(commands.build, cwd=dest)
    pr = parse(build.combined_output)
    return RepoReport(
        name=name,
        url=url,
        cloned=True,
        hipify_pct=(hstats.conversion_pct if hstats else None),
        build_ok=build.ok,
        num_clusters=len(pr.clusters),
        error_classes=pr.error_classes,
        primary_class=(pr.primary.error_class if pr.primary else None),
    )


def shortlist(executor, candidates: list[dict], workdir: str, commands) -> list[RepoReport]:
    reports = [evaluate_repo(executor, c["name"], c["url"], workdir, commands) for c in candidates]
    reports.sort(key=lambda r: r.score, reverse=True)
    return reports


def render_report(reports: list[RepoReport]) -> str:
    out = [
        f"{'#':<3}{'repo':<18}{'score':<7}{'hipify':<8}{'build':<7}{'clusters':<9}primary  [classes]",
        "-" * 92,
    ]
    for i, r in enumerate(reports, 1):
        if not r.cloned:
            out.append(f"{i:<3}{r.name:<18}{'-':<7}{'-':<8}{'-':<7}{'-':<9}{r.note}")
            continue
        hp = f"{r.hipify_pct}%" if r.hipify_pct is not None else "?"
        build = "GREEN" if r.build_ok else "red"
        classes = ", ".join(r.error_classes[:5]) or "-"
        out.append(
            f"{i:<3}{r.name:<18}{r.score:<7}{hp:<8}{build:<7}{r.num_clusters:<9}"
            f"{r.primary_class or '-'}  [{classes}]"
        )
    out += ["", "Pick: closest to green (high hipify%, few clusters) with the most",
            "interesting variety (high 'classes') — that makes the best live demo."]
    return "\n".join(out)
