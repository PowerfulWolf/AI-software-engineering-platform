# Manager-owned verification prerequisites and controlled execution

## Exact incremental Python/MySQL candidate verification (2026-10-02)

### 1. Scope / Trigger

An accepted immutable candidate needs real MySQL tests, but ordinary QA/Reviewer command policy
denies the host Docker socket and network. Do not pass the host business DSN, disable the outer
sandbox, replay a consumed approval, reset the terminal Task, or rerun Coder to solve this prerequisite.
This executor is a separately versioned application capability, not an Agent command tool.

### 2. Signatures and wire contracts

- `ContinueDeliveryIntent.python_mysql_tests` and `ResumeProjectDelivery.python_mysql_tests`:
  optional 1..32 `PytestSelection(node_id, criterion_ids)` values. Only exact `tests/**/test_*.py`
  function/class-method nodes with bounded parametrization; no directory, suite, glob or flags.
  Proposal is mutually exclusive with UI/repair/scope proposals and all approval fields. None is
  omitted from wire values, preserving old operation digests.
- `CandidateVerificationEntry.propose[_project](..., python_mysql_tests=...)` binds all and only
  original Task criterion IDs, candidate commit, full toolchain/runtime/dependency/runner hashes,
  local Docker Unix daemon identity, cached image SHA and exact selections. Native facts and
  the independent execution provider rediscover the capability before execution.
- `PythonMysqlSandboxCapability(kind=codex_sandbox_pytest_mysql_v1)` is discriminated from
  Swift in plan/receipt schemas. UI requires Swift. Exact Task deny globs are expanded from raw
  NUL-separated fixed Git inventory (no whitespace stripping) to `denied_relative_paths`.
  At most4096 entries; encoded denied paths plus node IDs must fit30000 bytes before proposal,
  leaving space within the runner's32000-byte protected configuration limit.
- `BoundPythonMysqlVerificationEvidence.evidence_for` supplies an immutable command receipt
  to the independent role. `MysqlResourceRecord(kind=python_mysql_resource)` stores INTENT,
  CREATED, CLEANED and first CLEANUP_FAILED observations. None is a verdict.

### 3. Execution and recovery contracts

Use resolved Python with `-I -S -B`, registered dependency bytes, the hash-bound standalone runner,
disabled ambient pytest plugins/addopts, at most256 collected cases and explicit deny-path ignores.
Ignores keep pytest from statting unreadable entries; OS `none` still denies their contents and
`.git`. Source/runtime/dependencies/config are read-only; only a separate scratch is writable.
Network stays disabled. Only the exact private Unix proxy socket is connectable; candidate cannot
unlink/rebind it, access the Docker daemon or connect to other sockets/TCP. Each role gets distinct
scratch, proxy, principal and MySQL resource. Only genuine SQL semantics are demonstrated, not
TCP/DNS/TLS/production-network behavior.

Durably publish admitted STARTED and exact resource INTENT before creation. Ignore ambient Docker
context/config/environment; bind binary and daemon, use `--pull=never --network none`, no ports or
host binds,512MiB/1CPU/128PIDs/AutoRemove and no restart. Name, image, owner label, entrypoint,
command, initialization environment, network/mounts/resources are checked and configuration-hashed.
Fixed image command is `/usr/bin/timeout --kill-after=5 1195 ...`; an already-started container
process runs for at most1200 seconds from its start even if TERM is ignored. A control-process
crash between Docker creation and start can leave an unstarted object/volume until the next
explicit Python verification reconciles its expired intent. It has no running SQL service,
candidate credentials, host binds or ports; do not describe this object as automatically deleted
within1200 seconds of intent publication. Wait for the final server's
`@@GLOBAL.skip_networking=0`, not the official image's temporary initialization server.
Rotate localhost root before creating any candidate-reachable proxy; credentials remain in memory,
stdin and a0600 private config, never argv/records. Verify exact CURRENT_USER/database/grants and
an actual root authentication denial. Least-privilege principal has only the isolated test database.

Docker discovery/control output is drained with hard limits and process-group kill/reap on timeout.
Reclaim the group even if its leader has already exited: an inherited pipe can keep a descendant
alive beyond the direct child's lifetime. Observe a late sentinel in the real fork regression;
Darwin `killpg(pid,0)` can return EPERM for an already killed orphan group and is not a liveness fact.
Known passwords are replaced in retained output. A truncated stream is conservatively replaced
entirely because a cutoff may retain an unrecognizable password prefix. Ordinary command output
limits and secret redaction remain enforced. A zero exit, installation or fixture success is never
QA PASS. Skipped/empty/over-bound collection fails; model independently evaluates all criteria.

