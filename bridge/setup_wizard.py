"""`bridge init` — guided setup for a live run.

The live-run journey used to be: copy config.example.yaml, hand-edit eight
fields (including knowing your gfx arch), then validate. The wizard collapses
that: it detects the GPU arch (rocm_agent_enumerator, then rocminfo), the build
system (CMakeLists.txt vs Makefile), and where the .cu files live, asks only
for what it cannot detect, and writes a config.yaml that is loaded back through
the schema before the command returns — so an invalid config is unrepresentable.

Interactive when stdin is a TTY; `--yes` (or a non-TTY stdin) takes the
detected defaults so it also works in scripts.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time

# gfx ids a user is likely to have, shown as the pick list when detection finds
# nothing (no ROCm on this machine, or configuring for a remote box).
KNOWN_ARCHES = [
    ("gfx942", "MI300X / MI300A (CDNA3)"),
    ("gfx90a", "MI250 / MI210 (CDNA2)"),
    ("gfx908", "MI100 (CDNA1)"),
    ("gfx1100", "RX 7900 / Radeon PRO W7900 (RDNA3)"),
    ("gfx1030", "RX 6800 / 6900 (RDNA2)"),
]


def pick_arch_from_output(text: str) -> str | None:
    """First real gfx id in tool output. rocm_agent_enumerator lists one id per
    line including the gfx000 CPU agent; rocminfo buries ids in `Name: gfxNNNN`
    lines. Token-splitting handles both."""
    for tok in text.split():
        if tok.startswith("gfx") and tok != "gfx000":
            return tok
    return None


def detect_offload_arch() -> str | None:
    for cmd in (["rocm_agent_enumerator"], ["rocminfo"]):
        try:
            out = subprocess.run(
                cmd, capture_output=True, text=True, timeout=10
            ).stdout
        except (OSError, subprocess.SubprocessError):
            continue
        arch = pick_arch_from_output(out or "")
        if arch:
            return arch
    return None


def find_cuda_roots(repo_path: str) -> list[str]:
    """Top-level dirs (repo-relative) containing .cu/.cuh files — the sweep
    targets for the hipify command. '.' means files at the repo root."""
    roots: set[str] = set()
    for dirpath, dirnames, filenames in os.walk(repo_path):
        dirnames[:] = [d for d in dirnames if not d.startswith(".") and d != "build"]
        if any(f.endswith((".cu", ".cuh")) for f in filenames):
            rel = os.path.relpath(dirpath, repo_path)
            roots.add("." if rel == "." else rel.replace(os.sep, "/").split("/")[0])
    if "." in roots:
        return ["."]
    return sorted(roots)


def detect_commands(repo_path: str) -> dict[str, str | None]:
    """Prefill the four driven commands from the repo's build system."""
    cuda_roots = find_cuda_roots(repo_path)
    sweep = " ".join(cuda_roots) if cuda_roots else "."
    hipify = f"hipify-perl -inplace -print-stats $(find {sweep} -name '*.cu' -o -name '*.cuh')"
    if os.path.exists(os.path.join(repo_path, "CMakeLists.txt")):
        return {
            "build_system": "cmake",
            "configure": "cmake -S . -B build -DCMAKE_CXX_COMPILER=hipcc",
            "build": "cmake --build build -j",
            # --no-tests=error: a suite that silently shrank to zero tests must
            # never read as a pass (the de-registration cheat).
            "test": "ctest --test-dir build --output-on-failure --no-tests=error",
            "hipify": hipify,
        }
    if os.path.exists(os.path.join(repo_path, "Makefile")):
        return {
            "build_system": "make",
            "configure": None,
            "build": "make -j CXX=hipcc",
            "test": "make test",
            "hipify": hipify,
        }
    return {
        "build_system": None,
        "configure": None,
        "build": "cmake --build build -j",
        "test": "ctest --test-dir build --output-on-failure --no-tests=error",
        "hipify": hipify,
    }


def default_prompts_dir() -> str:
    """The versioned prompts live in the Bridge checkout, not the installed
    package — resolve them absolutely so `bridge init` works from inside the
    user's CUDA repo, not just from the Bridge clone."""
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    candidate = os.path.join(here, "prompts")
    return candidate if os.path.isdir(candidate) else "prompts"


