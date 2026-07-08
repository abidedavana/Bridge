"""The LLM backend interface: one method, two implementations.

`OpenAIBackend` talks to any OpenAI-compatible endpoint (Fireworks, or self-hosted
vLLM on the MI300X). `ReplayBackend` returns recorded responses for deterministic,
zero-cost, offline development and CI. The orchestrator only sees this interface,
so flipping between "think for real on Fireworks" and "replay a recorded run" is a
config change, never a code change.

`usage` carries real token counts (the dashboard's token/cost counter). A backend
never raises for a *model* problem (a bad answer is data the agent handles); it
raises only for a *transport* problem (network down, auth failed).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class LLMResponse:
    text: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    model: str = ""
    # The raw provider payload, kept so a live run can be recorded to a cassette.
    raw: Optional[dict] = None


Message = dict  # {"role": "system"|"user"|"assistant", "content": str}


class LLMBackend(ABC):
    @abstractmethod
    def complete(
        self,
        messages: list[Message],
        *,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> LLMResponse:
        """Return the model's completion. Raises only on transport failure."""

    def close(self) -> None:  # pragma: no cover - trivial default
        pass


class LLMTransportError(RuntimeError):
    """Network/auth/HTTP failure talking to the endpoint (not a model problem)."""