Cleanup revalidates the binary/daemon and performs successful exact-name enumeration before
declaring absence. Lost create responses are recovered by full name, owner/config and observed
container ID; only that container may be removed. A daemon error is not absence. Expired resources
are reconciled under the execution lock on the next explicit Python verification execution; reads
never clean resources. Validate immutable intent against its plan, approval, invocation and STARTED,
retain first failed cleanup, and append successful cleanup. No bulk deletion or test replay.
Later CREATED facts may fill unknown fields of a historical CLEANUP_FAILED; they must not make that
old record unreadable. Compare every previously known ID/hash, reject actual conflicts, preserve
the original bytes and revalidate the failed→created→cleaned chain after reopening the store.
The fixed timeout independently converges already-started resources when the control process dies
before a next execution; exact expired-intent reconciliation also removes owned unstarted objects.
STARTED without a final receipt always requires a new exact plan. Native Task/events, candidate,
old invocations and approvals are preserved. Reviewer-only recovery retains the sealed QA and its
Python selections, skips Coder/QA and requires a new exact approval. Python failures bypass the
Swift-only UI coordination path and name Python/Docker/MySQL prerequisites in the user remedy.

### 4. Validation and error matrix

| Fact | Outcome |
| --- | --- |
| Unapproved/wrong role/changed candidate, selectors or fingerprints | Reject before execution |
| Suite/glob/flags, unknown/missing criteria, over-budget deny config | Reject before proposal/approval |
| Exact selections with dedicated MySQL | Seal actual bounded command results; no inferred verdict |
| Root/cross-database/global grants, source write, deny-file read, socket replacement, TCP | Real negative fixture must reject |
| Lost create response or CREATED publish failure | Inspect exact owned identity and clean; retain audit |
| Expired already-absent resource | Successful exact query permits CLEANED; daemon failure does not |
| Unowned/config-changed resource | CLEANUP_FAILED; never remove |
| Restart after uncertain execution | Exact expired-resource cleanup only; do not replay tests |
| QA retained, Reviewer interrupted | Fresh approved Reviewer only; preserve original QA bytes |

### 5. Good / Base / Bad

Good: a delegated human submits exact incremental selections, reviews and approves the sealed plan,
then native independent QA/Reviewer consume separately executed receipts. Base: old Swift plans,
None fields and their hashes remain unchanged. Bad: use a business DSN, accept host-test output as
a native verdict, broaden Agent shell, skip QA, or label a Python failure as macOS UI availability.

### 6. Required tests

`test_python_verification*.py`: exact selections, tree fingerprints, raw deny inventory/config
bounds and real OS denials. `test_python_mysql_resources.py`: ownership/config rejection, intent
before create, lost response, failed publication and absence versus daemon failure.
`test_python_mysql_execution.py`: real store/admission receipts, no uncertain replay, credential
cutoffs, process bounds and restart cleanup. `test_python_mysql_boundary.py`: explicitly enabled
single disposable MySQL + real macOS sandbox fixture, root/cross-db/source/deny/socket/TCP rejection
and TERM-ignoring timeout escalation. `test_python_mysql_contract.py`: typed/JSON Schema exclusivity
and legacy wire. `test_verification_reviewer_resume.py` Python case: actual production entry selection,
fresh exact approval, preserved Task/QA history and only Reviewer on continuation.

### 7. Existing data and rollback

No production SQL migration or Task rewrite. For an existing blocked candidate, reload the trusted
host only after verifying no active role; submit selectors through normal Continue, obtain a new
candidate-bound plan and approve its exact digest. Continue native QA/Reviewer and attach only its
sealed completion. Do not reuse the failed old approval or reset Manager budgets. Rollback disables
new Python proposals/reverts the platform commit; preserve every resource record and receipt,
allow started-container deadlines to converge, reconcile any owned unstarted object through its
exact retained intent, and keep the original candidate available for recovery.

## Bounded pytest diagnostics (2026-10-02)

`_SelectionGuard.summary(exit_code)` emits `ASE_PYTEST_SUMMARY=` followed by compact JSON,
at most3000 bytes. Fixed columns are selector index, collected, call passed/failed, skipped
at any phase, setup error and teardown error. Every approved selector retains its counters;
at most16 error samples retain only index/phase, an anchored allowlisted exception class and
numeric OS/MySQL code. Unknown types remain UNKNOWN. No exception message, path, argv or
parametrized node ID is echoed. Samples may be omitted only with an explicit count; they are
diagnostics, never role verdicts. Collection errors and report overflow are explicit.

