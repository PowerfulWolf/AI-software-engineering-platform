# Design

`ProductionProjectDeliveryBackend` remains the single composition seam for normal and recovery
delivery. A pure role-to-timeout function resolves the existing `AgentDefinition.timeout_seconds`:

- Coder: 1,800 seconds
- QA and Reviewer: 1,200 seconds
- Orchestrator: unchanged at 60 seconds

The values are fixed and versioned with platform code for v0.1. This keeps a hard upper bound,
avoids runtime configuration drift after approval, and automatically covers both delivery paths
because both consume `_agent_definitions`. Unsupported roles fail closed.
