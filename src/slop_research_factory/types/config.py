from dataclasses import dataclass

from slop_research_factory.types.enums import CheckpointBackend


@dataclass(frozen=True)
class FactoryConfig:
    generator_model: str = "deepseek/deepseek-r1"
    verifier_model: str = "google/gemini-2.5-flash"
    reviser_model: str = "deepseek/deepseek-r1"

    max_rejections: int = 3
    max_revisions: int = 5
    max_total_cycles: int = 10
    max_total_tokens: int | None = None
    max_total_cost_usd: float | None = None

    verifier_confidence_threshold: float = 0.8
    enable_citation_checking: bool = True
    citation_check_sources: tuple[str, ...] = ("crossref", "semantic_scholar")
    enable_tavily_search: bool = True

    weight_logical_soundness: float = 0.35
    weight_mathematical_rigor: float = 0.25
    weight_citation_accuracy: float = 0.20
    weight_scope_compliance: float = 0.15
    weight_novelty_plausibility: float = 0.05

    target_length_words: int = 5000
    capture_think_tokens: bool = True

    enable_provenance: bool = True
    hash_algorithm: str = "sha256"

    workspace_base_path: str = "./workspaces"
    checkpoint_backend: CheckpointBackend = CheckpointBackend.SQLITE

    def __post_init__(self) -> None:
        if self.target_length_words < 100:
            raise ValueError("target_length_words must be >= 100")
        total_weight = (
            self.weight_logical_soundness
            + self.weight_mathematical_rigor
            + self.weight_citation_accuracy
            + self.weight_scope_compliance
            + self.weight_novelty_plausibility
        )
        if abs(total_weight - 1.0) > 1e-9:
            raise ValueError("Verdict weights must sum to 1.0")