Trusted pytest flags suppress tracebacks, summaries, captured streams, color and live logging.
Override `verbosity_test_cases=-1`: candidate ini can otherwise defeat `-q`, print long identities
and include full secret-bearing skip reasons. Candidate-configured verbose skip cases must retain
the quiet output bound and diagnostic counters without exposing their reasons.
The existing4096-byte command output and whole-stream truncation redaction remain unchanged.
Pass/skip/error and collection fixtures must remain inspectable;200 failures with long secret
exceptions must fit the limit without credential text. A setup skip must not appear as a pass.
Historical redacted receipts and native QA findings are immutable; new runner bytes require
new fingerprint-bound approval. A recorded business finding still routes to Coder.

## Historical verification read graph

Scope: public FileRecoveryStore verification getters validate a DAG of plans, advice, incidents,
completions, approvals, invocations and receipts. Repeated failure/recovery grows shared ancestry;
naive recursive validation was exponential (live snapshot 35s timeout/3201 plan validations).

Signature: `_validated_read(Callable[P,R]) -> Callable[P,R]` wraps read nodes only, not writes.
ContextVar holds a store-identity-scoped synchronous graph. A node is memoized only after its
complete semantic/hash/lineage validation succeeds. Active reentry is a cyclic-reference error;
at most128 active nodes and4096 completed nodes; all context is reset in finally on success/error.
No process-lifetime trusted cache. Every new public read rereads durable bytes and can detect
tampering; another store/thread cannot share trust. No files, digests, approvals or verdicts change.

Matrix: repeated diamond edge -> reuse validated node in this call; next public read -> revalidate;
bad bytes -> existing RecoveryRejected; cyclic/over-bound -> RecoveryRejected, no recursion overflow;
failed read then restored bytes -> independently validate again. No error/partial node is cached.

Good: completion reuses its already-checked plan when validating authorization/invocation.
Base: a single-node read still performs full validation. Bad: global lru_cache on digest that hides
later changed on-disk bytes. Existing no-follow/path/private-file checks remain in _get.

Tests: `test_verification_read_graph.py` counts validation across real completion/incident diamonds,
fresh reads, tamper/restoration, cyclic references, and concurrent same-store read isolation.
Use a bounded read-only live profile to compare the actual seam; do not modify history or interrupt
an admitted verifier to load a performance fix. Observed post-fix snapshot:2.4s for all14 views,
versus timing out after35s/only5 views before the fix.

## Production verification context budget (2026-09-28)

### 1. Scope / Trigger

Candidate verification runs after terminal delivery; QA PASS can be sealed before Reviewer
context compilation fails. This is a platform context failure, not business QA failure.

### 2. Signatures

`CandidateVerificationEntry.execute(path)` composes `FileRunContextBuilder` with the shared
`PRODUCTION_DELIVERY_CONTEXT_BUDGET` (128,000 input / 4,000 reserved output).
`ManagerConsoleAdapter.execute(intent)` maps `ContextBudgetExceeded` to
`ConsoleCommandRejected(code="CONTEXT_BUDGET_EXHAUSTED", safe_summary=...)`.

### 3. Contracts

Low-level default remains 12,000. Recovery must explicitly inherit the existing production
budget; no failure-driven expansion or required-section truncation. Approved plan, policy, Task,
criteria and full upstream artifacts remain required. Compile before admission/model invocation.
On failure release the verification reservation, preserve the original error and all sealed QA,
invocations and terminal Task/events. Console names the Manager remedy without echoing source data.
An incomplete independent verification is not a native accepted-QA event or sealed completion.
Do not fabricate either to reuse it. Normal Continue proposes a fresh exact plan; consumed plans
cannot replay. Current supported recovery reruns QA/Reviewer, never Coder, preserving the old PASS.
Reviewer-only reuse remains limited to the existing validated terminal accepted-QA contract.

### 4. Validation & Error Matrix

| Input | Outcome |
| --- | --- |
| QA fits 12k; full Reviewer input exceeds 12k but fits production budget | Both roles execute; complete QA section retained |
| Required input exceeds production budget | No affected Agent invocation; release reservation; no completion/verdict |
| Context failure reaches Console | Stable actionable code; no secret/source echo |
| QA sealed but Reviewer compilation failed | Preserve history; fresh separately approved verification, no old replay |

### 5. Good / Base / Bad Cases

Good: use one production constant and test the real entry with durable artifacts and contexts.
Base: small contexts and low-level defaults behave unchanged. Bad: drop QA details, auto-grow
the budget, accept an orphan report as completion, or label context overflow MANAGER_FAILURE.

### 6. Tests Required

`test_verification_context_budget.py` exercises real execute/runner/admission/context/store with
fixture external ports: full Reviewer QA JSON, bounded overflow, reservation release, clean-up
and unchanged original Task/events. `test_manager.py` checks actionable redacted Console mapping.
Keep admission/restart/Reviewer-only tests and ordinary context budget/truncation tests.

