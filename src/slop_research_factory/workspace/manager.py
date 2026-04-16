# src/slop_research_factory/workspace/manager.py

"""
Workspace directory layout and atomic I/O — D-2 §13, D-9 §3.

Manages the on-disk workspace for a single pipeline run.
Every public write method guarantees:

- **Atomic writes:** temp file → fsync → ``os.replace``.
- **UTF-8 encoding** with **Unix newlines** (``\\n``).
- **Deterministic JSON:** sorted keys, 2-space indent.

Directory tree (D-2 §13)::

    {base_dir}/
      {run_id}/
        config.json
        state.json
        brief.json
        chain.json
        steps/
          0000_genesis/
          0001_generator/
          0002_verifier/
          ...
        rescue/
        output/
          paper.md
          hai_card.md
          manifest.json
          provenance_report.md

Crash recovery depends on ``state.json`` being atomically
updated.  The ``os.replace`` call is atomic on POSIX
filesystems when source and destination reside on the same
mount — ensured by writing the temp file into the same
directory as the target.

Spec references:
    D-2 §13  Workspace layout.
    D-5 §10  Crash recovery (relies on atomic state writes).
    D-9 §3   Setup and verification scripts.
"""

from __future__ import annotations

import contextlib
import dataclasses
import json
import logging
import os
import tempfile
from enum import Enum
from pathlib import Path
from typing import Any

from slop_research_factory.config import FactoryConfig
from slop_research_factory.types.enums import (
    CheckpointBackend,
    NodeName,
)
from slop_research_factory.types.state import FactoryState

__all__ = [
    "WorkspaceError",
    "WorkspaceManager",
    "WorkspaceNotInitializedError",
]

logger = logging.getLogger(__name__)

# Characters that must never appear in a run_id.

_UNSAFE_RUN_ID_CHARS: frozenset[str] = frozenset(
    "/\\\0",
)


# ── Errors ───────────────────────────────────────────────


class WorkspaceError(Exception):
    """Base error for workspace operations."""


class WorkspaceNotInitializedError(WorkspaceError):
    """Workspace directory does not exist.

    Raised when a read or write operation is attempted
    before :meth:`WorkspaceManager.initialize` has been
    called (or on a directory that was deleted).
    """


# ── Serialization helpers ────────────────────────────────


def _serialize_config(
    config: FactoryConfig,
) -> dict[str, Any]:
    """Serialize :class:`FactoryConfig` to a JSON dict.

    Enum fields are stored as their ``.value`` strings.
    """
    data: dict[str, Any] = {}
    for field in dataclasses.fields(config):
        value = getattr(config, field.name)
        if isinstance(value, Enum):
            value = value.value
        data[field.name] = value
    return data


def _deserialize_config(
    data: dict[str, Any],
) -> FactoryConfig:
    """Deserialize :class:`FactoryConfig` from a JSON dict.

    Handles enum and tuple coercion. Unknown keys are
    silently dropped for forward compatibility.
    """
    known = {
        f.name for f in dataclasses.fields(FactoryConfig)
    }
    kwargs: dict[str, Any] = {
        k: v for k, v in data.items() if k in known
    }

    # Enum coercion
    if "checkpoint_backend" in kwargs:
        kwargs["checkpoint_backend"] = CheckpointBackend(
            kwargs["checkpoint_backend"],
        )

    # JSON array > tuple
    if "citation_check_sources" in kwargs:
        kwargs["citation_check_sources"] = tuple(
            kwargs["citation_check_sources"],
        )

    return FactoryConfig(**kwargs)


# ── WorkspaceManager ────────────────────────────────────


