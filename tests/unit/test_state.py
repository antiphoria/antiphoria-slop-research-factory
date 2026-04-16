# tests/unit/test_state.py

"""
E1 unit tests for types/state.py — D-2 §6.

Test-to-spec traceability
~~~~~~~~~~~~~~~~~~~~~~~~~
  E1-S03  FactoryState JSON round-trip.
  E1-S22  Nested FactoryConfig reconstruction.
  (plus)  AppendOnlyList enforcement (D-2 §6, §16 invariant 12).
"""

from __future__ import annotations

import json

import pytest

from slop_research_factory.config import FactoryConfig
from slop_research_factory.types.enums import (
    CheckpointBackend,
    RunStatus,
)
from slop_research_factory.types.state import (
    AppendOnlyList,
    FactoryState,
)


# ── AppendOnlyList enforcement (D-2 §6, §16 invariant 12) ────


class TestAppendOnlyList:
    """Runtime enforcement of append-only semantics."""

    def test_append_succeeds(self) -> None:
        ao = AppendOnlyList([1, 2])
        ao.append(3)
        assert ao == [1, 2, 3]

    def test_extend_succeeds(self) -> None:
        ao = AppendOnlyList([1])
        ao.extend([2, 3])
        assert ao == [1, 2, 3]

    def test_setitem_raises_type_error(self) -> None:
        ao = AppendOnlyList([1, 2])
        with pytest.raises(TypeError, match="reassignment"):
            ao[0] = 99

    def test_delitem_raises_type_error(self) -> None:
        ao = AppendOnlyList([1, 2])
        with pytest.raises(TypeError, match="deletion"):
            del ao[0]

    def test_insert_at_end_succeeds(self) -> None:
        ao = AppendOnlyList([1, 2])
        ao.insert(2, 3)
        assert ao == [1, 2, 3]

    def test_insert_not_at_end_raises(self) -> None:
        ao = AppendOnlyList([1, 2])
        with pytest.raises(TypeError, match="append-at-end"):
            ao.insert(0, 99)

    def test_slice_assign_raises(self) -> None:
        ao = AppendOnlyList([1, 2, 3])
        with pytest.raises(TypeError, match="reassignment"):
            ao[0:2] = [9, 8]

    # ── New mutation guards (pop / remove / clear / sort) ────

    def test_pop_raises_type_error(self) -> None:
        ao = AppendOnlyList([1, 2])
        with pytest.raises(TypeError, match="pop"):
            ao.pop()

    def test_remove_raises_type_error(self) -> None:
        ao = AppendOnlyList([1, 2])
        with pytest.raises(TypeError, match="removal"):
            ao.remove(1)

    def test_clear_raises_type_error(self) -> None:
        ao = AppendOnlyList([1, 2])
        with pytest.raises(TypeError, match="clear"):
            ao.clear()

    def test_reverse_raises_type_error(self) -> None:
        ao = AppendOnlyList([1, 2])
        with pytest.raises(TypeError, match="reordering"):
            ao.reverse()

    def test_sort_raises_type_error(self) -> None:
        ao = AppendOnlyList([3, 1, 2])
        with pytest.raises(TypeError, match="reordering"):
            ao.sort()


# ── E1-S03: FactoryState JSON round-trip (D-2 §6) ────────────


