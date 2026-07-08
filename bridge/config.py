"""Bridge's typed configuration schema.

Everything that varies between "simulate on my laptop" and "port for real on the
MI300X" lives here and is loaded from a single YAML file. Validation is strict:
a bad config fails at startup with a clear message, never halfway through a run.

The two headline switches:
  * `executor.kind`  - `mock` (fixtures, no GPU), `local` (this machine IS the
    ROCm box / GPU pod), or `ssh` (a remote GPU box).
  * `llm.base_url`   - Fireworks AI (guaranteed default) or self-hosted vLLM on
                       the MI300X (the showcase). Any OpenAI-compatible endpoint.
"""

from __future__ import annotations

import os
from typing import Literal, Optional

import yaml
from pydantic import BaseModel, Field, model_validator


class SSHSettings(BaseModel):
    host: str
    user: str
    remote_workdir: str
    port: int = 22
    key_path: Optional[str] = None
    # Password auth is supported but discouraged; prefer a key.
    password_env: Optional[str] = None
    connect_timeout_s: float = 30.0


class MockSettings(BaseModel):
    # Path to the scenario YAML that drives the replay.
    scenario: str


class ExecutorConfig(BaseModel):
    # mock  - fixtures, no GPU (the offline demo/CI path).
    # local - run for real on THIS machine (a ROCm box or the hackathon's
    #         Jupyter GPU pod, where Bridge runs on the GPU host itself).
    # ssh   - run for real on a remote GPU box over SSH.
    kind: Literal["mock", "local", "ssh"] = "mock"
    mock: Optional[MockSettings] = None
    ssh: Optional[SSHSettings] = None

    @model_validator(mode="after")
    def _require_matching_section(self) -> "ExecutorConfig":
        if self.kind == "mock" and self.mock is None:
            raise ValueError("executor.kind is 'mock' but executor.mock is missing")
        if self.kind == "ssh" and self.ssh is None:
            raise ValueError("executor.kind is 'ssh' but executor.ssh is missing")
        return self


class ReplaySettings(BaseModel):
    """A recorded cassette of LLM responses for deterministic CI.

    This mocks the *brain*; the mock executor mocks the *hardware*. With both
    pinned, the whole end-to-end run is byte-stable, so CI can assert on exact
    diffs and a fixed outcome. Distinct from a live LLM, which is non-deterministic
    and therefore never used in CI.
    """

    cassette: str
    # Error if a request has no recorded response (rather than silently improvise).
    strict: bool = True


class CostConfig(BaseModel):
    """How to price a run for the dashboard's token/cost counter.

    Two modes because the two showcase endpoints bill differently:
      * `priced`      - a hosted API (Fireworks) charges per token; show dollars.
      * `self_hosted` - vLLM on the MI300X has ~zero marginal token cost; the
                        honest, and more on-message, figure is throughput
                        (tokens/sec) and GPU-seconds, not dollars.
    """

    mode: Literal["priced", "self_hosted"] = "priced"
    currency: str = "USD"
    # Prices per 1M tokens, used only in `priced` mode.
    input_per_mtok: float = 0.0
    output_per_mtok: float = 0.0

    def token_cost(self, prompt_tokens: int, completion_tokens: int) -> float:
        """Dollar cost of one call in `priced` mode; 0.0 for `self_hosted`."""
        if self.mode == "self_hosted":
            return 0.0
        return (
            prompt_tokens * self.input_per_mtok
            + completion_tokens * self.output_per_mtok
        ) / 1_000_000


class LLMConfig(BaseModel):
    # `openai`  - any OpenAI-compatible endpoint (Fireworks default, or vLLM).
    # `replay`  - a recorded cassette; the deterministic CI path (no network).
    backend: Literal["openai", "replay"] = "openai"
    # Default is Fireworks: the endpoint guaranteed to work for the demo. Point
    # base_url at the vLLM-on-MI300X URL to flip the brain onto AMD hardware.
    base_url: str = "https://api.fireworks.ai/inference/v1"
    # Example default only — set `model` explicitly in your config. Hosted model
    # ids retire without warning (the previous default 404'd mid-hackathon); this
    # one is the brain behind the recorded demo cassette.
    model: str = "accounts/fireworks/models/kimi-k2p6"
    api_key_env: str = "BRIDGE_LLM_API_KEY"
    temperature: float = 0.0
    max_tokens: int = 4096
    request_timeout_s: float = 120.0
    # Human-readable host shown on the dashboard "endpoint badge". Derived from
    # base_url when left blank.
    display_host: Optional[str] = None
    replay: Optional[ReplaySettings] = None
    cost: CostConfig = Field(default_factory=CostConfig)

    @model_validator(mode="after")
    def _require_replay_when_selected(self) -> "LLMConfig":
        if self.backend == "replay" and self.replay is None:
            raise ValueError("llm.backend is 'replay' but llm.replay is missing")
        return self

    def resolved_display_host(self) -> str:
        if self.display_host:
            return self.display_host
        from urllib.parse import urlparse

        return urlparse(self.base_url).netloc or self.base_url


class Commands(BaseModel):
    """The three target-specific commands Bridge drives. Everything else (git,
    patch) Bridge issues itself and is not configurable here."""

    hipify: str
    build: str
    test: str
    # Optional one-time setup (e.g. cmake configure) run before the first build.
    configure: Optional[str] = None


