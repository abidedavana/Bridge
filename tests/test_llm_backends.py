"""Replay + recording backends round-trip; replay is deterministic and offline."""

from __future__ import annotations

import json

import pytest

from bridge.llm.base import LLMBackend, LLMResponse
from bridge.llm.recorder import RecordingBackend
from bridge.llm.replay import ReplayBackend


def _cassette(tmp_path, entries):
    p = tmp_path / "cas.json"
    p.write_text(json.dumps(entries), encoding="utf-8")
    return str(p)


def test_replay_returns_responses_in_order(tmp_path):
    path = _cassette(tmp_path, [
        {"response": {"text": "one", "prompt_tokens": 10, "completion_tokens": 2}},
        {"response": {"text": "two", "prompt_tokens": 20, "completion_tokens": 4}},
    ])
    b = ReplayBackend(path)
    r1 = b.complete([{"role": "user", "content": "a"}])
    r2 = b.complete([{"role": "user", "content": "b"}])
    assert (r1.text, r1.prompt_tokens) == ("one", 10)
    assert (r2.text, r2.completion_tokens) == ("two", 4)


def test_replay_strict_raises_when_exhausted(tmp_path):
    b = ReplayBackend(_cassette(tmp_path, [{"response": {"text": "x"}}]), strict=True)
    b.complete([])
    with pytest.raises(IndexError):
        b.complete([])


class _Fake(LLMBackend):
    def complete(self, messages, *, temperature=None, max_tokens=None):
        return LLMResponse(text="fixed diff", prompt_tokens=7, completion_tokens=3, model="fake")


def test_openai_backend_retries_transient_timeouts(monkeypatch):
    """A single read-timeout on a long thinking-model request must not kill the
    run (live run 6 died this way). The client retries with backoff."""
    httpx = pytest.importorskip("httpx")
    from bridge.llm.openai_client import OpenAIBackend

    monkeypatch.setattr("bridge.llm.openai_client.time.sleep", lambda s: None)

    class FakeResp:
        def raise_for_status(self):
            pass

        def json(self):
            return {
                "choices": [{"message": {"content": "ok"}}],
                "usage": {"prompt_tokens": 5, "completion_tokens": 2},
                "model": "m",
            }

    class FlakyClient:
        calls = 0

        def post(self, *a, **kw):
            FlakyClient.calls += 1
            if FlakyClient.calls < 3:
                raise httpx.ReadTimeout("timed out")
            return FakeResp()

    b = OpenAIBackend("https://x/v1", "m", "key")
    b._client = FlakyClient()
    r = b.complete([{"role": "user", "content": "hi"}])
    assert r.text == "ok" and FlakyClient.calls == 3  # two timeouts survived


def test_openai_backend_gives_up_after_retries(monkeypatch):
    httpx = pytest.importorskip("httpx")
    from bridge.llm.base import LLMTransportError
    from bridge.llm.openai_client import OpenAIBackend

    monkeypatch.setattr("bridge.llm.openai_client.time.sleep", lambda s: None)

    class DeadClient:
        def post(self, *a, **kw):
            raise httpx.ConnectError("network unreachable")

    b = OpenAIBackend("https://x/v1", "m", "key")
    b._client = DeadClient()
    with pytest.raises(LLMTransportError):
        b.complete([{"role": "user", "content": "hi"}])



def test_recorder_writes_replayable_cassette(tmp_path):
    path = str(tmp_path / "rec.json")
    rec = RecordingBackend(_Fake(), path)
    rec.complete([{"role": "user", "content": "hello"}])
    rec.complete([{"role": "user", "content": "world"}])
    # the recording is exactly what ReplayBackend consumes
    replay = ReplayBackend(path)
    assert replay.complete([]).text == "fixed diff"
    data = json.loads(open(path).read())
    assert len(data) == 2 and data[0]["messages"][0]["content"] == "hello"
    assert data[0]["response"]["prompt_tokens"] == 7
