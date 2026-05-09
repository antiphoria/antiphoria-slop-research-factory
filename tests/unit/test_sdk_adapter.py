# tests/unit/test_sdk_adapter.py

"""
Unit tests for the SDK bridge adapter.

Tests:
- Hash prefix stripping and adding
- Receipt mapping from SDK types to factory types
- Verification report mapping
- Engine selection logic (provenance on/off)

NOTE: These tests use mock SDK objects and a stub ``sys.modules``
entry for ``antiphoria_sdk`` where needed so they do not require a
working liboqs install.
"""

from __future__ import annotations

import types
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from slop_research_factory.seal.engine import SealReceipt, VerificationReport
from slop_research_factory.seal.sdk_adapter import (
    _KEY_B64_VARS,
    _KEY_LOCATION_VARS,
    _add_hash_prefix,
    _map_receipt,
    _map_step_verification,
    _map_verification_report,
    _resolve_sdk_hybrid_keys,
    _strip_hash_prefix,
    create_seal_engine,
)
from slop_research_factory.types.enums import StepType

# Non-/tmp paths — ruff S108 flags hard-coded /tmp in tests.
_FIXTURE_CHAIN_POST = "/workspace/fixture/chain/000003_POST_GENERATOR.json"
_FIXTURE_CHAIN_GENESIS = "/workspace/fixture/chain/000000_GENESIS.json"


@dataclass
class _FakeHybridKeys:
    """Stand-in for ``antiphoria_sdk.HybridKeys`` when testing file/env resolution."""

    mldsa_public: bytes
    ed25519_public: bytes
    mldsa_private: bytes
    ed25519_private: bytes


def _fake_antiphoria_sdk_module(*, load_keys_from_env: MagicMock | None = None) -> types.ModuleType:
    """Minimal ``antiphoria_sdk`` so ``_resolve_sdk_hybrid_keys`` can run without liboqs/oqs."""

    mod = types.ModuleType("antiphoria_sdk")
    mod.HybridKeys = _FakeHybridKeys
    mod.load_keys_from_env = load_keys_from_env if load_keys_from_env is not None else MagicMock()
    return mod


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
        assert result.step_type == StepType.POST_GENERATOR
        assert result.content_hash == "e" * 64
        assert result.parent_hash == "f" * 64
        assert result.receipt_path == Path(_FIXTURE_CHAIN_POST)
        assert result.payload_path == Path(_FIXTURE_CHAIN_POST)
        assert isinstance(result.timestamp, datetime)
        assert result.seal_id

    def test_none_previous_hash(self) -> None:
        """Genesis receipt has None previous_hash."""
        sdk_receipt = _MockSDKReceipt(previous_hash=None, step_index=0)
        result = _map_receipt(sdk_receipt)
        assert result.parent_hash is None

    def test_none_record_path(self) -> None:
        """None record_path maps to placeholder path."""
        sdk_receipt = _MockSDKReceipt(record_path=None)
        result = _map_receipt(sdk_receipt)
        assert result.receipt_path == Path(".")


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
        assert result.steps[2].receipt_valid is False
        assert "signature mismatch" in result.steps[2].errors

    def test_step_ok_property(self) -> None:
        """StepVerification.ok reflects all-pass."""
        sdk_step = _MockSDKStepVerification()
        result = _map_step_verification(sdk_step)
        assert result.ok is True

        broken = _MockSDKStepVerification(content_hashes_valid=False)
        result_broken = _map_step_verification(broken)
        assert result_broken.payload_valid is False
        assert result_broken.ok is False


# ── Hybrid key env resolution (B64 vs filesystem) ─────────────────────


