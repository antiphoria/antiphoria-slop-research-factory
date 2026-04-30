"""LLM middleware (D-0 §4A): client Protocol + structured-output helper.

Public API (M1):

- :class:`LLMClient` Protocol consumed by every node.
- :class:`LiteLLMClient` for production runs (lazy import of
  ``litellm``).
- :class:`CannedLLMClient` for tests and offline development.
- :class:`LLMResponse` dataclass returned by all clients.
- :func:`complete_structured` for Verifier-style typed Pydantic
  outputs (Instructor wrapper).
- :func:`detect_no_output` and :func:`parse_think_tokens` parsing
  helpers.
"""

from slop_research_factory.llm.client import (
    CannedLLMClient,
    LiteLLMClient,
    LiteLLMNotInstalledError,
    LLMClient,
    LLMResponse,
)
from slop_research_factory.llm.no_output import detect_no_output
from slop_research_factory.llm.structured import (
    InstructorClient,
    InstructorNotInstalledError,
    complete_structured,
)
from slop_research_factory.llm.think_parser import parse_think_tokens

__all__ = [
    "CannedLLMClient",
    "InstructorClient",
    "InstructorNotInstalledError",
    "LLMClient",
    "LLMResponse",
    "LiteLLMClient",
    "LiteLLMNotInstalledError",
    "complete_structured",
    "detect_no_output",
    "parse_think_tokens",
]
