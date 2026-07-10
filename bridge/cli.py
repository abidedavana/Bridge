"""Bridge command-line entry point.

The three smooth-journey commands most users need:

    bridge demo       - one command, one terminal: serve the dashboard, open the
                        browser, and replay a real recorded migration (no GPU, no
                        API key).
    bridge port       - one command for a LIVE run: point at a CUDA repo (URL or
                        path); it clones, auto-configures, and runs with the
                        dashboard open.
    bridge init       - guided setup for a live run: detect the GPU arch and the
                        repo's build system, ask only for what can't be detected,
                        write a validated config.yaml.

Plus the underlying pieces, individually scriptable:

    bridge validate   - load and validate a config; print a resolved summary.
    bridge run        - the real agent loop (diagnose -> diff -> policy gate ->
                        commit); --dashboard watches it live in the browser.
    bridge dashboard  - serve the dashboard alone (e.g. on another host/port).
    bridge mock-demo  - drive a scenario through the mock executor (plumbing
                        check, not the agent).
    bridge shortlist  - triage candidate CUDA repos for the best demo pick.
"""

from __future__ import annotations

import argparse
import os
import sys

from .config import BridgeConfig
from .executor import Phase, create_executor
from .executor.mock import MockExecutor


def _load(config_path: str) -> BridgeConfig:
    if not os.path.exists(config_path):
        print(
            f"bridge: config not found: {config_path}\n"
            "        `bridge init` writes one for your repo; `bridge demo` needs none.",
            file=sys.stderr,
        )
        raise SystemExit(2)
    return BridgeConfig.load(config_path)


def _start_dashboard(state_path: str, host: str, port: int):
    """Serve the dashboard on a daemon thread so `demo` and `run --dashboard`
    need one terminal, not two. Returns (server, thread), or None when the
    extras are missing or the port never came up — callers continue headless."""
    import threading
    import time as _time

    try:
        import uvicorn

        from .dashboard.app import create_app
    except ImportError:
        print(
            "bridge: dashboard extras not installed -- continuing headless.\n"
            "        pip install 'bridge-migrate[dashboard]'  (or: pip install fastapi uvicorn)",
            file=sys.stderr,
        )
        return None
    server = uvicorn.Server(
        uvicorn.Config(create_app(state_path), host=host, port=port, log_level="warning")
    )
    thread = threading.Thread(target=server.run, name="bridge-dashboard", daemon=True)
    thread.start()
    for _ in range(100):  # up to ~5s for startup
        if server.started or not thread.is_alive():
            break
        _time.sleep(0.05)
    if not server.started:
        print(
            f"bridge: dashboard failed to start on {host}:{port} (port in use?) -- "
            "continuing headless.",
            file=sys.stderr,
        )
        return None
    return server, thread


def _open_dashboard(host: str, port: int) -> None:
    import webbrowser

    url = f"http://{host}:{port}"
    print(f"== dashboard live: {url} ==")
    webbrowser.open(url)


def _wait_for_interrupt(server, thread) -> None:
    """Keep the dashboard alive after the run so the final report stays
    explorable; Ctrl+C exits cleanly."""
    print("== dashboard still live -- press Ctrl+C to exit ==")
    try:
        while thread.is_alive():
            thread.join(0.5)
    except KeyboardInterrupt:
        pass
    server.should_exit = True
    thread.join(3)


