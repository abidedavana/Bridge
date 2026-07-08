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
import time
from typing import Optional

from ..executor.base import Phase
from ..llm import LLMTransportError
from ..parser import parse
from ..patcher import apply_patch
from ..run_state import IterationRecord, RunRecorder
from .context import build_context, refresh_source
from .stages import diagnose, propose_edit


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
        self._reached_green = False

    def run(self) -> RunOutcome:
        """Run to a terminal state. Never raises, never leaves the run log
        unfinished: even a dead LLM endpoint (after the backend's own retries)
        degrades to an honest STUCK/PARTIAL with the reason recorded."""
        try:
            outcome = self._loop()
        except LLMTransportError as exc:
            self.transport_error = str(exc)
            self.stuck_clusters.append(("llm_endpoint_unreachable", None))
            outcome = RunOutcome.PARTIAL if self._reached_green else RunOutcome.STUCK
        self.recorder.finish(outcome.value)
        return outcome

    def _loop(self) -> RunOutcome:
        self._hipify()
        attempts: dict[tuple, int] = {}
        outcome = RunOutcome.EXHAUSTED

        for iteration in range(1, self.cfg.caps.max_iterations + 1):
            build = self.executor.run(self.cfg.commands.build, phase=Phase.BUILD)
            if build.ok:
                self._reached_green = True
                test = self.executor.run(self.cfg.commands.test, phase=Phase.TEST)
                pr = parse(test.combined_output)
                if test.ok:
                    self._record(iteration, "test", True, pr, None, 0, 0, 0.0)
                    outcome = RunOutcome.SUCCESS
                    break
                phase, raw = "test", test
            else:
                pr = parse(build.combined_output)
                phase, raw = "build", build

            primary = pr.primary
            cluster = (primary.error_class, primary.file) if primary else ("unknown", None)

            if attempts.get(cluster, 0) >= self.cfg.caps.max_attempts_per_cluster:
                self.stuck_clusters.append(cluster)
                outcome = RunOutcome.PARTIAL if self._reached_green else RunOutcome.STUCK
                self._record(iteration, phase, False, pr, None, 0, 0, 0.0,
                             note=f"STUCK: cluster {cluster[0]} hit attempt cap")
                break
            attempts[cluster] = attempts.get(cluster, 0) + 1

            diff_applied, pt, ct, cost = self._attempt_fix(iteration, pr, raw, phase, primary)
            self._record(iteration, phase, False, pr, diff_applied, pt, ct, cost)
            if self.delay:
                time.sleep(self.delay)

        return outcome

    # -- one fix attempt: diagnose -> propose -> gate+apply -> commit ---------

    def _attempt_fix(self, iteration, pr, raw, phase, primary):
        try:
            bundle = build_context(pr, raw.combined_output, self.executor, self.cfg)
            diagnosis, dp, dc, dstatus = diagnose(self.backend, self.prompts, bundle, phase)
            pp = pc = 0
            applied_diff = None
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
                        pp, pc = pp + pp2, pc + pc2
                        if pstatus2 == "ok" and diff2:
                            diff = diff2
                            patch = apply_patch(self.executor, diff, self.cfg)
                    if patch.applied:
                        applied_diff = diff
                        self._commit(iteration, primary, diagnosis)
            pt, ct = dp + pp, dc + pc
            return applied_diff, pt, ct, self.cfg.llm.cost.token_cost(pt, ct)
        except LLMTransportError:
            raise  # a dead brain aborts the run cleanly (caught by the caller)
        except Exception:
            # any other failure is a spent attempt, never a crash
            return None, 0, 0, 0.0

    def _commit(self, iteration, primary, diagnosis) -> None:
        klass = primary.error_class if primary else "unknown"
        summary = str(diagnosis.get("fix_summary", "apply fix")).replace("\n", " ")[:120]
        msg = f"bridge(iter {iteration}, {klass}): {summary}\n"
        # -F from a file avoids any shell-quoting of model-authored text.
        self.executor.write_file(".git/bridge_commit_msg.txt", msg)
        self.executor.run("git add -A", phase=Phase.OTHER)
        self.executor.run("git commit -q -F .git/bridge_commit_msg.txt", phase=Phase.OTHER)

    def _hipify(self) -> None:
        hip = self.executor.run(self.cfg.commands.hipify, phase=Phase.HIPIFY)
        stats = parse(hip.combined_output).hipify
        if stats:
            self.recorder.set_hipify(stats.conversion_pct, stats.warnings)

    def _record(self, iteration, phase, ok, pr, diff, pt, ct, cost, note: Optional[str] = None):
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
        ))
