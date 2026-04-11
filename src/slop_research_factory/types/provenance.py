from dataclasses import dataclass, fields
from typing import Any

from slop_research_factory.types.config import FactoryConfig


@dataclass(frozen=True)
class SealPayload:
    run_id: str
    step_index: int
    step_type: str
    timestamp: str
    prev_hash: str
    content_file_paths: list[str]
    content_hash: str
    metadata: dict[str, Any]


@dataclass(frozen=True)
class SealedStepReceipt:
    run_id: str
    step_index: int
    step_type: str
    timestamp: str
    prev_hash: str
    content_file_paths: list[str]
    content_hash: str
    metadata: dict[str, Any]
    seal_hash: str
    algorithm: str


@dataclass(frozen=True)
class ProvenanceManifest:
    manifest_version: str
    run_id: str
    factory_version: str
    genesis_hash: str
    final_hash: str | None
    manifest_seal_step_index: int
    total_steps: int
    chain: list[dict[str, Any]]
    config: dict[str, Any]
    configuration_overrides: list[dict[str, Any]]
    brief: dict[str, Any]
    brief_hash: str
    output_file: str
    output_hash: str
    hai_card_file: str
    hai_card_hash: str
    models_used: list[dict[str, Any]]
    verdict_history: list[dict[str, Any]]
    citation_summary: dict[str, Any]
    started_at: str
    completed_at: str
    total_duration_seconds: float
    security_statement: str


def configuration_overrides_for(config: FactoryConfig) -> list[dict[str, Any]]:
    """Fields that differ from `FactoryConfig()` defaults (D-2 §4, §7.3)."""
    default_config = FactoryConfig()
    overrides: list[dict[str, Any]] = []
    for f in fields(config):
        default_val = getattr(default_config, f.name)
        actual_val = getattr(config, f.name)
        if actual_val != default_val:
            overrides.append({"field": f.name, "default": default_val, "actual": actual_val})
    return overrides
