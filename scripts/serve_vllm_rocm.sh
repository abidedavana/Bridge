#!/usr/bin/env bash
# serve_vllm_rocm.sh — serve an OpenAI-compatible LLM on an AMD Instinct MI300X
# with vLLM, so Bridge's "brain" runs ON AMD. This is the showcase: the agent
# porting code TO AMD, thinking ON AMD.
#
# Run this ON the MI300X box (AMD Developer Cloud). It starts vLLM's
# OpenAI-compatible server; then point Bridge's config at it (see footer).
#
#   MODEL=Qwen/Qwen2.5-Coder-32B-Instruct PORT=8000 ./scripts/serve_vllm_rocm.sh
#
# Gemma challenge entry (ACT II "Best Use of Gemma Models") — Gemma on the MI300X
# is two judge boxes in one demo. google/gemma-* is gated on Hugging Face: accept
# the license on the model page once, then export HF_TOKEN before running:
#   HF_TOKEN=... MODEL=google/gemma-3-27b-it ./scripts/serve_vllm_rocm.sh
#
# Notes verified against AMD/vLLM docs (Jan 2026): the image is
# vllm/vllm-openai-rocm (AMD's rocm/vllm is deprecated in favour of it). A single
# MI300X has 192 GB HBM, so a 27–32B model fits comfortably at TP=1.

set -euo pipefail

MODEL="${MODEL:-Qwen/Qwen2.5-Coder-32B-Instruct}"   # strong open-weights coder; fits one MI300X
PORT="${PORT:-8000}"
TP="${TP:-1}"                                         # tensor-parallel size; 1 = single GPU
MAX_LEN="${MAX_LEN:-16384}"                           # context window
IMAGE="${IMAGE:-vllm/vllm-openai-rocm:latest}"        # pin a specific tag for the demo

echo "== Bridge: serving '$MODEL' via vLLM on ROCm (port $PORT, TP=$TP) =="

# Sanity: confirm we are on a ROCm box with visible GPUs before pulling anything.
if command -v rocm-smi >/dev/null 2>&1; then
  rocm-smi --showproductname || { echo "!! rocm-smi failed — not a healthy ROCm box"; exit 1; }
else
  echo "!! rocm-smi not found — are you on the MI300X instance?"; exit 1
fi

# The device/cap flags are what give the container access to the AMD GPUs.
docker run --rm -it \
  --group-add=video \
  --ipc=host \
  --cap-add=SYS_PTRACE \
  --security-opt seccomp=unconfined \
  --device /dev/kfd \
  --device /dev/dri \
  -v "${HOME}/.cache/huggingface:/root/.cache/huggingface" \
  ${HF_TOKEN:+--env HF_TOKEN=$HF_TOKEN} \
  -p "${PORT}:${PORT}" \
  "$IMAGE" \
  --model "$MODEL" \
  --tensor-parallel-size "$TP" \
  --max-model-len "$MAX_LEN" \
  --port "$PORT"

# ---------------------------------------------------------------------------
# When vLLM prints "Uvicorn running on http://0.0.0.0:PORT", the OpenAI-compatible
# endpoint is live at  http://<box-ip>:PORT/v1  (or http://localhost:PORT/v1 here).
#
# Point Bridge at it (config.yaml):
#     llm:
#       backend: openai
#       base_url: http://<box-ip>:8000/v1
#       model: Qwen/Qwen2.5-Coder-32B-Instruct
#       api_key_env: BRIDGE_LLM_API_KEY   # vLLM ignores the key; any value works
#       display_host: mi300x-vllm         # makes the dashboard badge say "on AMD"
#       cost:
#         mode: self_hosted               # zero marginal token cost -> show throughput
#
# Quick check from your laptop (or on the box):
#   curl http://<box-ip>:8000/v1/models
# ---------------------------------------------------------------------------
