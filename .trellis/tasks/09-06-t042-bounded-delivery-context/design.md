# Contract

`project_profile_context(profile: ProjectProfile) -> ContextSource` emits a labeled projection,
not a schema-valid replacement ProjectProfile. Its URI pins profile_sha256. Each language retains
marker_count and the first three sorted marker_samples. No native_rules or build_systems removed.

`RuntimeConfig.context_max_input_tokens: StrictInt = 12000` (1..2,000,000) is passed to
`FileRunContextBuilder(..., budget: ContextBudget)`; default builder input/output stays 12000/4000.
Production sets input 32000, output reserve 4000, and role token declaration 36000. No provider
context-window claim is made by these local estimator limits. No historical configuration mutation.

Good: marker-heavy profile plus required approved documents fits the explicit production cap.
Base: old runtime configs still use 12000. Bad: required input beyond cap throws before Agent.run;
schema rejects zero/bool/oversized caps. No path/command/role permissions change.

`RetryingOrchestrator.run_task` catches only ContextBudgetExceeded, re-reads durable Task/events,
and uses the existing `_blocked` transition with BUDGET_EXHAUSTED, a fixed safe message, current
attempt, prior event artifact IDs and last source revision. Builder still raises; Runtime returns
BlockedResult, allowing the Project Manager to seal the actual status/revision, not its stale NEW
dispatch snapshot. Other context/invariant exceptions are not reclassified. No old record repair.