def cmd_validate(args: argparse.Namespace) -> int:
    cfg = _load(args.config)
    print(f"config: {args.config}  (valid)")
    print(f"executor.kind: {cfg.executor.kind}")
    print(f"repo.path: {cfg.repo.path}   offload_arch: {cfg.repo.offload_arch}")
    brain_host = (
        cfg.llm.replay.cassette
        if cfg.llm.backend == "replay" and cfg.llm.replay
        else cfg.llm.resolved_display_host()
    )
    print(
        f"llm: [{cfg.llm.backend}] {cfg.llm.model} @ {brain_host} "
        f"(cost mode: {cfg.llm.cost.mode})"
    )
    print(
        f"caps: iters={cfg.caps.max_iterations} "
        f"attempts/cluster={cfg.caps.max_attempts_per_cluster} "
        f"max_patch_lines={cfg.caps.max_patch_lines} "
        f"token_budget={cfg.caps.token_budget_per_iteration}"
    )
    print(
        f"policy: patch_test_files={cfg.policy.patch_test_files} "
        f"allow_tolerance_relaxation={cfg.policy.allow_tolerance_relaxation}"
    )
    print(
        f"security: writable_globs={len(cfg.security.writable_globs)} "
        f"protected_globs={len(cfg.security.protected_globs)} "
        f"forbidden_insertions={len(cfg.security.forbidden_insertions)} "
        f"sandbox={cfg.security.sandbox}"
    )
    ex = create_executor(cfg)
    if isinstance(ex, MockExecutor):
        s = ex.scenario
        print(f"scenario: {s.name} ({len(s.stages)} stages) -- {s.description.strip()[:80]}")
        for i, st in enumerate(s.stages):
            kind = "build+test" if st.test else "build"
            flag = " [sticky]" if st.sticky else ""
            print(f"  stage {i}: {st.name} [{kind}]{flag}")
    ex.close()
    return 0


def _ensure_git_repo(workdir: str) -> None:
    """Make sure a git repo exists at workdir so mock-demo can make real commits."""
    import subprocess

    os.makedirs(workdir, exist_ok=True)
    if not os.path.isdir(os.path.join(workdir, ".git")):
        subprocess.run(["git", "init", "-q"], cwd=workdir, check=True)
        subprocess.run(["git", "config", "user.email", "bridge@example.com"], cwd=workdir, check=True)
        subprocess.run(["git", "config", "user.name", "Bridge"], cwd=workdir, check=True)
        subprocess.run(["git", "config", "core.autocrlf", "false"], cwd=workdir, check=True)
        readme = os.path.join(workdir, "BRIDGE_TARGET.md")
        with open(readme, "w", encoding="utf-8") as fh:
            fh.write("# mock target repo\nScratch working copy for Bridge's mock-demo.\n")
        subprocess.run(["git", "add", "-A"], cwd=workdir, check=True)
        subprocess.run(["git", "commit", "-q", "-m", "initial import (mock target)"], cwd=workdir, check=True)


def _sim_tokens(cfg: BridgeConfig, log_text: str) -> tuple[int, int, float]:
    """Plausible per-iteration token usage for the dashboard while no real LLM is
    in the loop (M3 replaces this with real usage). Prompt scales with the error
    context; cost via the configured cost model (0 in self_hosted mode)."""
    prompt = len(log_text) // 4 + 500
    completion = 160
    return prompt, completion, cfg.llm.cost.token_cost(prompt, completion)


