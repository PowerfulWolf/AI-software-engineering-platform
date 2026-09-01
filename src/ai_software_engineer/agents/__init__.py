"""Public Agent Execution Plane contracts and offline adapter."""

from ai_software_engineer.agents.fake import FakeAgentAdapter
from ai_software_engineer.agents.models import (
    AgentErrorCode,
    AgentFailure,
    AgentRequest,
    AgentResult,
    AgentRunStatus,
    FakeBehavior,
    FakeScenario,
)
from ai_software_engineer.agents.ports import (
    AgentAdapter,
    AgentConfigurationError,
    AgentError,
    AgentRequestConflict,
)

__all__ = [
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
]
