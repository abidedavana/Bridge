"""RunRecorder writes an atomic, valid, accumulating run-state file."""

from __future__ import annotations

import json

from bridge.run_state import IterationRecord, RunRecorder, RunState, load_state


def test_recorder_accumulates_and_persists(tmp_path):
    p = tmp_path / "runs" / "current.json"
    st = RunState(
        run_id="r1", scenario="success", executor="mock",
        llm_backend="openai", llm_model="llama", llm_host="api.fireworks.ai",
        cost_mode="priced", cost_currency="USD", simulated_cost=True,
    )
    rec = RunRecorder(str(p), st)
    assert p.exists()  # flushed on construction (dashboard can read immediately)

    rec.set_hipify(84, 7)
    rec.add(IterationRecord(
        iteration=1, phase="build", outcome="fail",
        error_class="cmake_cuda_language", location="CMakeLists.txt:3",
        error_classes=["cmake_cuda_language"],
        prompt_tokens=100, completion_tokens=20, cost=0.001,
    ))
    rec.add(IterationRecord(
        iteration=2, phase="test", outcome="fail",
        error_class="warp_size_assumption", passed=3, total=5,
        prompt_tokens=200, completion_tokens=40, cost=0.002,
    ))
    rec.finish("PARTIAL")

    data = load_state(str(p))
    assert data["status"] == "PARTIAL"
    assert data["hipify_conversion_pct"] == 84 and data["hipify_warnings"] == 7
    assert data["total_prompt_tokens"] == 300
    assert data["total_completion_tokens"] == 60
    assert data["total_cost"] == 0.003
    assert data["current"]["iteration"] == 2
    assert [it["error_class"] for it in data["iterations"]] == [
        "cmake_cuda_language", "warp_size_assumption"
    ]


def test_output_is_valid_json(tmp_path):
    p = tmp_path / "s.json"
    RunRecorder(str(p), RunState(run_id="r", scenario="s", executor="mock"))
    json.loads(p.read_text(encoding="utf-8"))  # must parse


def test_load_state_none_when_absent(tmp_path):
    assert load_state(str(tmp_path / "nope.json")) is None
