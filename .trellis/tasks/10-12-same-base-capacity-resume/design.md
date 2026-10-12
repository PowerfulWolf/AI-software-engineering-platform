# Purpose choice and minimal contract

Preferred: add `BaselinePurpose.CONTEXT_CAPACITY_RESUME = "context_capacity_resume"`
and optional `ExecutionBaselineBinding.context_capacity_receipt_sha256: Sha256 | None`.
The purpose means runtime input assembly has been repaired while target-project source
remains unchanged. Reuse existing typed plan, exact PAUSE approval, binding and separate
RESUME services; add no new delivery state, retry cause, role, permission or execution API.

Alternative: keep source_rebind and admit a same-base exception. That touches fewer enum
consumers but misstates the operation, requires implicit inference from optional evidence,
and leaves the UI saying code was updated when it was not. Reject that alternative.
SOURCE_REBIND must retain its different-execution-base contract and reject a no-op at
proposal time before publishing a usable plan. Do not silently reinterpret old plans.

The optional digest is durable audit evidence linking this new purpose to its exact sealed
plan. It is not itself a no-start proof, operator authorization or ability to ignore dirty
files. Only the trusted collector can select it; public proposal accepts identity facts and
purpose, never a caller-asserted capacity receipt, stop flag or budget.

# Domain invariants

For `purpose=context_capacity_resume`, require all of:

1. `input_mode=preserve_draft`, `continuation_mode=pause`, and
   `authority_source=engineering_operator_decision`.
2. `execution_base_ref == prior_execution_base_ref` and
   `execution_source_revision == prior_source_revision`; source may legitimately be a
   retained committed-work descendant of execution base. Do not force source==base.
3. `before_inventory_sha256 == after_inventory_sha256`; original same branch/worktree,
   empty staged delta, complete legal dirty/committed capture remain checked.
4. Non-null `context_capacity_receipt_sha256` equals the plan facts' exact current receipt.
   No legacy containment, completed-output or stopped-provider evidence may be mixed in.
5. No native rule change; the previous authorized native-rule epoch is carried forward.
6. The plan continuation is `uninvoked`, `reservation_already_applied=true`, and
   `current_attempt == next_execution_attempt == facts.task.attempts`. No retry_failure,
   failure refund, added ordinary attempt or changed permissions/scope/acceptance is allowed.
7. Target base equals the existing resolved execution base, dirty capture source equals
   current resolved execution source, prepared source equals that exact dirty source.

For every other purpose, the new binding digest must be absent/None. Different-source
capacity SOURCE_REBIND still uses its existing plan.facts proof and PAUSE contract, without
adopting the new binding-only digest. A purpose plus the new field cannot broaden ordinary
source change, legacy recovery or stopped-provider retry semantics.

The binding model enforces local fields; shared typed plan/binding validators enforce
cross-record relations. Reuse those validators at service creation/publication, immutable
store reads and queue consumption. JSON Schema must express the local purpose/field/mode/
authority conditions, while comments/tests distinguish cross-record guards enforced in code.

# Exact authority and anti-grafting checks

