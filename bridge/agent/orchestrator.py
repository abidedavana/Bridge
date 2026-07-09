"""The orchestrator: Bridge's explicit state machine (no framework, no magic).

One loop, readable top to bottom:

    hipify once
    repeat up to max_iterations:
        build
          ok  -> test -> (ok: SUCCESS) or (fail: this is the cluster to fix)
          fail-> (this is the cluster to fix)
        parse -> pick primary diagnostic -> its cluster
        if the cluster has hit the attempt cap -> mark STUCK, stop (PARTIAL if we
            ever had a green build, else STUCK)
        build context -> diagnose -> propose_edit -> policy-gate + apply -> commit
        (a real commit advances the port; a rejected/failed patch just costs an
         attempt)

Every terminal state is reported; nothing loops forever; no executor or model
output can crash it (the spec's orchestrator property). Each iteration is written
to the RunRecorder, so the dashboard shows the loop live and the run log persists.
"""

from __future__ import annotations

import enum
import hashlib
import time
from typing import Optional

from ..executor.base import Phase
from ..llm import LLMTransportError
from ..parser import parse
from ..patcher import apply_patch
from ..run_state import IterationRecord, RunRecorder
from .context import build_context, refresh_source
from .stages import diagnose, propose_edit


def _error_fingerprint(output: str) -> str:
    """Stable short id for an unrecognised error: hash of the last meaningful
    lines. The same failure keeps its identity across attempts (so the attempt
    cap still catches true loops), while a *different* failure gets a fresh
    cluster and a fresh budget."""
    tail = [ln.strip() for ln in output.strip().splitlines() if ln.strip()][-6:]
    return hashlib.md5("\n".join(tail).encode("utf-8", "replace")).hexdigest()[:8]


class RunOutcome(str, enum.Enum):
    SUCCESS = "SUCCESS"    # build green and all tests pass
    PARTIAL = "PARTIAL"    # build green, but a test cluster exhausted its attempts
    STUCK = "STUCK"        # build never went green; a build cluster exhausted
    EXHAUSTED = "EXHAUSTED"  # hit max_iterations


