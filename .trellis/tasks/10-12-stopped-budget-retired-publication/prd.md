# Exact consumed rejected publication retirement

AcceptedRoleArtifact.checkpoint_sequence is the publishing claim's input checkpoint. Distinct attempts can share it; comparison alone cannot identify a successor output. The production K1 stopped permanent failure shares checkpoint 8 with an older CoderProgress which has already been retired by a committed RETRY_REJECTED_CODER_OUTPUT decision.

Use the existing typed consumed WAIT_RESOLVED decision as the only retirement authority. Match Task, work, lease, dispatch, checkpoint, Run, Context, source, artifact ID and SHA exactly. A current work/Run or actual later checkpoint can never be exempted. Do not infer retirement from a low attempt, timestamp, different source, supersedes ancestor or input membership.

Apply the same pure predicate in stopped settlement, rejected-output collection and transactional retry consumption. Read consumed decisions using the same SQL cursor when inside the authority fence. No policy, schema or adoption semantics change.

Acceptance: actual SQL first rejected progress is consumed, successor shares checkpoint, later stopped exhaustion settles and replays without changing audit prefixes. Two genuine rejected output rounds work. Unconsumed, current, mismatched identity/digest and actual later checkpoint remain rejected atomically. Offline collector coverage is independently assigned.

Validation: exclusive isolated MySQL settlement/rejected-output suites, targeted collector regression, Ruff format/lint, strict mypy and git diff --check. No full test run. Stock handling is the original Requirement's exact public HANDLE after deployment, never direct production SQL or a duplicated Requirement.
