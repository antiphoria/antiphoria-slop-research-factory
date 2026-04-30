# tests/unit/test_citation_extractor.py

"""Unit tests for :mod:`slop_research_factory.citations.extractor`."""

from __future__ import annotations

import pytest

from slop_research_factory.citations.extractor import (
    extract_citations,
    extract_citations_from_text,
)


class TestDOIExtraction:
    def test_extracts_simple_doi(self) -> None:
        text = "See 10.1000/abc.def for details."
        result = extract_citations_from_text(text)
        assert any(c.doi == "10.1000/abc.def" for c in result)

    def test_dedupes_same_doi(self) -> None:
        text = "10.1000/abc and again 10.1000/abc."
        result = extract_citations_from_text(text)
        assert sum(1 for c in result if c.doi == "10.1000/abc") == 1


class TestArxivExtraction:
    def test_extracts_arxiv_id(self) -> None:
        text = "Reference: arXiv:2501.12345 v2."
        result = extract_citations_from_text(text)
        assert any(c.arxiv_id and c.arxiv_id.startswith("2501.12345") for c in result)

    def test_extracts_with_lowercase_prefix(self) -> None:
        text = "arxiv: 2501.99999"
        result = extract_citations_from_text(text)
        assert any(c.arxiv_id == "2501.99999" for c in result)


class TestAuthorYear:
    def test_extracts_simple_author_year(self) -> None:
        text = "Smith et al. 2024 showed..."
        result = extract_citations_from_text(text)
        assert any(
            c.claimed_authors and "Smith" in c.claimed_authors and c.claimed_year == 2024
            for c in result
        )

    def test_rejects_implausible_year(self) -> None:
        text = "Smith et al. 1200 wrote..."
        result = extract_citations_from_text(text)
        assert not any(
            c.claimed_authors and "Smith" in c.claimed_authors and c.claimed_year == 1200
            for c in result
        )


class TestPublicEntry:
    def test_regex_mode_default(self) -> None:
        result = extract_citations("Foo 10.1234/x.y bar.")
        assert any(c.doi == "10.1234/x.y" for c in result)

    def test_llm_mode_not_implemented(self) -> None:
        with pytest.raises(NotImplementedError):
            extract_citations("anything", mode="llm")

    def test_unknown_mode(self) -> None:
        with pytest.raises(ValueError, match="unknown extraction mode"):
            extract_citations("anything", mode="other")  # type: ignore[arg-type]