| Boundary | Complete authority and refusal |
| --- | --- |
| Public Console/Host proposal | Fresh parent Requirement checkpoint; unique matching native child Task; exact Project/repository/allocation; Task intent/revision/WorkItem/current source; engineering duty. Caller supplies no receipt fact. |
| Collector under Worker/process + SQL fence | Unique non-CLOSED current Coder, Task IMPLEMENTING, no ACTIVE claims even if expired; original allocation/accepted artifacts/permissions; target equals resolved existing base. |
| Current capacity selection | Current disposition classification CONTEXT_CAPACITY, evidence exactly context-capacity://receipt digest, unique current dispatch sequence, exact Task snapshot SHA/revision/source and claimed_context_capacity proof. A different Task receipt or old generation cannot match. |
| Full historical no-start proof | Reopen immutable receipt key/digest, actual original claim/assignment/lease/dispatch/checkpoint, original step epoch and exact untruncated Context/Task/claim/request. Historical baseline selected at original claim time; full store patch/authority checked. Unreadable/orphan ledgers reject. |
| Contradictory execution | Existing actual original Run/claim invocation-start/outcome, provider route, artifact, native capture-start/stop/receipt/admission rejects no-start. Alternate Run under same claim also rejects; later legitimate claims require their exact independent provenance. |
| Prepare plan | Full dirty/complete captures, source/target, native rules and inventory; purpose-specific feasibility before publishing. Same-base refresh does not call Git merge/replay. |
| Execute | Exact plan/facts digest, exact operator PAUSE; recollect current receipt/queue/Task/full workspace under same fence before authority/start. Compare fresh facts/inventory with frozen plan; stale/foreign/already-started receipt cannot be grafted by resealing a digest. |
| Publish binding/store read | Cross-check binding purpose/digest equals exact plan current receipt, continuation invariants, capture sources/target/inventory and exact independent authorization; start embeds exact plan, binding extends exact predecessor. Model hash alone is insufficient. |
| Queue consumption | Real Task row/intent/revision/current WorkItem/source, no ACTIVE owner, already-applied uninvoked attempt; full binding/plan association. Same original WorkItem dispatch generation only; no Task UPDATE/refund. |
| Separate RESUME | Latest complete binding, exact original Task revision/source/inventory, paused disposition and distinct engineering continue authority; full re-collection covers original no-start claim. Stale binding/foreign disposition/source/workspace reject. |
| New execution/reader | Fresh actual claim/Context/Run, baseline full-store verifier and exact dirty inventory gate. Historical capacity marker remains bound to original source/claim; future legitimate provider invocation belongs to a newer generation. Old resume authority cannot kick a later claimed/result generation. |

For the new purpose, skip the Git mutation adapter entirely: no reverse/reapply of an
identical patch. Reopen full captures and inventory before and after recording the operation
start/binding; publish only the same exact source and inventory under process/SQL ownership.
Existing SOURCE_REBIND and conflict/coder_reapply Git operations remain unchanged.

# Data flow

Original Task/events + exact native receipts + capacity claim/Context/no-start evidence
→ collector full facts + dirty/complete captures + context_capacity_resume exact plan
→ exact engineering PAUSE authorization
→ append-only binding carrying exact capacity digest and equal inventories
→ existing same WorkItem overlay and EXECUTION_BASELINE_PAUSED disposition
→ separate continue authority pinned to latest binding/inventory/disposition
→ fresh Coder claim + BaselineInitialWorkspaceAdmission
→ retained work → candidate → independent QA → independent Reviewer → DONE.

Native interruption receipts may be resolved by the exact new binding. The old receipt
remains history and must not be reused as active authority. Production baseline inventory
admission must remain the selected dirty gate, rather than a consumed recovery seed or
generic clean-worktree gate. Complete historical evidence stays in the store; any reading
projection still requires full trusted validation before provider start.

# Positive, negative and boundary matrix

| Condition | Result |
| --- | --- |
| Exact same-base no-start capacity + legal draft + new purpose + exact PAUSE | Preserve inventory; bind; same attempt pause |
| Same-base SOURCE_REBIND even with valid capacity evidence | Reject at proposal; use semantically exact new purpose |
| New purpose without current exact capacity evidence | Reject before plan/start/authority/source/queue mutation |
| New purpose with coder_reapply or changed source/native rules/inventory | Reject; no policy expansion |
| EngineeringAdmission instead of exact operator PAUSE | Reject |
| Capacity receipt has real invocation/provider/native output | Reject full no-start gate |
| Wrong Task/claim/source/Context/receipt/plan digest | Reject; preserve original records |
| Previous dispatch receipt/resealed foreign receipt/old disposition | Reject current selection and full identity independently |
| File/index/ignored protected path drift after proposal | Refuse execute/continue; retained files unchanged |
| Initial capacity attempt1 clean / current attempt3 dirty / repeated same-base capacity | Same respective reserved attempt; no duplicate Run, refund or extra work identity |
| Real source descendant of unchanged execution base | Preserve exact descendant source; no flatten/reapply |
| New purpose with old native receipts resolved | Native receipts remain durable; baseline gate admits exact dirty inventory |
| Missing optional binding digest on old source-change records | Original wire/hash and behavior |
| Different-source existing plan with capacity proof | Existing source-change PAUSE path; unchanged budget |
| Default/null optional field | Omitted in canonical wire; old digest unchanged |
| Changed new-purpose field in resealed binding | Full store plan/authority relation rejects even if local SHA is recomputed |

