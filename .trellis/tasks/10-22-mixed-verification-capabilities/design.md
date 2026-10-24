# Original K1 verification — staged minimum design v2

Status: proposed design only, no implementation/registration/deployment. Base `1ec4edd6f08bb09e8709f2c3e7519d734ee98f46`. Root accepted all three findings in `/private/tmp/ase-mixed-verification-independent-review-20261022/review.md`; this version replaces the implementation proposal, not the historical files, in the original package.

Historical package manifest SHA: `19c28def43b23556bc8b77d56c270d54e4579a8656b799042d0d47c6e5684ad0`. Historical design SHA: `2d2cd4b0c1dc529098cc9d953d4fc3389ef74dbef031ac5c11075e1330170729`. Those files remain byte-for-byte unchanged. `review-disposition.md` records the corrected claims.

## 1. Immediate objective and boundaries

Stage 1 adds lossless typed requirement partition/discovery and truthful exact prerequisite guidance. It keeps existing v1 execution, immutable bindings/receipts and independent QA/Reviewer admission intact. It does not implement, publish or freeze aggregate schemas, child journals, a heterogeneous registry, browser/live executors or shared-deadline changes.

The original immutable K1 Plan was already validated by read-only FileArtifactStore; see `../original-plan-index.json`, SHA `b8641349675a283592eb1114d0e1fec594f5042e58d03661b7554198ccedcef9`:

- Task `task_recovery_6c7e369928a23df6e2ccf8ba32d6f816`, source `5547815464a04991f50a2e0532d6f2f13d8daa69`.
- Plan `art_plan_9a1e1138a870bef5f7104892`, SHA `844d632f773cdf7c83fa4623510dcd28322b4f55fc4ee2181703bb0d13d2c3f8`.
- Ordered raw QA requirement tuple SHA `6e3489f7458b6e266ffeb1f45a62c7c998084ab6b0488ac7efda2976338e544e`.
- 61 original mappings: 55 explicit Python/MySQL; 1 true Node/Playwright/Chrome e2e command; 4 true live A-to-B e2e mappings sharing one exact pytest node; 1 document inspection.

Do not change ProductSpec, immutable Plan, Task/source/candidate, original requirement IDs/argv/criteria/levels, role permissions, frozen policy/budgets, prior approvals/results or branches. No replacement Requirement, SQL reset, fabricated verdict or direct K1 source change.

Python/composition success cannot replace browser/live e2e. Browser and live currently lack registered proven execution capabilities. Installing Node/Chrome, a downloaded image, a scripted Host factory, an ordinary subprocess or an old Swift/macOS Mock native_ui grant cannot establish them. Stage 1 makes the missing work precise; K1 still requires those capabilities for its original independent e2e acceptance.

## 2. Stage 1 typed partition and exact digests

Add one internal module, `manager/native_verification_partition.py`, with typed immutable containers, pure partitioning and bounded prerequisite facts. These are application-side types, not a new persisted root or Artifact format.

Proposed signatures:

```python
partition_role_verification_requirements(
    plan: PlanArtifact, role: Literal[AgentRole.QA, AgentRole.REVIEWER], *,
    semantic_hints: tuple[ExactVerificationEntrypointHint, ...] = (),
) -> NativeVerificationRequirementPartition

class NativeVerificationRequirementPartition(DomainModel):
    selection_mode: Literal["explicit_role", "qa_fallback_for_independent_review"]
    # complete original immutable tuple in original order
    requirements: tuple[PlannedVerificationRequirement, ...]
    requirements_sha256: Sha256
    python_v1_requirements: tuple[PlannedVerificationRequirement, ...]
    inspection_requirements: tuple[PlannedVerificationRequirement, ...]
    unavailable_requirements: tuple[NativeRequirementPrerequisite, ...]

class NativeRequirementPrerequisite(DomainModel):
    effective_role: Literal[AgentRole.QA, AgentRole.REVIEWER]
    requirement_id: NonEmptyStr
    requirement_sha256: Sha256
    argv_sha256: Sha256
    criterion_ids_sha256: Sha256
    verification_levels_sha256: Sha256
    reason: NativeVerificationWaitReason
    detail: NativeVerificationCapabilityDetail

class NativeVerificationPartitionDiscovery(DomainModel):
    # exact scope/source/Plan/policy/group binding, no readiness authority
    partitions: tuple[NativeVerificationRequirementPartition, ...]
    capabilities: tuple[DiscoveredControlledCapability, ...]
    prerequisites: tuple[NativeRequirementPrerequisite, ...]
```

