# Bridge

**An autonomous CUDA → ROCm/HIP migration agent.**

Bridge takes a git repository containing CUDA code and ports it to ROCm/HIP so it
builds and passes its test suite on an AMD Instinct MI300X — and it can run its
own reasoning *on* AMD, with its LLM brain served by vLLM on the same MI300X.

HIPIFY does the mechanical 90%. Bridge earns its keep on the last mile: build
systems (CMake/Make), APIs HIPIFY misses, `cuBLAS`→`hipBLAS`/`rocBLAS` quirks,
warp-size 32-vs-64 assumptions on CDNA, `__shfl_sync` semantics,
`-arch=sm_XX` → `--offload-arch=gfx942`, and header/link failures. When it can't
finish a migration it says so precisely — every run ends in a complete, honest
report ("HIPIFY got X%, Bridge autonomously fixed these classes, these remain").

> **Status:** the full agent loop, the live dashboard, the safety gate, and the
> hardware-day tooling are built and verified — **117 tests passing**, and the
> entire thing runs on a laptop with **no GPU and no API key**. The offline demo
> replays a **genuine live migration**: a real Fireworks run (Kimi K2.6) that
> reached `SUCCESS` with all 7 error classes fixed autonomously, for ~$0.30 at
> list price. A port on a real MI300X is the only step that still needs hardware.

---

## 30-second demo (no GPU, no API key)

From a fresh clone, with Docker:

```bash
docker compose up
```

Open **http://localhost:8000**. A full CUDA→ROCm migration climbs to `SUCCESS`
live and on a loop: the pass-rate chart rising per iteration, each agent-written
diff shown beside the error it fixed, the error classes fixed autonomously,
HIPIFY's conversion %, a token/cost counter, and an endpoint badge. Every fix is a
**real git commit** in a scratch repo (`bridge(iter N, <error_class>): …`); only
the GPU-bound compile/test result is replayed from captured fixtures.

### No Docker? Run it natively

Requires Python 3.10+ and git.

```bash
python -m pip install pydantic PyYAML fastapi uvicorn

# headless — prints the outcome report:
python -m bridge run --config config.replay.example.yaml

# or watch it live in a browser (two terminals):
python -m bridge dashboard --config config.replay.example.yaml     # http://127.0.0.1:8000
python -m bridge run --config config.replay.example.yaml --delay 1.0
```

## The hardware run — a real autonomous migration recorded on AMD hardware (gfx1100)

On 2026-07-08, on an AMD hackathon GPU pod (Radeon PRO W7900-class, `gfx1100`,
ROCm 7.2), Bridge autonomously ported this CUDA project for real: live Kimi K2.6
diagnosed cmake's actual (ANSI-colored) errors, two policy-gated fixes landed as
real commits, and the ported binary passed `ctest` on the GPU — 3 iterations,
$0.07. That run's unmodified recording is
[fixtures/cassettes/hardware.json](fixtures/cassettes/hardware.json); the build
and test logs in its replay scenario are the genuine captured pod outputs.
Replay it, no GPU or key needed:

```bash
python -m bridge run --config config.replay.hardware.yaml
```

## Graceful degradation is a feature

Point it at the other scenarios (copy `config.replay.example.yaml`, change
`scenario:`) to see the honest outcomes:

- **SUCCESS** — build green, all tests pass.
- **PARTIAL** — build green, but one fp32-tolerance test can't be fixed without
  cheating (policy forbids it), so it stops at a real number and reports it.
- **STUCK** — build never goes green; tests never run, and the report says exactly
  that. Nothing crashes; nothing claims success.

## Real hardware (MI300X)

One config switch (`executor.kind: mock → ssh`) runs the identical loop on an AMD
Instinct box over SSH; another (`llm.base_url`) points the brain at Fireworks or a
self-hosted vLLM server on the MI300X. The Day-1 runbook, the vLLM serving script,
and the demo-repo picker are ready:

- [provision_checklist.md](provision_checklist.md) — step-by-step provisioning.
- [scripts/serve_vllm_rocm.sh](scripts/serve_vllm_rocm.sh) — serve the brain on AMD.
- `python -m bridge shortlist --config config.example.yaml --repos shortlist.example.yaml`
  — rank candidate CUDA repos "closest to green, most interesting failures".

## Best Use of Gemma — the model-comparison run

