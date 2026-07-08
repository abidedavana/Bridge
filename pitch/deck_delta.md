# Canva deck edits ("Bridge — AMD Hackathon ACT II", design DAHOz4mjblU)

Apply these text changes slide by slide. Old text is what the deck says now;
new text is what it should say for submission. Everything else stays.

## Slide 5 — "The Demo: One Command"
- OLD: "No GPU, no API key. A full CUDA to ROCm migration climbs to SUCCESS on a
  live dashboard — 11 iterations, 7 of 7 error classes fixed autonomously,
  about $0.30."
- NEW: unchanged (numbers verified) — keep as is.

## Slide 6 — "Aligned With the AMD Stack"
- OLD: "Next on hardware: a live migration on a real AMD MI300X on Developer
  Cloud — the tooling is written and ready, and runs on approval."
- NEW: "Proven on hardware: on an AMD Radeon GPU pod (gfx1100, ROCm 7.2),
  Bridge autonomously ported a real CUDA project — two policy-gated fixes,
  ctest 100% on the GPU, $0.07. MI300X remains a one-line arch swap away."

## Slide 7 — "Proof by the Numbers"
- OLD: big stat "119" / caption "tests green, with CI"
- NEW: big stat "135" / caption unchanged.
- OLD: caption under "$0.30": "total LLM cost, at list price"
- NEW: unchanged (that figure is the recorded demo run; correct as is).
- OLD: "7 of 7 CUDA-porting error classes fixed with no human help, across 11
  iterations."
- NEW: "7 of 7 error classes fixed with no human help — and a second SUCCESS
  on real AMD hardware: 3 iterations, ctest 100%, $0.07."

## Slide 9 — "Swap the Brain in One Line"
- OLD (card 2, "Gemma challenge"): "Swap Kimi K2.6 for Google Gemma 3 27B to
  enter the Best Use of Gemma challenge — the same agent, a different brain."
- NEW: "We ran it: Gemma 4 31B fixed 3 of 7 error classes on the same
  migration Kimi aced — honest numbers, recorded, same safety gate holding."
- OLD (card 3, "Gemma on AMD"): "Gemma can be self-hosted on the MI300X via
  vLLM — thinking on AMD while it ports code to AMD. The gate is
  model-independent."
- NEW: "The comparison surfaced a real fix: Gemma 4's <thought> markup broke
  diff extraction; Bridge's output-hardening now strips it (test-pinned).
  The gate is model-independent."

## Slide 10 — "Everything You See Is Real"
- OLD: "Not a mockup. A genuine Fireworks Kimi K2.6 run reached SUCCESS —
  including the correct 64-bit CDNA warp-mask fix. One real git commit per fix
  makes the migration an auditable history, and the whole demo runs offline on
  a laptop."
- NEW: "Not a mockup. A genuine Fireworks run reached SUCCESS — including the
  correct 64-bit CDNA warp-mask fix — and a second run ported real CUDA on an
  AMD Radeon GPU (gfx1100), ctest 100%. Every fix is a real git commit; both
  recordings replay offline on a laptop."

## Slide 11 — "Status & Roadmap"
- OLD (shipped card): "Shipped and verified: the full agent loop, the policy
  gate, a live dashboard, 119 tests with CI, the docker compose demo, a live
  Fireworks run to SUCCESS, and a public MIT repo."
- NEW: "Shipped and verified: the full agent loop, the policy gate, a live
  dashboard, 135 tests with CI, the docker compose demo, a live Fireworks run
  to SUCCESS, an autonomous port on real AMD hardware (gfx1100), and a public
  MIT repo."
- OLD (next card): "Next: a live migration on a real AMD MI300X, self-hosted
  Gemma on AMD via vLLM, and a recorded Gemma comparison run. The hardware
  tooling is written and waiting."
- NEW: "Next: the same run on an MI300X (a one-line arch swap), and
  self-hosted Gemma on AMD via vLLM. The Gemma comparison is done and
  recorded — 3 of 7 classes, reported honestly."

## Notes
- The audit's cost fix is already reflected: anywhere the deck says the demo
  cost, it must read "~$0.30 at list price" (slide 5 and slide 7 already do).
- Do not add an MI300X claim anywhere — the hardware run was Radeon gfx1100.
- The offline .pptx (pitch/bridge_pitch.pptx) has the same lines on its demo,
  stack, status, and Gemma slides if you use it instead — apply the same edits.
