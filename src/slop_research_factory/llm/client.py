# src/slop_research_factory/llm/client.py

"""
LLM client Protocol + LiteLLM-backed and canned implementations
(D-0 §4A, D-0 §13 Step 4).

The :class:`LLMClient` Protocol is the call-site contract used by every
node (Generator, Verifier, Reviser).  Two concrete implementations
ship with M1:

- :class:`LiteLLMClient` — wraps `litellm.acompletion` for production
  and live integration runs.  Lazy-imports ``litellm`` so the package
  remains importable in environments where the SDK is not installed.
- :class:`CannedLLMClient` — replays a scripted list of
  :class:`LLMResponse` objects in order; ideal for unit / integration
  tests and for offline development.

The :class:`LLMResponse` dataclass mirrors the field set
:func:`slop_research_factory.nodes.generator_node.generator_node`
already consumes; see that module for the integration contract.

Reasoning-trace handling
~~~~~~~~~~~~~~~~~~~~~~~~

DeepSeek-R1 (and other reasoning models) emit reasoning content in a
provider-specific field (``message.reasoning_content`` in OpenRouter's
schema).  When :class:`LiteLLMClient` detects that field, it folds the
reasoning into the returned ``content`` wrapped in a
``<details>...</details>`` block so the existing
:func:`slop_research_factory.llm.think_parser.parse_think_tokens`
extracts it without per-provider branching.

Spec references:
    D-0 §4    Model topology.
    D-0 §4A   Inference middleware and think-token capture.
    D-1 §10   Raw-bytes-before-parse sealing requirement.
    D-5 §6    Raw API response sealing.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

__all__ = [
    "CannedLLMClient",
    "LLMClient",
    "LLMResponse",
    "LiteLLMClient",
    "LiteLLMNotInstalledError",
]

logger = logging.getLogger(__name__)


# ── LLMResponse ─────────────────────────────────────────


@dataclass(frozen=True)
class LLMResponse:
    """Provider-agnostic response object handed back by every client.

    Attributes mirror the field set consumed by ``generator_node``:

    Attributes:
        content:           Final assistant message text.  Reasoning
            traces (when present) are wrapped in a ``<details>`` block
            and prepended so that
            :func:`slop_research_factory.llm.think_parser.parse_think_tokens`
            extracts them without per-provider branching.
        raw_response:      Provider response as a JSON-serialisable
            dict.  Sealed verbatim under D-1 §10.
        input_tokens:      Prompt tokens consumed.
        output_tokens:     Completion tokens (excluding reasoning).
        think_tokens:      Reasoning tokens, when reported; ``None``
            otherwise.
        model:             Model identifier as returned by the
            provider (may differ from the requested string when
            providers route to a specific revision).
        api_response_id:   Provider response ID (``response.id``).
        api_provider:      Lowercase provider slug, e.g.
            ``"openrouter"``, ``"google"``, ``"ollama"``.
        retries:           Retry count consumed before success
            (LiteLLM `num_retries` setting).
        sampling_params:   Sampling kwargs that were sent to the
            provider; sealed alongside the response for full
            reproducibility.
    """

    content: str
    raw_response: dict[str, Any]
    input_tokens: int
    output_tokens: int
    think_tokens: int | None
    model: str
    api_response_id: str | None
    api_provider: str
    retries: int = 0
    sampling_params: dict[str, Any] = field(default_factory=dict)


# ── LLMClient Protocol ──────────────────────────────────


@runtime_checkable
class LLMClient(Protocol):
    """Frozen Protocol used by every node (D-0 §13 Step 4).

    Implementations MUST be safe to call concurrently from a single
    asyncio event loop; serialisation across runs is the
    orchestrator's responsibility.
    """

    async def complete(
        self,
        *,
        model: str,
        messages: list[dict[str, Any]],
        **kwargs: Any,
    ) -> LLMResponse:
        """Run a single completion and return a :class:`LLMResponse`."""
        ...


# ── LiteLLM-backed implementation ───────────────────────


class LiteLLMNotInstalledError(RuntimeError):
    """Raised when :class:`LiteLLMClient` is used without ``litellm`` installed."""


class LiteLLMClient:
    """Production :class:`LLMClient` backed by ``litellm.acompletion``.

    The underlying SDK is imported lazily so the module remains
    importable in slim CI / development environments that have not
    installed the LLM dependency stack yet.
    """

    def __init__(
        self,
        *,
        default_sampling: dict[str, Any] | None = None,
        num_retries: int = 0,
        request_timeout_seconds: float | None = None,
    ) -> None:
        self._default_sampling: dict[str, Any] = dict(default_sampling or {})
        self._num_retries = max(int(num_retries), 0)
        self._timeout = request_timeout_seconds

    async def complete(
        self,
        *,
        model: str,
        messages: list[dict[str, Any]],
        **kwargs: Any,
    ) -> LLMResponse:
        litellm = _import_litellm()

        sampling = {**self._default_sampling, **kwargs}
        sampling.setdefault("num_retries", self._num_retries)
        if self._timeout is not None:
            sampling.setdefault("request_timeout", self._timeout)

        response = await litellm.acompletion(
            model=model,
            messages=messages,
            **sampling,
        )

        raw_dict = _coerce_to_dict(response)
        content, think_tokens_from_field = _extract_content(raw_dict)
        usage = raw_dict.get("usage") or {}
        return LLMResponse(
            content=content,
            raw_response=raw_dict,
            input_tokens=int(usage.get("prompt_tokens") or 0),
            output_tokens=int(usage.get("completion_tokens") or 0),
            think_tokens=_extract_think_tokens(usage, think_tokens_from_field),
            model=str(raw_dict.get("model") or model),
            api_response_id=_optional_str(raw_dict.get("id")),
            api_provider=_extract_provider(raw_dict, model),
            retries=int(raw_dict.get("_litellm_retries") or 0),
            sampling_params=dict(sampling),
        )


# ── Canned client ───────────────────────────────────────


class CannedLLMClient:
    """Replay scripted :class:`LLMResponse` objects in order.

    Useful for unit tests, integration tests, and offline development.
    Records every call's keyword arguments under :attr:`calls` so tests
    can assert on routing and sampling parameters.

    Raises:
        RuntimeError: When :meth:`complete` is invoked after the
            scripted response list has been exhausted.
    """

    def __init__(self, responses: list[LLMResponse] | None = None) -> None:
        self._responses: list[LLMResponse] = list(responses or [])
        self.calls: list[dict[str, Any]] = []

    def queue(self, response: LLMResponse) -> None:
        """Append a response to the script (FIFO)."""
        self._responses.append(response)

    @property
    def remaining(self) -> int:
        """Number of un-consumed scripted responses."""
        return len(self._responses)

    async def complete(
        self,
        *,
        model: str,
        messages: list[dict[str, Any]],
        **kwargs: Any,
    ) -> LLMResponse:
        if not self._responses:
            raise RuntimeError(
                "CannedLLMClient: scripted responses exhausted; queue another with .queue()"
            )
        self.calls.append({"model": model, "messages": messages, **kwargs})
        return self._responses.pop(0)


# ── Internal helpers ────────────────────────────────────


def _import_litellm() -> Any:
    """Import ``litellm`` lazily; raise a typed error on failure."""
    try:
        import litellm
    except ImportError as exc:  # pragma: no cover - exercised in install-less envs
        raise LiteLLMNotInstalledError(
            "LiteLLMClient requires the `litellm` package; install with "
            "`pip install litellm` or use CannedLLMClient for offline runs."
        ) from exc
    return litellm


def _coerce_to_dict(response: Any) -> dict[str, Any]:
    """Best-effort conversion of a LiteLLM response to a plain ``dict``.

    LiteLLM's ``ModelResponse`` exposes ``model_dump`` (Pydantic v2),
    ``dict`` (Pydantic v1), or behaves dict-like depending on version.
    """
    for attr in ("model_dump", "dict"):
        method = getattr(response, attr, None)
        if callable(method):
            try:
                result = method()
            except TypeError:
                continue
            if isinstance(result, dict):
                return result
    if isinstance(response, dict):
        return dict(response)
    return {"raw_repr": repr(response)}


def _extract_content(raw: dict[str, Any]) -> tuple[str, int | None]:
    """Pull the assistant text out of ``choices[0].message.content``.

    When the message also carries provider-specific reasoning content
    (DeepSeek-R1 / OpenRouter ``reasoning_content``), wrap it in a
    ``<details>`` block and prepend so existing think-parser logic
    extracts it without per-provider branching.

    Returns ``(content, think_tokens_estimate)`` where the estimate is
    a coarse word-count heuristic used only when the API does not
    provide a ``reasoning_tokens`` figure.
    """
    choices = raw.get("choices") or []
    if not choices:
        return "", None

    first = choices[0] or {}
    message = first.get("message") or {}
    content_text = str(message.get("content") or "")
    reasoning_text = message.get("reasoning_content")
    if isinstance(reasoning_text, str) and reasoning_text.strip():
        wrapped = (
            "<details><summary>Reasoning</summary>\n"
            f"{reasoning_text.strip()}\n"
            "</details>\n"
        )
        return wrapped + content_text, _estimate_tokens(reasoning_text)
    return content_text, None


def _extract_think_tokens(usage: dict[str, Any], fallback: int | None) -> int | None:
    """Resolve the reasoning-token count from usage stats.

    Honours OpenAI / OpenRouter conventions:
    ``usage.completion_tokens_details.reasoning_tokens`` first, then
    a top-level ``reasoning_tokens`` field, then the heuristic
    fallback derived from any inline reasoning text.
    """
    details = usage.get("completion_tokens_details")
    if isinstance(details, dict):
        value = details.get("reasoning_tokens")
        if isinstance(value, (int, float)):
            return int(value)
    top_level = usage.get("reasoning_tokens")
    if isinstance(top_level, (int, float)):
        return int(top_level)
    return fallback


def _extract_provider(raw: dict[str, Any], model: str) -> str:
    """Best-effort provider slug extraction.

    Prefers an explicit ``provider`` field on the response, falls back
    to the leading segment of *model* (e.g. ``"deepseek/deepseek-r1"``
    → ``"deepseek"``).
    """
    explicit = raw.get("provider") or raw.get("_provider")
    if isinstance(explicit, str) and explicit.strip():
        return explicit.strip().lower()
    if "/" in model:
        return model.split("/", 1)[0].lower()
    return model.lower()


def _optional_str(value: Any) -> str | None:
    """Return *value* as a string when truthy, else ``None``."""
    if value is None:
        return None
    text = str(value)
    return text if text else None


def _estimate_tokens(text: str) -> int:
    """Cheap fallback token estimate (≈ 4 chars per token)."""
    if not text:
        return 0
    return max(1, len(text) // 4)