### 7. Wrong vs Correct

Wrong: production recovery silently constructs `FileRunContextBuilder(root)` with 12k.
Correct: explicitly pass the normal production constant; reject real overflow, keep evidence.

## Desktop-session prerequisite recovery (2026-09-28)

### 1. Scope / Trigger

An admitted UI execution failed at session preflight or during a UI step. Preserve its exact
receipt while coordinating a changed desktop prerequisite; do not reinterpret it as queue state.

### 2. Signatures

- `probe_native_ui_session(SwiftSandboxCapability | None) -> NativeUiSession | None`
- `NativeUiSessionPrerequisite(observed_status, current_session?, kind=macos_console_session,
  owner=logged_in_user, is_execution_mutex=False)`; `ready` and `next_action` are derived.
- `ManagerVerificationAdvice.environment_prerequisite` is optional and input v5 includes the
  same typed fact under `latest_execution_failure.environment_prerequisite`.

### 3. Contracts

- A sealed `NATIVE_UI_SESSION_LOCKED` means the macOS desktop was locked, not an executor mutex,
  TaskLease or queue ownership. Manager's typed environment prerequisite names the logged-in
  user, manual unlock/login remedy and fresh exact-approval resume condition. Never propose lock
  file deletion, force-killing an owner, automatic unlock or password collection for this code.
- After a session-specific failure only, normal Continue performs a bounded candidate-free
  session probe using the trusted native driver's `--session-check`. Compile in read-only Codex
  isolation with private scratch, no network or candidate execution. Unknown/failed probing is
  not READY. GUI execution still independently preflights after exact approval.
- Advice input includes the historical failure semantics and current session status; unchanged
  observations reuse advice. READY after LOCKED invalidates the old advice cache, not its history
  or consumed approval. It authorizes no execution by itself. The optional prerequisite is sealed
  with advice and omitted from historical digests; no database migration is needed.
- Before READY, reject UI/repair proposals and render the typed Manager human remedy, not a
  speculative free-text lock diagnosis. Tests cover receipt without UI steps, mid-step locks,
  unknown probes, cache/restart, unlock-driven reproposal and legacy digest/schema compatibility.
- Probe env is exactly PATH/LANG/LC_ALL/DEVELOPER_DIR/TMPDIR/CLANG_MODULE_CACHE_PATH. Fixed compiler
  argv accepts no repository/model-selected command. Private scratch is removed on success/failure.

### 4. Validation & Error Matrix

| Input | Required outcome |
| --- | --- |
| LOCKED with no UI steps | Typed desktop meaning retained; no fake child/window diagnostic |
| Same LOCKED after reopen | Cached advice reused, no candidate execution |
| Current READY after historical LOCKED | New input/advice identity; new exact approval required |
| Missing toolchain, changed binary, malformed/failed probe | Unknown, never READY |
| Unresolved prerequisite plus UI/repair draft | One bounded correction, then INVALID_OUTPUT |
| Prerequisite observed status differs from receipt | Reject advice on store write/read |
| Historical advice/plan without new field | Original digest unchanged |

### 5. Good / Base / Bad Cases

Good: user unlocks, Continue re-probes READY, Manager proposes new candidate-bound UI execution.
Base: still locked, Manager identifies the logged-in user's action without repeating tests.
Bad: remove a lease file for a screen lock, or trust a stale cached WAITING_HUMAN forever.

### 6. Tests Required

`test_manager_coordination.py` covers sealed no-QA failure, cache/reopen, changed-session identity,
immutable old advice, receipt mismatch and canonical human remedy in immediate/resumed paths.
`test_native_ui.py` checks candidate-free argv, private scratch, env isolation, changed capability,
invalid output and existing GUI preflight. `test_verification_coordination.py` rejects proposals
while LOCKED/UNAVAILABLE/unknown, allows READY proposals and checks legacy advice hashes.

### 7. Wrong vs Correct

Wrong: `failure_code -> model guesses lock owner -> cached wait without a readiness probe`.
Correct: `sealed desktop failure + fresh typed session probe -> Manager handoff or new exact plan`.

## Scenario: executor failure must reach Manager (2026-09-27)

### 1. Scope / Trigger

A controlled executor stops before a verifier model starts. An admitted invocation is not a
QA report; routing only inconclusive QA skips this failure and repeatedly offers the same plan.

### 2. Signatures

