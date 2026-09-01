"""Public orchestration seams for the v0.1 serial workflow."""

from ai_software_engineer.orchestration.context import (
    FileRunContextBuilder,
    RunContextBuilder,
)
from ai_software_engineer.orchestration.runner import (
    AgentRunFailed,
    DeliveryContractViolation,
    DeliveryResult,
    OrchestrationError,
    OrchestrationIdentityFactory,
    OrchestratorConfigurationError,
    SerialOrchestrator,
    TaskNotRunnable,
    UnexpectedVerdict,
    UuidOrchestrationIdentityFactory,
)
from ai_software_engineer.orchestration.state_machine import (
    IllegalTransition,
    StaleEvent,
    StateMachineError,
    TaskMismatch,
    TerminalTask,
    apply_event,
    build_event,
    validate_transition,
)

__all__ = [
    "AgentRunFailed",
    "DeliveryContractViolation",
    "DeliveryResult",
    "FileRunContextBuilder",
    "IllegalTransition",
    "OrchestrationError",
    "OrchestrationIdentityFactory",
    "OrchestratorConfigurationError",
    "RunContextBuilder",
    "SerialOrchestrator",
    "StaleEvent",
    "StateMachineError",
    "TaskMismatch",
    "TaskNotRunnable",
    "TerminalTask",
    "UnexpectedVerdict",
    "UuidOrchestrationIdentityFactory",
    "apply_event",
    "build_event",
    "validate_transition",
]