class TestFactoryStateRoundTrip:
    """E1-S03: asdict → json.dumps → json.loads → from_dict
    produces an identical object."""

    @staticmethod
    def _minimal() -> FactoryState:
        return FactoryState(
            run_id="550e8400-e29b-41d4-a716-446655440000",
            status=RunStatus.INITIALIZING,
            config=FactoryConfig(),
            brief={"thesis": "Test thesis"},
            step_index=0,
            latest_hash="",
        )

    def test_e1_s03_minimal_round_trip(self) -> None:
        """Minimal state round-trips identically."""
        state = self._minimal()
        json_str = json.dumps(state.to_dict(), indent=2)
        restored = FactoryState.from_dict(json.loads(json_str))
        assert restored == state

    def test_e1_s03_populated_round_trip(self) -> None:
        """Populated state (messages, counters, draft)."""
        msgs = AppendOnlyList()
        msgs.append({
            "role": "generator",
            "step_index": 1,
            "timestamp": "2026-04-15T14:32:07Z",
            "model": "deepseek/deepseek-r1",
            "prompt_hash": "aaa",
            "response_hash": "bbb",
            "token_counts": {
                "input": 100, "output": 200, "think": 50,
            },
        })

        checks = AppendOnlyList()
        checks.append({
            "citation": "Smith 2020",
            "result": "VERIFIED",
        })

        state = FactoryState(
            run_id="550e8400-e29b-41d4-a716-446655440000",
            status=RunStatus.VERIFYING,
            config=FactoryConfig(max_rejections=5),
            brief={
                "thesis": "Full test",
                "domain": "testing",
            },
            step_index=4,
            latest_hash="deadbeef01234567",
            cycle_count=2,
            rejection_count=1,
            revision_count=1,
            current_draft="# Draft\nSome content.",
            total_input_tokens=500,
            total_output_tokens=300,
            messages=msgs,
            citation_checks=checks,
            workspace="/tmp/test-workspace",
            created_at="2026-04-15T14:32:07Z",
            updated_at="2026-04-15T14:35:00Z",
        )

        json_str = json.dumps(state.to_dict(), indent=2)
        restored = FactoryState.from_dict(json.loads(json_str))

        # Auditable field-by-field
        assert restored.run_id == state.run_id
        assert restored.status is RunStatus.VERIFYING
        assert restored.step_index == 4
        assert restored.latest_hash == "deadbeef01234567"
        assert restored.cycle_count == 2
        assert restored.rejection_count == 1
        assert restored.current_draft == "# Draft\nSome content."
        assert restored.total_input_tokens == 500
        assert len(restored.messages) == 1
        assert restored.messages[0]["role"] == "generator"
        assert len(restored.citation_checks) == 1
        assert restored.workspace == "/tmp/test-workspace"
        assert restored.created_at == "2026-04-15T14:32:07Z"
        # Full equality
        assert restored == state

    def test_e1_s03_no_enum_objects_in_json(self) -> None:
        """Serialized dict contains only JSON primitives."""
        state = self._minimal()
        d = state.to_dict()
        json_str = json.dumps(d)  # TypeError if enums leaked
        assert '"INITIALIZING"' in json_str
        assert '"sha256"' in json_str

    def test_e1_s03_append_only_type_preserved(self) -> None:
        """AppendOnlyList type survives the round-trip."""
        state = self._minimal()
        json_str = json.dumps(state.to_dict())
        restored = FactoryState.from_dict(json.loads(json_str))
        assert isinstance(restored.messages, AppendOnlyList)
        assert isinstance(
            restored.citation_checks, AppendOnlyList,
        )


# ── E1-S22: Nested FactoryConfig reconstruction (D-2 §2, §6) ─


class TestNestedConfigReconstruction:
    """E1-S22: FactoryConfig inside FactoryState deserializes
    with correct types (CheckpointBackend enum, tuple)."""

    def test_e1_s22_custom_config_survives(self) -> None:
        """Non-default config fields round-trip correctly."""
        config = FactoryConfig(
            generator_model="test/gen-model",
            verifier_model="test/ver-model",
            reviser_model="test/rev-model",
            max_rejections=7,
            max_revisions=3,
            verifier_confidence_threshold=0.65,
            checkpoint_backend=CheckpointBackend.SQLITE,
            citation_check_sources=(
                "crossref", "semantic_scholar", "extra",
            ),
        )
        state = FactoryState(
            run_id="cfg-test",
            status=RunStatus.GENERATING,
            config=config,
            brief={"thesis": "Nested config test"},
            step_index=1,
            latest_hash="abc",
        )

        json_str = json.dumps(state.to_dict())
        restored = FactoryState.from_dict(
            json.loads(json_str),
        )
        rc = restored.config

        assert rc.generator_model == "test/gen-model"
        assert rc.verifier_model == "test/ver-model"
        assert rc.reviser_model == "test/rev-model"
        assert rc.max_rejections == 7
        assert rc.max_revisions == 3
        assert rc.verifier_confidence_threshold == 0.65
        # Enum type preserved
        assert rc.checkpoint_backend is CheckpointBackend.SQLITE
        assert isinstance(
            rc.checkpoint_backend, CheckpointBackend,
        )
        # Tuple type preserved (not list)
        assert rc.citation_check_sources == (
            "crossref", "semantic_scholar", "extra",
        )
        assert isinstance(rc.citation_check_sources, tuple)
        # Full config equality
        assert rc == config

    def test_e1_s22_default_config_survives(self) -> None:
        """All-default config round-trips identically."""
        state = FactoryState(
            run_id="default-cfg",
            status=RunStatus.INITIALIZING,
            config=FactoryConfig(),
            brief={"thesis": "t"},
            step_index=0,
            latest_hash="",
        )
        json_str = json.dumps(state.to_dict())
        restored = FactoryState.from_dict(
            json.loads(json_str),
        )
        assert restored.config == FactoryConfig()