- `FileRecoveryStore.latest_verification_execution(plan) -> VerificationExecutionRecord | None`
- `ManagerVerificationAdvice.execution_failure: VerificationFailureReference | None`
- `VerificationFailureReference(plan_sha256, record_sha256, role)`
- Coordination payload v3 adds `latest_execution_failure` and permits absent QA identity only
  when a sealed executor failure supplies the evidence source.
- v4 adds the explicit direct-binary/mock launch contract and source prerequisite repair
  capability; Manager may propose `PROPOSE_REPAIR`, never execute or approve it. The separate
  sealed observation/repair/dispatch contracts are in `prerequisite-repair.md`.

### 3. Contracts

Both the immediate `VerificationExecutionBlocked` catch and a later Continue of an admitted,
incomplete plan consult Manager before offering another execution. Select the latest validated
final receipt for the same original Task/candidate, not orphan STARTED records or another Task.
Supply the actual failed step, error, bounded/redacted diagnostic, command exit codes and exact
receipt reference. The source plan's scenario, not the newly proposed one, is the previous scenario.
Advice readback validates the referenced BLOCKED receipt/candidate. Old advice without the new
optional field retains its digest. Preserve original criteria, human approval and all failure history.
Only exact admitted run IDs may account for source-input changes during this handoff.
No UI diagnosis or remedy is inferred from build success. Manager owns the solution or concrete
handoff; Codex may repair the platform capability but never substitute business UI observations.

### 4. Validation & Error Matrix

| Condition | Outcome |
| --- | --- |
| Executor blocked before any QA | Manager receives receipt; no fabricated QA |
| Continue after consumed execution | Consult Manager before successor approval |
| Same facts after restart | Reuse advice; no model/executor replay |
| Wrong receipt hash/candidate/role or non-BLOCKED source | Reject advice |
| Different Task/candidate receipt | Exclude from coordination |
| Unknown extra source run ID | Reject drift |

### 5. Good / Base / Bad Cases

Good: Manager sees `initial / WINDOW_UNAVAILABLE / count=0` and requests bounded launch diagnostics.
Base: unavailable capability remains a concrete handoff. Bad: relabel every runtime exception as
an environment problem, blindly approve the same scenario, or have an operator edit business code.

### 6. Tests Required

`test_manager_coordination.py` covers immediate and restart routing, real append-only receipt
readback, first-failure/no-QA context, exact source identity, cross-candidate exclusion and tampering.
Retain historical digest, independent QA/Reviewer, Console and wire-schema contract tests.

### 7. Wrong vs Correct

Wrong: `executor error -> generic message -> identical successor approval`.
Correct: `sealed failure -> Manager context/decision -> scoped remedy -> new exact approval`.

## Scenario: Manager closes missing verification plans (2026-09-27)

### 1. Scope / Trigger

An exact terminal candidate has an inconclusive QA report, but the proposed successor only
repeats build/tests. Environment coordination is Manager work, not an operator-authored UI script
or a request for humans to produce the future QA result.

### 2. Signatures

- `CandidateVerificationEntry.coordinate(plan) -> ManagerVerificationAdvice | None`
- `coordinate_verification(client, payload, criterion_ids, ...) -> ManagerVerificationAdvice`
- `FileRecoveryStore.put/get_verification_advice(...)`; storage key is exact input SHA-256.
- `CandidateVerificationPlan.manager_advice` is optional, omitted for historical digests.
- `CodexCliStructuredModelClient(allow_native_commands=False)` for Manager proposal calls.
- `no_command_arguments()` plus read-only sandbox for CLI QA/Reviewer;
  Production source now uses `candidate_read_scope` / `BoundCandidateSource` and complete candidate
  difference views; see [candidate-review-source.md](candidate-review-source.md).
  `candidate_read_snapshot(root, revision, permissions, max_bytes=2_000_000)` is only the conservative
  low-level fallback without a typed resolver.

### 3. Contracts

- Normal Continue coordinates an unadmitted failed verification before accepting another exact
  approval. Manager consumes unchanged Task criteria, sealed QA, candidate blobs and available
  capabilities. It proposes bounded Mock UI steps covering all criteria or an actionable human
  handoff (missing fact, owner, remedy, resume condition). It cannot execute, install or approve.
- Cache the complete decision with input/scope/candidate/QA hashes and Manager provider/model/run
  identity. Same-input restart reuses it; changed facts allow a new decision. Scenario and criterion
  mapping enter the exact plan and Console approval facts. Old build-only approval is not reused.
- `CandidateVerificationEntry.coordinate` selects native QA in durable event order, then prefers
  the matching sealed verification completion over that terminal history. Artifact `created_at`
  is model-authored metadata, not execution ordering: clock skew or timezone mistakes must not
  hide a newer QA finding. Keep all old report/advice bytes and hashes; changed QA content changes
  the coordination input digest and requires a new proposal, not an old approval replay.
