"""Scenarios: scripted, deterministic replays of a real porting session.

A scenario is what makes the zero-GPU path faithful. It is an ordered list of
*stages*, each holding the build (and, once building, test) output the agent would
see at that point in the port. The mock executor walks the stages as the agent
lands commits, replaying real fixture logs captured from HIPIFY and the ROCm
toolchain.

Advancement model (deliberately simple and coupling-free):
  * A stage advances to the next once the agent lands `min_commits` accepted git
    commits while in it. This models "the fix worked, the next error surfaces."
  * A `sticky` stage never advances. Use it for the terminal green state, or for
    an error the agent can never fix -- the orchestrator's attempt cap will mark
    that cluster STUCK and the run degrades gracefully to PARTIAL.

Determinism: fixture text is fixed, and advancement depends only on commit count,
so a given (scenario, agent-decision-sequence) always produces the same replay.
For CI both sides are pinned, giving a byte-stable end-to-end run.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

import yaml


@dataclass
class ResultSpec:
    """One canned command result: a fixture log plus its exit code.

    For test stages, `passed`/`total` feed the dashboard's pass-rate chart so the
    money-shot graph is driven by the same data the orchestrator sees.
    """

    log_path: str
    exit_code: int
    text: str
    passed: int | None = None
    total: int | None = None

    @property
    def ok(self) -> bool:
        return self.exit_code == 0


@dataclass
class Stage:
    name: str
    build: ResultSpec
    test: ResultSpec | None = None
    min_commits: int = 1
    sticky: bool = False


@dataclass
class Scenario:
    name: str
    description: str
    hipify: ResultSpec
    stages: list[Stage] = field(default_factory=list)
    source_path: str | None = None
    # Optional directory of source files to seed the scratch repo with, so the
    # agent's diffs apply to real code. Resolved relative to the scenario file.
    repo_seed: str | None = None

    @classmethod
    def load(cls, path: str) -> "Scenario":
        """Load and validate a scenario YAML.

        Log paths inside the YAML are resolved relative to the scenario file's
        directory, so a scenario is a self-contained bundle. Missing fixtures or
        malformed exit codes fail loudly here rather than mid-run.
        """
        path = os.path.abspath(path)
        base_dir = os.path.dirname(path)
        with open(path, "r", encoding="utf-8") as fh:
            raw = yaml.safe_load(fh)

        if not isinstance(raw, dict):
            raise ValueError(f"scenario {path}: top level must be a mapping")

        def load_result(spec: dict, ctx: str) -> ResultSpec:
            if not isinstance(spec, dict) or "log" not in spec:
                raise ValueError(f"scenario {path}: {ctx} needs a 'log' field")
            log_rel = spec["log"]
            log_abs = log_rel if os.path.isabs(log_rel) else os.path.join(base_dir, log_rel)
            if not os.path.exists(log_abs):
                raise FileNotFoundError(
                    f"scenario {path}: {ctx} log not found: {log_abs}"
                )
            with open(log_abs, "r", encoding="utf-8") as lf:
                text = lf.read()
            exit_code = spec.get("exit_code", 0)
            if not isinstance(exit_code, int):
                raise ValueError(f"scenario {path}: {ctx} exit_code must be int")
            passed = spec.get("passed")
            total = spec.get("total")
            return ResultSpec(
                log_path=log_abs,
                exit_code=exit_code,
                text=text,
                passed=passed,
                total=total,
            )

        if "hipify" not in raw:
            raise ValueError(f"scenario {path}: missing 'hipify' section")
        hipify = load_result(raw["hipify"], "hipify")

        stages_raw = raw.get("stages") or []
        if not stages_raw:
            raise ValueError(f"scenario {path}: needs at least one stage")

        stages: list[Stage] = []
        for i, sraw in enumerate(stages_raw):
            ctx = f"stage[{i}] '{sraw.get('name', i)}'"
            if "build" not in sraw:
                raise ValueError(f"scenario {path}: {ctx} needs a 'build' result")
            build = load_result(sraw["build"], f"{ctx}.build")
            test = (
                load_result(sraw["test"], f"{ctx}.test")
                if sraw.get("test")
                else None
            )
            min_commits = int(sraw.get("min_commits", 1))
            if min_commits < 1:
                raise ValueError(f"scenario {path}: {ctx} min_commits must be >= 1")
            stages.append(
                Stage(
                    name=str(sraw.get("name", f"stage_{i}")),
                    build=build,
                    test=test,
                    min_commits=min_commits,
                    sticky=bool(sraw.get("sticky", False)),
                )
            )

        repo_seed = raw.get("repo_seed")
        if repo_seed and not os.path.isabs(repo_seed):
            repo_seed = os.path.normpath(os.path.join(base_dir, repo_seed))

        return cls(
            name=str(raw.get("name", os.path.basename(path))),
            description=str(raw.get("description", "")),
            hipify=hipify,
            stages=stages,
            source_path=path,
            repo_seed=repo_seed,
        )
