# tests/unit/test_canned_tool_client.py

"""Unit tests for :class:`CannedCitationCheckClient`."""

from __future__ import annotations

import pytest

from slop_research_factory.tools.canned import (
    CannedCitationCheckClient,
    CannedScript,
)
from slop_research_factory.tools.protocol import (
    CitationCheckClient,
    ToolInvocation,
)
from slop_research_factory.types.tool_types import (
    CrossrefQuery,
    CrossrefResult,
    SemanticScholarQuery,
    SemanticScholarResult,
    TavilyQuery,
    TavilyResult,
)


@pytest.fixture
def client() -> CannedCitationCheckClient:
    script = CannedScript.from_mapping(
        {
            "crossref": {
                "10.1000/found": CrossrefResult(
                    found=True,
                    doi="10.1000/found",
                    title="Found Paper",
                    authors=["A. Author"],
                    year=2024,
                ),
                "10.1000/error": None,
            },
            "semantic_scholar": {
                "DOI:10.1000/found": SemanticScholarResult(
                    found=True,
                    paper_id="DOI:10.1000/found",
                    title="Found Paper",
                ),
            },
            "tavily": {
                "novelty check": TavilyResult(
                    query="novelty check",
                    results=[{"title": "T", "url": "u", "content": "c", "score": 0.5}],
                ),
            },
        },
    )
    return CannedCitationCheckClient(script=script)


class TestProtocolConformance:
    def test_satisfies_protocol(self, client: CannedCitationCheckClient) -> None:
        assert isinstance(client, CitationCheckClient)


class TestCrossref:
    @pytest.mark.asyncio
    async def test_hit(self, client: CannedCitationCheckClient) -> None:
        inv = await client.crossref(CrossrefQuery(doi="10.1000/found"))
        assert isinstance(inv, ToolInvocation)
        assert inv.status == "ok"
        assert inv.result.found is True
        assert inv.error is None

    @pytest.mark.asyncio
    async def test_miss(self, client: CannedCitationCheckClient) -> None:
        inv = await client.crossref(CrossrefQuery(doi="10.1000/missing"))
        assert inv.status == "not_found"
        assert inv.result.found is False

    @pytest.mark.asyncio
    async def test_simulated_error(self, client: CannedCitationCheckClient) -> None:
        inv = await client.crossref(CrossrefQuery(doi="10.1000/error"))
        assert inv.status == "error"
        assert "simulated failure" in (inv.error or "")


class TestSemanticScholar:
    @pytest.mark.asyncio
    async def test_hit(self, client: CannedCitationCheckClient) -> None:
        inv = await client.semantic_scholar(
            SemanticScholarQuery(paper_id="DOI:10.1000/found"),
        )
        assert inv.status == "ok"
        assert inv.result.found is True

    @pytest.mark.asyncio
    async def test_miss(self, client: CannedCitationCheckClient) -> None:
        inv = await client.semantic_scholar(
            SemanticScholarQuery(query_title="not registered"),
        )
        assert inv.status == "not_found"


class TestTavily:
    @pytest.mark.asyncio
    async def test_hit(self, client: CannedCitationCheckClient) -> None:
        inv = await client.tavily(TavilyQuery(query="novelty check"))
        assert inv.status == "ok"
        assert len(inv.result.results) == 1


class TestToolInvocationSerialisation:
    @pytest.mark.asyncio
    async def test_to_dict_contains_query_and_result(
        self,
        client: CannedCitationCheckClient,
    ) -> None:
        inv = await client.crossref(CrossrefQuery(doi="10.1000/found"))
        as_dict = inv.to_dict()
        assert as_dict["tool_name"] == "crossref"
        assert as_dict["query"]["doi"] == "10.1000/found"
        assert as_dict["result"]["found"] is True
        assert as_dict["status"] == "ok"
        assert as_dict["_schema_version"] == "0.1"
