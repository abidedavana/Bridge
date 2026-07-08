const pptxgen = require("pptxgenjs");

// ---- design system -------------------------------------------------------
const BG      = "0E0F13";   // near-black, all slides (dark throughout = premium)
const CARD    = "1B1E26";   // card surface
const RED      = "E4002B";  // AMD-red primary accent
const RED_DIM  = "B3001F";
const TEXT     = "F4F5F7";  // off-white
const MUTED    = "9AA1AD";  // muted grey
const GREEN    = "35D08A";  // success / metrics
const AMBER     = "F2B441";  // "next / planned"
const HEAD = "Arial";
const BODY = "Calibri";
const MONO = "Courier New";
const W = 13.333, H = 7.5, ML = 0.7;

const pres = new pptxgen();
pres.layout = "LAYOUT_WIDE";
pres.author = "Abid Edavana Zakir";
pres.title = "Bridge — AMD Developer Hackathon ACT II";

const shadow = () => ({ type: "outer", color: "000000", blur: 9, offset: 3, angle: 90, opacity: 0.35 });

function base(slide) { slide.background = { color: BG }; }

function eyebrow(slide, text) {
  slide.addShape(pres.shapes.OVAL, { x: ML, y: 0.62, w: 0.12, h: 0.12, fill: { color: RED } });
  slide.addText(text.toUpperCase(), { x: ML + 0.22, y: 0.5, w: 11, h: 0.35,
    fontFace: HEAD, fontSize: 12, bold: true, color: RED, charSpacing: 3, align: "left", valign: "middle", margin: 0 });
}

function title(slide, text, opts = {}) {
  slide.addText(text, { x: ML, y: opts.y || 1.0, w: opts.w || 11.9, h: opts.h || 1.1,
    fontFace: HEAD, fontSize: opts.size || 33, bold: true, color: TEXT, align: "left", valign: "top", margin: 0, lineSpacingMultiple: 1.02 });
}

function footer(slide, n) {
  slide.addText("Bridge  ·  AMD Developer Hackathon · ACT II", { x: ML, y: 7.02, w: 9, h: 0.3,
    fontFace: BODY, fontSize: 9.5, color: "5C626C", align: "left", valign: "middle", margin: 0 });
  slide.addText(String(n).padStart(2, "0"), { x: W - 1.3, y: 7.02, w: 0.6, h: 0.3,
    fontFace: BODY, fontSize: 9.5, color: "5C626C", align: "right", valign: "middle", margin: 0 });
}

// numbered process step (circle + label)
function stepCircle(slide, x, y, num, label, hot) {
  const d = 0.62;
  slide.addShape(pres.shapes.OVAL, { x, y, w: d, h: d, fill: { color: hot ? RED : CARD },
    line: hot ? { color: RED, width: 1 } : { color: "343842", width: 1 } });
  slide.addText(String(num), { x, y, w: d, h: d, fontFace: HEAD, fontSize: 16, bold: true,
    color: hot ? "FFFFFF" : MUTED, align: "center", valign: "middle", margin: 0 });
  slide.addText(label, { x: x - 0.45, y: y + d + 0.06, w: d + 0.9, h: 0.6, fontFace: BODY, fontSize: 11.5,
    bold: hot, color: hot ? TEXT : MUTED, align: "center", valign: "top", margin: 0 });
}

function card(slide, x, y, w, h, fill) {
  slide.addShape(pres.shapes.ROUNDED_RECTANGLE, { x, y, w, h, rectRadius: 0.08,
    fill: { color: fill || CARD }, line: { color: "2A2E38", width: 1 }, shadow: shadow() });
}

// ==========================================================================
// SLIDE 1 — TITLE
// ==========================================================================
let s = pres.addSlide(); base(s);
// loop/GPU ring motif, partly off right edge
s.addShape(pres.shapes.OVAL, { x: 9.2, y: 0.7, w: 6.2, h: 6.2, fill: { type: "none" }, line: { color: RED_DIM, width: 2.5 } });
s.addShape(pres.shapes.OVAL, { x: 10.1, y: 1.6, w: 4.4, h: 4.4, fill: { type: "none" }, line: { color: "2A2E38", width: 1.5 } });
s.addShape(pres.shapes.OVAL, { x: 9.06, y: 3.6, w: 0.28, h: 0.28, fill: { color: RED } });

