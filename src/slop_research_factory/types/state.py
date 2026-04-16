# src/slop_research_factory/types/state.py

"""
FactoryState and AppendOnlyList — D-2 §6.

Core orchestration state that flows through every LangGraph node.
Serialized to ``{workspace}/state.json`` after each node execution.

Mutation contract (enforced by orchestrator, not this module):
  run_id, config, brief     — immutable after creation
  step_index                — increment-only
  latest_hash               — write-after-seal-only
  messages, citation_checks — append-only (AppendOnlyList)
  total_*                   — increment-only
  status                    — forward-only transitions (D-2 §3.3)
"""
from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from slop_research_factory.config import FactoryConfig
from slop_research_factory.types.enums import (
    CheckpointBackend,
    RunStatus,
)

__all__ = ["AppendOnlyList", "FactoryState"]


# ── AppendOnlyList ────────────────────────────────────────────


class AppendOnlyList(list[Any]):
    """``list`` subclass forbidding overwrite, delete, non-tail insert.

    D-2 §6 requires ``messages`` and ``citation_checks`` to be
    append-only.  This wrapper enforces that contract at runtime.

    Permitted operations: ``append``, ``extend``, ``insert(len, v)``.
    Forbidden: ``__setitem__``, ``__delitem__``, ``insert(i, v)``
    where ``i != len(self)``.
    """

    def __setitem__(self, key: Any, value: Any) -> None:
        raise TypeError(
            "AppendOnlyList does not support item reassignment"
        )

    def __delitem__(self, key: Any) -> None:
        raise TypeError(
            "AppendOnlyList does not support deletion"
        )

    def insert(self, index: int, value: Any) -> None:
        if index != len(self):
            raise TypeError(
                "AppendOnlyList only permits append-at-end"
            )
        super().insert(index, value)

    def pop(self, *a):
        raise TypeError("AppendOnlyList does not support pop")

    def remove(self, *a):
        raise TypeError("AppendOnlyList does not support removal")

    def clear(self):
        raise TypeError("AppendOnlyList does not support clear")

    def reverse(self):
        raise TypeError("AppendOnlyList does not support reordering")

    def sort(self, *a, **kw):
        raise TypeError("AppendOnlyList does not support reordering")


# ── FactoryState ──────────────────────────────────────────────


@dataclass
class FactoryState:
    """Central state object flowing through every LangGraph node.

    D-2 §6.  Dataclass (not Pydantic) because it is produced
    exclusively by factory code, never by an LLM.
    """

    # --- Identity (immutable after creation) ---------------
    run_id: str
    status: RunStatus
    config: FactoryConfig
    brief: dict[str, Any]

    # --- Provenance chain ----------------------------------
    step_index: int
    latest_hash: str

    # --- Loop counters -------------------------------------
    cycle_count: int = 0
    rejection_count: int = 0
    revision_count: int = 0

    # --- Content -------------------------------------------
    current_draft: str | None = None
    current_think_trace: str | None = None
    current_critique: dict[str, Any] | None = None
    current_extracted_citations: list[dict[str, Any]] = field(
        default_factory=list,
    )

    # --- Running totals / budget enforcement ---------------
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    total_think_tokens: int = 0
    total_tool_call_seconds: float = 0.0
    total_wall_clock_seconds: float = 0.0
    total_estimated_cost_usd: float = 0.0

    # --- Message history (append-only, D-2 §6) -------------
    messages: list[dict[str, Any]] = field(
        default_factory=AppendOnlyList,
    )

    # --- Discovered citations (append-only, D-2 §6) --------
    citation_checks: list[dict[str, Any]] = field(
        default_factory=AppendOnlyList,
    )

    # --- Workspace path ------------------------------------
    workspace: str = ""

    # --- Timestamps (ISO 8601 UTC) -------------------------
    created_at: str = ""
    updated_at: str = ""

    # --- Error tracking ------------------------------------
    last_error: str | None = None

    # ── Serialization ─────────────────────────────────────

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a JSON-compatible plain ``dict``.

        Enums → ``.value`` (D-2 §3).
        Tuples → lists (JSON has no tuple type, D-2 §2).
        """
        return _deep_serialize(dataclasses.asdict(self))

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> FactoryState:
        """Reconstruct from a JSON-parsed ``dict``.

        D-2 §6 crash-recovery contract: nested ``FactoryConfig``,
        ``RunStatus`` enum, and ``AppendOnlyList`` wrappers are
        rebuilt explicitly.
        """
        data: dict[str, Any] = dict(raw)

        # ── Nested FactoryConfig ──────────────────────────
        config_raw: dict[str, Any] = dict(data.pop("config"))
        if "checkpoint_backend" in config_raw:
            config_raw["checkpoint_backend"] = CheckpointBackend(
                config_raw["checkpoint_backend"],
            )
        if "citation_check_sources" in config_raw:
            config_raw["citation_check_sources"] = tuple(
                config_raw["citation_check_sources"],
            )
        config = FactoryConfig(**config_raw)

        # ── RunStatus enum ────────────────────────────────
        status = RunStatus(data.pop("status"))

        # ── AppendOnlyList fields ─────────────────────────
        messages = AppendOnlyList(data.pop("messages", []))
        citation_checks = AppendOnlyList(
            data.pop("citation_checks", []),
        )

        return cls(
            config=config,
            status=status,
            messages=messages,
            citation_checks=citation_checks,
            **data,
        )


# ── Private helpers ───────────────────────────────────────────


def _deep_serialize(obj: Any) -> Any:
    """Walk *obj* recursively, converting enum → ``.value``
    and tuple → list for JSON compatibility."""
    if isinstance(obj, Enum):
        return obj.value
    if isinstance(obj, dict):
        return {
            k: _deep_serialize(v) for k, v in obj.items()
        }
    if isinstance(obj, (list, tuple)):
        return [_deep_serialize(item) for item in obj]
    return obj