- Read existing approved Requirement knowledge resolutions through `list_gap_views`; preserve
  gap/run/resolution integrity. Include them in Manager input and the exact plan's required
  QA/Reviewer context. Do not lose a user-approved Mock data strategy and then invent a real-OAuth
  requirement from a prior verifier's prose. Original criteria remain unchanged.
- Capability facts explicitly list AX tree/value/position/size and press results, and declare
  screenshot/real-login/network support false. A model cannot promise nonexistent pixel evidence.
- `PROPOSE_UI` itself is awaiting exact approval. `WAITING_HUMAN` means a genuine missing
  prerequisite and must have a null scenario. Invalid drafts receive at most one fixed corrective
  model call, then safe `MODEL_INVALID_OUTPUT`; raw validation input is never echoed or persisted.
- The older immutable incident's WAITING_HUMAN record remains historical. Advice is a new fact,
  not an in-place rewrite claiming the old incident repaired. No business verdict is produced.
- CLI QA/Reviewer native command surfaces are disabled; source comes from tracked, regular,
  policy-readable exact candidate blobs, never dirty checkout content/untracked files/symlink
  targets. Redact secrets, bound total bytes and fail closed on overflow. Binary omissions are
  explicit. Testing evidence must come from controlled executors; absent evidence remains a block.
- Shell disable alone is not a full boundary: installed Codex still advertises apply_patch.
  Pair with read-only OS sandbox and test actual rejection. Disable alternate browser/app/plugin/
  subagent execution surfaces. Do not grant arbitrary shell as fallback when evidence is absent.
- This slice is verification coordination, not a universal installer or complete repair registry
  for every delivery stage. Coder and other upstream CLI tool policies still require separate audit.

### 4. Validation & Error Matrix

| Input | Outcome |
| --- | --- |
| Missing original criterion mapping / nonexistent step | Reject model draft |
| Same exact input after restart | Reuse immutable advice, no second model call |
| Old QA has a future timestamp; later native event or matching completion exists | Use durable latest report; preserve old report |
| Different scope/candidate/scenario | Reject advice/plan binding |
| Missing UI capability | Actionable Manager handoff, no automatic install |
| Old build-only approval when UI advice appears | Fresh exact approval, no verifier run |
| Native CLI patch attempt | Read-only sandbox rejects; candidate unchanged |
| Source overflow | Fail closed, no silently partial review |

### 5. Good / Base / Bad Cases

Good: Manager maps the candidate's documented Mock entry to missing interaction checks and asks
approval. Base: missing capability returns an explicit prerequisite action. Bad: operator writes
the scenario for Manager or generic shell disables the inner sandbox outside the trusted executor.

### 6. Tests Required

`test_manager_coordination.py`: real immutable store/reopen, source binding, normal Continue old
approval refusal and human handoff. `test_verification_coordination.py`: exact criterion coverage.
`test_manager_uses_durable_qa_order_not_report_timestamp` covers both native event order and a
real admitted/sealed completion with an older-looking report time; assert the actual Manager
payload, advice binding, reopen/cache and unchanged historical records.
`test_candidate_read_snapshot.py`: candidate blobs, denied paths, redaction and overflow.
Opt-in `ASE_TEST_CODEX_EXECUTABLE=/absolute/codex pytest tests/agents/test_tool_free_codex.py`
uses a local mock provider (no remote model) to inspect actual tool catalog and attempt a patch.
Retain independent QA/Review, historical hash/schema, Console and recovery regressions.

### 7. Wrong vs Correct

Wrong: `inconclusive -> identical build-only approval -> QA NOT_TESTED` indefinitely.
Correct: `inconclusive -> Manager proposal/handoff -> exact approval -> controlled executor ->
independent QA/Reviewer -> delivery continuation`.
For report selection, wrong: `max(reports, key=lambda report: report.created_at)`;
correct: last validated native event report, superseded by the matching sealed verification result.

## 1. Scope / Trigger

Use when inconclusive candidate QA needs environment repair or a verifier requires a bounded
executor exception. Project facts, host availability, platform capabilities, human authority and
independent acceptance are different facts. This slice covers candidate verification continuation;
it is not a universal installer, GUI driver or automatic repair system for every stage.

## 2. Signatures

```python
FileRecoveryStore.record_verification_incident(completion) -> VerificationEnvironmentIncident
FileRecoveryStore.get_verification_incident(incident_sha256) -> VerificationEnvironmentIncident
discover_swift_sandbox_capability(executable) -> SwiftSandboxCapability | None
CandidateVerificationPlan.executor_capability: SwiftSandboxCapability | None
CandidateVerificationPlan.prerequisite_incident_sha256: Sha256 | None
BoundSwiftVerificationEvidence.evidence_for(request, workspace_root, execution_guard=None) -> str
ConfiguredDeliveryRouteAdapterFactory.with_verification_evidence(provider)
FileRecoveryStore.put_verification_execution(record) -> VerificationExecutionRecord
```

