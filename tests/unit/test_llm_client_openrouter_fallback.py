# tests/unit/test_llm_client_openrouter_fallback.py

"""LiteLLMClient OpenRouter routing when LiteLLM cannot infer a provider."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from litellm.exceptions import BadRequestError

from slop_research_factory.llm.client import LiteLLMClient


def _fake_completion_payload(model: str) -> dict:
    return {
        "id": "ok",
        "model": model,
        "choices": [{"message": {"content": "done"}}],
        "usage": {"prompt_tokens": 1, "completion_tokens": 2},
    }


class TestLiteLLMOpenRouterFallback:
    @pytest.mark.asyncio
    async def test_retries_with_openrouter_prefix_when_provider_unknown(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test")
        models_seen: list[str] = []

        async def fake_acompletion(*, model: str, messages: list, **kw: object) -> dict:
            models_seen.append(model)
            if model == "inclusionai/ring:x":
                raise BadRequestError(
                    "LLM Provider NOT provided",
                    model=model,
                    llm_provider="",
                )
            return _fake_completion_payload(model)

        fake_litellm = SimpleNamespace(acompletion=fake_acompletion)
        monkeypatch.setattr(
            "slop_research_factory.llm.client._import_litellm",
            lambda: fake_litellm,
        )

        client = LiteLLMClient()
        resp = await client.complete(
            model="inclusionai/ring:x",
            messages=[{"role": "user", "content": "hi"}],
        )

        assert models_seen == ["inclusionai/ring:x", "openrouter/inclusionai/ring:x"]
        assert resp.content == "done"

    @pytest.mark.asyncio
    async def test_no_retry_when_already_openrouter_prefixed(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test")
        models_seen: list[str] = []

        async def fake_acompletion(*, model: str, messages: list, **kw: object) -> dict:
            models_seen.append(model)
            if model.startswith("openrouter/"):
                raise BadRequestError(
                    "LLM Provider NOT provided",
                    model=model,
                    llm_provider="",
                )
            return _fake_completion_payload(model)

        monkeypatch.setattr(
            "slop_research_factory.llm.client._import_litellm",
            lambda: SimpleNamespace(acompletion=fake_acompletion),
        )

        client = LiteLLMClient()
        with pytest.raises(BadRequestError):
            await client.complete(
                model="openrouter/inclusionai/ring:x",
                messages=[],
            )
        assert models_seen == ["openrouter/inclusionai/ring:x"]

    @pytest.mark.asyncio
    async def test_no_retry_without_openrouter_api_key(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)

        async def fake_acompletion(*, model: str, **kw: object) -> dict:
            raise BadRequestError(
                "LLM Provider NOT provided",
                model=model,
                llm_provider="",
            )

        monkeypatch.setattr(
            "slop_research_factory.llm.client._import_litellm",
            lambda: SimpleNamespace(acompletion=fake_acompletion),
        )

        client = LiteLLMClient()
        with pytest.raises(BadRequestError):
            await client.complete(model="vendor/model", messages=[])

    @pytest.mark.asyncio
    async def test_no_retry_on_unrelated_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test")

        async def fake_acompletion(**kw: object) -> dict:
            raise RuntimeError("something else")

        monkeypatch.setattr(
            "slop_research_factory.llm.client._import_litellm",
            lambda: SimpleNamespace(acompletion=fake_acompletion),
        )

        client = LiteLLMClient()
        with pytest.raises(RuntimeError, match="something else"):
            await client.complete(model="vendor/model", messages=[])