s.addShape(pres.shapes.OVAL, { x: ML, y: 0.92, w: 0.13, h: 0.13, fill: { color: RED } });
s.addText("AMD DEVELOPER HACKATHON · ACT II  ·  TRACK 3 / UNICORN", { x: ML + 0.24, y: 0.8, w: 9, h: 0.35,
  fontFace: HEAD, fontSize: 12.5, bold: true, color: RED, charSpacing: 2, valign: "middle", margin: 0 });

s.addText("Bridge", { x: ML - 0.03, y: 2.15, w: 9, h: 1.5, fontFace: HEAD, fontSize: 82, bold: true, color: TEXT, margin: 0 });
s.addText([
  { text: "Autonomous CUDA → ROCm migration", options: { color: TEXT } },
  { text: "  —  that finishes the job, ", options: { color: MUTED } },
  { text: "safely", options: { color: RED, bold: true } },
  { text: ".", options: { color: MUTED } },
], { x: ML, y: 3.75, w: 8.4, h: 0.7, fontFace: HEAD, fontSize: 22, bold: true, valign: "top", margin: 0 });

s.addText([
  { text: "An agent that ports CUDA repos to AMD ROCm/HIP until they build and pass tests —", options: { breakLine: true } },
  { text: "with a mechanical safety gate over every model-written diff.", options: {} },
], { x: ML, y: 4.6, w: 8.2, h: 0.9, fontFace: BODY, fontSize: 14.5, color: MUTED, valign: "top", margin: 0, lineSpacingMultiple: 1.15 });

s.addText([
  { text: "Abid Edavana Zakir", options: { color: TEXT, bold: true } },
  { text: "   ·   github.com/abidedavana/Bridge   ·   MIT", options: { color: MUTED } },
], { x: ML, y: 6.5, w: 11, h: 0.4, fontFace: BODY, fontSize: 13, valign: "middle", margin: 0 });
footer(s, 1);

// ==========================================================================
// SLIDE 2 — THE PROBLEM
// ==========================================================================
s = pres.addSlide(); base(s);
eyebrow(s, "The problem");
title(s, "CUDA locks GPU code to one vendor.\nThe move to AMD stalls on the last mile.");
s.addText([
  { text: "Most GPU code targets CUDA — tied to one vendor's hardware.", options: { breakLine: true, bullet: { code: "2022" , indent: 18 } } },
  { text: "HIPIFY mechanically converts most of it to AMD's HIP.", options: { breakLine: true, bullet: { code: "2022", indent: 18 } } },
  { text: "But the last ~10% is manual and brutal: CMake/build systems, the warp-size 32-vs-64 assumption on CDNA, cuBLAS→hipBLAS quirks, arch flags, link and header failures.", options: { bullet: { code: "2022", indent: 18 } } },
], { x: ML, y: 2.75, w: 6.7, h: 3.0, fontFace: BODY, fontSize: 15.5, color: TEXT, valign: "top", margin: 0, paraSpaceAfter: 12, lineSpacingMultiple: 1.1 });

// two stat cards: 90% vs 10%
card(s, 8.05, 2.75, 2.35, 3.2);
s.addText("~90%", { x: 8.05, y: 3.2, w: 2.35, h: 0.9, fontFace: HEAD, fontSize: 40, bold: true, color: GREEN, align: "center", margin: 0 });
s.addText([{ text: "HIPIFY", options: { breakLine: true, bold: true, color: TEXT } }, { text: "mechanical, automated", options: { color: MUTED } }],
  { x: 8.1, y: 4.15, w: 2.25, h: 1.3, fontFace: BODY, fontSize: 13, align: "center", valign: "top", margin: 0, lineSpacingMultiple: 1.1 });
card(s, 10.55, 2.75, 2.35, 3.2);
s.addText("~10%", { x: 10.55, y: 3.2, w: 2.35, h: 0.9, fontFace: HEAD, fontSize: 40, bold: true, color: RED, align: "center", margin: 0 });
s.addText([{ text: "the last mile", options: { breakLine: true, bold: true, color: TEXT } }, { text: "manual — where projects stall", options: { color: MUTED } }],
  { x: 10.6, y: 4.15, w: 2.25, h: 1.3, fontFace: BODY, fontSize: 13, align: "center", valign: "top", margin: 0, lineSpacingMultiple: 1.1 });
footer(s, 2);

// ==========================================================================
// SLIDE 3 — HOW IT WORKS (loop)
// ==========================================================================
s = pres.addSlide(); base(s);
eyebrow(s, "How it works");
title(s, "An agent that closes the last 10% —\nchecked by a safety gate before every change.");

