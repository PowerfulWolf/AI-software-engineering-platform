# Manager-owned verification prerequisites and controlled execution

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
`PRODUCTION_DELIVERY_CONTEXT_BUDGET` (64,000 input / 4,000 reserved output).
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
  `candidate_read_snapshot(root, revision, permissions, max_bytes=2_000_000)` supplies source.

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
