# Bridge — AMD GPU Pod Runbook (notebooks.amd.com/hackathon)

Environment: **ROCm 7.2 + vLLM 0.16.0 + PyTorch 2.9**, team `team-3531`.
Budget: **8h / 24h** — the clock runs while the pod is active, so move top-to-bottom.
Everything runs **inside the pod**. In Jupyter: **New → Terminal** (easiest), or prefix
cell commands with `!`. Bridge runs with `executor.kind: local` — no SSH.

> ⚡ The one gate: **Phase 0 confirms the GPU arch.** Do not skip it — the whole
> demo (offload_arch, the warpSize-64 CDNA story) assumes MI300X / `gfx942`.

---

## Phase 0 — Confirm the hardware (2 min) ⇐ PASTE BACK TO CLAUDE
```bash
rocm-smi                                  # GPUs healthy?
rocminfo | grep -i gfx | head             # arch: gfx942 = MI300X/CDNA3 (wave64) ✅
hipcc --version                           # HIP compiler present?
which hipify-perl hipcc cmake             # tools on PATH?
```
**Paste me the `gfx` line + hipcc version.**
- `gfx942` → MI300X/CDNA3, wave64 → everything is correct as built.
- `gfx90a` → MI200/CDNA2, also wave64 → fine, set `offload_arch: gfx90a`.
- `gfx11xx` (RDNA/Radeon, wave32) → tell me: I change `offload_arch` and soften the
  "warpSize 32-vs-64" pitch point (RDNA is 32-wide, like CUDA).

If `cmake` is missing: `pip install cmake` (or `apt-get update && apt-get install -y cmake`).

---

## Phase 1 — Bridge on the pod + offline sanity (5 min) — quick win
```bash
cd ~
git clone https://github.com/abidedavana/Bridge.git
cd Bridge
pip install -q pydantic PyYAML fastapi uvicorn pytest httpx
python -m bridge --version
python -m pytest -q -p no:warnings          # expect: 135 passed
python -m bridge run --config config.replay.example.yaml   # replays the real run → SUCCESS
```
This alone is a talking point: **Bridge running on an AMD Instinct GPU.**
⇐ Paste the report line (outcome / iterations / cost).

---

## Phase 2 — Capture REAL HIPIFY + build logs (15 min) — the credibility step
Pick one *small* CUDA repo (a few `.cu` files, CMake). Then:
```bash
cd ~ && git clone --depth 1 <SMALL_CUDA_REPO> probe && cd probe
hipify-perl -inplace -print-stats $(find . -name '*.cu')  2>&1 | tee ~/real_hipify.txt
cmake -S . -B build -DCMAKE_CXX_COMPILER=hipcc            2>&1 | tee ~/real_configure.txt
cmake --build build -j                                    2>&1 | tee ~/real_build.txt
```
⇐ Paste `real_hipify.txt`, `real_configure.txt`, `real_build.txt`. I diff them against
our fixtures — this is the single highest-value thing we do on hardware.

---

## Phase 3 — A REAL migration on the pod (20 min) — the headline
Bridge drives the real build; the brain is Fireworks (your $50 coupon).
```bash
export BRIDGE_LLM_API_KEY=<your Fireworks key>     # env only, never commit
cd ~/Bridge
cp config.example.yaml config.pod.yaml
#  edit config.pod.yaml:
#    executor.kind: local
#    repo.path: /root/probe            (or wherever the CUDA repo is)
#    repo.offload_arch: gfx942         (or whatever Phase 0 reported)
#    commands.{configure,hipify,build,test}: the repo's real commands
#    llm.model: accounts/fireworks/models/kimi-k2p6
python -m bridge validate --config config.pod.yaml
python -m bridge run --config config.pod.yaml --record fixtures/cassettes/hardware.json
```
⇐ Paste the final report. `--record` captures the on-hardware cassette.

---

## Phase 4 — (showcase, if time) The brain ON AMD via vLLM
vLLM 0.16 is preinstalled — no Docker needed.
```bash
# ungated coder model is simplest; Gemma needs `export HF_TOKEN=...` + license accept
vllm serve Qwen/Qwen2.5-Coder-32B-Instruct --port 8000 &
#  wait for "Uvicorn running", then in config.pod.yaml:
#    llm.base_url: http://localhost:8000/v1
#    llm.model: Qwen/Qwen2.5-Coder-32B-Instruct   (or google/gemma-3-27b-it for the Gemma challenge)
#    llm.display_host: mi300x-vllm
#    llm.cost.mode: self_hosted
python -m bridge run --config config.pod.yaml
```
This is the money shot: **Gemma/Qwen thinking on the MI300X while it ports code to AMD.**

---

## Phase 5 — Capture for the video/deck (5 min)
```bash
python -m bridge dashboard --config config.pod.yaml &   # then open the port in Jupyter
```
Screenshot the dashboard (endpoint badge shows the pod). Grab `rocm-smi` during a run.
Save `real_*.txt` and `fixtures/cassettes/hardware.json` — download them from Jupyter before the pod expires.

---

## Don't-waste-the-clock checklist
- [ ] Have your Fireworks key handy (Phase 3).
- [ ] Pick the small CUDA repo *before* launching (Phase 2).
- [ ] Download artifacts (logs, cassette, screenshots) before the 8h ends — the pod is disposable.
- [ ] Paste Phase 0 + Phase 2 back to me first; those drive every adjustment.
