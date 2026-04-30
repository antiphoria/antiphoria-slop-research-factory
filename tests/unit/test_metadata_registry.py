# tests/unit/test_metadata_registry.py

"""Unit tests for :mod:`slop_research_factory.seal.registry` (D-2 §15)."""

from __future__ import annotations

import pytest

from slop_research_factory.seal.registry import (
    METADATA_REGISTRY,
    MetadataSchema,
    MetadataSchemaError,
    MetadataStrictness,
    register_metadata_schema,
    validate_metadata,
)
from slop_research_factory.types.enums import StepType

_FAKE_HASH = "a" * 64


class TestRegistryCoverage:
    def test_every_step_type_has_a_schema(self) -> None:
        missing = [st for st in StepType if st not in METADATA_REGISTRY]
        assert missing == [], f"missing schemas: {missing}"


class TestPreGenerator:
    def test_minimal_valid(self) -> None:
        validate_metadata(
            StepType.PRE_GENERATOR,
            {"prompt_hash": _FAKE_HASH, "model_id": "x", "cycle": 1},
        )

    def test_missing_required_raises(self) -> None:
        with pytest.raises(MetadataSchemaError, match="missing required"):
            validate_metadata(
                StepType.PRE_GENERATOR,
                {"prompt_hash": _FAKE_HASH, "cycle": 1},
            )

    def test_unknown_key_raises_in_strict_mode(self) -> None:
        with pytest.raises(MetadataSchemaError, match="unknown metadata"):
            validate_metadata(
                StepType.PRE_GENERATOR,
                {
                    "prompt_hash": _FAKE_HASH,
                    "model_id": "x",
                    "cycle": 1,
                    "rogue_key": "boom",
                },
            )

    def test_unknown_key_warns_in_lenient_mode(
        self,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        validate_metadata(
            StepType.PRE_GENERATOR,
            {
                "prompt_hash": _FAKE_HASH,
                "model_id": "x",
                "cycle": 1,
                "rogue_key": "ok",
            },
            strictness=MetadataStrictness.LENIENT,
        )
        assert any("unknown metadata keys" in r.message for r in caplog.records)

    def test_type_mismatch_raises(self) -> None:
        with pytest.raises(MetadataSchemaError, match="type violation"):
            validate_metadata(
                StepType.PRE_GENERATOR,
                {"prompt_hash": _FAKE_HASH, "model_id": "x", "cycle": "one"},
            )


class TestPostGenerator:
    def test_full_payload_accepted(self) -> None:
        validate_metadata(
            StepType.POST_GENERATOR,
            {
                "model_id": "deepseek/deepseek-r1",
                "input_tokens": 100,
                "output_tokens": 200,
                "cycle": 1,
                "draft_hash": _FAKE_HASH,
                "raw_response_hash": _FAKE_HASH,
                "think_hash": None,
                "api_response_id": None,
                "is_no_output": False,
                "prompt_version": "v0.1",
            },
        )


class TestVerifierSchemas:
    def test_pre_verifier_accepts_tool_call_steps(self) -> None:
        validate_metadata(
            StepType.PRE_VERIFIER,
            {
                "prompt_hash": _FAKE_HASH,
                "model_id": "gemini-flash",
                "cycle": 1,
                "num_citations_checked": 3,
                "tool_call_steps": [2, 3, 4],
                "draft_hash": _FAKE_HASH,
                "draft_version": 1,
                "prompt_version": "verifier_v0.1",
            },
        )

    def test_post_verifier_accepts_full_payload(self) -> None:
        validate_metadata(
            StepType.POST_VERIFIER,
            {
                "raw_critique_hash": _FAKE_HASH,
                "critique_hash": _FAKE_HASH,
                "raw_verdict": "CORRECT",
                "verdict": "CORRECT",
                "confidence": 0.92,
                "model_id": "gemini-flash",
                "cycle": 1,
                "input_tokens": 1,
                "output_tokens": 2,
                "resolution_type": "explanation",
                "prompt_version": "verifier_v0.1",
            },
        )


class TestToolCallSchema:
    def test_minimal_tool_call(self) -> None:
        validate_metadata(
            StepType.TOOL_CALL,
            {
                "tool_name": "crossref",
                "query": "10.1234/abc",
                "response_hash": _FAKE_HASH,
            },
        )


class TestRegisterMetadataSchema:
    def test_overwrite_required(self) -> None:
        new_schema = MetadataSchema(
            required=frozenset({"foo"}),
            allowed=frozenset({"foo"}),
            types={"foo": (str,)},
        )
        with pytest.raises(ValueError):
            register_metadata_schema(StepType.GENESIS, new_schema)
        # Restore-tolerant test isolation: leave registry untouched.

    def test_unknown_step_type_branch(self) -> None:
        # Use a real StepType that's still in the registry, but pop it
        # temporarily to trigger the missing-schema branch.
        cached = METADATA_REGISTRY.pop(StepType.MANIFEST)
        try:
            with pytest.raises(MetadataSchemaError, match="no metadata schema"):
                validate_metadata(StepType.MANIFEST, {})
        finally:
            METADATA_REGISTRY[StepType.MANIFEST] = cached
