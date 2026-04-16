# tests/unit/test_tool_types.py

"""
E1 unit tests for types/tool_types.py — D-8 §3.1.

Covers frozen-ness, JSON serialisation, and default values
for all external tool types (Crossref, Semantic Scholar, Tavily).

Human rescue types live in types/human_rescue.py and are
tested separately.
"""
from __future__ import annotations

import json
from dataclasses import FrozenInstanceError, asdict

import pytest

from slop_research_factory.types.tool_types import (
    CrossrefQuery,
    CrossrefResult,
    SemanticScholarQuery,
    SemanticScholarResult,
    TavilyQuery,
    TavilyResult,
)


# ── Crossref types (D-2 §11.1) ──────────────────────────────


class TestCrossrefTypes:
    """CrossrefQuery/Result: frozen, JSON-serialisable."""

    def test_query_frozen(self) -> None:
        q = CrossrefQuery(doi="10.1234/test")
        with pytest.raises(FrozenInstanceError):
            q.doi = "changed"  # type: ignore[misc]

    def test_query_all_none_defaults(self) -> None:
        q = CrossrefQuery()
        assert q.doi is None
        assert q.query_title is None
        assert q.query_author is None

    def test_result_frozen(self) -> None:
        r = CrossrefResult(found=True, doi="10.1234/x")
        with pytest.raises(FrozenInstanceError):
            r.found = False  # type: ignore[misc]

    def test_result_json_roundtrip(self) -> None:
        r = CrossrefResult(
            found=True,
            doi="10.1234/test",
            title="A Paper",
            authors=["Alice", "Bob"],
            year=2024,
            journal="J. Testing",
            raw_response={"status": "ok"},
        )
        loaded = json.loads(json.dumps(asdict(r)))
        assert loaded["found"] is True
        assert loaded["doi"] == "10.1234/test"
        assert loaded["authors"] == ["Alice", "Bob"]
        assert loaded["year"] == 2024

    def test_result_not_found_defaults(self) -> None:
        r = CrossrefResult(found=False)
        assert r.doi is None
        assert r.authors is None
        assert r.raw_response == {}


# ── Semantic Scholar types (D-2 §11.2) ───────────────────────


class TestSemanticScholarTypes:
    """SemanticScholarQuery/Result: frozen, JSON-serialisable."""

    def test_query_frozen(self) -> None:
        q = SemanticScholarQuery(
            paper_id="DOI:10.1234/x",
        )
        with pytest.raises(FrozenInstanceError):
            q.paper_id = "other"  # type: ignore[misc]

    def test_result_with_abstract(self) -> None:
        r = SemanticScholarResult(
            found=True,
            paper_id="S2:12345",
            title="A Paper",
            authors=["Alice"],
            year=2023,
            abstract="We prove a theorem.",
            citation_count=42,
            raw_response={"paperId": "12345"},
        )
        assert r.abstract == "We prove a theorem."
        assert r.citation_count == 42

    def test_result_json_roundtrip(self) -> None:
        r = SemanticScholarResult(
            found=False, raw_response={},
        )
        loaded = json.loads(json.dumps(asdict(r)))
        assert loaded["found"] is False
        assert loaded["abstract"] is None


# ── Tavily types (D-2 §11.3) ─────────────────────────────────


class TestTavilyTypes:
    """TavilyQuery/Result: frozen, JSON-serialisable."""

    def test_query_defaults(self) -> None:
        q = TavilyQuery(query="test query")
        assert q.search_depth == "basic"
        assert q.max_results == 5

    def test_query_frozen(self) -> None:
        q = TavilyQuery(query="test")
        with pytest.raises(FrozenInstanceError):
            q.query = "other"  # type: ignore[misc]

    def test_result_with_entries(self) -> None:
        r = TavilyResult(
            query="test",
            results=[{
                "title": "Page",
                "url": "https://example.com",
                "content": "Some content.",
                "score": 0.95,
            }],
            raw_response={"query": "test"},
        )
        assert len(r.results) == 1
        assert r.results[0]["score"] == 0.95

    def test_result_empty_defaults(self) -> None:
        r = TavilyResult(query="nothing")
        assert r.results == []
        assert r.raw_response == {}

    def test_result_json_roundtrip(self) -> None:
        entry = {
            "title": "T", "url": "U",
            "content": "C", "score": 0.5,
        }
        r = TavilyResult(
            query="q",
            results=[entry],
            raw_response={"raw": True},
        )
        loaded = json.loads(json.dumps(asdict(r)))
        assert loaded["results"][0]["title"] == "T"
        assert loaded["raw_response"]["raw"] is True
