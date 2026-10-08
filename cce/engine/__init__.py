"""State machine engine package for Clinical Completion Engine (CCE)."""

from cce.engine.state_machine import (
    ObligationStateTuple,
    TransitionContext,
    TransitionResult,
    transition,
)

__all__ = [
    "ObligationStateTuple",
    "TransitionContext",
    "TransitionResult",
    "transition",
]
