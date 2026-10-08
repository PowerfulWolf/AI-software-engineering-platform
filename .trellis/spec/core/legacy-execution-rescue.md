# Legacy execution rescue

## Scope / trigger
Only a nonterminal local native Coder invocation with a real exact invocation-start and historical
claim but genuinely missing final outcome and original capture/stop ledger. This is a new
engineering disposition, never reconstruction of the old execution.

## Signatures and wire

- `manager/legacy_containment.py`: `TrustedLocalBootObserver.observe() -> LocalBootObservation`
  (`machine_sha256`, `boot_session_sha256`, `booted_at`), twice observed stable. The exact
  `LegacyExecutionContainment` embeds `original_start`, `original_claim`, native child
  `requirement_id`, `dispatch_sha256`, `scope`, `task_intent_sha256`, `boot`, `containment_sha256`.
- `manager/legacy_local_execution.py`: `TrustedLegacyLocalExecutionObserver.observe(*,
  worktree_root: Path, boot: LocalBootObservation) -> LegacyLocalExecutionSurvey`, with exact
  worktree/device/account/boot/scanner boundary, observed time, bounded blocker enums and SHA.
  `LegacyRescuePrerequisiteError(code, safe_message, next_action)` is a typed expected wait.
  No original PID/argv/environment or historical stopped boolean is invented.
- `manager/baseline_production.py`: `BaselineProposeCommand.purpose` and
  `BaselineExecuteCommand.confirm_legacy_containment: Literal[True] | None`.
  `BaselineOperatorAuthorization.for_plan(..., confirm_legacy_containment=True)` binds the
  human declarations to the exact plan/facts/principal digest, not to request text alone.
- `method=operator_confirmed_local_stop` requires **only** the separate
  `confirm_local_execution_stopped: Literal[True]`; `method=os_reboot` requires **only** the
  existing `confirm_legacy_containment`. Both absent for source rebind; both present is invalid.
- `manager/execution_baseline.py`: `ExecutionBaselineService.propose(target_base_ref,
  input_mode=preserve_draft, purpose=legacy_workspace_rescue)` captures full facts;
  `execute(plan_sha256, authority=BaselineOperatorAuthorization)` publishes once.
- `work_queue/baseline.py`: `consume_baseline(..., cursor, validate_new_consumption)` calls the
  trusted callback only after checking no existing consumption. The callback revalidates complete
  current capture, inventory and same-device stable boot before the SQL transaction proceeds.

Console `POST /api/v1/operations` wraps the normal exact Project/Requirement checkpoint plus
`PROPOSE_EXECUTION_BASELINE` with `purpose=legacy_workspace_rescue`, `input_mode=preserve_draft`,
original `task_id`, `expected_task_revision`, `expected_task_intent_sha256`,
`expected_work_item_id`, `expected_source_revision` and unchanged `target_base_ref`.
Execution selects only `EXECUTE_EXECUTION_BASELINE`, exact `expected_plan_sha256`, human
`reference` and the method's exact human confirmation. HTTP cannot assert boot/survey facts or
original stop. Console contract 3 supports local-stop confirmation; contract 2 retains old reboot
plans. `legacy_rescue_preparation` is typed READY with exact plan or WAITING without any plan,
approval or binding. Expected incomplete/active observations return a successful check, not a
failed delivery or Pydantic error. All ValidationError inputs are replaced with fixed safe Chinese.

## Persistence and replay

New facts reuse `state/execution-baselines/<task_id>` append-only `baseline-plans`,
`baseline-authorities`, `baseline-starts`, `baseline-bindings`; queue `work_queue_execution_baselines`
stores the exact plan/binding/next item consumption. No table migration or old-record rewrite.
Bindings carry `purpose` and `legacy_containment_sha256`; readers load the complete plan and
operator authorization rather than treating the hash alone as isolation authority.

Binding publication before SQL commit is replayable: an already authorized original boot proof
remains valid after a later stable boot on the same device, provided the complete workspace is
unchanged. Preparing again for the same start returns the original sealed plan after verifying
the exact unchanged snapshot; retry the original exact approval without a second binding. Completed
queue consumption replays without reobserving a later boot or duplicating budgets. A new prepared
but not approved plan can always be prepared again after source/boot facts drift.

## Contracts
`purpose=legacy_workspace_rescue` reuses baseline capture/plan/binding/queue contracts but selects
the unchanged prior execution base, preserve_draft mode and exact original source. It must not
mutate source files, HEAD, index or branch. All current dirty bodies are captured against immutable
Git, checked against frozen write/deny policy, and verified twice under Task lock and queue fence.

An OS observer reads current stable local machine identity, boot-session identity and boot time.
For `method=os_reboot` (the omitted legacy default), the observed boot must postdate the exact
invocation start. This proves containment only together
with a separate trusted engineering authorization explicitly attesting that the original native
execution used this same local computer, was never migrated/remote, that a whole-computer reboot
actually happened after the original execution, and that the time evidence is trusted. The original
Run lacks host identity; therefore automatic EngineeringAdmission is refused.
Attestation is human-supplied engineering evidence, not an owned runner stop or autonomous recovery.