# Old hashes and Schema parity

Use the established `Field(default=None, exclude_if=lambda value: value is None)` pattern.
Do not inject a new field or purpose into old records and do not change existing enum values,
defaults, schema_version, canonical hashing or serializers. Existing bindings without the field
must reproduce byte-identical to_wire and recompute_sha256 values, including explicit input null
normalizing to the historical omitted form. New records intentionally acquire a different hash.

Regenerate every canonical static Schema embedding BaselinePurpose/ExecutionBaselineBinding,
including execution-baseline-plan.schema.json, execution-baseline.schema.json and Console
operation/Context/recovery embedded definitions. Apply canonical JSON cross-field guard helpers
so `model_json_schema()` fresh parity and external jsonschema enforce purpose-local rules.
Do not relax additionalProperties or hand-edit only one duplicated $defs. Test legal new purpose,
wrong purpose/digest pairing, wrong mode/authority, old absent/null wire and embedded parity.

# Public intent and UI effects

No new ConsoleAction: retain PROPOSE_EXECUTION_BASELINE, EXECUTE_EXECUTION_BASELINE and
RESUME_EXECUTION_BASELINE. Add the enum to BaselineProposeCommand/Intent and declared versioned
capability metadata so older servers do not advertise it. New-purpose proposal must omit target_base_ref or set it to None; the backend derives the
unchanged resolved current execution base from verified facts. An explicit caller SHA is rejected.

Audit the frontend purpose allowlists and matchers: engineeringBaselineProposalOperation,
engineeringBaselinePlan, engineering pending/execute operation matching, rendering and supported
actions/contract-version guards. Route capacity waiting to “平台输入已修复，准备保留进度继续”;
show “代码版本和完整开发进度保持，模型尚未开始本轮执行”，approve “批准保留进度，保持暂停”，
then the existing “继续原需求”. Do not claim code/repository baseline was updated. Source-update
controls keep “更新原分支的代码与项目规范” and conflict/native rule review semantics.

Console manager result/guidance, copied processing reports and Team read-side purpose labels
must use the same semantics. Existing capacity receipts remain actual historical no-start facts.

# Consumer impact and implementation ownership follow-up

After approval, audit domain/execution_baseline.py; manager baseline_models/propose collector/
execution_baseline/baseline_store; work_queue/baseline consumption/release; capacity_input_reader
historical epochs; recovery/baseline_source terminal history; orchestration/context baseline
readers; agents candidate/source bindings; Host/Console command/results; team_view snapshots/JS;
Schema generation helpers and contract fixtures. Exact-purpose branch decisions must not fall
through source-change Git behavior. Existing trusted downstream readers can remain code-identical
only if they call the strengthened full store/association validator. Record every checked site.

# Test design

The new integration regression uses public TeamHost calls with a temporary repository,
real isolated MySQL queue claims, real owned subprocess termination, real native receipts,
real Codex workspace admission/finalizer, and fake provider output only. It intentionally
fails at the current same-base final binding refusal; after implementation it must continue
through the actual pause, separate resume and independent role gates. It must not mock a
binding, manually update Task attempts, insert native receipts or reset the dirty workspace.

Root explicitly authorized production implementation after independent design review. Deployment
and real Requirement approval remain root-owned; all implementation receives independent review.
