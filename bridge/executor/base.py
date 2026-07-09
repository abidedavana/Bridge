"""The Executor interface: the single seam between Bridge's logic and the hardware.

Every command Bridge runs against the target repo -- HIPIFY, build, test, git,
file reads/writes -- goes through an `Executor`. Three implementations:

  * `MockExecutor`  - replays realistic fixture logs; needs no GPU (dev/CI path).
  * `LocalExecutor` - runs for real on THIS machine (the ROCm box / GPU pod path
                      used for the recorded gfx1100 hardware run).
  * `SSHExecutor`   - runs everything on a remote AMD box over SSH/SFTP.

One config switch (`executor.kind`) chooses between them. Because the orchestrator
only ever sees this interface, the *exact same* agent loop drives a laptop
simulation and a live hardware port.

Design note on phases: build systems and compilers scatter diagnostics across
stdout and stderr, so the parser always reads `combined_output`. The orchestrator
tags build/test/hipify invocations with a `Phase` so a mock executor knows which
calls to simulate; untagged calls (git, cp, mkdir) are treated as ordinary
commands and really executed.
"""

from __future__ import annotations

import shlex
from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum


class Phase(str, Enum):
    """What kind of step a command represents.

    The mock executor simulates HIPIFY/BUILD/TEST from fixtures and really runs
    everything tagged OTHER (git, filesystem). The SSH executor ignores the tag
    and runs everything remotely; the tag is still recorded for the run log.
    """

    HIPIFY = "hipify"
    BUILD = "build"
    TEST = "test"
    OTHER = "other"


@dataclass
class ExecResult:
    """The outcome of one command. Immutable record for the run log."""

    command: str
    exit_code: int
    stdout: str
    stderr: str
    duration_s: float
    phase: Phase = Phase.OTHER

    @property
    def ok(self) -> bool:
        return self.exit_code == 0

    @property
    def combined_output(self) -> str:
        """stdout and stderr merged, in that order, empty streams dropped.

        This is what the error parser consumes. Compiler errors frequently land
        on stderr while progress lands on stdout; the parser needs both, and the
        relative order within each stream is what carries include-depth context.
        """
        parts = [p for p in (self.stdout, self.stderr) if p]
        return "\n".join(parts)

    def summary(self, max_chars: int = 240) -> str:
        """A short one-line description for logs and dashboards."""
        tail = self.combined_output.strip().splitlines()
        last = tail[-1] if tail else ""
        if len(last) > max_chars:
            last = last[: max_chars - 1] + "…"
        status = "ok" if self.ok else f"exit={self.exit_code}"
        return f"[{self.phase.value}] {status} ({self.duration_s:.2f}s) {last}".rstrip()


class Executor(ABC):
    """Abstract command runner + minimal filesystem access for the target repo.

    Implementations must be safe to use as a context manager. `close()` releases
    any transport (e.g. an SSH connection); the default is a no-op.
    """

    @abstractmethod
    def run(
        self,
        command: str,
        *,
        cwd: str | None = None,
        timeout: float | None = None,
        phase: Phase = Phase.OTHER,
    ) -> ExecResult:
        """Run a shell command and capture its result. Never raises on non-zero
        exit -- a failed build is data, not an exception. Raises only on transport
        failure (e.g. the SSH connection dropped)."""

    @abstractmethod
    def read_file(self, path: str) -> str:
        """Read a UTF-8 text file from the target working copy."""

    @abstractmethod
    def write_file(self, path: str, content: str) -> None:
        """Write a UTF-8 text file in the target working copy (creating parents)."""

    @abstractmethod
    def exists(self, path: str) -> bool:
        """Whether a path exists in the target working copy."""

    def close(self) -> None:  # pragma: no cover - trivial default
        """Release any underlying transport. Default: nothing to release."""

    def __enter__(self) -> "Executor":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # -- convenience helpers shared by all implementations -------------------

    @staticmethod
    def is_git_commit(command: str) -> bool:
        """True if `command` is a `git commit`, tolerating git's global flags
        between `git` and the subcommand — the agent commits with explicit
        `-c user.name=... -c user.email=...` identity so the audit trail works
        on boxes with no git identity configured (e.g. the hackathon GPU pod)."""
        try:
            tokens = shlex.split(command, posix=True)
        except ValueError:
            tokens = command.split()
        if not tokens or tokens[0] != "git":
            return False
        i = 1
        while i < len(tokens):
            tok = tokens[i]
            if tok in ("-c", "-C"):
                i += 2  # global option with a separate value argument
                continue
            if tok.startswith("-"):
                i += 1  # other global flag (e.g. --no-pager)
                continue
            return tok == "commit"  # first non-flag token is the subcommand
        return False

    @staticmethod
    def looks_like(command: str, needle: str) -> bool:
        """True if the first meaningful token(s) of `command` start with `needle`.

        Used to classify commands (e.g. detect `git commit`). Robust to leading
        environment assignments and quoting.
        """
        try:
            tokens = shlex.split(command, posix=True)
        except ValueError:
            tokens = command.split()
        # drop leading VAR=value environment prefixes
        while tokens and "=" in tokens[0] and not tokens[0].startswith("-"):
            head = tokens[0].split("=", 1)[0]
            if head and head.replace("_", "").isalnum() and head.upper() == head:
                tokens.pop(0)
            else:
                break
        joined = " ".join(tokens)
        return joined.startswith(needle)
