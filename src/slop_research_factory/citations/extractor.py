# src/slop_research_factory/citations/extractor.py

"""Lightweight citation extraction.

The Verifier node needs a canonical list of citations BEFORE running
its tool checks. The full design prescribes a small LLM call
for robustness; for M2 we ship a regex + heuristic extractor that
covers the dominant patterns:

* DOIs in any form (``10.xxxx/yyyy``).
* arXiv IDs (``arXiv:YYMM.NNNNN`` or ``YYMM.NNNNN`` next to ``arXiv``).
* Author-year citations (``Smith et al. 2024``) inside running text.
* Bracketed numeric refs ``[12]`` linked to a References section.

The output list is order-preserving and free of duplicates. It maps
1:1 to :class:`CitationEntry` Pydantic objects so downstream code can
treat the list as ground truth without further parsing.

Design note
-----------

Empirical comparison between regex extraction and an LLM-based
extractor is on the open-questions list. M2 defers the LLM
path; the function signature accepts a future ``mode`` argument that
will switch to LLM extraction without breaking callers.
"""

from __future__ import annotations

import logging
import re
from typing import Literal

from slop_research_factory.types.verifier_output import CitationEntry

__all__ = [
    "ExtractionMode",
    "extract_citations",
    "extract_citations_from_text",
]

logger = logging.getLogger(__name__)

ExtractionMode = Literal["regex", "llm"]

# DOIs — most permissive form, ``10.<digits>/<chars>``.
_DOI_RE = re.compile(
    r"\b10\.\d{4,9}/[-._;()/:A-Z0-9]+\b",
    re.IGNORECASE,
)

# arXiv: ``arXiv:2501.12345`` or ``arXiv: 2501.12345v3``.
_ARXIV_RE = re.compile(
    r"\barXiv:?\s*(\d{4}\.\d{4,5}(?:v\d+)?)\b",
    re.IGNORECASE,
)

# Author-year citation in running prose.
# Captures: ``Smith et al. (2024)`` / ``Smith and Jones, 2024``.
_AUTHOR_YEAR_RE = re.compile(
    r"\b([A-Z][A-Za-z'\-]+(?:(?:\s+(?:and|&)\s+|,\s+)[A-Z][A-Za-z'\-]+)*"
    r"(?:\s+et\s+al\.)?)"
    r"[,\s]+\(?(\d{4}[a-z]?)\)?",
)


def extract_citations_from_text(text: str) -> list[CitationEntry]:
    """Extract all citations from ``text`` using regex heuristics.

    The result is order-preserving by first appearance and
    deduplicated by ``(doi or arxiv_id or claimed_authors+year)``.
    """
    DedupKey = tuple[str | None, str | None, str | None, int | None]
    seen: set[DedupKey] = set()
    results: list[CitationEntry] = []

    for match in _DOI_RE.finditer(text):
        doi = match.group(0)
        doi_key: DedupKey = (doi, None, None, None)
        if doi_key in seen:
            continue
        seen.add(doi_key)
        results.append(CitationEntry(citation_text=doi, doi=doi))

    for match in _ARXIV_RE.finditer(text):
        full = match.group(0)
        arxiv_id = match.group(1)
        arxiv_key: DedupKey = (None, arxiv_id, None, None)
        if arxiv_key in seen:
            continue
        seen.add(arxiv_key)
        results.append(CitationEntry(citation_text=full, arxiv_id=arxiv_id))

    for match in _AUTHOR_YEAR_RE.finditer(text):
        authors = match.group(1).strip()
        year_str = match.group(2)
        try:
            year = int(year_str[:4])
        except ValueError:
            continue
        if year < 1500 or year > 2100:
            # Reject obvious false positives (page numbers etc.).
            continue
        ay_key: DedupKey = (None, None, authors, year)
        if ay_key in seen:
            continue
        seen.add(ay_key)
        results.append(
            CitationEntry(
                citation_text=match.group(0),
                claimed_authors=authors,
                claimed_year=year,
            ),
        )

    logger.debug(
        "extract_citations_from_text: %d unique citations from %d chars",
        len(results),
        len(text),
    )
    return results


def extract_citations(
    draft: str,
    *,
    mode: ExtractionMode = "regex",
) -> list[CitationEntry]:
    """Public extractor entry point.

    Args:
        draft: The draft text to scan.
        mode: ``"regex"`` (M2 default) or ``"llm"`` (deferred to M3).

    Raises:
        NotImplementedError: When called with ``mode="llm"`` in M2.
    """
    if mode == "regex":
        return extract_citations_from_text(draft)
    if mode == "llm":
        raise NotImplementedError(
            "LLM-based citation extraction is deferred to M3 — use mode='regex' until then.",
        )
    raise ValueError(f"unknown extraction mode: {mode!r}")