const steps = [
  ["1", "HIPIFY"], ["2", "Build"], ["3", "Parse errors"], ["4", "Diagnose (LLM)"], ["5", "Policy gate"], ["6", "Commit"],
];
const n = steps.length, gap = (11.9 - 0.62) / (n - 1);
const rowY = 3.35;
for (let i = 0; i < n - 1; i++) {
  s.addShape(pres.shapes.LINE, { x: ML + 0.62 + i * gap, y: rowY + 0.31, w: gap - 0.62, h: 0, line: { color: "3A3E48", width: 1.5 } });
}
steps.forEach((st, i) => stepCircle(s, ML + i * gap, rowY, st[0], st[1], st[1] === "Policy gate"));
// loop-back caption
s.addText("↺  rebuild — repeat until SUCCESS / PARTIAL / STUCK, always with an honest report",
  { x: ML, y: 4.75, w: 11.9, h: 0.4, fontFace: BODY, fontSize: 13, italic: true, color: MUTED, align: "center", margin: 0 });
s.addText([
  { text: "Plain Python, an explicit state machine, no agent frameworks.  ", options: { color: MUTED } },
  { text: "The policy gate is the trust boundary — everything the model proposes passes through it.", options: { color: TEXT, bold: true } },
], { x: ML, y: 5.7, w: 11.9, h: 0.7, fontFace: BODY, fontSize: 14, align: "center", valign: "top", margin: 0, lineSpacingMultiple: 1.1 });
footer(s, 3);

// ==========================================================================
// SLIDE 4 — THE DEMO
// ==========================================================================
s = pres.addSlide(); base(s);
eyebrow(s, "The demo — one command");
title(s, "docker compose up  →  a full migration climbs to SUCCESS", { size: 28 });
s.addText("no GPU · no API key · live dashboard", { x: ML, y: 1.75, w: 8, h: 0.35, fontFace: MONO, fontSize: 12.5, color: GREEN, margin: 0 });

s.addChart(pres.charts.LINE, [{
  name: "Error classes fixed", labels: ["1","2","3","4","5","6","7","8","9","10","11"],
  values: [0, 1, 2, 3, 3, 4, 5, 5, 6, 7, 7],
}], {
  x: ML, y: 2.35, w: 7.0, h: 4.25,
  chartColors: [GREEN], lineSize: 3, lineSmooth: true,
  chartArea: { fill: { color: "14161C" } }, plotArea: { fill: { color: "14161C" } },
  showTitle: true, title: "Autonomous fixes accumulate each iteration", titleColor: MUTED, titleFontFace: BODY, titleFontSize: 12,
  catAxisLabelColor: MUTED, valAxisLabelColor: MUTED, catAxisLabelFontSize: 10, valAxisLabelFontSize: 10,
  catAxisTitle: "iteration", showCatAxisTitle: true, catAxisTitleColor: MUTED, catAxisTitleFontSize: 10,
  valGridLine: { color: "23262E", size: 0.5 }, catGridLine: { style: "none" },
  valAxisMinVal: 0, valAxisMaxVal: 8, valAxisMajorUnit: 2, showLegend: false,
  lineDataSymbol: "circle", lineDataSymbolSize: 6,
});

const stats = [
  ["SUCCESS", "final outcome", GREEN],
  ["11", "iterations to green", TEXT],
  ["7 / 7", "error classes fixed autonomously", TEXT],
  ["~$0.30", "total LLM cost, at list price", TEXT],
];
let sy = 2.4;
stats.forEach(([big, lab, col]) => {
  s.addText(big, { x: 8.15, y: sy, w: 4.7, h: 0.65, fontFace: HEAD, fontSize: 33, bold: true, color: col, align: "left", margin: 0 });
  s.addText(lab, { x: 8.17, y: sy + 0.62, w: 4.7, h: 0.35, fontFace: BODY, fontSize: 12.5, color: MUTED, align: "left", margin: 0 });
  sy += 1.05;
});
s.addText("Replays a genuine recorded Fireworks run (Kimi K2.6). Every fix is a real git commit; only the GPU compile/test result is replayed from captured fixtures.",
  { x: ML, y: 6.62, w: 12.0, h: 0.4, fontFace: BODY, fontSize: 11, italic: true, color: "7B818B", align: "left", margin: 0 });
footer(s, 4);