def _y(value: str) -> str:
    """YAML-safe scalar. json.dumps output is valid YAML (flow scalar) and
    handles Windows backslashes, quotes, and $() in command strings."""
    return json.dumps(value)


def _ask(label: str, default: str) -> str:
    reply = input(f"  {label} [{default}]: ").strip()
    return reply or default


def _build_config_text(v: dict) -> str:
    lines = [
        f"# Bridge configuration -- written by `bridge init` on {time.strftime('%Y-%m-%d')}.",
        "# Edit freely (`bridge validate` re-checks it); every field is documented",
        "# in config.example.yaml. Re-run `bridge init --force` to regenerate.",
        "",
        "executor:",
        f"  kind: {v['executor_kind']}",
    ]
    if v["executor_kind"] == "ssh":
        lines += [
            "  ssh:",
            f"    host: {_y(v['ssh_host'])}",
            f"    user: {_y(v['ssh_user'])}",
            f"    remote_workdir: {_y(v['ssh_workdir'])}",
            f"    port: {v['ssh_port']}",
            f"    key_path: {_y(v['ssh_key_path'])}",
        ]
    lines += [
        "",
        "repo:",
        f"  path: {_y(v['repo_path'])}",
        f"  offload_arch: {v['arch']}   # {v['arch_label']}",
        "",
        "commands:",
    ]
    if v["configure"]:
        lines.append(f"  configure: {_y(v['configure'])}")
    lines += [
        f"  hipify: {_y(v['hipify'])}",
        f"  build: {_y(v['build'])}",
        f"  test: {_y(v['test'])}",
        "",
        "llm:",
        "  backend: openai              # any OpenAI-compatible endpoint",
        f"  base_url: {_y(v['base_url'])}",
        f"  model: {_y(v['model'])}",
        f"  api_key_env: {v['api_key_env']}",
        "  max_tokens: 16384            # thinking models need room before the diff",
        "  request_timeout_s: 300",
        "",
        f"prompts_dir: {_y(v['prompts_dir'])}",
        "runs_dir: runs",
        "",
    ]
    return "\n".join(lines)


def _arch_label(arch: str) -> str:
    for gfx, label in KNOWN_ARCHES:
        if gfx == arch:
            return label
    return "set to your GPU's gfx id"


def cmd_init(args: argparse.Namespace) -> int:
    out_path = args.out
    if os.path.exists(out_path) and not args.force:
        print(
            f"bridge: {out_path} already exists -- pass --force to overwrite it.",
            file=sys.stderr,
        )
        return 2

    interactive = sys.stdin.isatty() and not args.yes
    try:
        return _run_init(args, out_path, interactive)
    except (KeyboardInterrupt, EOFError):
        print("\nbridge init: aborted -- nothing written.", file=sys.stderr)
        return 130


