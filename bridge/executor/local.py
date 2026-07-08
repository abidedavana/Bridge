"""LocalExecutor: really runs commands on the local machine.

This is the substrate the MockExecutor builds on. Bridge never asks LocalExecutor
to build or test CUDA (there is no GPU on the dev box); it is used for the parts of
the loop that must be *real* even in simulation -- git commits, file writes, patch
application -- so that "real diffs, real commits to a scratch repo" (Milestone 3)
is genuinely real, not faked.

On its own it is also a legitimate executor for a machine that *does* have ROCm
installed locally, though that is not the supported demo path.
"""

from __future__ import annotations

import os
import subprocess
import time

from .base import ExecResult, Executor, Phase


class LocalExecutor(Executor):
    """Run commands in a local working directory via the system shell."""

    def __init__(self, workdir: str, *, shell: bool = True, env: dict | None = None):
        self.workdir = os.path.abspath(workdir)
        self._shell = shell
        self._env = env

    def run(
        self,
        command: str,
        *,
        cwd: str | None = None,
        timeout: float | None = None,
        phase: Phase = Phase.OTHER,
    ) -> ExecResult:
        run_cwd = os.path.abspath(cwd) if cwd else self.workdir
        env = None
        if self._env is not None:
            env = {**os.environ, **self._env}
        start = time.monotonic()
        try:
            proc = subprocess.run(
                command,
                shell=self._shell,
                cwd=run_cwd,
                capture_output=True,
                text=True,
                timeout=timeout,
                env=env,
            )
            duration = time.monotonic() - start
            return ExecResult(
                command=command,
                exit_code=proc.returncode,
                stdout=proc.stdout or "",
                stderr=proc.stderr or "",
                duration_s=duration,
                phase=phase,
            )
        except subprocess.TimeoutExpired as exc:
            duration = time.monotonic() - start
            return ExecResult(
                command=command,
                exit_code=124,  # conventional timeout exit code
                stdout=(exc.stdout or b"").decode("utf-8", "replace")
                if isinstance(exc.stdout, bytes)
                else (exc.stdout or ""),
                stderr=f"bridge: command timed out after {timeout}s",
                duration_s=duration,
                phase=phase,
            )

    # -- filesystem access ---------------------------------------------------

    def _abspath(self, path: str) -> str:
        return path if os.path.isabs(path) else os.path.join(self.workdir, path)

    def read_file(self, path: str) -> str:
        with open(self._abspath(path), "r", encoding="utf-8") as fh:
            return fh.read()

    def write_file(self, path: str, content: str) -> None:
        target = self._abspath(path)
        os.makedirs(os.path.dirname(target) or ".", exist_ok=True)
        with open(target, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(content)

    def exists(self, path: str) -> bool:
        return os.path.exists(self._abspath(path))
