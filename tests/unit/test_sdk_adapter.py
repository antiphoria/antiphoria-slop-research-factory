# tests/unit/test_sdk_adapter.py

"""
Unit tests for the SDK bridge adapter.

Tests:
- Hash prefix stripping and adding
- Receipt mapping from SDK types to factory types
- Verification report mapping
- Engine selection logic (provenance on/off)

NOTE: These tests use mock SDK objects — they do NOT require
antiphoria_sdk to be installed (except for the engine selection
integration test which is skipped if unavailable).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from unittest.mock import patch

import pytest

from slop_research_factory.seal.sdk_adapter import (
    _add_hash_prefix,
    _map_receipt,
    _map_step_verification,
    _map_verification_report,
    _strip_hash_prefix,
    create_seal_engine,
)
from slop_research_factory.types.provenance import (
    SealReceipt,
    VerificationReport,
)

# Non-/tmp paths — ruff S108 flags hard-coded /tmp in tests.
_FIXTURE_CHAIN_POST = "/workspace/fixture/chain/000003_POST_GENERATOR.json"
_FIXTURE_CHAIN_GENESIS = "/workspace/fixture/chain/000000_GENESIS.json"

# ── Hash normalization ────────────────────────────────────────────────


class TestHashNormalization:
    """Hash prefix stripping/adding at adapter boundary."""

    def test_strip_prefixed_hash(self) -> None:
        """'sha256:abc...' → 'abc...'"""
        h = "sha256:" + "a" * 64
        assert _strip_hash_prefix(h) == "a" * 64

    def test_strip_bare_hash_unchanged(self) -> None:
        """Already bare hash passes through."""
        h = "b" * 64
        assert _strip_hash_prefix(h) == "b" * 64

    def test_strip_none_returns_none(self) -> None:
        """None input → None output."""
        assert _strip_hash_prefix(None) is None

    def test_add_prefix_to_bare(self) -> None:
        """Bare hash gets 'sha256:' prefix."""
        h = "c" * 64
        assert _add_hash_prefix(h) == "sha256:" + "c" * 64

    def test_add_prefix_idempotent(self) -> None:
        """Already prefixed hash is not double-prefixed."""
        h = "sha256:" + "d" * 64
        assert _add_hash_prefix(h) == h

    def test_add_prefix_none(self) -> None:
        """None → None."""
        assert _add_hash_prefix(None) is None


# ── Receipt mapping ───────────────────────────────────────────────────


@dataclass
class _MockSDKReceipt:
    step_index: int = 3
    step_type: str = "POST_GENERATOR"
    entry_hash: str = "sha256:" + "e" * 64
    previous_hash: str = "sha256:" + "f" * 64
    record_path: str = _FIXTURE_CHAIN_POST
    timestamp: str = "2025-06-15T12:00:00Z"


class TestReceiptMapping:
    """SDK receipt → factory SealReceipt."""

    def test_maps_all_fields(self) -> None:
        """All fields transfer with hash stripping."""
        sdk_receipt = _MockSDKReceipt()
        result = _map_receipt(sdk_receipt)
        assert isinstance(result, SealReceipt)
        assert result.step_index == 3
        assert result.step_type == "POST_GENERATOR"
        assert result.entry_hash == "e" * 64
        assert result.previous_hash == "f" * 64
        assert result.record_path == Path(_FIXTURE_CHAIN_POST)
        assert result.timestamp == "2025-06-15T12:00:00Z"

    def test_none_previous_hash(self) -> None:
        """Genesis receipt has None previous_hash."""
        sdk_receipt = _MockSDKReceipt(previous_hash=None, step_index=0)
        result = _map_receipt(sdk_receipt)
        assert result.previous_hash is None

    def test_none_record_path(self) -> None:
        """None record_path maps to None."""
        sdk_receipt = _MockSDKReceipt(record_path=None)
        result = _map_receipt(sdk_receipt)
        assert result.record_path is None


# ── Verification report mapping ───────────────────────────────────────


@dataclass
class _MockSDKStepVerification:
    step_index: int = 0
    step_type: str = "GENESIS"
    record_path: str = _FIXTURE_CHAIN_GENESIS
    signature_valid: bool = True
    content_hashes_valid: bool = True
    previous_hash_matches: bool = True
    canonical_form_valid: bool = True
    errors: list = None

    def __post_init__(self):
        if self.errors is None:
            self.errors = []


@dataclass
class _MockSDKReport:
    run_id: str = "test-run-001"
    chain_intact: bool = True
    total_steps: int = 5
    steps: list = None
    first_error_index: int | None = None

    def __post_init__(self):
        if self.steps is None:
            self.steps = [_MockSDKStepVerification(step_index=i) for i in range(5)]


class TestVerificationReportMapping:
    """SDK VerificationReport → factory VerificationReport."""

    def test_intact_chain_maps_correctly(self) -> None:
        """Intact chain maps all fields."""
        sdk_report = _MockSDKReport()
        result = _map_verification_report(sdk_report)
        assert isinstance(result, VerificationReport)
        assert result.chain_intact is True
        assert result.total_steps == 5
        assert result.first_error_index is None
        assert len(result.steps) == 5

    def test_broken_chain_captures_error(self) -> None:
        """Broken chain reports first_error_index and step errors."""
        broken_step = _MockSDKStepVerification(
            step_index=2,
            signature_valid=False,
            errors=["signature mismatch"],
        )
        sdk_report = _MockSDKReport(
            chain_intact=False,
            first_error_index=2,
            steps=[
                _MockSDKStepVerification(step_index=0),
                _MockSDKStepVerification(step_index=1),
                broken_step,
            ],
            total_steps=3,
        )
        result = _map_verification_report(sdk_report)
        assert result.chain_intact is False
        assert result.first_error_index == 2
        assert result.steps[2].signature_valid is False
        assert "signature mismatch" in result.steps[2].errors

    def test_step_ok_property(self) -> None:
        """StepVerification.ok reflects all-pass."""
        sdk_step = _MockSDKStepVerification()
        result = _map_step_verification(sdk_step)
        assert result.ok is True

        broken = _MockSDKStepVerification(content_hashes_valid=False)
        result_broken = _map_step_verification(broken)
        assert result_broken.ok is False


# ── Engine selection ──────────────────────────────────────────────────


class TestEngineSelection:
    """create_seal_engine dispatches correctly based on enable_provenance."""

    def test_provenance_disabled_returns_in_memory(self, tmp_path: Path) -> None:
        """enable_provenance=False → InMemorySealEngine."""
        engine = create_seal_engine(
            workspace=tmp_path,
            run_id="test-001",
            enable_provenance=False,
        )
        from slop_research_factory.seal.engine import InMemorySealEngine

        assert isinstance(engine, InMemorySealEngine)

    def test_provenance_enabled_without_sdk_raises(self, tmp_path: Path) -> None:
        """enable_provenance=True without SDK installed → RuntimeError."""
        with (
            patch.dict("sys.modules", {"antiphoria_sdk": None}),
            pytest.raises(RuntimeError, match="antiphoria_sdk"),
        ):
            create_seal_engine(
                workspace=tmp_path,
                run_id="test-001",
                enable_provenance=True,
            )