class Orchestrator:
    def __init__(self, config, executor, backend, prompts: dict, recorder: RunRecorder,
                 delay: float = 0.0):
        self.cfg = config
        self.executor = executor
        self.backend = backend
        self.prompts = prompts
        self.recorder = recorder
        self.delay = delay  # optional pause per iteration so the dashboard shows a live climb
        self.stuck_clusters: list[tuple] = []
        self.transport_error: str | None = None
        self.internal_error: str | None = None
        self._reached_green = False
        self._max_test_total = 0

    def run(self) -> RunOutcome:
        """Run to a terminal state. Never raises, never leaves the run log
        unfinished: a dead LLM endpoint (after the backend's own retries) or any
        unexpected internal failure degrades to an honest STUCK/PARTIAL with the
        reason recorded."""
        try:
            outcome = self._loop()
        except LLMTransportError as exc:
            self.transport_error = str(exc)
            self.stuck_clusters.append(("llm_endpoint_unreachable", None))
            outcome = RunOutcome.PARTIAL if self._reached_green else RunOutcome.STUCK
        except Exception as exc:  # noqa: BLE001 — the run log must always finish
            self.internal_error = f"{type(exc).__name__}: {exc}"
            self.stuck_clusters.append(("internal_error", None))
            outcome = RunOutcome.PARTIAL if self._reached_green else RunOutcome.STUCK
        self.recorder.finish(outcome.value)
        return outcome

    def _loop(self) -> RunOutcome:
        self._hipify()
        attempts: dict[tuple, int] = {}
        outcome = RunOutcome.EXHAUSTED

        # CMake projects need their one-time configure step; running it as part
        # of every build keeps configure-stage errors (cmake_cuda_language etc.)
        # visible and fixable by the loop, exactly like the recorded live runs.
        build_cmd = self.cfg.commands.build
        if self.cfg.commands.configure:
            build_cmd = f"{self.cfg.commands.configure} && {build_cmd}"

        for iteration in range(1, self.cfg.caps.max_iterations + 1):
            build = self.executor.run(build_cmd, phase=Phase.BUILD)
            if build.ok:
                self._reached_green = True
                test = self.executor.run(self.cfg.commands.test, phase=Phase.TEST)
                pr = parse(test.combined_output)
                if pr.total is not None and 0 < pr.total < self._max_test_total:
                    # The suite SHRANK. A "pass" that runs fewer tests than we
                    # have already seen is treated as de-registration (an edit
                    # to a build file can remove add_test without touching any
                    # test file) — never as progress, never as SUCCESS.
                    self.stuck_clusters.append(("test_count_dropped", None))
                    self._record(iteration, "test", False, pr, None, 0, 0, 0.0,
                                 note=(f"test total dropped {self._max_test_total} -> "
                                       f"{pr.total}: refusing (possible de-registration)"),
                                 duration=test.duration_s)
                    outcome = RunOutcome.PARTIAL
                    break
                if pr.total:
                    self._max_test_total = max(self._max_test_total, pr.total)
                if test.ok:
                    self._record(iteration, "test", True, pr, None, 0, 0, 0.0,
                                 duration=test.duration_s)
                    outcome = RunOutcome.SUCCESS
                    break
                phase, raw = "test", test
            else:
                pr = parse(build.combined_output)
                phase, raw = "build", build

            primary = pr.primary
            # Unparsed errors get a fingerprint identity instead of a shared
            # ("unknown", None): otherwise three DIFFERENT unrecognised errors
            # burn one cluster's attempt budget and a run that is making real
            # progress gets declared STUCK prematurely (hardware-day find).
            cluster = (
                (primary.error_class, primary.file)
                if primary
                else ("unknown", _error_fingerprint(raw.combined_output))
            )

            if attempts.get(cluster, 0) >= self.cfg.caps.max_attempts_per_cluster:
                self.stuck_clusters.append(cluster)
                outcome = RunOutcome.PARTIAL if self._reached_green else RunOutcome.STUCK
                self._record(iteration, phase, False, pr, None, 0, 0, 0.0,
                             note=f"STUCK: cluster {cluster[0]} hit attempt cap",
                             duration=raw.duration_s)
                break
            attempts[cluster] = attempts.get(cluster, 0) + 1

            diff_applied, pt, ct, cost, note = self._attempt_fix(iteration, pr, raw, phase, primary)
            self._record(iteration, phase, False, pr, diff_applied, pt, ct, cost,
                         note=note, duration=raw.duration_s)
            if self.delay:
                time.sleep(self.delay)

        return outcome

    # -- one fix attempt: diagnose -> propose -> gate+apply -> commit ---------

    def _attempt_fix(self, iteration, pr, raw, phase, primary):
        """One fix attempt. Returns (applied_diff, prompt_tokens, completion_tokens,
        cost, note). Tokens already spent are reported even when the attempt dies
        partway — the cost counter never undercounts."""
        pt = ct = 0
        applied_diff = None
        note = None
        try:
            bundle = build_context(pr, raw.combined_output, self.executor, self.cfg)
            diagnosis, dp, dc, dstatus = diagnose(self.backend, self.prompts, bundle, phase)
            pt, ct = pt + dp, ct + dc
            if dstatus == "ok":
                # Build-system/linker/test errors often carry no file:line, which
                # leaves the source window empty. Fall back to the file the
                # diagnosis itself named, so the patch stage has code to edit.
                if not bundle.source_window:
                    for cand in diagnosis.get("files_to_touch") or []:
                        refresh_source(bundle, self.executor, cand)
                        if bundle.source_window:
                            break
                diff, pp, pc, pstatus = propose_edit(self.backend, self.prompts, diagnosis, bundle)
                pt, ct = pt + pp, ct + pc
                if pstatus == "ok" and diff:
                    patch = apply_patch(self.executor, diff, self.cfg)
                    if not patch.applied and patch.rejected_by == "apply":
                        # The diff was well-formed and in-policy but didn't apply
                        # (LLMs miscount hunks / drift context). Feed git's error
                        # back for ONE regeneration. Policy rejections are never
                        # retried this way — we don't coach past the security gate.
                        diff2, pp2, pc2, pstatus2 = propose_edit(
                            self.backend, self.prompts, diagnosis, bundle,
                            feedback=(diff, patch.reason),
                        )
                        pt, ct = pt + pp2, ct + pc2
                        if pstatus2 == "ok" and diff2:
                            diff = diff2
                            patch = apply_patch(self.executor, diff, self.cfg)
                    if patch.applied:
                        applied_diff = diff
                        if not self._commit(iteration, primary, diagnosis,
                                            patch.touched_files):
                            note = "fix applied but git commit FAILED (audit trail gap)"
        except LLMTransportError:
            raise  # a dead brain aborts the run cleanly (caught by the caller)
        except Exception as exc:  # noqa: BLE001 — a spent attempt, never a crash
            note = f"attempt aborted: {type(exc).__name__}: {exc}"[:200]
        return applied_diff, pt, ct, self.cfg.llm.cost.token_cost(pt, ct), note

    def _commit(self, iteration, primary, diagnosis, touched_files) -> bool:
        klass = primary.error_class if primary else "unknown"
        summary = str(diagnosis.get("fix_summary", "apply fix")).replace("\n", " ")[:120]
        msg = f"bridge(iter {iteration}, {klass}): {summary}\n"
        # -F from a file avoids any shell-quoting of model-authored text. The
        # -c identity flags make the commit work on boxes with no global git
        # identity (the hackathon GPU pod had none, and every audit-trail commit
        # silently failed — hardware-day find).
        self.executor.write_file(".git/bridge_commit_msg.txt", msg)
        # Stage ONLY the files the gated diff touched: `git add -A` would sweep
        # build artifacts (or anything else untracked) into the audit commits on
        # repos without a .gitignore. Paths are gate-vetted (no leading '-', no
        # absolute/traversal), and `--` ends option parsing.
        paths = " ".join(f'"{p}"' for p in dict.fromkeys(touched_files) if '"' not in p)
        add = self.executor.run(f"git add -- {paths}" if paths else "git add -A",
                                phase=Phase.OTHER)
        res = self.executor.run(
            "git -c user.name=bridge-agent -c user.email=bridge@agent.local "
            "commit -q -F .git/bridge_commit_msg.txt",
            phase=Phase.OTHER,
        )
        return add.ok and res.ok

    def _hipify(self) -> None:
        hip = self.executor.run(self.cfg.commands.hipify, phase=Phase.HIPIFY)
        stats = parse(hip.combined_output).hipify
        if stats:
            self.recorder.set_hipify(stats.conversion_pct, stats.warnings)

    def _record(self, iteration, phase, ok, pr, diff, pt, ct, cost,
                note: Optional[str] = None, duration: float = 0.0):
        p = pr.primary
        self.recorder.add(IterationRecord(
            iteration=iteration,
            phase=phase,
            outcome="ok" if ok else "fail",
            error_class=p.error_class if p else None,
            location=p.location if p else None,
            message=note or (p.message if p else None),
            error_classes=pr.error_classes,
            passed=pr.passed,
            total=pr.total,
            diff=diff,
            prompt_tokens=pt,
            completion_tokens=ct,
            cost=cost,
            duration_s=duration,
        ))