`schemas/candidate-verification.schema.json` includes the incident/execution variants. Regenerate
with `.venv/bin/python scripts/generate-verification-schema.py`. Optional absent plan fields are
omitted from canonical JSON; legacy plan hashes remain unchanged.

## 3. Contracts

- Only a validated, sealed `RETRY_VERIFICATION` completion may create a prerequisite incident.
  The Manager decision binds source plan/completion, exact candidate, QA artifact and counts.
  Production continuation and successor proposal call the existing `ManagerLeaderRecovery` seam.
  No automatic capability is registered by this slice: the decision is WAITING_HUMAN, not repaired.
- Incident identity is content-based, stored in the existing private append-only scope store.
  Readback rechecks the source completion and candidate. A successor carries its incident hash;
  exact-plan authorization is the human decision authorizing the listed attempted verification,
  not proof that every prerequisite is resolved. Ordinary repeated Continue invokes no model.
- Candidate `Package.swift` plus host Codex/Xcode availability may **propose** the versioned
  `codex_sandbox_swiftpm_v1` capability. The proposal binds the canonical executable path and binary
  SHA-256, selected Developer directory, Swift version and fixed `native` build backend. Discovery
  executes only host version probes, never the package. Installation alone grants no permission.
- Before new-plan admission, a changed capability/toolchain requires reproposal. Before actual
  commands, revalidate the approved plan, exact durable role invocation, request and detached
  role worktree, clean candidate and current host capability. Coder cannot use the capability.
- The trusted deterministic executor, not the model, creates each role's private temporary root
  and runs fixed `swift build`/`swift test` commands. It invokes `codex sandbox` with an explicit
  profile extending built-in `:read-only`, only that root writable, network disabled and managed
  requirements retained. It adds `--disable-sandbox` **only to SwiftPM**, never to Codex. No
  plain Responses/Subprocess/native model command receives an inner-sandbox exception.
- The capability fixes `--build-system native`, `--disable-automatic-resolution`, `--skip-update`,
  `--disable-netrc`, scratch/cache/config/security paths. Environment is exactly PATH/LANG/LC_ALL,
  DEVELOPER_DIR, TMPDIR, CLANG_MODULE_CACHE_PATH and SWIFTPM_MODULECACHE_OVERRIDE. No HOME or
  CODEX_HOME repurposing, inherited credentials, tool installation, signing script or network grant.
- Both QA and Reviewer use separate scratch and candidate-readonly outer profiles. The provider
  route is separate: Responses and CLI consume the same explicit trusted receipt wrapper. No
  fallback path can replace the sandbox command with unsandboxed execution.
- Persist STARTED before commands; COMPLETED or BLOCKED afterward. All receipts bind plan,
  authorization, invocation, role, candidate and capability. Normal output is bounded/redacted;
  timeout/start failure is typed and stored as BLOCKED before returning control to Manager.
  A STARTED without a final receipt is uncertain and cannot execute again. A sealed receipt may
  be supplied again to another configured model route in the **same** admitted role run, not rerun.
- Exact argv/cwd and start/final identity are checked on receipt readback. Scratch is disposable;
  permanent receipts retain its path and command evidence. Nonzero build/test results remain
  evidence for QA to interpret, not an automatic business verdict. UI criteria are never removed.
- Console exact approval facts show the Manager incident and capability restrictions. Operation
  success, environment probe success, QA PASS, Review APPROVE and requirement DONE remain distinct.

## 4. Validation & Error Matrix

| Facts | Required outcome |
|---|---|
| Unchanged legacy plan without optional fields | Same historical digest |
| New capability or toolchain binary/version | New exact plan; old approval cannot gain it |
| Unknown/cross-candidate incident or tampered completion | Reject before approval/execution |
| Business FAIL / verified completion | Cannot classify as environment repair |
| Wrong role, request, source revision or worktree | No controlled commands |
| Source/scratch overlap or symlink | Reject |
| Timeout/start failure | Durable BLOCKED receipt; Manager WAITING_HUMAN; no model verdict |
| Unknown interruption after STARTED | No replay; fresh plan required |
| Model attempts `swift ... --disable-sandbox` | Existing command policy still rejects |
| Successful tests with missing UI prerequisites | No automatic PASS/APPROVE/DONE |

## 5. Good / Base / Bad Cases

