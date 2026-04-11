"""D-8 §3.1 E1-S01–E1-S23: state schema unit tests (glascannon-ai-draft/step1.md)."""

from __future__ import annotations

import json
from dataclasses import FrozenInstanceError, asdict

import pytest
from jsonschema.validators import validator_for
from pydantic import ValidationError

from slop_research_factory.types import (
    AppendOnlyList,
    ConfidenceTier,
    FactoryConfig,
    FactoryState,
    HumanRescueResponse,
    InferenceRecord,
    InvalidRunStatusTransition,
    ResearchBrief,
    RunStatus,
    SealedStepReceipt,
    SealPayload,
    Verdict,
    VerifierOutput,
    assert_legal_run_transition,
    confidence_to_tier,
    configuration_overrides_for,
    factory_state_from_jsonable,
    factory_state_to_jsonable,
)


def test_e1_s01_config_defaults() -> None:
    """E1-S01: FactoryConfig instantiates with all defaults."""
    config = FactoryConfig()
    assert config.generator_model == "deepseek/deepseek-r1"
    assert config.verifier_confidence_threshold == 0.8


def test_e1_s02_config_frozen() -> None:
    """E1-S02: FactoryConfig is frozen: assignment raises error."""
    config = FactoryConfig()
    with pytest.raises(FrozenInstanceError):
        config.max_revisions = 10  # type: ignore[misc]


def test_e1_s03_state_roundtrip() -> None:
    """E1-S03: FactoryState round-trips through JSON via helpers."""
    state = FactoryState(
        run_id="test-run-123",
        status=RunStatus.INITIALIZING,
        config=FactoryConfig(),
        brief={"thesis": "test"},
    )
    state.messages.append({"role": "system", "content": "hi"})

    jsonable = factory_state_to_jsonable(state)
    json_str = json.dumps(jsonable)
    reloaded_jsonable = json.loads(json_str)

    restored_state = factory_state_from_jsonable(reloaded_jsonable)

    assert restored_state.run_id == state.run_id
    assert restored_state.status == state.status
    assert restored_state.config.generator_model == state.config.generator_model
    assert len(restored_state.messages) == 1
    assert isinstance(restored_state.messages, AppendOnlyList)


def test_e1_s04_brief_empty_thesis() -> None:
    """E1-S04: ResearchBrief rejects empty thesis."""
    with pytest.raises(ValidationError):
        ResearchBrief(thesis="")


def test_e1_s05_brief_whitespace_thesis() -> None:
    """E1-S05: ResearchBrief rejects whitespace-only thesis."""
    with pytest.raises(ValidationError):
        ResearchBrief(thesis="   ")


def test_e1_s06_brief_valid() -> None:
    """E1-S06: ResearchBrief accepts a minimal valid brief."""
    brief = ResearchBrief(thesis="Test thesis")
    assert brief.thesis == "Test thesis"


def test_e1_s07_verifier_output_roundtrip() -> None:
    """E1-S07: VerifierOutput round-trips through Pydantic JSON serialization."""
    vo = VerifierOutput(
        critique_summary="Summary",
        critique_entries=[],
        verdict=Verdict.CORRECT,
        resolution_type="explanation",
        verdict_confidence=0.9,
        resolution="Looks good.",
        confidence_logical_soundness=0.9,
        confidence_mathematical_rigor=0.9,
        confidence_citation_accuracy=0.9,
        confidence_scope_compliance=0.9,
        confidence_novelty_plausibility=0.5,
    )
    json_str = vo.model_dump_json()
    vo_restored = VerifierOutput.model_validate_json(json_str)
    assert vo_restored.verdict == Verdict.CORRECT


def test_e1_s08_verifier_output_json_schema() -> None:
    """E1-S08: VerifierOutput.model_json_schema() validates against metaschema."""
    schema = VerifierOutput.model_json_schema()
    validator_for(schema).check_schema(schema)


def test_e1_s09_no_enums_in_json() -> None:
    """E1-S09: All enums serialize to string values in json.dumps."""
    state = FactoryState(
        run_id="test",
        status=RunStatus.COMPLETED,
        config=FactoryConfig(),
        brief={},
    )
    jsonable = factory_state_to_jsonable(state)
    json_str = json.dumps(jsonable)
    assert "RunStatus" not in json_str
    assert "COMPLETED" in json_str


def test_e1_s10_config_overrides_default() -> None:
    """E1-S10: configuration_overrides is empty list when all fields default."""
    overrides = configuration_overrides_for(FactoryConfig())
    assert overrides == []


def test_e1_s11_config_overrides_custom() -> None:
    """E1-S11: configuration_overrides correctly identifies changed fields."""
    config = FactoryConfig(max_revisions=2)
    overrides = configuration_overrides_for(config)
    assert len(overrides) == 1
    assert overrides[0]["field"] == "max_revisions"
    assert overrides[0]["default"] == 5
    assert overrides[0]["actual"] == 2


def test_e1_s12_seal_payload_frozen() -> None:
    """E1-S12: SealPayload is frozen."""
    payload = SealPayload(
        run_id="x",
        step_index=0,
        step_type="x",
        timestamp="x",
        prev_hash="x",
        content_file_paths=[],
        content_hash="x",
        metadata={},
    )
    with pytest.raises(FrozenInstanceError):
        payload.run_id = "y"  # type: ignore[misc]


