# tests/unit/test_llm_structured.py

"""
Unit tests for :func:`complete_structured`.

We do not import ``instructor`` directly in tests — instead we inject
a stub Instructor-shaped client (``client.chat.completions
.create_with_completion``) and assert the helper:

1. Returns ``(pydantic_model, LLMResponse)``.
2. Surfaces the raw provider completion verbatim in
   :attr:`LLMResponse.raw_response`.
3. Forwards ``max_retries`` through to Instructor unchanged.
4. Raises :class:`InstructorNotInstalledError` cleanly when no
   client is supplied and the SDK is unavailable.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest
from pydantic import BaseModel

from slop_research_factory.llm.structured import (
    InstructorNotInstalledError,
    _build_default_client_for_model,
    complete_structured,
)

# ── Sample Pydantic response model ─────────────────────


class _SampleModel(BaseModel):
    answer: str
    confidence: float


# ── Stub Instructor client ─────────────────────────────


@dataclass
class _StubCompletions:
    parsed: BaseModel
    raw: dict[str, Any]
    captured: list[dict[str, Any]] = field(default_factory=list)

    async def create_with_completion(
        self,
        *,
        model: str,
        messages: list[dict[str, Any]],
        response_model: type,
        max_retries: int,
        **kwargs: Any,
    ) -> tuple[BaseModel, dict[str, Any]]:
        self.captured.append(
            {
                "model": model,
                "messages": messages,
                "response_model": response_model.__name__,
                "max_retries": max_retries,
                **kwargs,
            }
        )
        return self.parsed, self.raw


@dataclass
class _StubChat:
    completions: _StubCompletions


@dataclass
class _StubInstructorClient:
    chat: _StubChat


def _build_stub_client(
    parsed: BaseModel,
    raw: dict[str, Any] | None = None,
) -> _StubInstructorClient:
    completions = _StubCompletions(
        parsed=parsed,
        raw=raw
        or {
            "id": "resp-stub",
            "model": "test/model",
            "choices": [
                {"message": {"content": '{"answer": "yes", "confidence": 0.9}'}},
            ],
            "usage": {
                "prompt_tokens": 12,
                "completion_tokens": 34,
            },
        },
    )
    return _StubInstructorClient(chat=_StubChat(completions=completions))


# ── Tests ──────────────────────────────────────────────


class TestCompleteStructured:
    @pytest.mark.asyncio
    async def test_returns_parsed_and_llm_response(self) -> None:
        parsed_model = _SampleModel(answer="yes", confidence=0.9)
        client = _build_stub_client(parsed_model)
        parsed, raw = await complete_structured(
            model="google/gemini-2.5-flash",
            messages=[{"role": "user", "content": "?"}],
            response_model=_SampleModel,
            instructor_client=client,
        )
        assert isinstance(parsed, _SampleModel)
        assert parsed.answer == "yes"
        assert raw.input_tokens == 12
        assert raw.output_tokens == 34
        assert raw.api_response_id == "resp-stub"
        assert raw.api_provider == "google"
        assert raw.raw_response["id"] == "resp-stub"

    @pytest.mark.asyncio
    async def test_max_retries_propagates(self) -> None:
        client = _build_stub_client(_SampleModel(answer="x", confidence=0.5))
        await complete_structured(
            model="m",
            messages=[],
            response_model=_SampleModel,
            max_retries=4,
            instructor_client=client,
        )
        assert client.chat.completions.captured[0]["max_retries"] == 4

    @pytest.mark.asyncio
    async def test_sampling_params_forwarded(self) -> None:
        client = _build_stub_client(_SampleModel(answer="x", confidence=0.5))
        await complete_structured(
            model="m",
            messages=[],
            response_model=_SampleModel,
            sampling_params={"temperature": 0.0, "top_p": 0.95},
            instructor_client=client,
        )
        captured = client.chat.completions.captured[0]
        assert captured["temperature"] == 0.0
        assert captured["top_p"] == 0.95

    @pytest.mark.asyncio
    async def test_raw_dict_round_trips_for_sealing(self) -> None:
        """raw_response must be a JSON-serialisable dict."""
        import json

        client = _build_stub_client(
            _SampleModel(answer="y", confidence=0.7),
            raw={
                "id": "abc",
                "model": "m",
                "choices": [],
                "usage": {"prompt_tokens": 1, "completion_tokens": 2},
            },
        )
        _, raw_resp = await complete_structured(
            model="m",
            messages=[],
            response_model=_SampleModel,
            instructor_client=client,
        )
        # Round trip via JSON — guarantees the seal layer can serialise it.
        json.dumps(raw_resp.raw_response)


class TestOpenRouterInstructorMode:
    """OpenRouter + Instructor default ``TOOLS`` mode triggers provider 404."""

    def test_openrouter_selects_structured_outputs_mode(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        import instructor

        captured: dict[str, Any] = {}

        def fake_from_litellm(_acompletion: Any, mode: Any = None, **_kw: Any) -> Any:
            captured["mode"] = mode

            class _Dummy:
                chat = object()

            return _Dummy()

        monkeypatch.setattr(instructor, "from_litellm", fake_from_litellm)

        _build_default_client_for_model("openrouter/nemotron")
        assert captured["mode"] == instructor.Mode.OPENROUTER_STRUCTURED_OUTPUTS

    def test_non_openrouter_keeps_default_tools_mode(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        import instructor

        captured: dict[str, Any] = {}

        def fake_from_litellm(_acompletion: Any, mode: Any = None, **_kw: Any) -> Any:
            captured["mode"] = mode

            class _Dummy:
                chat = object()

            return _Dummy()

        monkeypatch.setattr(instructor, "from_litellm", fake_from_litellm)

        _build_default_client_for_model("google/gemini-2.5-flash")
        assert captured["mode"] == instructor.Mode.TOOLS


class TestStructuredOpenRouterFallback:
    @pytest.mark.asyncio
    async def test_retries_with_openrouter_model_and_rebuilt_client(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from litellm.exceptions import BadRequestError

        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")
        parsed_ok = _SampleModel(answer="ok", confidence=1.0)
        raw_ok = {
            "id": "r2",
            "model": "openrouter/google/gemma:x",
            "choices": [{"message": {"content": "{}"}}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 2},
        }

        builds: list[str] = []

        def fake_build(m: str) -> _StubInstructorClient:
            builds.append(m)
            built_for = m

            class Completions:
                async def create_with_completion(
                    self,
                    *,
                    model: str,
                    messages: list[dict[str, Any]],
                    response_model: type,
                    max_retries: int,
                    **kwargs: Any,
                ) -> tuple[BaseModel, dict[str, Any]]:
                    assert model == built_for
                    if not built_for.startswith("openrouter/"):
                        raise BadRequestError(
                            "LLM Provider NOT provided",
                            model=model,
                            llm_provider="",
                        )
                    return parsed_ok, raw_ok

            return _StubInstructorClient(chat=_StubChat(completions=Completions()))

        monkeypatch.setattr(
            "slop_research_factory.llm.structured._build_default_client_for_model",
            fake_build,
        )

        parsed, raw = await complete_structured(
            model="google/gemma:x",
            messages=[{"role": "user", "content": "?"}],
            response_model=_SampleModel,
        )
        assert builds == ["google/gemma:x", "openrouter/google/gemma:x"]
        assert parsed.answer == "ok"
        assert raw.api_provider == "openrouter"


class TestImportFallback:
    @pytest.mark.asyncio
    async def test_missing_instructor_raises_typed_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Force the lazy import to fail.
        import builtins

        original_import = builtins.__import__

        def fake_import(name: str, *a: Any, **kw: Any) -> Any:
            if name == "instructor":
                raise ImportError("not installed")
            return original_import(name, *a, **kw)

        monkeypatch.setattr(builtins, "__import__", fake_import)
        with pytest.raises(InstructorNotInstalledError):
            await complete_structured(
                model="m",
                messages=[],
                response_model=_SampleModel,
            )