// ==========================================================================
// SLIDE 5 — IT'S REAL
// ==========================================================================
s = pres.addSlide(); base(s);
eyebrow(s, "Not a mockup");
title(s, "Everything you see is real.");
const proof = [
  ["Real recorded run", "A genuine Fireworks Kimi K2.6 run reached SUCCESS — all 7 error classes fixed autonomously, including the correct 64-bit CDNA warp-mask."],
  ["Real git commits", "One commit per fix (bridge(iter N, error_class): …) in a scratch repo — the migration is an auditable history, not a printout."],
  ["119 tests · CI green", "Property test: no model/executor output can crash the loop. Red-team test: the policy gate rejects a live injection payload."],
  ["Runs offline", "No GPU, no API key. One command (docker compose up) reproduces the whole demo on a laptop."],
];
const cw = 5.85, ch = 1.9, cx0 = ML, cx1 = ML + cw + 0.35, cy0 = 2.55, cy1 = 2.55 + ch + 0.3;
proof.forEach((p, i) => {
  const x = i % 2 === 0 ? cx0 : cx1, y = i < 2 ? cy0 : cy1;
  card(s, x, y, cw, ch);
  s.addShape(pres.shapes.OVAL, { x: x + 0.3, y: y + 0.32, w: 0.16, h: 0.16, fill: { color: GREEN } });
  s.addText(p[0], { x: x + 0.6, y: y + 0.22, w: cw - 0.9, h: 0.4, fontFace: HEAD, fontSize: 16.5, bold: true, color: TEXT, margin: 0 });
  s.addText(p[1], { x: x + 0.6, y: y + 0.72, w: cw - 0.95, h: 1.05, fontFace: BODY, fontSize: 12.5, color: MUTED, valign: "top", margin: 0, lineSpacingMultiple: 1.1 });
});
footer(s, 5);

// ==========================================================================
// SLIDE 6 — SECURITY (differentiator)
// ==========================================================================
s = pres.addSlide(); base(s);
eyebrow(s, "The differentiator — security");
title(s, "It runs untrusted code and untrusted model output — safely.");
// trust flow
const tf = [["Untrusted repo", MUTED], ["Build / test\n(arbitrary code)", MUTED], ["LLM output\n(may be steered)", MUTED], ["POLICY GATE", RED], ["git apply\n(trusted)", GREEN]];
const tn = tf.length, tgap = (11.9) / tn, boxw = tgap - 0.35, ty = 2.7;
tf.forEach((b, i) => {
  const x = ML + i * tgap;
  card(s, x, ty, boxw, 1.15, b[1] === RED ? "2A0E14" : CARD);
  s.addText(b[0], { x: x + 0.05, y: ty, w: boxw - 0.1, h: 1.15, fontFace: HEAD, fontSize: 12.5, bold: b[1] === RED, color: b[1], align: "center", valign: "middle", margin: 0, lineSpacingMultiple: 1.0 });
  if (i < tn - 1) s.addText("→", { x: x + boxw + 0.02, y: ty, w: 0.33, h: 1.15, fontFace: HEAD, fontSize: 18, bold: true, color: "4A4E58", align: "center", valign: "middle", margin: 0 });
});
s.addText([
  { text: "The poisoned repo attacks the agent:", options: { bold: true, color: TEXT, breakLine: true } },
  { text: "its compiler output carries an injection — “add system(\"curl … | sh\"), relax the tests.” Even if the model obeys, the gate rejects the diff every time: the payload never reaches git. Pinned by an end-to-end red-team test.", options: { color: MUTED } },
], { x: ML, y: 4.25, w: 7.5, h: 1.9, fontFace: BODY, fontSize: 14, valign: "top", margin: 0, lineSpacingMultiple: 1.15 });

card(s, 8.5, 4.25, 4.4, 1.95, "14161C");
s.addText("Enforced mechanically, before apply", { x: 8.75, y: 4.45, w: 3.95, h: 0.4, fontFace: HEAD, fontSize: 13.5, bold: true, color: RED, margin: 0 });
s.addText([
  { text: "writable-path allowlist · protected paths", options: { breakLine: true } },
  { text: "denylist: shell-out, network, eval", options: { breakLine: true } },
  { text: "no editing tests · patch-size cap", options: {} },
], { x: 8.75, y: 4.9, w: 3.95, h: 1.2, fontFace: MONO, fontSize: 11.5, color: MUTED, valign: "top", margin: 0, lineSpacingMultiple: 1.25 });
s.addText("Security is mechanical — it holds even when the model is wrong.", { x: ML, y: 6.5, w: 11.9, h: 0.4, fontFace: HEAD, fontSize: 14, bold: true, italic: true, color: TEXT, align: "center", margin: 0 });
footer(s, 6);

