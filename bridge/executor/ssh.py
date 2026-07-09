"""SSHExecutor: runs the whole loop on a remote AMD GPU box over SSH/SFTP.

This is the remote-hardware implementation of `Executor` (the recorded gfx1100
hardware run used `local` — Bridge on the GPU host itself). It is
interface-complete and unit-tested, but has NOT been exercised against a live
remote box; treat it as beta.

`paramiko` is imported lazily so the rest of Bridge -- the mock path, the parser,
the tests -- imports and runs with zero SSH dependencies installed.
"""

from __future__ import annotations

import posixpath
import shlex
import time

from .base import ExecResult, Executor, Phase


class SSHExecutor(Executor):
    def __init__(
        self,
        host: str,
        user: str,
        remote_workdir: str,
        *,
        port: int = 22,
        key_path: str | None = None,
        password: str | None = None,
        connect_timeout: float = 30.0,
        accept_unknown_host_key: bool = False,
    ):
        self.host = host
        self.user = user
        self.port = port
        self.remote_workdir = remote_workdir
        self._key_path = key_path
        self._password = password
        self._connect_timeout = connect_timeout
        self._accept_unknown_host_key = accept_unknown_host_key
        self._client = None
        self._sftp = None

    # -- connection management ----------------------------------------------

    def _connect(self):
        if self._client is not None:
            return self._client
        try:
            import paramiko
        except ImportError as exc:  # pragma: no cover - environment dependent
            raise RuntimeError(
                "SSHExecutor requires paramiko. Install with: pip install "
                "'bridge-migrate[ssh]'"
            ) from exc

        client = paramiko.SSHClient()
        client.load_system_host_keys()
        # Unknown host keys are rejected by default: a MITM on this hop could
        # tamper with the audit-trail commits and read repo content. Opt in to
        # auto-accept only for throwaway boxes (ssh.accept_unknown_host_key).
        if self._accept_unknown_host_key:
            client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        else:
            client.set_missing_host_key_policy(paramiko.RejectPolicy())
        client.connect(
            hostname=self.host,
            port=self.port,
            username=self.user,
            key_filename=self._key_path,
            password=self._password,
            timeout=self._connect_timeout,
        )
        self._client = client
        return client

    def _get_sftp(self):
        if self._sftp is None:
            self._sftp = self._connect().open_sftp()
        return self._sftp

    def close(self) -> None:
        if self._sftp is not None:
            try:
                self._sftp.close()
            finally:
                self._sftp = None
        if self._client is not None:
            try:
                self._client.close()
            finally:
                self._client = None

    # -- executor contract ---------------------------------------------------

    def _remote_path(self, path: str) -> str:
        if posixpath.isabs(path):
            return path
        return posixpath.join(self.remote_workdir, path)

    def run(
        self,
        command: str,
        *,
        cwd: str | None = None,
        timeout: float | None = None,
        phase: Phase = Phase.OTHER,
    ) -> ExecResult:
        client = self._connect()
        run_cwd = self._remote_path(cwd) if cwd else self.remote_workdir
        # Wrap so relative paths and multi-line commands behave predictably.
        # shlex.quote, not repr: the remote shell is POSIX, not Python.
        wrapped = f"cd {shlex.quote(run_cwd)} && {command}"
        start = time.monotonic()
        _stdin, stdout, stderr = client.exec_command(wrapped, timeout=timeout)
        out = stdout.read().decode("utf-8", "replace")
        err = stderr.read().decode("utf-8", "replace")
        exit_code = stdout.channel.recv_exit_status()
        duration = time.monotonic() - start
        return ExecResult(
            command=command,
            exit_code=exit_code,
            stdout=out,
            stderr=err,
            duration_s=duration,
            phase=phase,
        )

    def read_file(self, path: str) -> str:
        sftp = self._get_sftp()
        with sftp.open(self._remote_path(path), "r") as fh:
            return fh.read().decode("utf-8", "replace")

    def write_file(self, path: str, content: str) -> None:
        sftp = self._get_sftp()
        remote = self._remote_path(path)
        self._makedirs(posixpath.dirname(remote))
        with sftp.open(remote, "w") as fh:
            fh.write(content)

    def exists(self, path: str) -> bool:
        sftp = self._get_sftp()
        try:
            sftp.stat(self._remote_path(path))
            return True
        except IOError:
            return False

    def _makedirs(self, remote_dir: str) -> None:
        if not remote_dir:
            return
        sftp = self._get_sftp()
        parts = remote_dir.strip("/").split("/")
        cur = "/" if remote_dir.startswith("/") else ""
        for part in parts:
            cur = posixpath.join(cur, part) if cur else part
            try:
                sftp.stat(cur)
            except IOError:
                sftp.mkdir(cur)
