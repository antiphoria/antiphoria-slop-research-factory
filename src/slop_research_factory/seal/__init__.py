# seal/__init__.py
# src/slop_research_factory/seal/__init__.py

"""
Provenance seal layer — engine protocol, helpers, registry, and SDK bridge.

Modules:
    engine        Protocol definition + InMemorySealEngine.
    helpers       ``seal_step()`` convenience wrapper.
    registry      Metadata schema validation per step type.
    sdk_adapter   Bridge to ``antiphoria_sdk`` (optional dependency).

Engine selection:
    Use :func:`sdk_adapter.create_seal_engine` as the single entry point.
    It returns the appropriate engine based on ``config.enable_provenance``.
"""

from slop_research_factory.seal.engine import InMemorySealEngine, SealEngine
from slop_research_factory.seal.helpers import seal_step
from slop_research_factory.seal.registry import validate_metadata
from slop_research_factory.seal.sdk_adapter import (
    SDKSealEngine,
    create_sdk_engine,
    create_sdk_engine_from_env,
    create_seal_engine,
)

__all__ = [
    "InMemorySealEngine",
    "SDKSealEngine",
    "SealEngine",
    "create_seal_engine",
    "create_sdk_engine",
    "create_sdk_engine_from_env",
    "seal_step",
    "validate_metadata",
]
