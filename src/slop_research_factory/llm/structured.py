# src/slop_research_factory/llm/structured.py

"""
Instructor / Pydantic structured-output wrapper.

The Verifier requires a strictly-typed Pydantic response
model — :class:`~slop_research_factory.types.verifier_output.VerifierOutput`.
Instructor patches LiteLLM to coerce raw model output into a Pydantic
instance, retrying when the parser fails validation. Models routed via
``openrouter/…`` use :data:`instructor.Mode.OPENROUTER_STRUCTURED_OUTPUTS`
(OpenRouter returns HTTP 404 for unconstrained ``tool_choice`` on many models).

This module exposes a single async helper:

.. code-block:: python

    parsed, raw_response = await complete_structured(
        model="google/gemini-2.5-flash",
        messages=[...],
        response_model=VerifierOutput,
    )

The returned ``raw_response`` is the same :class:`LLMResponse` shape
the rest of the system uses, so the caller can seal raw API bytes
**before parse** per / — Instructor's transformation
is purely a downstream parsing step.

Optional dependencies:
    ``instructor`` and ``litellm``. Both are imported lazily so this
    module is importable in environments without the LLM stack.
"""

from __future__ import annotations

import logging
import os
from typing import Any, TypeVar

from pydantic import BaseModel

from slop_research_factory.llm.client import (
    LLMResponse,
    _coerce_to_dict,
    _configure_litellm_runtime,
    _extract_provider,
    _extract_think_tokens,
    _optional_str,
    _should_retry_completion_as_openrouter,
)

__all__ = [
    "InstructorClient",
    "InstructorNotInstalledError",
    "complete_structured",
]

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)


# ── Errors ───────────────────────────────────────────────


class InstructorNotInstalledError(RuntimeError):
    """Raised when ``instructor`` is unavailable but required."""


# ── Public API ──────────────────────────────────────────


class InstructorClient:
    """Light Protocol-style alias for an Instructor-patched async client.

    Real implementations are returned by ``instructor.from_litellm``
    or ``instructor.patch``; this class is documentation-only and
    used as a typing hint for callers wishing to inject a pre-built
    client (especially handy in unit tests).
    """

    chat: Any  # Filled by instructor; here for type checkers.


async def complete_structured(
    *,
    model: str,
    messages: list[dict[str, Any]],
    response_model: type[T],
    sampling_params: dict[str, Any] | None = None,
    max_retries: int = 2,
    instructor_client: Any | None = None,
) -> tuple[T, LLMResponse]:
    """Run a single completion that returns a typed Pydantic model.

    Args:
        model: Provider model identifier (LiteLLM string).
        messages: OpenAI-format chat messages.
        response_model: Pydantic model class the LLM output is
            coerced into. Validation failures trigger Instructor's
            built-in retry (up to ``max_retries`` extra attempts).
        sampling_params: Optional sampling kwargs forwarded to
            LiteLLM (temperature, top_p, etc.).
        max_retries: Validation retry budget; ``2`` matches
            Instructor's documented default.
        instructor_client: Pre-built Instructor client (test seam).
            When ``None``, a fresh client is created via
            ``instructor.from_litellm``.

    Returns:
        ``(parsed, raw)`` where *parsed* is a validated instance of
        *response_model* and *raw* is the :class:`LLMResponse` derived
        from Instructor's underlying provider response — sealed
        verbatim under / .

    Raises:
        InstructorNotInstalledError: If ``instructor_client`` is
            ``None`` and the ``instructor`` / ``litellm`` packages
            cannot be imported.
        pydantic.ValidationError: When the LLM's structured output
            still fails validation after ``max_retries`` attempts.
    """
    sampling = dict(sampling_params or {})

    async def _invoke(request_model: str, client_obj: Any) -> tuple[Any, Any]:
        return await client_obj.chat.completions.create_with_completion(
            model=request_model,
            messages=messages,
            response_model=response_model,
            max_retries=max_retries,
            **sampling,
        )

    effective_model = model

    if instructor_client is not None:
        client = instructor_client
        parsed, raw_completion = await _invoke(model, client)
    else:
        client = _build_default_client_for_model(model)
        try:
            parsed, raw_completion = await _invoke(model, client)
        except Exception as exc:
            has_openrouter_key = bool(os.environ.get("OPENROUTER_API_KEY", "").strip())
            if (
                has_openrouter_key
                and not str(model).startswith("openrouter/")
                and _should_retry_completion_as_openrouter(exc)
            ):
                routed = f"openrouter/{model}"
                logger.info(
                    "LiteLLM could not infer provider for structured model=%r; retrying as %r",
                    model,
                    routed,
                )
                effective_model = routed
                client = _build_default_client_for_model(routed)
                parsed, raw_completion = await _invoke(routed, client)
            else:
                raise

    raw_dict = _coerce_to_dict(raw_completion)
    usage = raw_dict.get("usage") or {}

    llm_response = LLMResponse(
        content=_extract_assistant_text(raw_dict),
        raw_response=raw_dict,
        input_tokens=int(usage.get("prompt_tokens") or 0),
        output_tokens=int(usage.get("completion_tokens") or 0),
        think_tokens=_extract_think_tokens(usage, None),
        model=str(raw_dict.get("model") or effective_model),
        api_response_id=_optional_str(raw_dict.get("id")),
        api_provider=_extract_provider(raw_dict, effective_model),
        retries=int(raw_dict.get("_litellm_retries") or 0),
        sampling_params=dict(sampling),
    )

    return parsed, llm_response


# ── Internal helpers ────────────────────────────────────


def _load_instructor_litellm() -> tuple[Any, Any]:
    """Import Instructor + LiteLLM and apply runtime tuning."""
    try:
        import instructor
    except ImportError as exc:  # pragma: no cover - exercised in install-less envs
        raise InstructorNotInstalledError(
            "complete_structured requires the `instructor` package; install with "
            "`pip install instructor`."
        ) from exc
    try:
        import litellm
    except ImportError as exc:  # pragma: no cover - exercised in install-less envs
        raise InstructorNotInstalledError(
            "complete_structured requires the `litellm` package; install with "
            "`pip install litellm`."
        ) from exc

    _configure_litellm_runtime(litellm)
    return instructor, litellm


def _build_default_client_for_model(model: str) -> Any:
    """Construct Instructor client — provider-specific structured-output mode.

    OpenRouter rejects plain ``tool_call`` / ``tool_choice`` for many models
    (404: no endpoints support ``tool_choice``). Use OpenRouter's structured
    outputs mode instead.

    Other providers keep Instructor's default :data:`~instructor.Mode.TOOLS`.
    """
    instructor, litellm = _load_instructor_litellm()
    mode = instructor.Mode.TOOLS
    lead = model.strip().partition("/")[0].lower()
    if lead == "openrouter":
        mode = instructor.Mode.OPENROUTER_STRUCTURED_OUTPUTS
    return instructor.from_litellm(litellm.acompletion, mode=mode)


def _extract_assistant_text(raw: dict[str, Any]) -> str:
    """Extract assistant text from a parsed completion dict.

    Instructor still surfaces the raw provider completion alongside
    the parsed Pydantic instance, so the standard ``choices[0]``
    accessor works. Reasoning content (if any) is returned verbatim
    so the caller can seal it; structured-output flows do not
    automatically wrap reasoning in ``<details>`` because the
    Verifier's closed-book discipline keeps think traces
    out of its critique payload.
    """
    choices = raw.get("choices") or []
    if not choices:
        return ""
    message = (choices[0] or {}).get("message") or {}
    return str(message.get("content") or "")