Use the existing role selection rule: explicit role requirements, otherwise Reviewer reads the exact QA tuple under a different real Run and claim. Do not rewrite original QA row roles to Reviewer. Reject duplicate IDs, foreign/missing required criteria or malformed rows before any host probe or execution. Preserve every original row even where argv or criteria repeat.

Compute `requirements_sha256` from the ordered complete raw `[item.to_wire() for item in original_tuple]`. For every unavailable row, separately bind original ID, complete original wire SHA and canonical original argv/criterion tuple/level tuple SHA with `role_verification_digest`. Omitted levels versus an empty tuple, original argv versus inspection, planned files and checklist changes must remain distinguishable. Null argv/levels are hashed as canonical null, never silently normalized away.

Explicit Python/MySQL requirements are eligible only for the existing exact Python profile, never for a different fallback. Source/document rows stay inspections, with original paths/checklists and no machine test attribution. Existing supported homogeneous v1 paths retain their exact old behavior and hashes.

Unmarked commands need established execution semantics. `pytest`, `node`, a filename, an `e2e` label or a working executable is not proof that generic Python/MySQL isolation supports live/browser behavior. In the immediate mixed path, unmarked e2e rows cannot be absorbed into the Python subset. Unknown/unsupported rows remain prerequisites; an explicit unknown capability cannot fall back to Python or ordinary tools.

Precise browser/live diagnostic kinds may be used only when a trusted read-only entrypoint-semantics descriptor exactly matches the complete approved entry/levels. Such a descriptor is a diagnostic hint, not a registered executor, capability discovery or authorization. It must not contain K1 requirement IDs, broaden argv matching, or infer live merely from pytest/e2e. Where the input has no such structured trustworthy semantics, use the conservative generic-unregistered detail and show the exact original requirement ID/argv/levels through the existing Plan/reference presentation. Do not invent precision from prose.

A diagnostic hint is a code-owned typed entry with exact argv, exact levels, a finite missing-capability detail and its canonical digest; it is never accepted from model/source prose or request text. Stage 1 adds no persistent hint catalog. Empty hints are the default and yield generic-unregistered rows. Any production built-in descriptors require explicit source review and match no K1 requirement IDs; the design does not silently inject them.

The source review already establishes the original K1 obligations for the operator: browser command is `node --test tests/team_view/browser/learning-collection.test.cjs`; the four live mappings share `python -m pytest -q tests/learning_collection/test_live_a_to_b.py::test_production_a_to_b_live`. The integration/composition requirement explicitly uses Python/MySQL and remains distinct. These observations do not become a K1-specific runtime routing bypass.

## 3. Stage 1 discovery and v1 execution behavior

Add `RegisteredNativePythonVerifier.discover_partitioned(...) -> NativeVerificationPartitionDiscovery` without introducing a general registry/facade. It performs the pure full-group partition first. For supported homogeneous requests it can delegate to the existing discovery method, preserving old v1 discovery/binding semantics. For mixed requests it discovers only the exact Python subset and returns independent per-row unavailable facts for the other executable rows. Original whole-group SHA and original row digests remain bound separately from the subset discovery.

Python host discovery is read-only, bounded and distinct from executing candidate tests. A missing Python host dependency is attributed to its relevant Python rows and must not erase or replace browser/live prerequisite rows. If useful host discovery cannot complete, retain the known unsupported rows and return the existing typed host failure for the Python subset; do not manufacture READY.

The accepted-Plan production preflight consumes this typed result at `ProductionDeliveryBackend._inspect_native_prerequisites`. Extend `inspect_delivery_prerequisites` with an optional typed per-row prerequisite argument while keeping the legacy global discovery arguments readable. Verify incoming row IDs/role/full digest against the exact original tuple before using them. Reject foreign, duplicate or contradictory prerequisite facts rather than silently applying them to another row.

Each unavailable row produces the existing `DeliveryPreflightObservation` shape:

```text
status=WAIT_ENGINEERING
reason_code=CONTROLLED_VERIFICATION_CAPABILITY_REQUIRED
native_wait_reason=CONTROLLED_VERIFICATION_CAPABILITY_UNAVAILABLE
native_wait_detail=<bounded missing capability kind>
requirement_id=<exact original mapping ID>
```

