from slop_research_factory.types.enums import ConfidenceTier


def confidence_to_tier(confidence: float) -> ConfidenceTier:
    """Map float confidence to a human-readable tier (D-2 §3.5)."""
    if confidence >= 0.8:
        return ConfidenceTier.HIGH
    if confidence >= 0.5:
        return ConfidenceTier.MEDIUM
    if confidence >= 0.2:
        return ConfidenceTier.LOW
    return ConfidenceTier.VERY_LOW
