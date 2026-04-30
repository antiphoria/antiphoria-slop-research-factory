# src/slop_research_factory/llm/structured.py

"""
Instructor / Pydantic structured-output wrapper (D-0 §13 Step 5).

The Verifier (D-3 §4) requires a strictly-typed Pydantic response
model — :class:`~slop_research_factory.types.verifier_output.VerifierOutput`.
Instructor patches LiteLLM to coerce raw model output into a Pydantic
instance, retrying when the parser fails validation.

This module exposes a single async helper:

.. code-block:: python

    parsed, raw_response = await complete_structured(
        model="google/gemini-2.5-flash",
        messages=[...],
        response_model=VerifierOutput,
    )

The returned ``raw_response`` is the same :class:`LLMResponse` shape
the rest of the system uses, so the caller can seal raw API bytes
**before parse** per D-1 §10 / D-5 §6 — Instructor's transformation
is purely a downstream parsing step.

Optional dependencies:
    ``instructor`` and ``litellm``.  Both are imported lazily so this
    module is importable in environments without the LLM stack.
"""

from __future__ import annotations

import logging
from typing import Any, TypeVar

from pydantic import BaseModel

from slop_research_factory.llm.client import (
    LLMResponse,
    _coerce_to_dict,
    _extract_provider,
    _extract_think_tokens,
    _optional_str,
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
        model:              Provider model identifier (LiteLLM string).
        messages:           OpenAI-format chat messages.
        response_model:     Pydantic model class the LLM output is
            coerced into.  Validation failures trigger Instructor's
            built-in retry (up to ``max_retries`` extra attempts).
        sampling_params:    Optional sampling kwargs forwarded to
            LiteLLM (temperature, top_p, etc.).
        max_retries:        Validation retry budget; ``2`` matches
            Instructor's documented default.
        instructor_client:  Pre-built Instructor client (test seam).
            When ``None``, a fresh client is created via
            ``instructor.from_litellm``.

    Returns:
        ``(parsed, raw)`` where *parsed* is a validated instance of
        *response_model* and *raw* is the :class:`LLMResponse` derived
        from Instructor's underlying provider response — sealed
        verbatim under D-1 §10 / D-5 §6.

    Raises:
        InstructorNotInstalledError: If ``instructor_client`` is
            ``None`` and the ``instructor`` / ``litellm`` packages
            cannot be imported.
        pydantic.ValidationError: When the LLM's structured output
            still fails validation after ``max_retries`` attempts.
    """
    client = instructor_client if instructor_client is not None else _build_default_client()

    sampling = dict(sampling_params or {})

    parsed, raw_completion = await client.chat.completions.create_with_completion(
        model=model,
        messages=messages,
        response_model=response_model,
        max_retries=max_retries,
        **sampling,
    )

    raw_dict = _coerce_to_dict(raw_completion)
    usage = raw_dict.get("usage") or {}

    llm_response = LLMResponse(
        content=_extract_assistant_text(raw_dict),
        raw_response=raw_dict,
        input_tokens=int(usage.get("prompt_tokens") or 0),
        output_tokens=int(usage.get("completion_tokens") or 0),
        think_tokens=_extract_think_tokens(usage, None),
        model=str(raw_dict.get("model") or model),
        api_response_id=_optional_str(raw_dict.get("id")),
        api_provider=_extract_provider(raw_dict, model),
        retries=int(raw_dict.get("_litellm_retries") or 0),
        sampling_params=dict(sampling),
    )

    return parsed, llm_response


# ── Internal helpers ────────────────────────────────────


def _build_default_client() -> Any:
    """Construct a default Instructor-patched async LiteLLM client."""
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

    return instructor.from_litellm(litellm.acompletion)


def _extract_assistant_text(raw: dict[str, Any]) -> str:
    """Extract assistant text from a parsed completion dict.

    Instructor still surfaces the raw provider completion alongside
    the parsed Pydantic instance, so the standard ``choices[0]``
    accessor works.  Reasoning content (if any) is returned verbatim
    so the caller can seal it; structured-output flows do not
    automatically wrap reasoning in ``<details>`` because the
    Verifier's closed-book discipline (D-0 §6.3) keeps think traces
    out of its critique payload.
    """
    choices = raw.get("choices") or []
    if not choices:
        return ""
    message = (choices[0] or {}).get("message") or {}
    return str(message.get("content") or "")