// ==========================================================================
// SLIDE 7 — MODEL-AGNOSTIC + GEMMA
// ==========================================================================
s = pres.addSlide(); base(s);
eyebrow(s, "Model-agnostic brain · Gemma challenge");
title(s, "Swap the brain in one line.");
card(s, ML, 2.6, 11.9, 1.5, "14161C");
s.addText([
  { text: "llm.model: ", options: { color: MUTED } },
  { text: "accounts/fireworks/models/kimi-k2p6", options: { color: "8A9099" } },
  { text: "   →   ", options: { color: MUTED } },
  { text: "accounts/fireworks/models/gemma-3-27b-it", options: { color: GREEN, bold: true } },
], { x: ML + 0.3, y: 2.6, w: 11.3, h: 1.5, fontFace: MONO, fontSize: 16, valign: "middle", margin: 0 });

const gcards = [
  ["Enters the Gemma challenge", "The same agent, driven by Google's Gemma — a one-file config, no code change. Recorded as an honest model-vs-model comparison run."],
  ["Gemma, thinking on AMD", "The endpoint is just OpenAI-compatible, so Gemma can be self-hosted on the MI300X via vLLM — the brain running on AMD while it ports code to AMD."],
];
gcards.forEach((g, i) => {
  const x = ML + i * (5.9 + 0.1); const w = 5.9;
  card(s, x, 4.4, w, 1.95);
  s.addText(g[0], { x: x + 0.35, y: 4.62, w: w - 0.7, h: 0.5, fontFace: HEAD, fontSize: 16.5, bold: true, color: TEXT, margin: 0 });
  s.addText(g[1], { x: x + 0.35, y: 5.15, w: w - 0.7, h: 1.1, fontFace: BODY, fontSize: 13, color: MUTED, valign: "top", margin: 0, lineSpacingMultiple: 1.12 });
});
s.addText("The safety gate is model-independent — it doesn't care which brain is driving.", { x: ML, y: 6.55, w: 11.9, h: 0.4, fontFace: BODY, fontSize: 12.5, italic: true, color: "7B818B", align: "center", margin: 0 });
footer(s, 7);

// ==========================================================================
// SLIDE 8 — AMD STACK
// ==========================================================================
s = pres.addSlide(); base(s);
eyebrow(s, "Built for AMD");
title(s, "Aligned with the AMD stack.");
const align = [
  ["ROCm / HIP target", "The whole point: CUDA → HIP so it builds on Instinct.", true],
  ["Fireworks live brain", "The verified SUCCESS run used Fireworks (Kimi K2.6).", true],
  ["Docker demo", "One command reproduces the full migration.", true],
  ["Gemma one-line swap", "Model-agnostic; enters the Gemma challenge.", true],
  ["MI300X on AMD Dev Cloud", "Live on-hardware migration — tooling ready, runs on approval.", false],
];
let ay = 2.55; const rh = 0.82;
align.forEach((a) => {
  card(s, ML, ay, 11.9, rh);
  const mark = a[2] ? "✓" : "→";
  s.addShape(pres.shapes.OVAL, { x: ML + 0.28, y: ay + (rh - 0.44) / 2, w: 0.44, h: 0.44, fill: { color: a[2] ? "0E2A1E" : "2E2410" }, line: { color: a[2] ? GREEN : AMBER, width: 1 } });
  s.addText(mark, { x: ML + 0.28, y: ay + (rh - 0.44) / 2, w: 0.44, h: 0.44, fontFace: HEAD, fontSize: 15, bold: true, color: a[2] ? GREEN : AMBER, align: "center", valign: "middle", margin: 0 });
  s.addText(a[0], { x: ML + 0.95, y: ay, w: 4.3, h: rh, fontFace: HEAD, fontSize: 15.5, bold: true, color: TEXT, valign: "middle", margin: 0 });
  s.addText(a[1], { x: ML + 5.3, y: ay, w: 6.0, h: rh, fontFace: BODY, fontSize: 13, color: MUTED, valign: "middle", margin: 0 });
  if (!a[2]) s.addText("NEXT", { x: ML + 11.9 - 1.05, y: ay + (rh - 0.4) / 2, w: 0.85, h: 0.4, fontFace: HEAD, fontSize: 11, bold: true, color: AMBER, align: "center", valign: "middle", margin: 0 });
  ay += rh + 0.16;
});
footer(s, 8);

