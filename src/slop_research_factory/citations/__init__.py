# src/slop_research_factory/citations/__init__.py

"""Citation extraction and check helpers."""

from __future__ import annotations

from slop_research_factory.citations.extractor import (
    extract_citations,
    extract_citations_from_text,
)

__all__ = [
    "extract_citations",
    "extract_citations_from_text",
]
