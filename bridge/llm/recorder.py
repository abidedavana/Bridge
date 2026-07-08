"""RecordingBackend: wrap a live backend and capture every exchange to a cassette.

This is how the M6 deterministic e2e test gets its authentic base (Q4: record a
real Fireworks run, then hand-curate for SUCCESS/PARTIAL/STUCK coverage). The
cassette it writes is exactly what `ReplayBackend` consumes. Flushed after every
call so a crashed run still leaves a usable partial recording.
"""

from __future__ import annotations

import json
import os

from .base import LLMBackend, LLMResponse, Message


class RecordingBackend(LLMBackend):
    def __init__(self, inner: LLMBackend, cassette_path: str):
        self.inner = inner
        self.path = os.path.abspath(cassette_path)
        self.entries: list[dict] = []

    def complete(self, messages, *, temperature=None, max_tokens=None) -> LLMResponse:
        r = self.inner.complete(messages, temperature=temperature, max_tokens=max_tokens)
        self.entries.append(
            {
                "messages": messages,
                "response": {
                    "text": r.text,
                    "prompt_tokens": r.prompt_tokens,
                    "completion_tokens": r.completion_tokens,
                    "model": r.model,
                },
            }
        )
        self._flush()
        return r

    def _flush(self) -> None:
        os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(self.entries, fh, indent=2)
        os.replace(tmp, self.path)

    def close(self) -> None:
        self.inner.close()
