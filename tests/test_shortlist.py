"""Repo-shortlist harness: scoring, ranking, and evaluation against parsed output."""

from __future__ import annotations

from types import SimpleNamespace

from bridge.executor.base import ExecResult, Phase
from bridge.shortlist import RepoReport, evaluate_repo, render_report, shortlist


class StubExec:
    """Minimal executor that replays canned logs by command shape."""

    def __init__(self, hipify_log="", build_log="", build_ok=False, clone_ok=True):
        self.hipify_log, self.build_log = hipify_log, build_log
        self.build_ok, self.clone_ok = build_ok, clone_ok

    def run(self, command, *, cwd=None, timeout=None, phase=Phase.OTHER):
        if "git clone" in command:
            return ExecResult(command, 0 if self.clone_ok else 128, "", "", 0.0)
        if "hipify" in command:
            return ExecResult(command, 0, self.hipify_log, "", 0.0)
        return ExecResult(command, 0 if self.build_ok else 1, self.build_log, "", 0.0)

    def close(self):
        pass


CMDS = SimpleNamespace(hipify="hipify-perl x", configure=None, build="cmake --build build")


def test_evaluate_repo_scores_from_real_parse(fixtures_dir):
    hip = (fixtures_dir / "logs" / "hipify_run.txt").read_text(encoding="utf-8")
    build = (fixtures_dir / "logs" / "build_err_undeclared_cublas.txt").read_text(encoding="utf-8")
    r = evaluate_repo(StubExec(hip, build), "gemm", "http://x", "/tmp", CMDS)
    assert r.cloned and not r.build_ok
    assert r.hipify_pct == 84
    assert "undeclared_cuda_identifier" in r.error_classes
    assert r.num_clusters >= 1 and r.score > 0


def test_clone_failure_is_graceful():
    r = evaluate_repo(StubExec(clone_ok=False), "bad", "http://x", "/tmp", CMDS)
    assert not r.cloned and r.closeness == 0.0 and r.score == 0.0


def test_green_build_scores_highest():
    green = RepoReport("green", "u", cloned=True, build_ok=True)
    close = RepoReport("close", "u", cloned=True, hipify_pct=90, num_clusters=1,
                       error_classes=["a", "b", "c"])
    far = RepoReport("far", "u", cloned=True, hipify_pct=40, num_clusters=8, error_classes=["a"])
    assert green.closeness == 100.0
    assert green.score > close.score > far.score


def test_shortlist_ranks_and_renders(fixtures_dir):
    hip = (fixtures_dir / "logs" / "hipify_run.txt").read_text(encoding="utf-8")
    build = (fixtures_dir / "logs" / "build_err_undeclared_cublas.txt").read_text(encoding="utf-8")
    candidates = [{"name": "a", "url": "u1"}, {"name": "b", "url": "u2"}]
    # a builds green, b does not -> a ranks first
    reports = []
    for c, ok in zip(candidates, (True, False)):
        reports.append(evaluate_repo(StubExec(hip, build, build_ok=ok), c["name"], c["url"], "/tmp", CMDS))
    reports.sort(key=lambda r: r.score, reverse=True)
    assert reports[0].name == "a"
    txt = render_report(reports)
    assert "GREEN" in txt and "hipify" in txt