def test_e1_s13_sealed_step_receipt_frozen() -> None:
    """E1-S13: SealedStepReceipt is frozen."""
    receipt = SealedStepReceipt(
        run_id="x",
        step_index=0,
        step_type="x",
        timestamp="x",
        prev_hash="x",
        content_file_paths=[],
        content_hash="x",
        metadata={},
        seal_hash="x",
        algorithm="x",
    )
    with pytest.raises(FrozenInstanceError):
        receipt.seal_hash = "y"  # type: ignore[misc]


def test_e1_s14_confidence_to_tier() -> None:
    """E1-S14: ConfidenceTier maps correctly for mid-bands."""
    assert confidence_to_tier(0.85) == ConfidenceTier.HIGH
    assert confidence_to_tier(0.65) == ConfidenceTier.MEDIUM
    assert confidence_to_tier(0.35) == ConfidenceTier.LOW
    assert confidence_to_tier(0.15) == ConfidenceTier.VERY_LOW


def test_e1_s15_inference_record_frozen() -> None:
    """E1-S15: InferenceRecord is frozen and JSON-serializable."""
    record = InferenceRecord(
        run_id="x",
        step_index=1,
        role="x",
        model="x",
        timestamp_start="x",
        timestamp_end="x",
        duration_seconds=1.0,
        input_tokens=10,
        output_tokens=10,
        think_tokens=None,
        prompt_hash="x",
        response_hash="x",
        response_body_hash="x",
        think_trace_hash=None,
        api_provider="x",
        api_response_id=None,
    )
    with pytest.raises(FrozenInstanceError):
        record.input_tokens = 20  # type: ignore[misc]
    json.dumps(asdict(record))


def test_e1_s16_verifier_output_invalid_enum() -> None:
    """E1-S16: VerifierOutput with invalid string enum raises."""
    with pytest.raises(ValidationError):
        VerifierOutput(
            critique_summary="x",
            critique_entries=[],
            verdict="MAYBE",  # type: ignore[arg-type]
            resolution_type="x",
            verdict_confidence=0.5,
            resolution="x",
            confidence_logical_soundness=0.5,
            confidence_mathematical_rigor=0.5,
            confidence_citation_accuracy=0.5,
            confidence_scope_compliance=0.5,
            confidence_novelty_plausibility=0.5,
        )


def test_e1_s17_verifier_output_correct_empty_critiques() -> None:
    """E1-S17: VerifierOutput with CORRECT and empty critique_entries is valid."""
    vo = VerifierOutput(
        critique_summary="x",
        critique_entries=[],
        verdict=Verdict.CORRECT,
        resolution_type="x",
        verdict_confidence=0.5,
        resolution="x",
        confidence_logical_soundness=0.5,
        confidence_mathematical_rigor=0.5,
        confidence_citation_accuracy=0.5,
        confidence_scope_compliance=0.5,
        confidence_novelty_plausibility=0.5,
    )
    assert vo.verdict == Verdict.CORRECT


def test_e1_s18_verifier_output_fixable_empty_critiques() -> None:
    """E1-S18: VerifierOutput with FIXABLE and empty critique_entries is rejected."""
    with pytest.raises(ValidationError):
        VerifierOutput(
            critique_summary="x",
            critique_entries=[],
            verdict=Verdict.FIXABLE,
            resolution_type="x",
            verdict_confidence=0.5,
            resolution="x",
            confidence_logical_soundness=0.5,
            confidence_mathematical_rigor=0.5,
            confidence_citation_accuracy=0.5,
            confidence_scope_compliance=0.5,
            confidence_novelty_plausibility=0.5,
        )


def test_e1_s19_illegal_transition() -> None:
    """E1-S19: RunStatus forward-only transition enforcement."""
    with pytest.raises(InvalidRunStatusTransition):
        assert_legal_run_transition(RunStatus.COMPLETED, RunStatus.GENERATING)

    assert_legal_run_transition(RunStatus.INITIALIZING, RunStatus.GENERATING)


def test_e1_s20_confidence_1_is_high() -> None:
    """E1-S20: confidence == 1.0 maps to HIGH."""
    assert confidence_to_tier(1.0) == ConfidenceTier.HIGH


def test_e1_s21_confidence_0_is_very_low() -> None:
    """E1-S21: confidence == 0.0 maps to VERY_LOW."""
    assert confidence_to_tier(0.0) == ConfidenceTier.VERY_LOW


def test_e1_s22_state_nested_config_roundtrip() -> None:
    """E1-S22: FactoryState nested config object roundtrips robustly."""
    custom_config = FactoryConfig(max_revisions=42)
    state = FactoryState(
        run_id="test",
        status=RunStatus.INITIALIZING,
        config=custom_config,
        brief={},
    )
    reloaded = factory_state_from_jsonable(factory_state_to_jsonable(state))
    assert isinstance(reloaded.config, FactoryConfig)
    assert reloaded.config.max_revisions == 42


def test_e1_s23_human_rescue_config_modify_validation() -> None:
    """E1-S23: HumanRescueResponse 'modify_config' requires modified_config payload."""
    with pytest.raises(ValueError):
        HumanRescueResponse(run_id="x", decision="modify_config", modified_config=None)


def test_append_only_list_invariants() -> None:
    """D-2 §16 inv 12: AppendOnlyList rejects overwrite/delete."""
    lst: AppendOnlyList[int] = AppendOnlyList([1, 2])
    lst.append(3)
    assert len(lst) == 3

    with pytest.raises(TypeError):
        lst[0] = 5

    with pytest.raises(TypeError):
        del lst[0]

    with pytest.raises(TypeError):
        lst.insert(0, 99)

    with pytest.raises(TypeError):
        lst.clear()
