"""LLM layer: swappable brain + messy-output hardening.

    create_backend(cfg, record_path=None) -> LLMBackend
    LLMBackend, LLMResponse, LLMTransportError
    OpenAIBackend, ReplayBackend, RecordingBackend
    extract_diagnosis, extract_diff, ExtractionError, NoPatchProposed
"""

from __future__ import annotations

import os
from typing import Optional

from .base import LLMBackend, LLMResponse, LLMTransportError, Message
from .extract import (
    ExtractionError,
    NoPatchProposed,
    extract_diagnosis,
    extract_diff,
    extract_json,
    validate_diagnosis,
)
from .openai_client import OpenAIBackend
from .recorder import RecordingBackend
from .replay import ReplayBackend

__all__ = [
    "create_backend",
    "LLMBackend",
    "LLMResponse",
    "LLMTransportError",
    "OpenAIBackend",
    "ReplayBackend",
    "RecordingBackend",
    "extract_diagnosis",
    "extract_diff",
    "extract_json",
    "validate_diagnosis",
    "ExtractionError",
    "NoPatchProposed",
]


def create_backend(config, record_path: Optional[str] = None) -> LLMBackend:
    """Build the LLM backend selected by config; optionally record every exchange.

    `record_path` set (e.g. during a live run) wraps the backend so the run is
    captured to a cassette for later replay.
    """
    llm = config.llm
    if llm.backend == "replay":
        if llm.replay is None:
            raise ValueError("llm.backend is 'replay' but llm.replay is unset")
        backend: LLMBackend = ReplayBackend(llm.replay.cassette, strict=llm.replay.strict)
    else:
        api_key = os.environ.get(llm.api_key_env, "")
        backend = OpenAIBackend(
            llm.base_url,
            llm.model,
            api_key,
            temperature=llm.temperature,
            max_tokens=llm.max_tokens,
            timeout=llm.request_timeout_s,
        )
    if record_path:
        backend = RecordingBackend(backend, record_path)
    return backend
