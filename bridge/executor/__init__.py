"""Executor package: the seam between Bridge's logic and the target hardware.

Public surface:
    Executor, ExecResult, Phase   - the interface and its value types.
    LocalExecutor                 - really runs commands locally.
    MockExecutor                  - LocalExecutor + fixture-replayed build/test.
    SSHExecutor                   - runs everything on the MI300X over SSH.
    Scenario                      - the scripted replay a MockExecutor walks.
    create_executor(config)       - build the right executor from BridgeConfig.
"""

from __future__ import annotations

import os

from .base import ExecResult, Executor, Phase
from .local import LocalExecutor
from .mock import MockExecutor
from .scenario import Scenario
from .ssh import SSHExecutor

__all__ = [
    "Executor",
    "ExecResult",
    "Phase",
    "LocalExecutor",
    "MockExecutor",
    "SSHExecutor",
    "Scenario",
    "create_executor",
]


def create_executor(config) -> Executor:
    """Instantiate the executor selected by `config.executor.kind`.

    `config` is a `bridge.config.BridgeConfig`. Imported lazily by callers to
    avoid a hard import cycle; this function only reads attributes.
    """
    ex = config.executor
    if ex.kind == "mock":
        scenario = Scenario.load(ex.mock.scenario)
        return MockExecutor(
            workdir=config.repo.path,
            scenario=scenario,
            build_cmd=config.commands.build,
            test_cmd=config.commands.test,
            hipify_cmd=config.commands.hipify,
        )
    if ex.kind == "ssh":
        password = None
        if ex.ssh.password_env:
            password = os.environ.get(ex.ssh.password_env)
        return SSHExecutor(
            host=ex.ssh.host,
            user=ex.ssh.user,
            remote_workdir=ex.ssh.remote_workdir,
            port=ex.ssh.port,
            key_path=ex.ssh.key_path,
            password=password,
            connect_timeout=ex.ssh.connect_timeout_s,
        )
    raise ValueError(f"unknown executor.kind: {ex.kind!r}")
