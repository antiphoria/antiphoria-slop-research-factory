# tests/unit/test_manager.py

"""
Unit tests for workspace/manager.py.

Covers:
  - Construction and run_id validation.
  - Path properties.
  - Directory initialization (idempotent).
  - Step directory naming, creation, listing.
  - Atomic write: UTF-8, Unix newlines, overwrite safety,

    temp-file cleanup on failure.
  - JSON round-trip: sorted keys, indent, trailing newline.
  - State serialization round-trip (enums, config, counters).
  - Config serialization round-trip (CheckpointBackend enum, None optionals).
  - Brief round-trip.
  - Step artifact read/write.
  - Output file read/write.
  - WorkspaceNotInitializedError guard.

Spec references:
    D-2 §13  Workspace layout.
    D-5 §10  Crash recovery (atomic state writes).
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from slop_research_factory.config import FactoryConfig
from slop_research_factory.types.enums import (
    CheckpointBackend,
    NodeName,
    RunStatus,
)
from slop_research_factory.types.state import FactoryState
from slop_research_factory.workspace.manager import (
    WorkspaceError,
    WorkspaceManager,
    WorkspaceNotInitializedError,
)


# ── Fixtures ─────────────────────────────────────────────


@pytest.fixture()
def ws(tmp_path: Path) -> WorkspaceManager:
    """Initialized workspace manager."""
    mgr = WorkspaceManager(tmp_path, "test-run-001")
    mgr.initialize()
    return mgr


@pytest.fixture()
def ws_uninit(tmp_path: Path) -> WorkspaceManager:
    """Uninitialized workspace manager."""
    return WorkspaceManager(tmp_path, "test-run-001")


# ── Helpers ──────────────────────────────────────────────


def _make_config(**overrides: object) -> FactoryConfig:
    defaults: dict[str, object] = dict(
        max_rejections=3,
        max_revisions=5,
        max_total_cycles=10,
        max_total_tokens=500_000,
        max_total_cost_usd=5.0,
        verifier_confidence_threshold=0.8,
        generator_model="claude-sonnet-4-20250514",
        verifier_model="claude-sonnet-4-20250514",
        reviser_model="claude-sonnet-4-20250514",
    )
    defaults.update(overrides)
    return FactoryConfig(**defaults)  # type: ignore[arg-type]


def _make_state(**overrides: object) -> FactoryState:
    defaults: dict[str, object] = dict(
        run_id="test-run-001",
        status=RunStatus.GENERATING,
        config=_make_config(),
        brief={"thesis": "Test thesis", "tags": ["ai"]},
        step_index=2,
        latest_hash="abc123",
        rejection_count=1,
        revision_count=2,
        cycle_count=3,
        total_input_tokens=5000,
        total_output_tokens=10000,
        total_estimated_cost_usd=0.25,
    )
    defaults.update(overrides)
    return FactoryState(**defaults)  # type: ignore[arg-type]


# ── Construction ─────────────────────────────────────────


class TestWorkspaceManagerConstruction:
    """Constructor validation."""

    def test_valid_construction(
        self, tmp_path: Path,
    ) -> None:
        mgr = WorkspaceManager(tmp_path, "my-run-42")
        assert mgr.run_id == "my-run-42"
        assert mgr.base_dir == tmp_path

    def test_accepts_str_base_dir(
        self, tmp_path: Path,
    ) -> None:
        mgr = WorkspaceManager(str(tmp_path), "run-001")
        assert mgr.base_dir == tmp_path

    def test_empty_run_id_rejected(
        self, tmp_path: Path,
    ) -> None:
        with pytest.raises(ValueError, match="run_id"):
            WorkspaceManager(tmp_path, "")

    def test_whitespace_run_id_rejected(
        self, tmp_path: Path,
    ) -> None:
        with pytest.raises(ValueError, match="run_id"):
            WorkspaceManager(tmp_path, "   ")

    def test_dot_run_id_rejected(
        self, tmp_path: Path,
    ) -> None:
        with pytest.raises(ValueError, match="run_id"):
            WorkspaceManager(tmp_path, ".")

    def test_dotdot_run_id_rejected(
        self, tmp_path: Path,
    ) -> None:
        with pytest.raises(ValueError, match="run_id"):
            WorkspaceManager(tmp_path, "..")

    def test_slash_in_run_id_rejected(
        self, tmp_path: Path,
    ) -> None:
        with pytest.raises(ValueError, match="unsafe"):
            WorkspaceManager(tmp_path, "a/b")

    def test_backslash_in_run_id_rejected(
        self, tmp_path: Path,
    ) -> None:
        with pytest.raises(ValueError, match="unsafe"):
            WorkspaceManager(tmp_path, "a\\b")

    def test_null_in_run_id_rejected(
        self, tmp_path: Path,
    ) -> None:
        with pytest.raises(ValueError, match="unsafe"):
            WorkspaceManager(tmp_path, "a\0b")


# ── Path properties ──────────────────────────────────────


class TestWorkspaceManagerPaths:
    """Path composition correctness."""

    def test_run_dir(self, ws: WorkspaceManager) -> None:
        assert ws.run_dir == ws.base_dir / "test-run-001"

    def test_steps_dir(
        self, ws: WorkspaceManager,
    ) -> None:
        assert ws.steps_dir == ws.run_dir / "steps"

    def test_rescue_dir(
        self, ws: WorkspaceManager,
    ) -> None:
        assert ws.rescue_dir == ws.run_dir / "rescue"

    def test_output_dir(
        self, ws: WorkspaceManager,
    ) -> None:
        assert ws.output_dir == ws.run_dir / "output"

    def test_state_path(
        self, ws: WorkspaceManager,
    ) -> None:
        assert ws.state_path == ws.run_dir / "state.json"

    def test_config_path(
        self, ws: WorkspaceManager,
    ) -> None:
        assert ws.config_path == ws.run_dir / "config.json"

    def test_brief_path(
        self, ws: WorkspaceManager,
    ) -> None:
        assert ws.brief_path == ws.run_dir / "brief.json"

    def test_chain_path(
        self, ws: WorkspaceManager,
    ) -> None:
        assert ws.chain_path == ws.run_dir / "chain.json"


# ── Initialization ───────────────────────────────────────


class TestWorkspaceManagerInitialize:
    """Directory tree creation."""

    def test_creates_all_directories(
        self, ws: WorkspaceManager,
    ) -> None:
        assert ws.run_dir.is_dir()
        assert ws.steps_dir.is_dir()
        assert ws.rescue_dir.is_dir()
        assert ws.output_dir.is_dir()

    def test_idempotent(
        self, ws: WorkspaceManager,
    ) -> None:
        """Calling initialize twice raises no errors."""
        ws.initialize()
        assert ws.run_dir.is_dir()

    def test_returns_run_dir(
        self, tmp_path: Path,
    ) -> None:
        mgr = WorkspaceManager(tmp_path, "run-ret")
        result = mgr.initialize()
        assert result == mgr.run_dir
        assert result.is_dir()


# ── Step directories ─────────────────────────────────────


class TestWorkspaceManagerStepDir:
    """Step directory naming and creation."""

    def test_step_dir_name_brief(self) -> None:
        name = WorkspaceManager.step_dir_name(
            0, NodeName.BRIEF,
        )
        assert name == "0000_BRIEF"

    def test_step_dir_name_generator(self) -> None:
        name = WorkspaceManager.step_dir_name(
            1, NodeName.GENERATOR,
        )
        assert name == "0001_GENERATOR"

    def test_step_dir_name_verification(self) -> None:
        name = WorkspaceManager.step_dir_name(
            12, NodeName.VERIFICATION,
        )
        assert name == "0012_VERIFICATION"

    def test_step_dir_name_generator_high_index(self) -> None:
        name = WorkspaceManager.step_dir_name(
            99, NodeName.GENERATOR,
        )
        assert name == "0099_GENERATOR"

    def test_step_dir_path(
        self, ws: WorkspaceManager,
    ) -> None:
        path = ws.step_dir(3, NodeName.VERIFICATION)
        expected = ws.steps_dir / "0003_VERIFICATION"
        assert path == expected

    def test_ensure_step_dir_creates(
        self, ws: WorkspaceManager,
    ) -> None:
        path = ws.ensure_step_dir(0, NodeName.BRIEF)
        assert path.is_dir()
        assert path.name == "0000_BRIEF"

    def test_ensure_step_dir_idempotent(
        self, ws: WorkspaceManager,
    ) -> None:
        p1 = ws.ensure_step_dir(0, NodeName.BRIEF)
        p2 = ws.ensure_step_dir(0, NodeName.BRIEF)
        assert p1 == p2
        assert p1.is_dir()

    def test_list_step_dirs_empty(
        self, ws: WorkspaceManager,
    ) -> None:
        assert ws.list_step_dirs() == []

    def test_list_step_dirs_sorted(
        self, ws: WorkspaceManager,
    ) -> None:
        ws.ensure_step_dir(2, NodeName.VERIFICATION)
        ws.ensure_step_dir(0, NodeName.BRIEF)
        ws.ensure_step_dir(1, NodeName.GENERATOR)
        dirs = ws.list_step_dirs()
        names = [d.name for d in dirs]
        assert names == [
            "0000_BRIEF",
            "0001_GENERATOR",
            "0002_VERIFICATION",
        ]

    def test_list_step_dirs_ignores_files(
        self, ws: WorkspaceManager,
    ) -> None:
        ws.ensure_step_dir(0, NodeName.BRIEF)
        (ws.steps_dir / "stray_file.txt").write_text("x")
        dirs = ws.list_step_dirs()
        assert len(dirs) == 1


# ── Atomic write ─────────────────────────────────────────


class TestWorkspaceManagerWriteText:
    """Atomic UTF-8 writes with Unix newlines."""

    def test_writes_content(
        self, ws: WorkspaceManager,
    ) -> None:
        path = ws.run_dir / "test.txt"
        ws.write_text(path, "hello world")
        assert ws.read_text(path) == "hello world"

    def test_utf8_encoding(
        self, ws: WorkspaceManager,
    ) -> None:
        path = ws.run_dir / "utf8.txt"
        ws.write_text(path, "日本語テスト 🎉")
        raw = path.read_bytes()
        assert raw.decode("utf-8") == "日本語テスト 🎉"

    def test_normalizes_crlf_to_lf(
        self, ws: WorkspaceManager,
    ) -> None:
        path = ws.run_dir / "crlf.txt"
        ws.write_text(path, "line1\r\nline2\r\n")
        raw = path.read_bytes()
        assert b"\r" not in raw
        assert raw == b"line1\nline2\n"

    def test_normalizes_cr_to_lf(
        self, ws: WorkspaceManager,
    ) -> None:
        path = ws.run_dir / "cr.txt"
        ws.write_text(path, "line1\rline2\r")
        raw = path.read_bytes()
        assert b"\r" not in raw
        assert raw == b"line1\nline2\n"

    def test_overwrites_existing(
        self, ws: WorkspaceManager,
    ) -> None:
        path = ws.run_dir / "over.txt"
        ws.write_text(path, "original")
        ws.write_text(path, "updated")
        assert ws.read_text(path) == "updated"

    def test_creates_parent_dirs(
        self, ws: WorkspaceManager,
    ) -> None:
        path = ws.run_dir / "sub" / "deep" / "file.txt"
        ws.write_text(path, "nested")
        assert ws.read_text(path) == "nested"

    def test_failed_write_preserves_original(
        self,
        ws: WorkspaceManager,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Atomic guarantee: original survives failed write."""
        path = ws.run_dir / "safe.txt"
        ws.write_text(path, "original")

        def _bad_replace(*args: object) -> None:
            raise OSError("simulated replace failure")

        monkeypatch.setattr(os, "replace", _bad_replace)
        with pytest.raises(OSError, match="simulated"):
            ws.write_text(path, "should not appear")

        monkeypatch.undo()
        assert ws.read_text(path) == "original"

    def test_temp_file_cleaned_on_failure(
        self,
        ws: WorkspaceManager,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """No leftover .tmp_ files after failure."""
        path = ws.run_dir / "clean.txt"

        def _bad_replace(*args: object) -> None:
            raise OSError("simulated")

        monkeypatch.setattr(os, "replace", _bad_replace)
        with pytest.raises(OSError):
            ws.write_text(path, "content")

        tmp_files = list(ws.run_dir.glob(".tmp_*"))
        assert tmp_files == []


# ── JSON ─────────────────────────────────────────────────


class TestWorkspaceManagerJson:
    """JSON read/write with formatting guarantees."""

    def test_roundtrip(
        self, ws: WorkspaceManager,
    ) -> None:
        path = ws.run_dir / "data.json"
        original = {"key": "value", "num": 42, "nil": None}
        ws.write_json(path, original)
        assert ws.read_json(path) == original

    def test_sorted_keys(
        self, ws: WorkspaceManager,
    ) -> None:
        path = ws.run_dir / "sorted.json"
        ws.write_json(path, {"z": 1, "a": 2, "m": 3})
        text = ws.read_text(path)
        pos_a = text.index('"a"')
        pos_m = text.index('"m"')
        pos_z = text.index('"z"')
        assert pos_a < pos_m < pos_z

    def test_pretty_printed(
        self, ws: WorkspaceManager,
    ) -> None:
        path = ws.run_dir / "pretty.json"
        ws.write_json(path, {"key": "value"})
        text = ws.read_text(path)
        assert "\n" in text
        assert '  "key"' in text

    def test_trailing_newline(
        self, ws: WorkspaceManager,
    ) -> None:
        path = ws.run_dir / "trail.json"
        ws.write_json(path, {"a": 1})
        raw = path.read_bytes()
        assert raw.endswith(b"\n")

    def test_unicode_preserved(
        self, ws: WorkspaceManager,
    ) -> None:
        path = ws.run_dir / "uni.json"
        ws.write_json(path, {"emoji": "🔬", "kanji": "研究"})
        data = ws.read_json(path)
        assert data["emoji"] == "🔬"
        assert data["kanji"] == "研究"

    def test_read_json_file_not_found(
        self, ws: WorkspaceManager,
    ) -> None:
        with pytest.raises(FileNotFoundError):
            ws.read_json(ws.run_dir / "missing.json")

    def test_nested_structure(
        self, ws: WorkspaceManager,
    ) -> None:
        path = ws.run_dir / "nested.json"
        original = {
            "outer": {"inner": [1, 2, {"deep": True}]},
        }
        ws.write_json(path, original)
        assert ws.read_json(path) == original


# ── State round-trip ─────────────────────────────────────


class TestWorkspaceManagerState:
    """State serialization and deserialization."""

    def test_roundtrip(
        self, ws: WorkspaceManager,
    ) -> None:
        original = _make_state()
        ws.write_state(original)
        restored = ws.read_state()
        assert restored.run_id == original.run_id
        assert restored.step_index == original.step_index
        assert restored.latest_hash == original.latest_hash

    def test_run_status_enum_preserved(
        self, ws: WorkspaceManager,
    ) -> None:
        for status in RunStatus:
            state = _make_state(status=status)
            ws.write_state(state)
            restored = ws.read_state()
            assert restored.status is status

    def test_config_preserved(
        self, ws: WorkspaceManager,
    ) -> None:
        config = _make_config(
            max_rejections=7,
            max_total_tokens=None,
            max_total_cost_usd=None,
            checkpoint_backend=CheckpointBackend.POSTGRES,
        )
        state = _make_state(config=config)
        ws.write_state(state)
        restored = ws.read_state()
        assert restored.config.max_rejections == 7
        assert restored.config.max_total_tokens is None
        assert restored.config.max_total_cost_usd is None
        assert (
            restored.config.checkpoint_backend
            is CheckpointBackend.POSTGRES
        )

    def test_counters_preserved(
        self, ws: WorkspaceManager,
    ) -> None:
        state = _make_state(
            rejection_count=5,
            revision_count=3,
            cycle_count=8,
            total_input_tokens=123456,
            total_output_tokens=789012,
            total_estimated_cost_usd=4.56,
        )
        ws.write_state(state)
        restored = ws.read_state()
        assert restored.rejection_count == 5
        assert restored.revision_count == 3
        assert restored.cycle_count == 8
        assert restored.total_input_tokens == 123456
        assert restored.total_output_tokens == 789012
        assert restored.total_estimated_cost_usd == 4.56

    def test_brief_dict_preserved(
        self, ws: WorkspaceManager,
    ) -> None:
        brief = {
            "thesis": "Complex topic",
            "tags": ["ml", "nlp"],
            "nested": {"key": "val"},
        }
        state = _make_state(brief=brief)
        ws.write_state(state)
        restored = ws.read_state()
        assert restored.brief == brief

    def test_default_counters_zero(
        self, ws: WorkspaceManager,
    ) -> None:
        """Counters default to zero if absent in JSON."""
        state = _make_state(
            rejection_count=0,
            revision_count=0,
            cycle_count=0,
            total_input_tokens=0,
            total_output_tokens=0,
            total_estimated_cost_usd=0.0,
        )
        ws.write_state(state)
        restored = ws.read_state()
        assert restored.rejection_count == 0
        assert restored.total_estimated_cost_usd == 0.0

    def test_state_json_is_valid_json(
        self, ws: WorkspaceManager,
    ) -> None:
        """state.json can be parsed by stdlib json."""
        ws.write_state(_make_state())
        data = ws.read_json(ws.state_path)
        assert isinstance(data, dict)
        assert data["status"] == "GENERATING"

    def test_state_not_json_object_raises(
        self, ws: WorkspaceManager,
    ) -> None:
        """state.json containing an array → WorkspaceError."""
        ws.write_json(ws.state_path, [1, 2, 3])
        with pytest.raises(
            WorkspaceError, match="JSON object",
        ):
            ws.read_state()


# ── Config round-trip ────────────────────────────────────


class TestWorkspaceManagerConfig:
    """Config serialization and deserialization."""

    def test_roundtrip(
        self, ws: WorkspaceManager,
    ) -> None:
        original = _make_config()
        ws.write_config(original)
        restored = ws.read_config()
        assert restored.max_rejections == 3
        assert restored.max_revisions == 5
        assert (
            restored.verifier_confidence_threshold == 0.8
        )

    def test_checkpoint_backend_enum_roundtrip(
        self, ws: WorkspaceManager,
    ) -> None:
        for backend in CheckpointBackend:
            config = _make_config(
                checkpoint_backend=backend,
            )
            ws.write_config(config)
            restored = ws.read_config()
            assert (
                restored.checkpoint_backend is backend
            )

    def test_none_optional_fields(
        self, ws: WorkspaceManager,
    ) -> None:
        config = _make_config(
            max_total_tokens=None,
            max_total_cost_usd=None,
        )
        ws.write_config(config)
        restored = ws.read_config()
        assert restored.max_total_tokens is None
        assert restored.max_total_cost_usd is None

    def test_all_model_fields_preserved(
        self, ws: WorkspaceManager,
    ) -> None:
        config = _make_config(
            generator_model="model-gen",
            verifier_model="model-ver",
            reviser_model="model-rev",
        )
        ws.write_config(config)
        restored = ws.read_config()
        assert restored.generator_model == "model-gen"
        assert restored.verifier_model == "model-ver"
        assert restored.reviser_model == "model-rev"

    def test_config_not_json_object_raises(
        self, ws: WorkspaceManager,
    ) -> None:
        ws.write_json(ws.config_path, "not an object")
        with pytest.raises(
            WorkspaceError, match="JSON object",
        ):
            ws.read_config()

    def test_unknown_keys_ignored(
        self, ws: WorkspaceManager,
    ) -> None:
        """Forward compatibility: unknown keys are dropped."""
        config = _make_config()
        ws.write_config(config)
        data = ws.read_json(ws.config_path)
        data["future_field"] = "unknown"
        ws.write_json(ws.config_path, data)
        restored = ws.read_config()
        assert not hasattr(restored, "future_field")
        assert restored.max_rejections == 3


# ── Brief round-trip ─────────────────────────────────────


class TestWorkspaceManagerBrief:
    """Brief serialization and deserialization."""

    def test_roundtrip(
        self, ws: WorkspaceManager,
    ) -> None:
        brief = {"thesis": "AI safety", "depth": "survey"}
        ws.write_brief(brief)
        assert ws.read_brief() == brief

    def test_nested_dict_preserved(
        self, ws: WorkspaceManager,
    ) -> None:
        brief = {
            "thesis": "Complex",
            "constraints": {
                "max_pages": 10,
                "required_sections": ["intro", "methods"],
            },
        }
        ws.write_brief(brief)
        restored = ws.read_brief()
        assert (
            restored["constraints"]["max_pages"] == 10
        )

    def test_brief_not_json_object_raises(
        self, ws: WorkspaceManager,
    ) -> None:
        ws.write_json(ws.brief_path, [1, 2])
        with pytest.raises(
            WorkspaceError, match="JSON object",
        ):
            ws.read_brief()


# ── Step artifacts ───────────────────────────────────────


class TestWorkspaceManagerStepArtifact:
    """Step directory artifact read/write."""

    def test_write_and_read(
        self, ws: WorkspaceManager,
    ) -> None:
        ws.write_step_artifact(
            0, NodeName.GENERATOR, "prompt.txt",
            "You are a research assistant.",
        )
        content = ws.read_step_artifact(
            0, NodeName.GENERATOR, "prompt.txt",
        )
        assert content == "You are a research assistant."

    def test_creates_step_dir(
        self, ws: WorkspaceManager,
    ) -> None:
        ws.write_step_artifact(
            5, NodeName.VERIFICATION, "output.md", "# Draft",
        )
        step = ws.step_dir(5, NodeName.VERIFICATION)
        assert step.is_dir()

    def test_returns_file_path(
        self, ws: WorkspaceManager,
    ) -> None:
        path = ws.write_step_artifact(
            0, NodeName.BRIEF, "seal_pre.json", "{}",
        )
        assert path.name == "seal_pre.json"
        assert path.parent.name == "0000_BRIEF"

    def test_read_missing_artifact_raises(
        self, ws: WorkspaceManager,
    ) -> None:
        with pytest.raises(FileNotFoundError):
            ws.read_step_artifact(
                99, NodeName.GENERATOR, "nope.txt",
            )


# ── Output files ─────────────────────────────────────────


class TestWorkspaceManagerOutputFile:
    """Output directory file read/write."""

    def test_write_and_read(
        self, ws: WorkspaceManager,
    ) -> None:
        ws.write_output_file("paper.md", "# My Paper\n")
        content = ws.read_output_file("paper.md")
        assert content == "# My Paper\n"

    def test_returns_file_path(
        self, ws: WorkspaceManager,
    ) -> None:
        path = ws.write_output_file("hai_card.md", "card")
        assert path == ws.output_dir / "hai_card.md"

    def test_read_missing_output_raises(
        self, ws: WorkspaceManager,
    ) -> None:
        with pytest.raises(FileNotFoundError):
            ws.read_output_file("missing.md")


# ── Not-initialized guard ───────────────────────────────


class TestWorkspaceNotInitialized:
    """Operations fail cleanly on uninitialized workspace."""

    def test_write_state_raises(
        self, ws_uninit: WorkspaceManager,
    ) -> None:
        with pytest.raises(WorkspaceNotInitializedError):
            ws_uninit.write_state(_make_state())

    def test_read_state_raises(
        self, ws_uninit: WorkspaceManager,
    ) -> None:
        with pytest.raises(WorkspaceNotInitializedError):
            ws_uninit.read_state()

    def test_write_config_raises(
        self, ws_uninit: WorkspaceManager,
    ) -> None:
        with pytest.raises(WorkspaceNotInitializedError):
            ws_uninit.write_config(_make_config())

    def test_read_config_raises(
        self, ws_uninit: WorkspaceManager,
    ) -> None:
        with pytest.raises(WorkspaceNotInitializedError):
            ws_uninit.read_config()

    def test_write_brief_raises(
        self, ws_uninit: WorkspaceManager,
    ) -> None:
        with pytest.raises(WorkspaceNotInitializedError):
            ws_uninit.write_brief({"thesis": "x"})

    def test_read_brief_raises(
        self, ws_uninit: WorkspaceManager,
    ) -> None:
        with pytest.raises(WorkspaceNotInitializedError):
            ws_uninit.read_brief()

    def test_ensure_step_dir_raises(
        self, ws_uninit: WorkspaceManager,
    ) -> None:
        with pytest.raises(WorkspaceNotInitializedError):
            ws_uninit.ensure_step_dir(
                0, NodeName.BRIEF,
            )

    def test_list_step_dirs_raises(
        self, ws_uninit: WorkspaceManager,
    ) -> None:
        with pytest.raises(WorkspaceNotInitializedError):
            ws_uninit.list_step_dirs()

    def test_write_output_file_raises(
        self, ws_uninit: WorkspaceManager,
    ) -> None:
        with pytest.raises(WorkspaceNotInitializedError):
            ws_uninit.write_output_file("x.md", "y")

    def test_read_output_file_raises(
        self, ws_uninit: WorkspaceManager,
    ) -> None:
        with pytest.raises(WorkspaceNotInitializedError):
            ws_uninit.read_output_file("x.md")