def cmd_mock_demo(args: argparse.Namespace) -> int:
    import time as _time

    from .parser import parse as parse_log
    from .run_state import RunRecorder, RunState

    cfg = _load(args.config)
    if cfg.executor.kind != "mock":
        print("bridge: mock-demo requires executor.kind: mock", file=sys.stderr)
        return 2
    _ensure_git_repo(cfg.repo.path)
    ex = create_executor(cfg)
    assert isinstance(ex, MockExecutor)

    state_path = os.path.join(cfg.runs_dir, "current.json")
    state = RunState(
        run_id=_time.strftime("%Y%m%d-%H%M%S"),
        scenario=ex.scenario.name,
        executor=cfg.executor.kind,
        llm_backend=cfg.llm.backend,
        llm_model=cfg.llm.model,
        llm_host=(
            # An explicit display_host wins even in replay mode, so the badge can
            # name the real recorded brain; without one, show the cassette path.
            cfg.llm.display_host
            or (
                cfg.llm.replay.cassette
                if cfg.llm.backend == "replay" and cfg.llm.replay
                else cfg.llm.resolved_display_host()
            )
        ),
        cost_mode=cfg.llm.cost.mode,
        cost_currency=cfg.llm.cost.currency,
        simulated_cost=True,  # no real LLM in the loop yet (M3)
    )
    rec = RunRecorder(state_path, state)
    delay = max(0.0, args.delay)

    print(f"== mock-demo: scenario '{ex.scenario.name}' ==  (dashboard state -> {state_path})")
    hip = ex.run(cfg.commands.hipify, phase=Phase.HIPIFY)
    hstats = parse_log(hip.combined_output).hipify
    if hstats:
        rec.set_hipify(hstats.conversion_pct, hstats.warnings)
    print("  " + hip.summary())

    attempts_on_stage = 0
    outcome = "EXHAUSTED"
    for it in range(1, cfg.caps.max_iterations + 1):
        build = ex.run(cfg.commands.build, phase=Phase.BUILD)
        stage_before = ex.stage_index
        print(f"[iter {it}] {build.summary()}  (stage {ex.progress()['stage_name']})")

        if build.ok:
            test = ex.run(cfg.commands.test, phase=Phase.TEST)
            pr = parse_log(test.combined_output)
            pt, ct, cost = _sim_tokens(cfg, test.combined_output)
            rec.add(_iter_record(it, "test", test.ok, pr, pt, ct, cost, test.duration_s))
            rate = f"{pr.passed}/{pr.total}" if pr.total else "?"
            print(f"[iter {it}] {test.summary()}  pass-rate {rate}")
            if test.ok:
                outcome = "SUCCESS"
                break
        else:
            pr = parse_log(build.combined_output)
            pt, ct, cost = _sim_tokens(cfg, build.combined_output)
            rec.add(_iter_record(it, "build", False, pr, pt, ct, cost, build.duration_s))

        if delay:
            _time.sleep(delay)

        # Simulate an accepted fix: a real commit. Advances the scenario unless
        # the current stage is sticky (an error the agent can't clear).
        ex.run(
            f'git commit --allow-empty -q -m "bridge iter {it}: attempt fix"',
            phase=Phase.OTHER,
        )
        if ex.stage_index == stage_before:
            attempts_on_stage += 1
            if attempts_on_stage >= cfg.caps.max_attempts_per_cluster:
                outcome = "STUCK" if not build.ok else "PARTIAL"
                print(
                    f"[iter {it}] stage '{ex.progress()['stage_name']}' did not "
                    f"advance after {attempts_on_stage} attempts -> {outcome}"
                )
                break
        else:
            attempts_on_stage = 0

    rec.finish(outcome if outcome != "EXHAUSTED" else "PARTIAL")
    prog = ex.progress()
    print("== report ==")
    print(f"  outcome: {outcome}")
    print(f"  stage reached: {prog['stage_name']} ({prog['stage_index'] + 1}/{prog['stages_total']})")
    print(f"  commits made: {prog['commits_total']}")
    print(f"  build calls: {ex.build_calls}   test calls: {ex.test_calls}")
    print(f"  dashboard state: {state_path}")
    ex.close()
    return 0


def _iter_record(it, phase, ok, pr, pt, ct, cost, duration):
    from .run_state import IterationRecord

    p = pr.primary
    return IterationRecord(
        iteration=it,
        phase=phase,
        outcome="ok" if ok else "fail",
        error_class=p.error_class if p else None,
        location=p.location if p else None,
        message=p.message if p else None,
        error_classes=pr.error_classes,
        passed=pr.passed,
        total=pr.total,
        prompt_tokens=pt,
        completion_tokens=ct,
        cost=cost,
        duration_s=duration,
    )


