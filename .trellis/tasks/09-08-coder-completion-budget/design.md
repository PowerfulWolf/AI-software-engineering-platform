# Design

The correct deterministic seam is `_compile_prompt(AgentRequest, messages)`, immediately before the
Codex subprocess. Add a pure reserve calculation and role-specific completion-budget prose. This
makes the external deadline visible without adding mutable configuration or changing wire schemas.

The fast test proves the platform sends the contract. It cannot prove a remote model obeys it;
the original 30-minute run remains the end-to-end feedback loop and a fresh explicitly approved
recovery run is required after the platform repair.
