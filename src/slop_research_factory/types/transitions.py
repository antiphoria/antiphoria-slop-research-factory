from slop_research_factory.types.enums import RunStatus


class InvalidRunStatusTransition(Exception):
    """Raised when an illegal status transition is attempted."""


LEGAL_TRANSITIONS: dict[RunStatus, set[RunStatus]] = {
    RunStatus.INITIALIZING: {RunStatus.GENERATING, RunStatus.FAILED, RunStatus.NO_OUTPUT},
    RunStatus.GENERATING: {RunStatus.VERIFYING, RunStatus.FAILED, RunStatus.NO_OUTPUT},
    RunStatus.VERIFYING: {
        RunStatus.REVISING,
        RunStatus.AWAITING_HUMAN,
        RunStatus.FINALIZING,
        RunStatus.FAILED,
    },
    RunStatus.REVISING: {RunStatus.VERIFYING, RunStatus.FAILED, RunStatus.NO_OUTPUT},
    RunStatus.AWAITING_HUMAN: {
        RunStatus.GENERATING,
        RunStatus.REVISING,
        RunStatus.FINALIZING,
        RunStatus.NO_OUTPUT,
    },
    RunStatus.FINALIZING: {RunStatus.COMPLETED, RunStatus.FAILED},
    RunStatus.COMPLETED: set(),
    RunStatus.FAILED: set(),
    RunStatus.NO_OUTPUT: set(),
}


def assert_legal_run_transition(from_status: RunStatus, to_status: RunStatus) -> None:
    """Enforce the state machine transition rules (D-2 §3.3)."""
    allowed = LEGAL_TRANSITIONS[from_status]
    if to_status not in allowed:
        msg = f"Cannot transition from {from_status.value} to {to_status.value}"
        raise InvalidRunStatusTransition(msg)