// ==========================================================================
// SLIDE 9 — STATUS & ROADMAP
// ==========================================================================
s = pres.addSlide(); base(s);
eyebrow(s, "Honest status");
title(s, "Shipped today vs. what's next.");
// left: shipped
card(s, ML, 2.55, 5.85, 3.95);
s.addShape(pres.shapes.OVAL, { x: ML + 0.32, y: 2.85, w: 0.18, h: 0.18, fill: { color: GREEN } });
s.addText("Verified & shipping", { x: ML + 0.62, y: 2.72, w: 5.0, h: 0.45, fontFace: HEAD, fontSize: 17, bold: true, color: GREEN, margin: 0 });
s.addText([
  "Full agent loop + policy gate",
  "Live dashboard (real diffs & cost)",
  "119 tests green · GitHub Actions CI",
  "docker compose up demo, offline",
  "Live Fireworks run → SUCCESS",
  "Public repo, MIT",
].map((t, i, a) => ({ text: t, options: { bullet: { code: "2022", indent: 16 }, breakLine: true, color: TEXT } })),
  { x: ML + 0.35, y: 3.35, w: 5.2, h: 3.0, fontFace: BODY, fontSize: 14, valign: "top", margin: 0, paraSpaceAfter: 9 });
// right: next
card(s, ML + 6.05, 2.55, 5.85, 3.95, "1A1710");
s.addShape(pres.shapes.OVAL, { x: ML + 6.37, y: 2.85, w: 0.18, h: 0.18, fill: { color: AMBER } });
s.addText("Next", { x: ML + 6.67, y: 2.72, w: 5.0, h: 0.45, fontFace: HEAD, fontSize: 17, bold: true, color: AMBER, margin: 0 });
s.addText([
  "Live migration on a real MI300X",
  "Self-hosted Gemma on AMD (vLLM)",
  "Repo-shortlist on hardware, pick demo",
  "Recorded Gemma comparison run",
].map((t) => ({ text: t, options: { bullet: { code: "2022", indent: 16 }, breakLine: true, color: TEXT } })),
  { x: ML + 6.4, y: 3.35, w: 5.2, h: 2.4, fontFace: BODY, fontSize: 14, valign: "top", margin: 0, paraSpaceAfter: 9 });
s.addText("Every hardware step has tooling written and waiting — it runs the moment the MI300X is provisioned.",
  { x: ML + 6.4, y: 5.75, w: 5.2, h: 0.6, fontFace: BODY, fontSize: 11.5, italic: true, color: MUTED, valign: "top", margin: 0, lineSpacingMultiple: 1.1 });
footer(s, 9);

// ==========================================================================
// SLIDE 10 — CLOSE
// ==========================================================================
s = pres.addSlide(); base(s);
s.addShape(pres.shapes.OVAL, { x: 9.2, y: 0.7, w: 6.2, h: 6.2, fill: { type: "none" }, line: { color: RED_DIM, width: 2.5 } });
s.addShape(pres.shapes.OVAL, { x: 10.1, y: 1.6, w: 4.4, h: 4.4, fill: { type: "none" }, line: { color: "2A2E38", width: 1.5 } });
s.addText("Bridge", { x: ML - 0.03, y: 2.2, w: 9, h: 1.3, fontFace: HEAD, fontSize: 72, bold: true, color: TEXT, margin: 0 });
s.addText([
  { text: "Moves code to AMD — and does it ", options: { color: TEXT } },
  { text: "safely", options: { color: RED, bold: true } },
  { text: ".", options: { color: TEXT } },
], { x: ML, y: 3.65, w: 9, h: 0.7, fontFace: HEAD, fontSize: 24, bold: true, margin: 0 });
s.addText([
  { text: "github.com/abidedavana/Bridge", options: { color: TEXT, bold: true, breakLine: true } },
  { text: "Abid Edavana Zakir  ·  abidedavana@gmail.com", options: { color: MUTED, breakLine: true } },
  { text: "AMD Developer Hackathon · ACT II  ·  Track 3 / Unicorn + Best Use of Gemma", options: { color: MUTED } },
], { x: ML, y: 4.7, w: 9, h: 1.4, fontFace: BODY, fontSize: 14, valign: "top", margin: 0, lineSpacingMultiple: 1.3 });
s.addText("Thank you.", { x: ML, y: 6.35, w: 6, h: 0.5, fontFace: HEAD, fontSize: 16, bold: true, color: RED, margin: 0 });
footer(s, 10);

// speaker notes (mirror the script beats)
pres.writeFile({ fileName: "C:/Users/abide/Downloads/m/pitch/bridge_pitch.pptx" }).then((f) => console.log("WROTE", f));
