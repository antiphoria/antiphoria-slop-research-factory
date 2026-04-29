"""LLM response parsing utilities (not the API client; that lives with orchestration)."""

from slop_research_factory.llm.no_output import detect_no_output
from slop_research_factory.llm.think_parser import parse_think_tokens

__all__ = [
    "detect_no_output",
    "parse_think_tokens",
]
