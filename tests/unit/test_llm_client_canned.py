# tests/unit/test_llm_client_canned.py

"""
Unit tests for :class:`CannedLLMClient` and :class:`LLMResponse`.

The canned client is the lightest possible test seam for nodes —
nothing imports ``litellm`` here, so this module also doubles as a
sanity check that ``llm/client.py`` is importable in slim
environments.
"""

from __future__ import annotations

import pytest

from slop_research_factory.llm.client import (
    CannedLLMClient,
    LLMClient,
    LLMResponse,
)


def _resp(content: str, **overrides) -> LLMResponse:
    """Quick :class:`LLMResponse` builder for tests."""
    base = {
        "content": content,
        "raw_response": {"id": "r-001", "model": "test/model", "choices": []},
        "input_tokens": 10,
        "output_tokens": 20,
        "think_tokens": None,
        "model": "test/model",
        "api_response_id": "r-001",
        "api_provider": "test",
        "retries": 0,
        "sampling_params": {},
    }
    base.update(overrides)
    return LLMResponse(**base)


# ── Protocol conformance ───────────────────────────────


def test_canned_client_satisfies_llm_client_protocol() -> None:
    assert isinstance(CannedLLMClient(), LLMClient)


# ── Replay semantics ───────────────────────────────────


class TestCannedClientReplay:
    @pytest.mark.asyncio
    async def test_replays_in_fifo_order(self) -> None:
        client = CannedLLMClient([_resp("first"), _resp("second")])
        a = await client.complete(model="m", messages=[])
        b = await client.complete(model="m", messages=[])
        assert (a.content, b.content) == ("first", "second")

    @pytest.mark.asyncio
    async def test_exhaustion_raises_runtime_error(self) -> None:
        client = CannedLLMClient([_resp("only")])
        await client.complete(model="m", messages=[])
        with pytest.raises(RuntimeError, match="exhausted"):
            await client.complete(model="m", messages=[])

    @pytest.mark.asyncio
    async def test_records_call_args_in_order(self) -> None:
        client = CannedLLMClient([_resp("one"), _resp("two")])
        await client.complete(
            model="m1",
            messages=[{"role": "user", "content": "hi"}],
            temperature=0.0,
        )
        await client.complete(
            model="m2",
            messages=[{"role": "user", "content": "yo"}],
            top_p=0.95,
        )
        assert client.calls[0]["model"] == "m1"
        assert client.calls[0]["temperature"] == 0.0
        assert client.calls[1]["model"] == "m2"
        assert client.calls[1]["top_p"] == 0.95

    def test_queue_appends_response(self) -> None:
        client = CannedLLMClient()
        assert client.remaining == 0
        client.queue(_resp("late"))
        assert client.remaining == 1


# ── LLMResponse immutability + defaults ────────────────


class TestLLMResponseShape:
    def test_frozen(self) -> None:
        from dataclasses import FrozenInstanceError

        r = _resp("x")
        with pytest.raises(FrozenInstanceError):
            r.content = "mutated"  # type: ignore[misc]

    def test_default_sampling_params_is_independent(self) -> None:
        a = _resp("a", sampling_params={})
        b = _resp("b", sampling_params={})
        # Even though both used `{}`, the dataclass field uses
        # default_factory; so mutating one must not affect the other.
        a.sampling_params["temperature"] = 0.0
        assert "temperature" not in b.sampling_params
