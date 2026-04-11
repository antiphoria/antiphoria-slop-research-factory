from dataclasses import asdict, dataclass, field, is_dataclass
from enum import Enum
from typing import Any, cast

from slop_research_factory.types.append_only import AppendOnlyList
from slop_research_factory.types.config import FactoryConfig
from slop_research_factory.types.enums import CheckpointBackend, RunStatus


@dataclass
class FactoryState:
    run_id: str
    status: RunStatus
    config: FactoryConfig
    brief: dict[str, Any]

    step_index: int = 0
    latest_hash: str = ""
    cycle_count: int = 0
    rejection_count: int = 0
    revision_count: int = 0

    current_draft: str | None = None
    current_think_trace: str | None = None
    current_critique: dict[str, Any] | None = None
    current_extracted_citations: list[dict[str, Any]] = field(default_factory=list)

    total_input_tokens: int = 0
    total_output_tokens: int = 0
    total_think_tokens: int = 0
    total_tool_call_seconds: float = 0.0
    total_wall_clock_seconds: float = 0.0
    total_estimated_cost_usd: float = 0.0

    messages: AppendOnlyList[dict[str, Any]] = field(default_factory=AppendOnlyList)
    citation_checks: AppendOnlyList[dict[str, Any]] = field(default_factory=AppendOnlyList)

    workspace: str = ""
    created_at: str = ""
    updated_at: str = ""
    last_error: str | None = None


def _to_jsonable(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {k: _to_jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple, set)):
        return [_to_jsonable(v) for v in obj]
    if isinstance(obj, Enum):
        return obj.value
    if is_dataclass(obj) and not isinstance(obj, type):
        return _to_jsonable(asdict(obj))
    return obj


def factory_state_to_jsonable(state: FactoryState) -> dict[str, Any]:
    """Convert FactoryState to a JSON-serializable dict (enums as strings)."""
    return cast(dict[str, Any], _to_jsonable(state))


def factory_state_from_jsonable(data: dict[str, Any]) -> FactoryState:
    """Deserialize JSON-compatible dict to FactoryState (D-2 §6)."""
    raw = dict(data)
    config_data = dict(raw.pop("config"))
    if "checkpoint_backend" in config_data and isinstance(config_data["checkpoint_backend"], str):
        config_data["checkpoint_backend"] = CheckpointBackend(config_data["checkpoint_backend"])
    config = FactoryConfig(**config_data)

    raw["status"] = RunStatus(raw["status"])
    raw["messages"] = AppendOnlyList(raw.get("messages") or [])
    raw["citation_checks"] = AppendOnlyList(raw.get("citation_checks") or [])

    return FactoryState(config=config, **raw)