The existing receipt already binds the immutable Plan SHA, source/policy and complete raw requirements SHA. Do not add a new durable root just to copy row hashes. The builder must validate relational identity before publication; the original immutable Plan plus exact row ID provides re-readable full argv/criterion/level binding.

At the accepted-Plan diagnostic path, an exactly identified unsupported capability can be reported before the generic test-entry predicate; this cannot authorize execution. Still enforce original role command/read/deny policy. The current new-Plan feasibility gate and `multi_directory/integration_commands.py` remain unchanged: rejecting unsupported Node in a new Plan is correct.

Before any controlled Python test, MySQL resource creation, ordinary-tool fallback or MODEL invocation, role preparation must reject a group with unavailable executable rows through the existing typed wait. This includes direct binder calls and alternate allowed route kinds, not only UI preflight. No subset receipt or successful Python probe may mark the whole group prepared. Reviewer fallback receives the same incomplete original tuple under its independent claim and must wait as well.

For a completely supported existing Python/inspection group, continue the original v1 executor, binding, admission, receipt and current-facts validator. Do not create an aggregate, change result cardinality, add child records or extend machine coverage from diagnostics. Existing STARTED without final remains UNCERTAIN and is never replayed. Stage 1 writes no new native execution facts for unsupported mixed groups, so history/deletion reader changes are unnecessary in this increment.

## 4. Stage 1 public wait-remedy mapping

Add these bounded `NativeVerificationCapabilityDetail` members and update the exact published enum in `schemas/delivery-preflight.schema.json`. Existing serialized values and formats stay unchanged:

| Detail | Concrete truthful remedy through delivery_wait |
| --- | --- |
| `VERIFICATION_BROWSER_EXECUTOR_UNREGISTERED` | 计划的真实浏览器验证还没有已验证隔离边界并获授权注册的执行器。平台维护需完成真实 Chrome/Playwright 正例、拒绝边界、候选/claim 绑定和清理验证后注册；安装 Node/浏览器不能建立该能力。 |
| `VERIFICATION_LIVE_EXECUTOR_UNREGISTERED` | 计划的真实 A→B 验证还没有获授权注册的生产路径执行器。平台维护需建立可信 Configured 路径、隔离 Host/SQL、真实独立 claims 与原计划要求的发布、查询/读取/引用验证后注册；Scripted/composition 不能替代。 |
| `VERIFICATION_REQUIREMENT_EXECUTOR_UNREGISTERED` | 原计划的精确验证入口尚无对应的已授权注册执行能力。维护者应核对该 requirement 的 argv、准则和 level，补齐并独立验收能力后注册；不能仅安装执行文件或再次点击批准。 |

Update `delivery_wait.py:_CAPABILITY_DETAIL_ACTIONS` for every new member. Preserve deduplication across identical reasons, show both distinct browser/live remedies where exact hints are available, and retain the existing dominant PROCESS_STATE_UNCONFIRMED handling when process-stop facts are also missing. The public next step is a fresh engineering investigation after capability implementation/registration and current-facts recheck, never a repeated product approval or automatic retry while unavailable.

Exercise actual `DeliveryWaitService.inspect` and `handle` (existing public engineering investigation/result path), not just `_preflight_detail_action`. Assert exact original prerequisite receipt linkage, concrete Chinese user_action/next_action, no permitted retry/resolution while prerequisites remain, no consumed queue resolution or engineering allowance, no model/resource start and unchanged Task/Plan/budget. A changed future discovery requires a fresh proof and cannot rewrite an old WAIT.

## 5. Trust boundary correction: summary is not machine coverage

The old proposal's promotion of in-process pytest summary counters to trusted per-selector execution coverage is withdrawn. The reviewer demonstrated a real candidate conftest/plugin which mutates the actual `_SelectionGuard`, removes collected tests and forces status0: pytest reports no tests ran while the unique valid summary claims collected1/passed1. Schema/index/duplicate-marker checks, nonces or another file written by the same candidate process cannot authenticate those claims.

Trusted execution facts are the admitted candidate, exact authorized requested argv/selectors, actual supervised process start/stop/completion/result and protected receipt binding. Candidate stdout/stderr, pytest summaries/counts, test-produced files and model-authored evidence remain bounded untrusted diagnostics. They may help an independent QA/Reviewer inspect what happened; they cannot establish that a test ran, cover a requirement, generate PASS/APPROVE or bridge a missing browser/live command.

