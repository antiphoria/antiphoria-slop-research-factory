from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class HumanRescueRequest:
    run_id: str
    workspace: str
    status: str
    cycle_count: int
    rejection_count: int
    revision_count: int
    latest_verdict: str | None
    latest_critique: str | None
    latest_draft_path: str | None
    created_at: str


@dataclass(frozen=True)
class HumanRescueResponse:
    run_id: str
    decision: str
    reviewer_id: str | None = None
    comment: str | None = None
    modified_draft_path: str | None = None
    modified_config: dict[str, Any] | None = None

    def __post_init__(self) -> None:
        if self.decision == "modify_config" and self.modified_config is None:
            raise ValueError("modified_config must be provided when decision is 'modify_config'")
