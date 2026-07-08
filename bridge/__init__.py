"""Bridge: an autonomous CUDA to ROCm/HIP migration agent.

Bridge takes a git repository containing CUDA code and ports it to ROCm/HIP so it
builds and passes its test suite on an AMD Instinct MI300X. The mechanical 90% is
done by AMD's HIPIFY; the agent earns its keep on the last mile (build systems,
warp-size assumptions, library mapping quirks, link/header issues).

The package is organised as small, independently readable modules:

    bridge.config      - typed configuration schema (loaded from YAML).
    bridge.executor    - the one abstraction that separates *logic* from *hardware*.
                         `Executor` has a mock implementation (replays real fixture
                         logs, no GPU needed) and an SSH implementation (targets the
                         MI300X). One config switch chooses between them.

Later milestones add: error parser, orchestrator state machine, patcher, context
builder, LLM client, and the dashboard. Nothing in the system assumes full success:
every run ends in a complete, presentable report.
"""

__version__ = "0.1.0"
