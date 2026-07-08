"""MockExecutor: a faithful, GPU-free stand-in for the MI300X box.

It is a `LocalExecutor` with exactly three kinds of command intercepted and
replayed from a `Scenario`: HIPIFY, build, and test. Everything else -- git,
mkdir, cp, patch application -- is really executed on the local machine. That
split is intentional:

  * The parts that must be *real* to be convincing (git commits recording each
    agent attempt, patches actually applying to files) really happen.
  * The parts that need a GPU + ROCm toolchain (compiling and running CUDA/HIP)
    are replayed from logs captured from the real tools.

The result: `docker compose up` on a laptop drives the entire agent loop -- real
diffs, real commits, a live-climbing pass-rate chart -- against a scripted but
authentic AMD toolchain.
"""

from __future__ import annotations

import time

from .base import ExecResult, Executor, Phase
from .local import LocalExecutor
from .scenario import ResultSpec, Scenario, Stage


class MockExecutor(LocalExecutor):
    def __init__(
        self,
        workdir: str,
        scenario: Scenario,
        *,
        build_cmd: str | None = None,
        test_cmd: str | None = None,
        hipify_cmd: str | None = None,
        sim_hipify_s: float = 0.5,
        sim_build_s: float = 2.0,
        sim_test_s: float = 1.0,
    ):
        super().__init__(workdir)
        self.scenario = scenario
        self._build_cmd = build_cmd
        self._test_cmd = test_cmd
        self._hipify_cmd = hipify_cmd
        self._sim = {
            Phase.HIPIFY: sim_hipify_s,
            Phase.BUILD: sim_build_s,
            Phase.TEST: sim_test_s,
        }
        # replay state
        self.stage_index = 0
        self.commits_in_stage = 0
        self.build_calls = 0
        self.test_calls = 0
        self.hipify_calls = 0
        self.commits_total = 0

    # -- introspection for the dashboard and tests ---------------------------

    @property
    def current_stage(self) -> Stage:
        return self.scenario.stages[self.stage_index]

    def progress(self) -> dict:
        st = self.current_stage
        return {
            "stage_index": self.stage_index,
            "stage_name": st.name,
            "stages_total": len(self.scenario.stages),
            "commits_in_stage": self.commits_in_stage,
            "commits_total": self.commits_total,
            "sticky": st.sticky,
        }

    # -- command classification ---------------------------------------------

    def _classify(self, command: str, phase: Phase) -> Phase:
        # An explicit build/test/hipify tag from the caller is authoritative.
        if phase is not Phase.OTHER:
            return phase
        # Exact match against a configured command wins next.
        stripped = command.strip()
        if self._hipify_cmd and stripped == self._hipify_cmd.strip():
            return Phase.HIPIFY
        if self._build_cmd and stripped == self._build_cmd.strip():
            return Phase.BUILD
        if self._test_cmd and stripped == self._test_cmd.strip():
            return Phase.TEST
        # git and other bookkeeping commands are always executed for real, never
        # simulated -- this is what makes "real commits to a scratch repo" real.
        # Classification is by the *leading program token* only (via looks_like),
        # never a substring-anywhere match: a commit message such as
        # "fix test ..." must not be mistaken for a test run, and a `git apply`
        # must not be mistaken for a build.
        if Executor.looks_like(command, "git"):
            return Phase.OTHER
        for needle in ("hipify-perl", "hipify-clang", "hipify"):
            if Executor.looks_like(command, needle):
                return Phase.HIPIFY
        for needle in ("cmake --build", "make", "ninja", "msbuild"):
            if Executor.looks_like(command, needle):
                return Phase.BUILD
        for needle in ("ctest", "pytest", "run_tests"):
            if Executor.looks_like(command, needle):
                return Phase.TEST
        return Phase.OTHER

    # -- the executor contract ----------------------------------------------

    def run(
        self,
        command: str,
        *,
        cwd: str | None = None,
        timeout: float | None = None,
        phase: Phase = Phase.OTHER,
    ) -> ExecResult:
        kind = self._classify(command, phase)

        if kind is Phase.HIPIFY:
            self.hipify_calls += 1
            return self._replay(command, self.scenario.hipify, Phase.HIPIFY)

        if kind is Phase.BUILD:
            self.build_calls += 1
            return self._replay(command, self.current_stage.build, Phase.BUILD)

        if kind is Phase.TEST:
            self.test_calls += 1
            spec = self.current_stage.test
            if spec is None:
                # The orchestrator should only test after a green build, but stay
                # graceful: report that tests could not run rather than crash.
                spec = ResultSpec(
                    log_path="<synthetic>",
                    exit_code=1,
                    text="bridge(mock): build is not green; test stage not reached.",
                    passed=0,
                    total=None,
                )
            return self._replay(command, spec, Phase.TEST)

        # Everything else really runs locally (git, patch, mkdir, ...).
        result = super().run(command, cwd=cwd, timeout=timeout, phase=phase)
        self._maybe_advance_on_commit(command, result)
        return result

    # -- internals -----------------------------------------------------------

    def _replay(self, command: str, spec: ResultSpec, phase: Phase) -> ExecResult:
        # Simulated (deterministic) duration so the dashboard shows timing.
        duration = self._sim.get(phase, 0.0)
        return ExecResult(
            command=command,
            exit_code=spec.exit_code,
            stdout=spec.text,
            stderr="",
            duration_s=duration,
            phase=phase,
        )

    def _maybe_advance_on_commit(self, command: str, result: ExecResult) -> None:
        if not result.ok:
            return
        if not Executor.looks_like(command, "git commit"):
            return
        self.commits_total += 1
        self.commits_in_stage += 1
        stage = self.current_stage
        if stage.sticky:
            return  # sticky stages never advance (terminal green or STUCK error)
        if self.commits_in_stage >= stage.min_commits:
            if self.stage_index < len(self.scenario.stages) - 1:
                self.stage_index += 1
                self.commits_in_stage = 0