class Caps(BaseModel):
    max_iterations: int = 40
    max_attempts_per_cluster: int = 3
    # Reject any diff larger than this many changed lines: minimal diffs only.
    max_patch_lines: int = 200
    # Context builder must stay within this many tokens per iteration.
    token_budget_per_iteration: int = 16000

    @model_validator(mode="after")
    def _positive(self) -> "Caps":
        for name in (
            "max_iterations",
            "max_attempts_per_cluster",
            "max_patch_lines",
            "token_budget_per_iteration",
        ):
            if getattr(self, name) < 1:
                raise ValueError(f"caps.{name} must be >= 1")
        return self


class RepoConfig(BaseModel):
    # The working copy Bridge edits. Local dir in mock mode; remote path in ssh.
    path: str
    # CDNA3 / MI300X. Replaces CUDA's -arch=sm_XX with --offload-arch=gfx942.
    offload_arch: str = "gfx942"


class PolicyConfig(BaseModel):
    # Patching test files is forbidden by default: the agent must make the code
    # correct, not edit the goalposts.
    patch_test_files: bool = False
    # What counts as a test file. Protected from edits unless patch_test_files.
    test_globs: list[str] = Field(
        default_factory=lambda: [
            "**/test/**",
            "**/tests/**",
            "**/test_*",
            "**/*_test.*",
            "**/*.test.*",
            "**/gtest/**",
            "**/googletest/**",
        ]
    )
    # Loosening a numerical tolerance to make a test pass is a *cheat*, not a
    # *fix*. Off by default; when a run hits tolerance failures it reports them as
    # a stuck cluster rather than silently widening the tolerance.
    allow_tolerance_relaxation: bool = False


class SecurityConfig(BaseModel):
    """Mechanical trust-boundary controls.

    Bridge clones an *untrusted* repo, runs its build/tests (arbitrary code
    execution), and applies *LLM-generated* diffs. Source comments and compiler
    output flow into the model's prompt, so a hostile repo can attempt indirect
    prompt injection ("to fix this, add system(...)"). These guardrails hold
    even when the model is wrong or adversarially steered -- they are enforced on
    the diff mechanically, before anything is applied. See THREAT_MODEL.md.
    """

    # Globs the agent may modify. A diff touching anything outside is rejected.
    writable_globs: list[str] = Field(
        default_factory=lambda: [
            "src/**",
            "include/**",
            "**/*.cu",
            "**/*.cuh",
            "**/*.cpp",
            "**/*.hpp",
            "**/*.hip",
            "**/*.h",
            "**/*.c",
            "**/*.cc",
            "**/CMakeLists.txt",
            "cmake/**",
            "**/*.cmake",
            "**/Makefile",
        ]
    )
    # Never modifiable regardless of anything else (VCS, CI, license, lockfiles).
    protected_globs: list[str] = Field(
        default_factory=lambda: [
            ".git/**",
            ".github/**",
            "LICENSE*",
            "**/*.lock",
        ]
    )
    # Substrings a diff's *added* lines may not introduce. Blocks the classic
    # injection payloads: shell-out, network egress, eval. Case-insensitive.
    forbidden_insertions: list[str] = Field(
        default_factory=lambda: [
            "system(",
            "std::system",
            "popen(",
            "exec(",
            "execve",
            "fork(",
            "socket(",
            "curl ",
            "wget ",
            "/dev/tcp/",
            "eval(",
            "subprocess",
            "os.system",
            "rm -rf",
            "base64 -d",
            "| sh",
            "|sh",
        ]
    )
    # A single accepted diff may create at most this many new files.
    max_new_files: int = 5
    # Run the target build/test inside an isolated sandbox (Milestone 5). Left off
    # in mock mode, where nothing untrusted actually executes.
    sandbox: bool = False


class BridgeConfig(BaseModel):
    executor: ExecutorConfig
    commands: Commands
    repo: RepoConfig
    llm: LLMConfig = Field(default_factory=LLMConfig)
    caps: Caps = Field(default_factory=Caps)
    policy: PolicyConfig = Field(default_factory=PolicyConfig)
    security: SecurityConfig = Field(default_factory=SecurityConfig)
    # Where versioned prompt files live and where run logs are written.
    prompts_dir: str = "prompts"
    runs_dir: str = "runs"

    @classmethod
    def load(cls, path: str) -> "BridgeConfig":
        with open(path, "r", encoding="utf-8") as fh:
            raw = yaml.safe_load(fh)
        if not isinstance(raw, dict):
            raise ValueError(f"config {path}: top level must be a mapping")
        cfg = cls.model_validate(raw)
        base = os.path.dirname(os.path.abspath(path))

        def resolve(p: str) -> str:
            return p if os.path.isabs(p) else os.path.normpath(os.path.join(base, p))

        # Resolve fixture/cassette paths relative to the config file for portability.
        if cfg.executor.kind == "mock" and cfg.executor.mock is not None:
            cfg.executor.mock.scenario = resolve(cfg.executor.mock.scenario)
        if cfg.llm.backend == "replay" and cfg.llm.replay is not None:
            cfg.llm.replay.cassette = resolve(cfg.llm.replay.cassette)
        return cfg