- Good: human approves a new candidate-bound capability; independent QA and Reviewer receive their
  own isolated command receipts and judge the unchanged original acceptance criteria.
- Base: absent Swift capability leaves historical model tools unchanged; Manager explains missing
  conditions and waits for a human instead of claiming a repair.
- Bad: add `--disable-sandbox` to the global command allowlist, infer authority from Xcode being
  installed, silently reuse old approval, or present an operator probe as independent QA.

## 6. Tests Required

- `test_verification_environment.py`: legacy/new hash, model policy refusal, path containment,
  incident reopen/tamper/cross-candidate, role-bound receipts, same-run fallback reuse,
  uncertain/timeout/drift denial, two route factories, schema parity.
- `test_delivery_continuation.py`: actual Manager incident call on inconclusive continuation,
  no Coder invocation. `test_manager.py`: standalone/joint/Reviewer-only exact approval facts.
- Explicit real probe: `ASE_RUN_SANDBOX_TESTS=1 ASE_TEST_CODEX_EXECUTABLE=/absolute/codex
  .venv/bin/pytest -q tests/recovery/test_verification_environment.py -k real_swift`.
  Each verifier uses a separate no-dependency Swift fixture; tests verify XCTest runs, writes into
  the source are denied and network to a listening local socket is denied. No business credentials.
- Ruff, strict mypy, related recovery/agent/Console tests, diff check. MySQL integration needs the
  explicitly isolated `ASE_TEST_MYSQL_DSN`, never a production DSN.

## 7. Wrong vs Correct

```python
# Wrong: an environment workaround becomes arbitrary model authority.
permissions.commands += ("swift test --disable-sandbox",)
# Correct: unchanged model permissions plus a separately approved typed service.
factory = factory.with_verification_evidence(bound_approved_executor)
```

### Observed host behavior (2026-09-26)

Xcode 27 / Swift 6.4 defaults to `swiftbuild`. Its sandboxed fixture reached linking but failed
`permissionDenied`. The supported `native` backend passed the same isolated XCTest/read-only/network
tests. `native` is deprecated; do not silently switch if a future toolchain removes it. Revalidate
the capability and propose a new version. A normal subprocess XCTest pass did not prove the Codex
OS sandbox worked; cache relocation alone exposed a separate nested `sandbox_apply` denial.
Official profile semantics: https://developers.openai.com/codex/permissions ; the local executable
and actual denial tests, not documentation alone, establish this host's working boundary.

## Python/MySQL executor foundations (2026-10-01, not activated)

The new `manager/python_verification*.py` modules define exact `PytestSelection` values,
a versioned capability, read-only discovery and a fixed interpreter runner. They do not yet
register a production executor, extend model authority or authorize candidate verification.
Docker lifecycle, exact-plan/receipt integration and independent acceptance remain required.

- Discovery binds binary, runner, complete Python runtime and dependency tree hashes. `-B`
  prevents bytecode writes, not reads: existing `.pyc` is included. Directory scanning errors
  fail closed. Only direct regular-file aliases inside the registered tree are accepted; link
  text and canonical relative target are hashed. External hops, even returning inside, reject.
- Candidate selectors are checked from exact Git objects, with replacement refs and lazy fetch
  disabled and transport denied. No candidate import, image pull or container creation occurs.
- The standalone runner uses `-I -S -B`, bypasses editable `.pth`, disables ambient pytest
  plugins/addopts/parent conftest, checks both directions of exact collection membership and
  limits collection to 256 cases. Skipped checks make command exit nonzero; exit zero is not PASS.
- On the observed macOS Codex executable, `:root=none` plus `:minimal=read` still allowed
  reading unrelated public temporary files. Explicit `:slash_tmp=none` and `:tmpdir=none`
  are necessary before reopening only approved source/runtime/runner/config reads and scratch
  writes. Preserve `--include-managed-config`, disabled network and exact Unix socket access.
  Do not infer safety from a successful ordinary-directory probe.
- OS regression fixtures cover both user and public temporary roots, source writes, unrelated
  temporary secret reads/writes, socket unlink/rebind/alias and TCP denial, plus the permitted
  socket. Keep Unix socket paths below the macOS sockaddr limit when allocating owned temp roots.

Targeted checks: `tests/manager/test_python_verification.py`,
`test_python_verification_discovery.py`, and `test_python_verification_runner.py`.
Real OS checks require explicit `ASE_RUN_SANDBOX_TESTS=1` and
`ASE_TEST_CODEX_EXECUTABLE=/absolute/codex`; no production DSN or model invocation is used.
The official profile reference is <https://developers.openai.com/codex/permissions>; observed
denial tests remain authoritative for the installed version. Historical Swift plans are unchanged.
