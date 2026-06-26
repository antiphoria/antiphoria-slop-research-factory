"""Semantic Scholar query construction from extracted citations."""

from __future__ import annotations

from slop_research_factory.nodes.verifier_node import (
    _aggregate_citation_check,
    _semantic_scholar_query_from_citation,
)
from slop_research_factory.types.enums import CitationCheckResult
from slop_research_factory.types.verifier_output import CitationEntry


def test_s2_query_prefers_doi() -> None:
    q = _semantic_scholar_query_from_citation(
        CitationEntry(
            citation_text="[1]",
            doi="10.1000/182",
            claimed_title=None,
        ),
    )
    assert q is not None
    assert q.paper_id == "DOI:10.1000/182"
    assert q.query_title is None


def test_s2_query_falls_back_to_citation_text_when_no_title() -> None:
    q = _semantic_scholar_query_from_citation(
        CitationEntry(
            citation_text="Smith et al., Important Results, 2024.",
            claimed_title=None,
        ),
    )
    assert q is not None
    assert q.paper_id is None
    assert q.query_title == "Smith et al., Important Results, 2024."


def test_s2_query_none_when_no_usable_text() -> None:
    assert (
        _semantic_scholar_query_from_citation(
            CitationEntry(citation_text=" ", claimed_title=None),
        )
        is None
    )


def test_aggregate_no_sources_is_inconclusive() -> None:
    entry = _aggregate_citation_check(
        CitationEntry(citation_text="???"),
        crossref_inv=None,
        s2_inv=None,
    )
    assert entry.result == CitationCheckResult.INCONCLUSIVE
    assert entry.checked_sources == []
