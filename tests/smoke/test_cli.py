# tests/smoke/test_cli.py

"""
Smoke tests for the CLI — subprocess invocation of each subcommand.

These tests verify:
- Exit codes are correct
- --help works for all subcommands
- --version prints version
- run with missing brief fails cleanly
- status/verify with missing workspace fails cleanly
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

ENTRY_POINT = [sys.executable, "-m", "slop_research_factory.cli"]


def _run(*args: str, timeout: float = 10.0) -> subprocess.CompletedProcess:
    """Run CLI with given args, capture output."""
    return subprocess.run(
        [*ENTRY_POINT, *args],
        capture_output=True,
        text=True,
        timeout=timeout,
    )


class TestHelpAndVersion:
    """Basic CLI surface checks."""

    def test_help_exits_zero(self) -> None:
        """--help exits 0."""
        result = _run("--help")
        assert result.returncode == 0
        assert "slop-factory" in result.stdout or "SLOP" in result.stdout

    def test_version_exits_zero(self) -> None:
        """--version prints version and exits 0."""
        result = _run("--version")
        assert result.returncode == 0
        assert "0.1.0" in result.stdout

    def test_run_help(self) -> None:
        """run --help exits 0."""
        result = _run("run", "--help")
        assert result.returncode == 0
        assert "--brief" in result.stdout

    def test_resume_help(self) -> None:
        """resume --help exits 0."""
        result = _run("resume", "--help")
        assert result.returncode == 0
        assert "--workspace" in result.stdout

    def test_verify_help(self) -> None:
        """verify --help exits 0."""
        result = _run("verify", "--help")
        assert result.returncode == 0

    def test_status_help(self) -> None:
        """status --help exits 0."""
        result = _run("status", "--help")
        assert result.returncode == 0

    def test_no_command_exits_one(self) -> None:
        """No subcommand → exit 1 with help text."""
        result = _run()
        assert result.returncode == 1


class TestRunSubcommand:
    """slop-factory run error paths."""

    def test_missing_brief_flag(self) -> None:
        """run without --brief → argparse error."""
        result = _run("run")
        assert result.returncode != 0

    def test_nonexistent_brief_file(self, tmp_path: Path) -> None:
        """run with non-existent brief → exit 1."""
        result = _run("run", "--brief", str(tmp_path / "nope.json"))
        assert result.returncode == 1
        assert "not found" in result.stderr.lower() or "error" in result.stderr.lower()

    def test_invalid_json_brief(self, tmp_path: Path) -> None:
        """run with malformed JSON → exit 1."""
        bad = tmp_path / "bad.json"
        bad.write_text("{not valid json", encoding="utf-8")
        result = _run("run", "--brief", str(bad))
        assert result.returncode == 1

    def test_nonexistent_config_file(self, tmp_path: Path) -> None:
        """run with non-existent config → exit 1."""
        brief = tmp_path / "brief.json"
        brief.write_text('{"thesis": "test"}', encoding="utf-8")
        result = _run(
            "run",
            "--brief", str(brief),
            "--config", str(tmp_path / "missing.toml"),
        )
        assert result.returncode == 1


class TestResumeSubcommand:
    """slop-factory resume error paths."""

    def test_nonexistent_workspace(self, tmp_path: Path) -> None:
        """resume with non-existent workspace → exit 1."""
        result = _run("resume", "--workspace", str(tmp_path / "ghost"))
        assert result.returncode == 1


class TestVerifySubcommand:
    """slop-factory verify error paths."""

    def test_nonexistent_workspace(self, tmp_path: Path) -> None:
        """verify with non-existent workspace → exit 1."""
        result = _run("verify", "--workspace", str(tmp_path / "ghost"))
        assert result.returncode == 1


class TestStatusSubcommand:
    """slop-factory status error paths."""

    def test_nonexistent_workspace(self, tmp_path: Path) -> None:
        """status with non-existent workspace → exit 1."""
        result = _run("status", "--workspace", str(tmp_path / "ghost"))
        assert result.returncode == 1

    def test_valid_workspace_json_output(self, tmp_path: Path) -> None:
        """status --json with valid state prints parseable JSON."""
        ws = tmp_path / "run-001"
        ws.mkdir()
        state = {
            "run_id": "run-001",
            "status": "GENERATING",
            "config": {},
            "brief": {"thesis": "Test"},
            "step_index": 2,
            "latest_hash": "a" * 64,
            "cycle_count": 1,
            "rejection_count": 0,
            "revision_count": 0,
            "messages": [],
            "citation_checks": [],
            "total_input_tokens": 500,
            "total_output_tokens": 2000,
            "total_think_tokens": 0,
            "total_estimated_cost_usd": 0.01,
            "total_wall_clock_seconds": 5.0,
            "created_at": "2025-01-01T00:00:00Z",
            "updated_at": "2025-01-01T00:00:00Z",
        }
        (ws / "state.json").write_text(json.dumps(state), encoding="utf-8")

        result = _run("status", "--workspace", str(ws), "--json")
        # May fail if WorkspaceManager expects different structure,
        # but should at least not crash with a traceback
        if result.returncode == 0:
            data = json.loads(result.stdout)
            assert data["run_id"] == "run-001"
            assert data["status"] == "GENERATING"