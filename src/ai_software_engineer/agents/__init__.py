"""Public Agent Execution Plane contracts and offline adapter."""

from ai_software_engineer.agents.fake import FakeAgentAdapter
from ai_software_engineer.agents.models import (
    ROLE_OUTPUT_SCHEMA,
    AgentErrorCode,
    AgentFailure,
    AgentRequest,
    AgentResult,
    AgentRunStatus,
    FakeBehavior,
    FakeScenario,
    RunId,
)
from ai_software_engineer.agents.ports import (
    AgentAdapter,
    AgentConfigurationError,
    AgentError,
    AgentRequestConflict,
)

__all__ = [
    "ROLE_OUTPUT_SCHEMA",
    "AgentAdapter",
    "AgentConfigurationError",
    "AgentError",
    "AgentErrorCode",
    "AgentFailure",
    "AgentRequest",
    "AgentRequestConflict",
    "AgentResult",
    "AgentRunStatus",
    "FakeAgentAdapter",
    "FakeBehavior",
    "FakeScenario",
    "RunId",
]