def cmd_dashboard(args: argparse.Namespace) -> int:
    cfg = _load(args.config)
    state_path = os.path.abspath(os.path.join(cfg.runs_dir, "current.json"))
    try:
        import uvicorn

        from .dashboard.app import create_app
    except ImportError:
        print(
            "bridge: dashboard needs extras. Install: pip install 'bridge-migrate[dashboard]'",
            file=sys.stderr,
        )
        return 2
    app = create_app(state_path)
    print(f"bridge dashboard: http://{args.host}:{args.port}   (reading {state_path})")
    print("Run `python -m bridge mock-demo` in another terminal to see it fill live.")
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")
    return 0


def _reset_scratch(path: str) -> None:
    """Delete a mock scratch working copy so each run starts from a clean slate —
    the offline demo must be repeatable (a judge will run it more than once).
    Refuses to delete anything Bridge did not itself create (the provenance
    markers below), so a mock config accidentally pointed at a real directory
    can never wipe it. Handles Windows read-only .git objects."""
    import shutil
    import stat

    if not os.path.isdir(path):
        return
    if not (
        os.path.exists(os.path.join(path, "BRIDGE_TARGET.md"))
        or os.path.exists(os.path.join(path, ".bridge_seeded"))
    ):
        print(
            f"bridge: refusing to reset {path} -- it is not a Bridge scratch dir\n"
            "        (no BRIDGE_TARGET.md/.bridge_seeded marker). Point repo.path at a\n"
            "        disposable directory, or pass --keep to run in place.",
            file=sys.stderr,
        )
        raise SystemExit(2)

    def _onerror(func, p, _exc):
        try:
            os.chmod(p, stat.S_IWRITE)
            func(p)
        except OSError:
            pass

    shutil.rmtree(path, onerror=_onerror)


def _seed_repo(workdir: str, seed_dir: str) -> None:
    """Copy a scenario's source tree into the scratch repo once, then commit it, so
    the agent's diffs apply to real files. Mock/local path (SSH seeding is M5)."""
    import shutil
    import subprocess

    marker = os.path.join(workdir, ".bridge_seeded")
    if os.path.exists(marker):
        return
    for root, _dirs, files in os.walk(seed_dir):
        for f in files:
            src = os.path.join(root, f)
            dst = os.path.join(workdir, os.path.relpath(src, seed_dir))
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.copy2(src, dst)
    with open(marker, "w", encoding="utf-8") as fh:
        fh.write("seeded\n")
    subprocess.run(["git", "add", "-A"], cwd=workdir, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "seed: import target sources"], cwd=workdir, check=True)