The brain is any OpenAI-compatible endpoint, and the safety gate never trusts it
either way — so swapping models is a one-line config change, not a refactor. For
the Gemma challenge we ran the identical migration with **Gemma 4 31B** (Google
AI Studio) as the brain, recorded at
[fixtures/cassettes/gemma.live.json](fixtures/cassettes/gemma.live.json)
(config: [config.gemma.laptop.yaml](config.gemma.laptop.yaml)).

Access path, honestly: the hackathon names Fireworks as the Gemma route, but
this account's Fireworks *serverless* endpoint listed no Gemma model (every
Gemma id returned 404 NOT_FOUND when probed on 2026-07-09; an on-demand
dedicated deployment is a paid spin-up we skipped), so the comparison ran
against Google AI Studio's hosted **Gemma 4 31B** instead — same agent, same
scenario, one config line.

The honest result: Gemma 4 fixed **3 of the 7 error classes autonomously**
(`cmake_cuda_language`, `arch_flag_unsupported`, `missing_cuda_header`) before
the free-tier endpoint began returning 500s and the run degraded, honestly, to
STUCK (`llm_endpoint_unreachable`) — versus Kimi K2.6's 7 of 7. The comparison
also produced a real finding: Gemma 4 interleaves `<thought>` markup through its
replies, which broke diff extraction on the first attempt (1 fix); Bridge's
messy-output hardening now strips thought spans (test-pinned with the recorded
reply shape), which took Gemma from 1 fix to 3. The architectural point stands:
diagnosis quality varies by brain, but the mechanical patch policy gate held
identically for both models.

## Tests & CI

```bash
python -m pip install pytest httpx
python -m pytest -q          # 117 tests
```

Written to convince a skeptical judge, not just to pass CI: authentic ROCm/clang
fixture text, real git commits driving the loop, a property test that no sequence
of executor/model output can crash the orchestrator, the patch policy engine
rejecting a live prompt-injection payload, messy-model-output hardening, and a
deterministic SUCCESS/PARTIAL/STUCK end-to-end run. CI (GitHub Actions) runs the
suite plus the offline e2e on every push.

## How it works

```
clone repo → HIPIFY → build → parse errors → diagnose (LLM) → propose diff →
  policy gate → git apply → commit → rebuild →  (green) → run tests → (same loop)
  → SUCCESS / PARTIAL / STUCK, always with a complete report
```

Two seams make it testable and safe: the **`Executor`** interface (mock replays
real logs with zero GPU; SSH runs on the MI300X — one config switch), and the
**LLM backend** (`openai` for Fireworks/vLLM; `replay` for a deterministic
recorded run). Plain Python, an explicit state machine, no agent frameworks.

## Security posture

Bridge clones an **untrusted** repo, runs its build/tests (arbitrary code
execution), and applies **LLM-generated** diffs — a stack of trust boundaries it
treats as one. Guardrails are mechanical and enforced on the diff *before* it is
applied, so they hold even under indirect prompt injection from a hostile repo: a
writable-path allowlist, a never-touch protected list, a denylist of dangerous
insertions (shell-out, network egress, `eval`), a size cap, and a ban on editing
test files. The `poisoned` fixture is a repo that attempts exactly this attack;
a test proves the gate rejects it. See [THREAT_MODEL.md](THREAT_MODEL.md).

## Repository layout

```
bridge/
  config.py          typed, validated config schema (one YAML file)
  executor/          the Executor seam: base + local + mock (fixtures) + ssh
  parser/            raw ROCm/clang/ctest output -> structured, ranked diagnostics
  llm/               OpenAI-compatible + replay + recording backends; output hardening
  patcher/           the mechanical policy gate + atomic git-apply
  agent/             context builder, diagnose/propose stages, orchestrator loop
  dashboard/         FastAPI + one static page over the run state
  run_state.py       the persisted run log / dashboard feed
  shortlist.py       Day-1 demo-repo triage
  cli.py             validate | mock-demo | run | dashboard | shortlist
prompts/             versioned diagnose + propose-edit prompts (+ CUDA→ROCm cheat-sheet)
fixtures/            real HIPIFY/ROCm/ctest logs, scenarios, seed + poisoned repos, cassette
scripts/             serve_vllm_rocm.sh
DECISIONS.md · THREAT_MODEL.md · provision_checklist.md
```

## Team

- **Abid Edavana Zakir** — abidedavana@gmail.com — solo (design, implementation, security, tests).

## License

MIT — see [LICENSE](LICENSE). All work is original and open source.
