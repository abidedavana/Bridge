# Bridge — MI300X Provisioning Checklist (Hardware Day / Day 1)

Everything here is **your hands on the AMD Developer Cloud**. Do the steps in
order; each has a clear outcome, and the ⇐ **PASTE TO CLAUDE** markers tell you
exactly what to copy back so we adjust fixtures/config to reality.

Goal of the day, in priority order:
1. Get a healthy MI300X box (ROCm works).
2. Capture **real** HIPIFY + ROCm compiler logs → retire the #1 risk (do our
   fixtures match reality?).
3. Drive one command end-to-end through Bridge's SSH executor.
4. Pick the demo repo with the shortlist tool.
5. *Only if time remains:* serve the brain on AMD with vLLM.

---

## 0. Before you start (5 min)
- [ ] AMD Developer Cloud account created, hackathon credits applied.
- [ ] An SSH key on your laptop. If you don't have one, in PowerShell:
      `ssh-keygen -t ed25519 -C "abidedavana@gmail.com"` (press Enter through the prompts).
      Then show the public key to paste into the cloud console:
      `type $env:USERPROFILE\.ssh\id_ed25519.pub`

## 1. Launch the instance (5 min)
- [ ] In the AMD Developer Cloud console, create a **GPU Droplet / instance**.
- [ ] **Image:** choose the **"vLLM Quick Start"** image — it ships ROCm + Docker +
      vLLM preinstalled, which saves you an hour of setup.
- [ ] Add your SSH public key when prompted.
- [ ] Launch. It goes **Creating → Active** in ~2–4 minutes. Copy the **Public IP**.

## 2. Connect + verify ROCm (5 min) — do NOT skip
From your laptop (PowerShell), replacing the IP:
```
ssh root@<PUBLIC_IP>
```
On the box:
```
rocm-smi                         # should list the MI300X GPU(s)
rocminfo | grep -i gfx           # should show gfx942 (CDNA3)
```
⇐ **PASTE TO CLAUDE:** the output of `rocm-smi` and the `gfx` line.
**Do not continue until this works** — if ROCm is unhealthy, nothing else matters.

## 3. Put Bridge on the box (5 min)
```
apt-get update -y && apt-get install -y git python3-pip
git clone <YOUR_REPO_URL> bridge && cd bridge
pip install pydantic pyyaml
python -m bridge --version        # sanity: prints the version
```
(If the repo is still private/not pushed, `scp` it up instead — ask me and I'll
give you the exact command.)

## 4. Capture REAL logs on a small CUDA project (20 min) — the important one
This is what makes the whole agent trustworthy. Clone one *small* CUDA repo and
run the real tools, saving every output:
```
cd ~ && git clone --depth 1 <SMALL_CUDA_REPO> probe && cd probe
# 1) real HIPIFY:
hipify-perl -inplace -print-stats $(find . -name '*.cu')  2>&1 | tee ~/real_hipify.txt
# 2) real configure + build with hipcc (adapt paths to the repo):
cmake -S . -B build -DCMAKE_CXX_COMPILER=hipcc          2>&1 | tee ~/real_configure.txt
cmake --build build -j                                  2>&1 | tee ~/real_build.txt
```
⇐ **PASTE TO CLAUDE:** `real_hipify.txt`, `real_configure.txt`, `real_build.txt`.
I diff them against our fixtures and update the parser + fixtures to match real
output — this is the single highest-value thing we do on hardware day.

## 5. Wire Bridge's SSH executor (10 min)
Back **on your laptop**, edit `config.yaml` (copy from `config.example.yaml`):
```
executor:
  kind: ssh
  ssh:
    host: <PUBLIC_IP>
    user: root
    remote_workdir: /root/target-repo
    key_path: ~/.ssh/id_ed25519
```
Then:
```
python -m bridge validate --config config.yaml    # should say "valid", kind: ssh
```
⇐ **PASTE TO CLAUDE:** the `validate` output. Then we run one real build through it.

## 6. Pick the demo repo (15 min)
With 3 candidate CUDA repos in mind, run the shortlist tool (it clones each on the
box, runs HIPIFY + a dry build, and ranks them by "closest to green, most
interesting failures"):
```
python -m bridge shortlist --config config.yaml --repos shortlist.example.yaml
```
⇐ **PASTE TO CLAUDE:** the ranked table. **We pick the demo repo together.**

## 7. (Optional, if time) Serve the brain on AMD
Preferred model: **Gemma 3 27B** — one demo then ticks two judge boxes at once:
the "Best Use of Gemma Models" challenge *and* the brain running on AMD.
`google/gemma-*` weights are gated on Hugging Face: accept the license at
https://huggingface.co/google/gemma-3-27b-it once, then on the box:
```
export HF_TOKEN=<your HF token>            # required for gated Gemma weights
cd ~/bridge && MODEL=google/gemma-3-27b-it ./scripts/serve_vllm_rocm.sh
# fallback if Gemma download/serving misbehaves (ungated, coder-specialized):
# cd ~/bridge && MODEL=Qwen/Qwen2.5-Coder-32B-Instruct ./scripts/serve_vllm_rocm.sh
```
Wait for "Uvicorn running". Then on your laptop point `config.yaml` `llm.base_url`
at `http://<PUBLIC_IP>:8000/v1`, `llm.model: google/gemma-3-27b-it`,
`llm.display_host: mi300x-vllm`, `llm.cost.mode: self_hosted`. That flips the
dashboard badge to **"on AMD."**
⇐ **PASTE TO CLAUDE:** the output of `curl http://<PUBLIC_IP>:8000/v1/models`.

---

## Security note (say this in the pitch, live it here)
Treat this box as **disposable**: it runs untrusted repo build scripts and
model-written edits. Don't put real secrets on it, use it only for the demo, and
destroy the instance when done. Bridge's own guardrails (the patch policy engine)
assume exactly this trust boundary — see THREAT_MODEL.md.