def cmd_run(args: argparse.Namespace) -> int:
    import time as _time

    from .agent import Orchestrator, load_prompts
    from .llm import create_backend
    from .run_state import RunRecorder, RunState

    cfg = _load(args.config)
    # Mock runs start from a clean scratch repo so the offline demo is repeatable.
    # Real (local/ssh) repos are never wiped, and never silently git-initialised:
    # Bridge edits and commits, so a live target must already be a git checkout.
    if cfg.executor.kind == "mock":
        if not args.keep:
            _reset_scratch(cfg.repo.path)
        _ensure_git_repo(cfg.repo.path)
    elif cfg.executor.kind == "local" and not os.path.isdir(
        os.path.join(cfg.repo.path, ".git")
    ):
        print(
            f"bridge: repo.path is not a git checkout: {cfg.repo.path}\n"
            "        Bridge commits one fix per iteration -- clone or `git init` the\n"
            "        repo first (a scratch clone is recommended; see THREAT_MODEL.md).",
            file=sys.stderr,
        )
        return 2
    ex = create_executor(cfg)

    scenario = getattr(ex, "scenario", None)
    if scenario is not None and scenario.repo_seed:
        _seed_repo(cfg.repo.path, scenario.repo_seed)

    try:
        prompts = load_prompts(cfg.prompts_dir, cfg.repo.offload_arch)
    except FileNotFoundError as exc:
        print(f"bridge: missing prompt file: {exc}", file=sys.stderr)
        return 2

    backend = create_backend(cfg, record_path=args.record)
    live = cfg.llm.backend != "replay"
    if live and not os.environ.get(cfg.llm.api_key_env):
        print(
            f"bridge: llm.backend is '{cfg.llm.backend}' but ${cfg.llm.api_key_env} is not set.\n"
            f"        Set the key, or use a replay cassette (llm.backend: replay).",
            file=sys.stderr,
        )
        return 2

    state_path = os.path.join(cfg.runs_dir, "current.json")
    dash = None
    if getattr(args, "dashboard", False):
        dash = _start_dashboard(state_path, "127.0.0.1", getattr(args, "port", 8000))
        if dash:
            _open_dashboard("127.0.0.1", getattr(args, "port", 8000))
    state = RunState(
        run_id=_time.strftime("%Y%m%d-%H%M%S"),
        scenario=scenario.name if scenario is not None else "-",
        executor=cfg.executor.kind,
        llm_backend=cfg.llm.backend,
        llm_model=cfg.llm.model,
        llm_host=(
            # An explicit display_host wins even in replay mode, so the badge can
            # name the real recorded brain; without one, show the cassette path.
            cfg.llm.display_host
            or (
                cfg.llm.replay.cassette
                if cfg.llm.backend == "replay" and cfg.llm.replay
                else cfg.llm.resolved_display_host()
            )
        ),
        cost_mode=cfg.llm.cost.mode,
        cost_currency=cfg.llm.cost.currency,
        simulated_cost=False,  # real token usage from the backend
    )
    rec = RunRecorder(state_path, state)

    print(f"== bridge run: scenario '{state.scenario}' | brain [{cfg.llm.backend}] {state.llm_host} ==")
    orch = Orchestrator(cfg, ex, backend, prompts, rec, delay=args.delay)
    try:
        outcome = orch.run()
    finally:
        backend.close()
        ex.close()

    # A class whose cluster ended STUCK was not fixed, even if attempts on it
    # produced applied diffs along the way — never list it under both headings.
    stuck_classes = {c[0] for c in orch.stuck_clusters}
    fixed = sorted(
        {it.error_class for it in rec.state.iterations if it.error_class and it.diff}
        - stuck_classes
    )
    print("== report ==")
    print(f"  outcome: {outcome.value}")
    print(f"  iterations: {len(rec.state.iterations)}")
    print(f"  error classes fixed autonomously: {fixed}")
    if orch.stuck_clusters:
        print(f"  STUCK clusters: {[c[0] for c in orch.stuck_clusters]}")
    if orch.transport_error:
        print(f"  LLM endpoint failure (after retries): {orch.transport_error[:160]}")
    if orch.internal_error:
        print(f"  internal failure (run degraded, log finished): {orch.internal_error[:160]}")
    print(f"  tokens: {rec.state.total_prompt_tokens} prompt + "
          f"{rec.state.total_completion_tokens} completion   cost: ${rec.state.total_cost:.4f}")
    print(f"  dashboard state: {state_path}")
    if args.record:
        print(f"  recorded cassette: {args.record}")
    if dash:
        _wait_for_interrupt(*dash)
    return 0


def cmd_demo(args: argparse.Namespace) -> int:
    """The 30-second journey in one command: dashboard + browser + a replayed
    real migration. No GPU, no API key, one terminal."""
    if not os.path.exists(args.config):
        print(
            f"bridge: {args.config} not found — run `bridge demo` from the Bridge "
            "clone (it replays the recorded run that ships in fixtures/).",
            file=sys.stderr,
        )
        return 2
    cfg = _load(args.config)
    state_path = os.path.join(cfg.runs_dir, "current.json")

    dash = None
    if not args.headless:
        dash = _start_dashboard(state_path, args.host, args.port)
        if dash:
            _open_dashboard(args.host, args.port)

    rc = cmd_run(
        argparse.Namespace(
            config=args.config, record=None, keep=False, delay=args.delay, dashboard=False
        )
    )
    if dash:
        _wait_for_interrupt(*dash)
    return rc