class WorkspaceManager:
    """Manages one run's workspace directory and file I/O.

    Usage::

        ws = WorkspaceManager(Path("./workspaces"), "run-001")
        ws.initialize()
        ws.write_config(config)
        ws.write_brief(brief)
        ws.write_state(state)

    All write methods are atomic (temp + fsync + rename).
    All text files are UTF-8 with Unix newlines.

    Spec: D-2 §13, D-9 §3.
    """

    def __init__(
        self,
        base_dir: Path | str,
        run_id: str,
    ) -> None:
        if not run_id or not run_id.strip():
            raise ValueError("run_id must be non-empty")
        if run_id in (".", ".."):
            raise ValueError(
                f"run_id must not be '.' or '..', "
                f"got {run_id!r}"
            )
        if _UNSAFE_RUN_ID_CHARS & set(run_id):
            raise ValueError(
                "run_id contains unsafe characters: "
                f"{run_id!r}"
            )
        self._base_dir = Path(base_dir)
        self._run_id = run_id

    # ── Properties ───────────────────────────────────────

    @property
    def base_dir(self) -> Path:
        """Base workspace directory."""
        return self._base_dir

    @property
    def run_id(self) -> str:
        """Run identifier."""
        return self._run_id

    @property
    def run_dir(self) -> Path:
        """Root directory for this run."""
        return self._base_dir / self._run_id

    @property
    def steps_dir(self) -> Path:
        """Directory containing step sub-directories."""
        return self.run_dir / "steps"

    @property
    def rescue_dir(self) -> Path:
        """Directory for human rescue request/resolution files."""
        return self.run_dir / "rescue"

    @property
    def output_dir(self) -> Path:
        """Directory for final output artifacts."""
        return self.run_dir / "output"

    @property
    def state_path(self) -> Path:
        """Path to ``state.json``."""
        return self.run_dir / "state.json"

    @property
    def config_path(self) -> Path:
        """Path to ``config.json``."""
        return self.run_dir / "config.json"

    @property
    def brief_path(self) -> Path:
        """Path to ``brief.json``."""
        return self.run_dir / "brief.json"

    @property
    def chain_path(self) -> Path:
        """Path to ``chain.json`` (provenance chain)."""
        return self.run_dir / "chain.json"

    # ── Initialization ───────────────────────────────────

    def initialize(self) -> Path:
        """Create the full workspace directory tree.

        Idempotent — safe to call on an existing workspace.

        Returns:
            Path to the run directory.
        """
        for d in (
            self.run_dir,
            self.steps_dir,
            self.rescue_dir,
            self.output_dir,
        ):
            d.mkdir(parents=True, exist_ok=True)
        logger.info(
            "Workspace initialized: %s", self.run_dir,
        )
        return self.run_dir

    def _require_initialized(self) -> None:
        """Raise if the run directory does not exist."""
        if not self.run_dir.is_dir():
            raise WorkspaceNotInitializedError(
                f"Workspace not initialized: "
                f"{self.run_dir}. "
                f"Call initialize() first."
            )

    # ── Step directories ─────────────────────────────────

    @staticmethod
    def step_dir_name(
        step_index: int,
        node_name: NodeName,
    ) -> str:
        """Format step directory name.

        Returns ``'{step_index:04d}_{node_name}'``,
        e.g. ``'0002_VERIFICATION'`` (uses :attr:`NodeName.value`).
        """
        return f"{step_index:04d}_{node_name.value}"

    def step_dir(
        self,
        step_index: int,
        node_name: NodeName,
    ) -> Path:
        """Path to a step directory (may not exist yet)."""
        name = self.step_dir_name(step_index, node_name)
        return self.steps_dir / name

    def ensure_step_dir(
        self,
        step_index: int,
        node_name: NodeName,
    ) -> Path:
        """Create step directory if needed.

        Returns:
            Path to the step directory.
        """
        self._require_initialized()
        d = self.step_dir(step_index, node_name)
        d.mkdir(parents=True, exist_ok=True)
        return d

    def list_step_dirs(self) -> list[Path]:
        """List existing step directories in sorted order.

        Returns an empty list when no steps exist yet.
        """
        self._require_initialized()
        if not self.steps_dir.is_dir():
            return []
        return sorted(
            p for p in self.steps_dir.iterdir()
            if p.is_dir()
        )

    # ── Atomic I/O primitives ────────────────────────────

    def write_text(
        self,
        path: Path,
        content: str,
    ) -> None:
        """Atomic UTF-8 write with Unix newline normalization.

        Creates parent directories if they do not exist.
        Uses temp file → fsync → ``os.replace`` for POSIX
        atomicity.

        Args:
            path:    Target file path.
            content: Text content (``\\r\\n`` and ``\\r``
                     are normalized to ``\\n``).
        """
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        content = content.replace(
            "\r\n", "\n",
        ).replace("\r", "\n")

        fd, tmp = tempfile.mkstemp(
            dir=str(path.parent), prefix=".tmp_",
        )
        try:
            with os.fdopen(
                fd, "w", encoding="utf-8", newline="\n",
            ) as fh:
                fh.write(content)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp, str(path))
        except BaseException:
            with contextlib.suppress(OSError):
                os.unlink(tmp)
            raise

    def read_text(self, path: Path) -> str:
        """Read a UTF-8 text file.

        Args:
            path: File to read.

        Returns:
            File contents as a string.

        Raises:
            FileNotFoundError: If *path* does not exist.
        """
        return Path(path).read_text(encoding="utf-8")

    def write_json(
        self,
        path: Path,
        data: Any,
    ) -> None:
        """Atomic JSON write (sorted keys, 2-space indent).

        Delegates to :meth:`write_text` for atomicity and
        newline normalization.  A trailing newline is
        appended.
        """
        text = json.dumps(
            data,
            indent=2,
            ensure_ascii=False,
            sort_keys=True,
        )
        self.write_text(path, text + "\n")

    def read_json(self, path: Path) -> Any:
        """Read and parse a JSON file.

        Raises:
            FileNotFoundError: If *path* does not exist.
            json.JSONDecodeError: If contents are not valid
                JSON.
        """
        return json.loads(self.read_text(path))

    # ── State persistence ────────────────────────────────

    def write_state(self, state: FactoryState) -> None:
        """Atomically write ``state.json``.

        Uses ``FactoryState.to_dict()`` for complete
        serialization including all token counters,
        timestamps, and content fields.
        """
        self._require_initialized()
        self.write_json(self.state_path, state.to_dict())
        logger.debug(
            "State written: step=%d", state.step_index,
        )

    def read_state(self) -> FactoryState:
        """Read and deserialize ``state.json``.

        Uses ``FactoryState.from_dict()`` which handles
        enum coercion, tuple reconstruction, and
        AppendOnlyList wrapping.
        """
        self._require_initialized()
        data = self.read_json(self.state_path)
        if not isinstance(data, dict):
            raise WorkspaceError(
                "state.json must contain a JSON object"
            )
        return FactoryState.from_dict(data)

    # ── Config persistence ───────────────────────────────

    def write_config(self, config: FactoryConfig) -> None:
        """Atomically write ``config.json``."""
        self._require_initialized()
        self.write_json(
            self.config_path, _serialize_config(config),
        )

    def read_config(self) -> FactoryConfig:
        """Read and deserialize ``config.json``.

        Raises:
            WorkspaceNotInitializedError: If the workspace
                does not exist.
            FileNotFoundError: If ``config.json`` is absent.
            WorkspaceError: If the file is not a JSON object.
        """
        self._require_initialized()
        data = self.read_json(self.config_path)
        if not isinstance(data, dict):
            raise WorkspaceError(
                "config.json must contain a JSON object"
            )
        return _deserialize_config(data)

    # ── Brief persistence ────────────────────────────────

    def write_brief(
        self,
        brief: dict[str, Any],
    ) -> None:
        """Atomically write ``brief.json``."""
        self._require_initialized()
        self.write_json(self.brief_path, brief)

    def read_brief(self) -> dict[str, Any]:
        """Read and parse ``brief.json``.

        Raises:
            WorkspaceNotInitializedError: If the workspace
                does not exist.
            FileNotFoundError: If ``brief.json`` is absent.
            WorkspaceError: If the file is not a JSON object.
        """
        self._require_initialized()
        data = self.read_json(self.brief_path)
        if not isinstance(data, dict):
            raise WorkspaceError(
                "brief.json must contain a JSON object"
            )
        return data

    # ── Step artifact helpers ────────────────────────────

    def write_step_artifact(
        self,
        step_index: int,
        node_name: NodeName,
        filename: str,
        content: str,
    ) -> Path:
        """Write a text artifact into a step directory.

        Creates the step directory if it does not exist.

        Args:
            step_index: Zero-based step index.
            node_name:  Pipeline node.
            filename:   Artifact filename
                        (e.g. ``"prompt.txt"``).
            content:    Text content.

        Returns:
            Path to the written file.
        """
        step = self.ensure_step_dir(step_index, node_name)
        path = step / filename
        self.write_text(path, content)
        return path

    def read_step_artifact(
        self,
        step_index: int,
        node_name: NodeName,
        filename: str,
    ) -> str:
        """Read a text artifact from a step directory.

        Raises:
            FileNotFoundError: If the file does not exist.
        """
        self._require_initialized()
        path = (
            self.step_dir(step_index, node_name) / filename
        )
        return self.read_text(path)

    # ── Output helpers ───────────────────────────────────

    def write_output_file(
        self,
        filename: str,
        content: str,
    ) -> Path:
        """Write a file into the output directory.

        Returns:
            Path to the written file.
        """
        self._require_initialized()
        path = self.output_dir / filename
        self.write_text(path, content)
        return path

    def read_output_file(self, filename: str) -> str:
        """Read a file from the output directory.

        Raises:
            FileNotFoundError: If the file does not exist.
        """
        self._require_initialized()
        return self.read_text(self.output_dir / filename)

    # ── used by generator_node ───────────

    def drafts_path(self, filename: str) -> Path:
        """Return path inside the run's drafts directory.

        Creates the ``drafts/`` directory if needed.
        """
        drafts = self.run_dir / "drafts"
        drafts.mkdir(parents=True, exist_ok=True)
        return drafts / filename

    def write_bytes(
        self,
        path: Path,
        data: bytes,
    ) -> None:
        """Atomic binary write (temp + fsync + rename).

        Same atomicity guarantee as :meth:`write_text`.
        """
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(
            dir=str(path.parent), prefix=".tmp_",
        )
        try:
            with os.fdopen(fd, "wb") as fh:
                fh.write(data)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp, str(path))
        except BaseException:
            with contextlib.suppress(OSError):
                os.unlink(tmp)
            raise

    def relative(self, path: Path) -> str:
        """Return *path* relative to the run directory.

        Used for content_file_paths in seal metadata
        (D-5 §7).
        """
        return str(Path(path).relative_to(self.run_dir))

    def write_state_atomic(
        self,
        state: FactoryState,
    ) -> None:
        """Alias for :meth:`write_state`.

        Named explicitly for call sites that emphasize
        the atomicity contract (D-5 §10).
        """
        self.write_state(state)