Service restart, an expired lease, a free lock, absent PID or a process scan cannot establish this
condition. A second current OS observation must match before queue publication; caller-supplied
OS booleans/dates/PIDs cannot bypass the observer. Original historical UNKNOWN/outcome gaps remain.

### Current local survey and explicit supplied cessation evidence

When boot does not postdate the original start, collect a fresh trusted survey over the current
effective-account local execution boundary and the manager-owned original checkout. Fixed bounded
OS queries inspect native Codex execution/wrappers and cwd/open workspace references. App-server
identity alone is not native delivery execution. Unknown ownership/state, query denial/truncation,
target-associated processes and incomplete coverage refuse preparation. Commands never signal
discovered processes, read environment variables or publish raw arguments. The original exact
request/claim must still prove native local routing; unknown fallback or remote boundaries refuse.

This survey is **not** a historical process-stop proof. A trusted human with ENGINEERING duty
supplies the missing facts by confirming the original invocation always ran on the same local
computer/account, was never moved or remote, and the original invocation **and all its derived
tools** have actually ended and cannot modify the workspace again. They accept UNKNOWN and
authorize preserved-draft execution from remaining work allowance. Without that exact declaration
no machine EngineeringAdmission may continue. Persist it in immutable authority and
HumanActionEvent(SUPPLY_EVIDENCE) with the authority URI; preserve old reboot event bytes/notes.

Before preparation completion, execution and new queue consumption, freshly recheck the survey,
stable boot, all claims under Task lock/SQL fence and complete snapshots. Survey times and unrelated
process changes do not invalidate a valid plan: independently verify the typed boundary and retain
the sealed observation body/hash for exact facts comparison. Pin the approved observation before
collect. A genuinely later same-device boot may be accepted on replay with fresh same-account/path
survey; do not alter sealed proof. Already-consumed publication remains idempotent without rescanning
obsolete inputs. Survey/capture worktree paths must match in the plan model itself.

Unknown work is not refunded or classified as provider failure. Exact queue consumption keeps the
old WorkItem/history and reserves a distinct next work attempt/WorkItem. New Run and Context require
a real claim and the original permissions; independent QA/Review and same-candidate gates remain.

## Validation matrix
| Case | Behavior |
| --- | --- |
| OS boot before/equal original start | Current local survey + new exact engineering cessation declaration |
| Unreadable OS identity or incomplete survey / live execution | WAITING explanation, no plan or new invocation |
| Original final result now exists | Reject rescue; use original result replay |
| Missing original claim/start or nonlocal execution | Reject; no new invocation |
| Rescue authorization without exact same-device attestation | Reject before queue/source effects |
| Platform policy admission or changed source/input mode | Reject; explicit engineering decision required |
| Dirty/protected/ignored/staged drift or incomplete body | Preserve full现场; no reset/clear |
| Valid complete snapshot + OS observation + exact decision | Append binding, reserve next work, same Task |
| Crash/repeated approval | Exact record replay, no duplicate budget or WorkItem |

## Required tests
OS observer success/refusal, exact request/claim/boot binding, immutable legacy digests, no automatic
authority, complete retained draft and no filesystem mutation, unknown no-refund accounting,
public operation schema/Host/native completion, UI capability/stale guards and Chinese next steps.

Focused commands:
`pytest tests/manager/test_legacy_containment.py tests/manager/test_legacy_snapshot.py`,
`pytest tests/manager/test_legacy_rescue_delivery.py tests/web_console/test_legacy_rescue_acceptance.py`,
`node --test tests/team_view/browser/legacy-rescue.test.cjs` (configured Playwright NODE_PATH).
The public fixture must reach original Task DONE through distinct native Coder/QA/Review claims,
same candidate SHA, preserve unknown start/no original outcome, keep files/index/HEAD/branch,
record `HumanActionEvent(SUPPLY_EVIDENCE)` and validate all four updated static Schema documents.
After delivery, traverse `_invocations` across the complete Task queue: the old unknown has exact
legacy containment but no outcome/receipt, and the succeeding Coder/QA/Review have real outcomes.
Verify inherited baseline digests through immutable parent/consumption lineage while preserving
QA/Review candidate sources; foreign, missing, cyclic or stale-epoch lineages remain rejected.

## Good / base / bad
- Good: old local UNKNOWN plus genuine same-device post-invocation reboot, explicit engineering
  confirmation and complete legal snapshot; next ordinary work attempt delivers same Task.
- Base: only ASE restarted; survey can prepare preserved draft but never becomes automatic stop proof.
- Bad: inferred stop from lease/PID, invented provider refund, protected ignored input, automatic
  policy approval or new duplicate Task; refuse and preserve all files and historical records.

## Wrong vs correct
Wrong: manufacture a timeout stop from a restart, accept a user `stopped=true`, or reset the Task.
Correct: capture new engineering facts honestly, require exact human attestation where old machine
identity is absent, preserve the old unknown Run and use a separately claimed successor attempt.
