"""OpenAIBackend: any OpenAI-compatible /chat/completions endpoint.

Talks to Fireworks (the guaranteed demo brain) or self-hosted vLLM on the MI300X
(the showcase) with the same code — only `base_url`/`model` change. Uses `httpx`
directly rather than the vendor SDK to avoid lock-in and keep the dependency
surface small (see DECISIONS.md). Imported lazily so the core stays importable
without the `[llm]` extra.
"""

from __future__ import annotations

import time
from typing import Optional

from .base import LLMBackend, LLMResponse, LLMTransportError, Message


class OpenAIBackend(LLMBackend):
    def __init__(
        self,
        base_url: str,
        model: str,
        api_key: str,
        *,
        temperature: float = 0.0,
        max_tokens: int = 4096,
        timeout: float = 120.0,
    ):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_key = api_key
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.timeout = timeout
        self._client = None

    def _http(self):
        if self._client is None:
            import httpx

            self._client = httpx.Client(timeout=self.timeout)
        return self._client

    def complete(self, messages, *, temperature=None, max_tokens=None) -> LLMResponse:
        import httpx

        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature if temperature is None else temperature,
            "max_tokens": self.max_tokens if max_tokens is None else max_tokens,
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        # Transient network faults (read timeouts, dropped connections, 5xx)
        # are retried with backoff before giving up: a single blip on a long
        # thinking-model request must not kill a whole migration run.
        last_exc: Exception | None = None
        for attempt in range(3):
            try:
                resp = self._http().post(
                    f"{self.base_url}/chat/completions", json=payload, headers=headers
                )
                resp.raise_for_status()
                break
            except httpx.HTTPStatusError as exc:
                last_exc = exc
                if exc.response.status_code >= 500 and attempt < 2:
                    time.sleep(2.0 * (attempt + 1))
                    continue
                raise LLMTransportError(f"{type(exc).__name__}: {exc}") from exc
            except httpx.HTTPError as exc:  # timeouts, transport failures
                last_exc = exc
                if attempt < 2:
                    time.sleep(2.0 * (attempt + 1))
                    continue
                raise LLMTransportError(f"{type(exc).__name__}: {exc}") from exc
        else:  # pragma: no cover - loop always breaks or raises
            raise LLMTransportError(str(last_exc))

        data = resp.json()
        try:
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMTransportError(f"unexpected response shape: {exc}") from exc
        usage = data.get("usage") or {}
        return LLMResponse(
            text=content or "",
            prompt_tokens=usage.get("prompt_tokens", 0),
            completion_tokens=usage.get("completion_tokens", 0),
            model=data.get("model", self.model),
            raw=data,
        )

    def close(self) -> None:
        if self._client is not None:
            self._client.close()
            self._client = None