def _run_init(args: argparse.Namespace, out_path: str, interactive: bool) -> int:
    from .config import BridgeConfig

    print("bridge init -- set up a live CUDA -> ROCm migration")
    if interactive:
        print("(enter accepts the [detected default]; Ctrl+C aborts)\n")

    # 1. The repo to port.
    repo_path = args.repo or os.getcwd()
    if interactive:
        repo_path = _ask("CUDA repo to port", repo_path)
    repo_path = os.path.abspath(os.path.expanduser(repo_path))
    if not os.path.isdir(repo_path):
        print(f"bridge init: repo path does not exist: {repo_path}", file=sys.stderr)
        return 2

    # 2. Where builds run.
    executor_kind = args.executor or "local"
    if interactive and args.executor is None:
        executor_kind = _ask("Run builds where? (local = this ROCm box, ssh = remote AMD box)", executor_kind)
        if executor_kind not in ("local", "ssh"):
            print(f"bridge init: executor must be local or ssh, got {executor_kind!r}", file=sys.stderr)
            return 2
    v: dict = {"executor_kind": executor_kind}
    if executor_kind == "ssh":
        if not interactive:
            print("bridge init: ssh setup needs the interactive wizard (host, user, paths).", file=sys.stderr)
            return 2
        v["ssh_host"] = _ask("SSH host", "")
        v["ssh_user"] = _ask("SSH user", "bridge")
        v["ssh_workdir"] = _ask("Remote workdir (the repo path on that box)", "/workspace/target-repo")
        v["ssh_port"] = int(_ask("SSH port", "22"))
        v["ssh_key_path"] = _ask("SSH key path", "~/.ssh/id_ed25519")
        repo_path = v["ssh_workdir"]

    # 3. GPU arch — detect, else offer the pick list.
    arch = args.arch
    detected = None
    if not arch:
        detected = detect_offload_arch() if executor_kind == "local" else None
        arch = detected or "gfx942"
    if interactive and not args.arch:
        if detected:
            print(f"  detected GPU arch: {detected}")
        else:
            print("  no local GPU detected -- common targets:")
            for gfx, label in KNOWN_ARCHES:
                print(f"    {gfx:<8} {label}")
        arch = _ask("Target --offload-arch", arch)
    v["arch"], v["arch_label"] = arch, _arch_label(arch)
    if detected and arch == detected:
        v["arch_label"] += " — detected on this machine"

    # 4. The four driven commands, prefilled from the build system.
    det = detect_commands(repo_path if executor_kind == "local" else (args.repo or os.getcwd()))
    if det["build_system"] is None:
        print("  note: no CMakeLists.txt or Makefile found at the repo root -- "
              "check the build/test commands in the written config.")
    if not find_cuda_roots(repo_path) and executor_kind == "local":
        print("  note: no .cu/.cuh files found -- is this the right repo path?")
    if interactive:
        if det["configure"] is not None:
            det["configure"] = _ask("configure command", det["configure"])
        det["hipify"] = _ask("hipify command", det["hipify"])
        det["build"] = _ask("build command", det["build"])
        det["test"] = _ask("test command", det["test"])
    v.update(repo_path=repo_path, configure=det["configure"], hipify=det["hipify"],
             build=det["build"], test=det["test"])

    # 5. The brain.
    v["base_url"] = args.base_url
    v["model"] = args.model
    if interactive:
        v["base_url"] = _ask("LLM endpoint (OpenAI-compatible)", v["base_url"])
        v["model"] = _ask("Model", v["model"])
    v["api_key_env"] = "BRIDGE_LLM_API_KEY"
    v["prompts_dir"] = default_prompts_dir()

    with open(out_path, "w", encoding="utf-8") as fh:
        fh.write(_build_config_text(v))
    # Round-trip through the schema: the wizard must never leave behind a config
    # that `bridge run` will reject.
    BridgeConfig.load(out_path)

    key_set = bool(os.environ.get(v["api_key_env"]))
    print(f"\nWrote and validated {out_path}")
    print("\nNext steps:")
    step = 1
    if not key_set:
        print(f"  {step}. Set your LLM key (Fireworks, or any OpenAI-compatible endpoint):")
        print(f"       export {v['api_key_env']}=fw_your_key          # bash")
        print(f"       $env:{v['api_key_env']} = \"fw_your_key\"       # PowerShell")
        step += 1
    else:
        print(f"  (${v['api_key_env']} is already set)")
    print(f"  {step}. Port the repo and watch it live in your browser:")
    print(f"       bridge run --config {out_path} --dashboard")
    return 0


def add_init_parser(sub) -> None:
    pi = sub.add_parser("init", help="guided setup: detect GPU + build system, write config.yaml")
    pi.add_argument("--repo", default=None, help="path to the CUDA repo to port (default: current dir)")
    pi.add_argument("--arch", default=None, help="target --offload-arch (default: auto-detect, else gfx942)")
    pi.add_argument("--executor", default=None, choices=["local", "ssh"],
                    help="where builds run (default: local)")
    pi.add_argument("--base-url", default="https://api.fireworks.ai/inference/v1",
                    help="OpenAI-compatible LLM endpoint")
    pi.add_argument("--model", default="accounts/fireworks/models/kimi-k2p6")
    pi.add_argument("--out", default="config.yaml", help="where to write the config")
    pi.add_argument("--yes", action="store_true", help="no prompts: accept detected defaults")
    pi.add_argument("--force", action="store_true", help="overwrite an existing config")
    pi.set_defaults(func=cmd_init)
