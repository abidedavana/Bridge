"""Harden against messy real-model output.

Real models wrap answers in ```json fences, add "Here's the fix:" preamble, or
trail explanation after the payload. This module extracts the *structured* part —
a JSON object or a unified diff — from that noise, and validates it. Every failure
carries a `.reason` string that the orchestrator feeds back into a single
re-request ("your last reply was not valid JSON because …").

Kept separate and pure (no I/O) so the exact behaviours the spec demands — fence
stripping, preamble tolerance, schema validation, malformed rejection — are unit
tested against deliberately messy fixtures.
"""

from __future__ import annotations

import json
import re
from typing import Optional

# Diagnosis JSON must carry at least these, with these types.
_REQUIRED = {"error_class": str, "root_cause": str, "files_to_touch": list}

_FENCE_BLOCK = re.compile(r"```[^\n]*\n(.*?)```", re.DOTALL)
_DIFF_START = re.compile(r"^(diff --git |--- )", re.MULTILINE)
# Thinking models (Gemma 4 via the OpenAI-compat layer) interleave
# <thought>...</thought> spans in the content; strip them before extraction,
# the same way fences and preamble are tolerated. An unclosed <thought>
# (output-budget truncation) removes everything from the tag onward.
_THOUGHT_SPAN = re.compile(r"<thought>.*?</thought>", re.DOTALL)
_THOUGHT_OPEN = re.compile(r"<thought>.*\Z", re.DOTALL)
NO_PATCH = "NO_PATCH"


def strip_thoughts(text: str) -> str:
    """Remove closed <thought> spans, then any unclosed trailing one."""
    return _THOUGHT_OPEN.sub("", _THOUGHT_SPAN.sub("", text))


class ExtractionError(ValueError):
    """Raised when structured content can't be recovered. `.reason` is fed back to
    the model on the single allowed retry."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


class NoPatchProposed(Exception):
    """The model explicitly declined to patch (returned the NO_PATCH sentinel)."""


def unfence(text: str) -> str:
    """Return the contents of the first ```...``` block, else the text unchanged."""
    m = _FENCE_BLOCK.search(text)
    return m.group(1) if m else text


def _first_json_object(s: str) -> Optional[str]:
    """The first balanced {...} in s, respecting strings/escapes. None if absent."""
    start = s.find("{")
    if start < 0:
        return None
    depth, in_str, esc = 0, False, False
    for i in range(start, len(s)):
        c = s[i]
        if in_str:
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == '"':
                in_str = False
        elif c == '"':
            in_str = True
        elif c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return s[start : i + 1]
    return None


def extract_json(text: str) -> dict:
    """Recover a JSON object from fenced/preambled/trailing-text model output."""
    if not text or not text.strip():
        raise ExtractionError("empty response")
    text = strip_thoughts(text)
    if not text.strip():
        raise ExtractionError("response contained only <thought> text, no payload")
    candidate = _first_json_object(unfence(text)) or _first_json_object(text)
    if candidate is None:
        raise ExtractionError("no JSON object found in response")
    try:
        obj = json.loads(candidate)
    except json.JSONDecodeError as exc:
        raise ExtractionError(f"invalid JSON: {exc.msg}") from exc
    if not isinstance(obj, dict):
        raise ExtractionError("top-level JSON is not an object")
    return obj


def validate_diagnosis(obj: dict) -> dict:
    """Schema-check a diagnosis object; raise ExtractionError with a usable reason."""
    for key, typ in _REQUIRED.items():
        if key not in obj:
            raise ExtractionError(f"missing required field '{key}'")
        if not isinstance(obj[key], typ):
            raise ExtractionError(f"field '{key}' must be {typ.__name__}")
    if not obj["files_to_touch"]:
        raise ExtractionError("files_to_touch is empty")
    return obj


def extract_diagnosis(text: str) -> dict:
    return validate_diagnosis(extract_json(text))


def extract_diff(text: str) -> str:
    """Recover a unified diff from model output, or signal NO_PATCH.

    Tolerates ```diff fences and preamble/postamble prose. Raises ExtractionError
    if no diff markers are present, NoPatchProposed on the explicit sentinel.
    """
    if not text or not text.strip():
        raise ExtractionError("empty response")
    text = strip_thoughts(text)
    if not text.strip():
        raise ExtractionError("response contained only <thought> text, no payload")
    if text.strip() == NO_PATCH or text.strip().splitlines()[0].strip() == NO_PATCH:
        raise NoPatchProposed()
    body = unfence(text)
    m = _DIFF_START.search(body)
    if m is None:
        # maybe the fence hid it or diff is in raw text
        m = _DIFF_START.search(text)
        if m is None:
            raise ExtractionError("no unified diff (expected 'diff --git' or '--- ')")
        body = text
    diff = body[m.start():].rstrip() + "\n"
    if "+++ " not in diff and "diff --git" not in diff:
        raise ExtractionError("diff has no '+++' target header")
    return diff
