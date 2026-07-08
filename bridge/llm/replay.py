"""ReplayBackend: return recorded LLM responses by call order.

Deterministic and offline — the CI/dev brain. A cassette is a JSON list of
`{"messages": [...], "response": {"text", "prompt_tokens", "completion_tokens",
"model"}}` entries, produced by `RecordingBackend` wrapping a live run (Q4:
record real, then curate). Replay is by index: the Nth `complete()` returns the
Nth recorded response.
"""

from __future__ import annotations

import json

from .base import LLMBackend, LLMResponse, Message


class ReplayBackend(LLMBackend):
    def __init__(self, cassette_path: str, strict: bool = True):
        with open(cassette_path, "r", encoding="utf-8") as fh:
            self.entries = json.load(fh)
        if not isinstance(self.entries, list):
            raise ValueError(f"cassette {cassette_path}: top level must be a list")
        self.strict = strict
        self.i = 0

    def complete(self, messages, *, temperature=None, max_tokens=None) -> LLMResponse:
        if self.i >= len(self.entries):
            if self.strict:
                raise IndexError(
                    f"replay cassette exhausted after {len(self.entries)} calls"
                )
            entry = self.entries[-1]
        else:
            entry = self.entries[self.i]
        self.i += 1
        r = entry.get("response", entry)
        return LLMResponse(
            text=r["text"],
            prompt_tokens=r.get("prompt_tokens", 0),
            completion_tokens=r.get("completion_tokens", 0),
            model=r.get("model", "replay"),
        )