The existing v1 `receipt_covered_required_criterion_ids` describes the approved invocation scope for receipt citation checks; it does not authenticate execution of every candidate test body. Stage 1 keeps its interface and does not strengthen that claim using parsed counts.

Actual return code0 also does not establish coverage or a verdict. Independent QA must evaluate actual coverage and adequacy against the original required levels and inspect misleading/no-test behavior. Reviewer independently evaluates the same candidate and evidence. Retain current v1 contradictory-nonzero guards and exact receipt/current-claim checks; Stage 1 does not expand or weaken their trust claims. It adds no automatic per-test-count admission. Document the spoof failure mode and preserve the reviewer probe as a negative trust-boundary test fixture when implementing/tests authorize it.

## 6. Deferred Stage 2: feasible authorized heterogeneous capabilities

Do not freeze or publish an aggregate contract until at least one heterogeneous executor has a concrete, independently reviewed binding/execution/cleanup design and proven boundary. The existing browser research is not registration or K1 QA. Actual Node/Chrome positives and actual filesystem/network/socket/process denials must pass under the final versioned boundary; network=none alone did not deny loopback in the measured experiment.

Real live A→B needs a trusted model-broker/transport seam inside the production Configured factory, isolated Host/SQL, real independent claims, real automatic pending publication, exact operator publication and B search/read/citation. Do not inject a testing factory that bypasses KnowledgeRunContextBuilder/baseline/candidate/native-verifier branches. No Scripted or composition success may be presented as live acceptance.

Each future executor requires exact versioned runtime/dependency/profile/candidate/claim binding, appropriate new auditable authorization without changing the frozen original Plan/Product/source, and independent review. Existing `NATIVE_UI_SANDBOX` means Swift/macOS Mock; do not reinterpret it as browser/live or silently extend old grants through enum iteration. Unknown authorization remains a typed prerequisite.

## 7. Deferred Stage 3: aggregate and executable deadline contract

The historical noncircular aggregate hash graph, same-root kind fail-closed approach and complete reader/cleanup scope remain research directions, not a frozen schema or permission to implement them. Before freezing the future aggregate, review actual heterogeneous execution facts and preserve v1 bytes/readers. Include preparation/capacity, engineering history, close/delete/purge and all child resource owners together; never publish a new root unsupported by those readers.

The prior claim that unchanged `execute_python_mysql_verification` fits all work inside the role request window is withdrawn. Its request timeout currently bounds only the test subprocess; MySQL control/start/readiness/principal and cleanup have separate limits. Stage 1 preserves this existing bounded-operation behavior and makes no new hard wall-clock promise.

A future aggregate deadline must be executable, not a before/after-child check. Proposed mandatory service contract for that later reviewed work:

```python
class VerificationWorkDeadline:
    # Process-local trusted monotonic clock, exact original role work budget.
    def check(self) -> None: ...  # typed deadline failure when remaining <= 0
    def remaining_seconds(self) -> float: ...
    def timeout(self, operation_cap_seconds: float) -> float: ...
    def sleep(self, operation_cap_seconds: float) -> None: ...
```

Create one absolute monotonic work deadline before the first owned resource command and pass the same object through the full child chain. Restart never renews it or resumes a STARTED execution. Durable records bind the original work-window/profile budgets; a monotonic timestamp is not portable authorization. Every blocking operation must receive an actual cancellable remaining timeout, and each resource/process launch must check the guard/deadline immediately beforehand.

- `python_mysql_execution.execute_python_mysql_verification`: accept the shared deadline; check before creating resources/proxy/private config/test executor, not just after return. The test subprocess timeout is clipped to actual remaining float time, not `max(1, ...)` that can launch after exhaustion. No later child may start after deadline failure.
- `python_mysql_resources.IsolatedMysqlResource.command/require_daemon/start/inspect`: propagate `timeout=min(existing_operation_cap, deadline.remaining_seconds())` to the real bounded process supervisor. The command helper must accept remaining float time without rounding up beyond the deadline. Each readiness attempt checks ownership/deadline, and both its SQL command timeout and 0.5s sleep are clipped. The 100-iteration bound remains a second cap, never a way to run beyond shared time.
- `verify_principal`: direct driver timeouts plus post-return checks are insufficient for a strict shared limit across multiple queries. Move this deterministic trusted check to an owned, supervised helper process with source excluded, exact private Unix socket/config and scrubbed environment; pass secrets via owner-only private file/pipe, never argv/log. Kill its process group on the same remaining deadline. Keep each connect/read/write cap as defense in depth. Future exact allowlist must include this helper and its process/secret/identity tests.
- `python_mysql_proxy`: pass the work stop/deadline signal into owned bridge/control-process lifetime; supervise those processes, prevent a new bridge after exhaustion, and never infer stop from lease release. Existing explicit socket/isolation restrictions remain.
- Common `verification_process`/executor seam: every new timeout is actually enforced by the process monitor, group termination and final record, not only a Python loop check. Cancellation may require bounded termination; if it cannot establish stop, preserve UNKNOWN and refuse readiness.