class TestResolveSdkHybridKeys:
    """``_resolve_sdk_hybrid_keys`` — path quad vs B64, mutual exclusion."""

    def _clear_key_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        for n in _KEY_LOCATION_VARS + _KEY_B64_VARS:
            monkeypatch.delenv(n, raising=False)

    def test_partial_location_vars_raise(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """1–3 LOCATION vars set → clear error (no mixing with B64)."""
        fake = _fake_antiphoria_sdk_module()
        self._clear_key_env(monkeypatch)
        monkeypatch.setenv(
            "ANTIPHORIA_MLDSA_PUBLIC_KEY_LOCATION",
            str(tmp_path / "only_a"),
        )
        monkeypatch.setenv(
            "ANTIPHORIA_MLDSA_PRIVATE_KEY_LOCATION",
            str(tmp_path / "only_b"),
        )
        with (
            patch.dict("sys.modules", {"antiphoria_sdk": fake}),
            pytest.raises(RuntimeError, match="Incomplete ANTIPHORIA"),
        ):
            _resolve_sdk_hybrid_keys()

    def test_full_location_and_full_b64_raise(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """Both quads non-empty → mutual exclusion error."""
        fake = _fake_antiphoria_sdk_module()
        self._clear_key_env(monkeypatch)
        for name, content in (
            ("m_pub", b"a" * 64),
            ("m_priv", b"b" * 64),
            ("e_pub", b"c" * 32),
            ("e_priv", b"d" * 32),
        ):
            p = tmp_path / name
            p.write_bytes(content)
        monkeypatch.setenv(
            "ANTIPHORIA_MLDSA_PUBLIC_KEY_LOCATION",
            str(tmp_path / "m_pub"),
        )
        monkeypatch.setenv(
            "ANTIPHORIA_MLDSA_PRIVATE_KEY_LOCATION",
            str(tmp_path / "m_priv"),
        )
        monkeypatch.setenv(
            "ANTIPHORIA_ED25519_PUBLIC_KEY_LOCATION",
            str(tmp_path / "e_pub"),
        )
        monkeypatch.setenv(
            "ANTIPHORIA_ED25519_PRIVATE_KEY_LOCATION",
            str(tmp_path / "e_priv"),
        )
        monkeypatch.setenv("ANTIPHORIA_MLDSA_PUBLIC_KEY_B64", "YQ==")
        monkeypatch.setenv("ANTIPHORIA_MLDSA_PRIVATE_KEY_B64", "Yg==")
        monkeypatch.setenv("ANTIPHORIA_ED25519_PUBLIC_KEY_B64", "Yw==")
        monkeypatch.setenv("ANTIPHORIA_ED25519_PRIVATE_KEY_B64", "ZA==")
        with (
            patch.dict("sys.modules", {"antiphoria_sdk": fake}),
            pytest.raises(RuntimeError, match="not both"),
        ):
            _resolve_sdk_hybrid_keys()

    def test_location_quad_skips_load_keys_from_env(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """All four files present → builds HybridKeys from disk; no B64 loader."""
        load_mock = MagicMock()
        fake = _fake_antiphoria_sdk_module(load_keys_from_env=load_mock)
        self._clear_key_env(monkeypatch)
        for name, content in (
            ("m_pub", b"a" * 1952),
            ("m_priv", b"b" * 4000),
            ("e_pub", b"\x03" * 32),
            ("e_priv", b"\x04" * 32),
        ):
            (tmp_path / name).write_bytes(content)
        monkeypatch.setenv(
            "ANTIPHORIA_MLDSA_PUBLIC_KEY_LOCATION",
            str(tmp_path / "m_pub"),
        )
        monkeypatch.setenv(
            "ANTIPHORIA_MLDSA_PRIVATE_KEY_LOCATION",
            str(tmp_path / "m_priv"),
        )
        monkeypatch.setenv(
            "ANTIPHORIA_ED25519_PUBLIC_KEY_LOCATION",
            str(tmp_path / "e_pub"),
        )
        monkeypatch.setenv(
            "ANTIPHORIA_ED25519_PRIVATE_KEY_LOCATION",
            str(tmp_path / "e_priv"),
        )
        with patch.dict("sys.modules", {"antiphoria_sdk": fake}):
            keys = _resolve_sdk_hybrid_keys()
        load_mock.assert_not_called()
        assert keys.mldsa_public == b"a" * 1952
        assert keys.ed25519_public == b"\x03" * 32


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
