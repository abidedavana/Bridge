#!/usr/bin/env bash
# Bridge demo container: serve the dashboard and continuously replay a full
# CUDA->ROCm migration, so the browser always shows a fresh, live climb.
# No GPU, no API key — the brain is a recorded cassette, the hardware is mocked.
set -e

CONFIG="${BRIDGE_CONFIG:-config.replay.example.yaml}"
PORT="${PORT:-8000}"

echo "== Bridge demo — open http://localhost:${PORT} in your browser =="

# Background: re-run the offline migration forever. Each run resets its own
# scratch repo, so the dashboard perpetually shows the pass-rate climbing to
# SUCCESS with real diffs applied per fixed error class.
(
  while true; do
    python -m bridge run --config "$CONFIG" --delay 1.0 >/dev/null 2>&1 || true
    sleep 4
  done
) &

# Foreground: the dashboard keeps the container alive.
exec python -m bridge dashboard --config "$CONFIG" --host 0.0.0.0 --port "$PORT"
