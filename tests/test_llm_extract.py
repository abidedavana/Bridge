"""Messy-output hardening: fences, preamble, schema, malformed rejection.

These pin the exact behaviours the M3 spec demands against deliberately messy
model output — the kind a real model actually returns.
"""

from __future__ import annotations

import pytest

from bridge.llm.extract import (
    ExtractionError,
    NoPatchProposed,
    extract_diagnosis,
    extract_diff,
    extract_json,
)

GOOD_DIAG = (
    '{"error_class":"missing_cuda_header","root_cause":"cublas header not mapped",'
    '"files_to_touch":["src/gemm.hpp"],"confidence":0.9}'
)


def test_json_inside_fenced_block_with_preamble_and_trailer():
    msg = f"Sure, here is my diagnosis:\n```json\n{GOOD_DIAG}\n```\nHope that helps!"
    obj = extract_diagnosis(msg)
    assert obj["error_class"] == "missing_cuda_header"
    assert obj["files_to_touch"] == ["src/gemm.hpp"]


def test_json_with_preamble_no_fence():
    obj = extract_diagnosis(f"Diagnosis: {GOOD_DIAG} — done.")
    assert obj["error_class"] == "missing_cuda_header"


def test_nested_braces_in_json_are_handled():
    msg = '```json\n{"error_class":"x","root_cause":"a {b} c","files_to_touch":["f"]}\n```'
    obj = extract_json(msg)
    assert obj["root_cause"] == "a {b} c"


def test_malformed_json_raises_with_reason():
    with pytest.raises(ExtractionError) as e:
        extract_diagnosis('```json\n{"error_class": "x", oops}\n```')
    assert e.value.reason


def test_missing_required_field_raises():
    with pytest.raises(ExtractionError) as e:
        extract_diagnosis('{"error_class":"x","root_cause":"y"}')  # no files_to_touch
    assert "files_to_touch" in e.value.reason


def test_empty_files_to_touch_rejected():
    with pytest.raises(ExtractionError):
        extract_diagnosis('{"error_class":"x","root_cause":"y","files_to_touch":[]}')


def test_no_json_at_all_raises():
    with pytest.raises(ExtractionError):
        extract_diagnosis("I could not determine the cause, sorry.")


DIFF = (
    "--- a/src/gemm.hpp\n"
    "+++ b/src/gemm.hpp\n"
    "@@ -1,3 +1,3 @@\n"
    "-#include <cublas_v2.h>\n"
    "+#include <hipblas/hipblas.h>\n"
    " // rest\n"
)


def test_diff_in_fence_with_preamble():
    msg = f"Here's the minimal fix:\n```diff\n{DIFF}```\nLet me know."
    out = extract_diff(msg)
    assert out.startswith("--- a/src/gemm.hpp")
    assert "+#include <hipblas/hipblas.h>" in out


def test_diff_raw_with_preamble():
    out = extract_diff("The patch:\n" + DIFF)
    assert out.startswith("--- a/src/gemm.hpp")


def test_diff_git_header_form():
    body = "diff --git a/x b/x\n" + DIFF
    out = extract_diff("prose\n" + body)
    assert out.startswith("diff --git a/x b/x")


def test_no_patch_sentinel_raises_nopatch():
    with pytest.raises(NoPatchProposed):
        extract_diff("NO_PATCH")


def test_prose_only_diff_raises():
    with pytest.raises(ExtractionError):
        extract_diff("I think you should change the header, but I won't write it.")