Separate cleanup/finalization from work. Normal between-child cleanup consumes remaining work time; if it cannot finish, stop all later starts and enter finalization. Finalization starts once for the whole aggregate and grants a separately frozen cleanup budget C. Its absolute end is `min(finalization_started + C, original_work_end + C)`, so it cannot renew per child/resource or multiply C. All proxy close/join, Docker stop/remove/inspect and receipt finalization receive the remaining cleanup deadline and their existing per-operation cap. No work/model/child launch occurs after finalization mode. If stop or cleanup remains unproved at that bound, seal actual failure/UNKNOWN facts where possible, retain owned intents and refuse READY; a timeout is not proof of deletion.

The later implementation allowlist must explicitly include Python execution/resources/proxy, controlled process supervisor and the trusted principal helper. It must prove short-remaining-time slow startup deterministically: readiness reaches deadline before test launch, no later child starts, owned cleanup uses only its separate cap, actual resources remain accounted, and an uncooperative stop produces UNKNOWN rather than fabricated success. Stage 1 does not authorize any of those changes or claim the deadline already exists.

## 8. Stored data, deployment and rollback for Stage 1

No execution-data or SQL migration is needed: Stage 1 creates no new binding/start/final/aggregate format. Existing K1 unsupported receipts stay immutable. Fresh accepted-Plan preflight/investigation may add a new exact receipt with truthful per-row waits after reviewed deployment, retaining old history and budgets. It cannot flip old WAIT to READY, trigger an unsupported role, or automatically consume retry authority.

Continue implementation via the existing K1 checkpoint and real claims as allowed. Final independent QA still waits for original browser/live capabilities if absent. No new candidate, source baseline or replacement requirement is created to hide the gap.

Deploy only after independent review/tests at the established controlled idle boundary. Rollback Stage 1 code/enum presentation together; retain all immutable old/new preflight receipts and compatible enum readers. There are no aggregate reader/resource migrations in this increment. Do not erase new detail receipts to make an old reader appear compatible; an old binary's inability to parse new detail values is a reader prerequisite, not evidence absence.

## 9. Approval boundary

Only Stage 1's exact allowlist/tests are proposed for the next implementation approval. Stages 2–3 are deferred research requirements and need their own concrete design/allowlist/authorization/review. This design revision executes no candidate/model/database call, registers no capability and edits no repository source/spec.

## Accepted independent-review clarification

Root approved the Stage 1 17-path allowlist with this clarification: keep internal prerequisite facts keyed by (effective_role, original row identity). Accepted-Plan preflight projects each original Plan row once under its explicit role; do not flatten Reviewer fallback facts into that old receipt. Real independent Reviewer preparation/binding checks the full original QA fallback tuple before any model/resource launch. QA-only mixed fixture must produce 61 original observations, not 122.


## Independent implementation review corrections (2026-10-24)

Keep the two execution modes distinct. `is_ordinary_verification_requirement()` is a shared,
pure selector of already-supported precise ordinary Responses entries. It never grants a tool:
current role command/read/deny policy, actual pinned source and executable discovery remain
required. Any explicit capability, unmarked e2e/acceptance row, unknown command or incomplete
whole-group role/criterion scope prevents ordinary preparation. Ordinary Go/npm/Maven/unittest
and legacy focused pytest entries are not made dependent on Docker/Codex discovery. Responses
permissions cannot flow into a Codex/fallback route or absorb any unsupported mixed row.

When an otherwise mixed group's Python subset exceeds the existing 64-selector v1 limit,
convert all of that subset's original rows into exact UNSUPPORTED_ENTRYPOINT prerequisites;
retain every independently known browser/live prerequisite and inspection. No host probe,
resource, subset test or model is started. A supported homogeneous v1 group retains its prior
global-limit rejection and original hashes. Production preflight plus public inspect/handle
must preserve original-row order, exact browser/live remedies, history and unchanged budgets.
