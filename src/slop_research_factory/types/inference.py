from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class InferenceRecord:
    run_id: str
    step_index: int
    role: str
    model: str
    timestamp_start: str
    timestamp_end: str
    duration_seconds: float
    input_tokens: int
    output_tokens: int
    think_tokens: int | None
    prompt_hash: str
    response_hash: str
    response_body_hash: str
    think_trace_hash: str | None
    api_provider: str
    api_response_id: str | None
    retries: int = 0
    error: str | None = None
    sampling_params: dict[str, Any] = field(default_factory=dict)