def cmd_shortlist(args: argparse.Namespace) -> int:
    import yaml

    from .shortlist import render_report, shortlist

    cfg = _load(args.config)
    with open(args.repos, "r", encoding="utf-8") as fh:
        candidates = (yaml.safe_load(fh) or {}).get("repos", [])
    if not candidates:
        print(f"bridge: no repos listed in {args.repos}", file=sys.stderr)
        return 2
    ex = create_executor(cfg)
    try:
        print(f"== shortlist: evaluating {len(candidates)} candidate repos on {cfg.executor.kind} ==")
        reports = shortlist(ex, candidates, args.workdir, cfg.commands)
        print(render_report(reports))
    finally:
        ex.close()
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="bridge", description="Autonomous CUDA->ROCm migration agent.")
    p.add_argument("--version", action="store_true", help="print version and exit")
    sub = p.add_subparsers(dest="command")

    pdm = sub.add_parser(
        "demo",
        help="one-command offline demo: dashboard + browser + a replayed real migration",
    )
    pdm.add_argument("--config", default="config.replay.example.yaml")
    pdm.add_argument("--host", default="127.0.0.1")
    pdm.add_argument("--port", type=int, default=8000)
    pdm.add_argument("--delay", type=float, default=1.0, help="seconds per iteration so the climb is visible (0 = instant)")
    pdm.add_argument("--headless", action="store_true", help="no dashboard/browser; print the report only")
    pdm.set_defaults(func=cmd_demo)

    from .setup_wizard import add_init_parser, add_port_parser

    add_port_parser(sub)
    add_init_parser(sub)

    pv = sub.add_parser("validate", help="validate a config and print a summary")
    pv.add_argument("--config", default="config.yaml")
    pv.set_defaults(func=cmd_validate)

    pm = sub.add_parser("mock-demo", help="drive a scenario through the mock executor")
    pm.add_argument("--config", default="config.yaml")
    pm.add_argument(
        "--delay",
        type=float,
        default=0.8,
        help="seconds to pause per iteration so the dashboard shows live progress (0 = instant)",
    )
    pm.set_defaults(func=cmd_mock_demo)

    pd = sub.add_parser("dashboard", help="serve the live run dashboard (needs [dashboard] extras)")
    pd.add_argument("--config", default="config.yaml")
    pd.add_argument("--host", default="127.0.0.1")
    pd.add_argument("--port", type=int, default=8000)
    pd.set_defaults(func=cmd_dashboard)

    pr = sub.add_parser("run", help="run the real agent loop (LLM diagnose -> diff -> commit)")
    pr.add_argument("--config", default="config.yaml")
    pr.add_argument("--record", default=None, help="record the LLM exchange to this cassette path")
    pr.add_argument("--keep", action="store_true", help="(mock) keep the existing scratch repo instead of resetting it")
    pr.add_argument("--delay", type=float, default=0.0, help="pause N seconds per iteration so the dashboard shows a live climb")
    pr.add_argument("--dashboard", action="store_true", help="serve + open the live dashboard during the run (one terminal)")
    pr.add_argument("--port", type=int, default=8000, help="dashboard port (with --dashboard)")
    pr.set_defaults(func=cmd_run)

    ps = sub.add_parser("shortlist", help="triage candidate CUDA repos and rank the best demo pick")
    ps.add_argument("--config", default="config.yaml")
    ps.add_argument("--repos", default="shortlist.example.yaml", help="YAML with a 'repos' list of {name, url}")
    ps.add_argument("--workdir", default="bridge-shortlist", help="base dir on the target to clone into")
    ps.set_defaults(func=cmd_shortlist)

    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.version:
        from . import __version__

        print(f"bridge {__version__}")
        return 0
    if not getattr(args, "command", None):
        parser.print_help()
        return 1
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
