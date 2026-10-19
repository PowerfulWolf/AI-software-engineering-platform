# Legacy knowledge preparation: current engineering isolation

Status: parent-confirmed design, implemented for independent verification. This is a separate,
explicit engineering recovery path for stored data; prospective admission-pause receipts
cannot be backfilled into old runs.

## Goal, scope and unchanged facts

The exact current Coder WorkItem has a sealed knowledge intent and FAILED/SERVICE_PAUSED
outcome with no execution observations, no main-role invocation start, and a released real
claim. Its knowledge transport history remains UNKNOWN. Absence of execution observations,
the error message, released Lease, elapsed time and service READY cannot prove historical
no-start or process stop.

Allow an ENGINEERING principal to establish and approve current isolation, retain all
accepted progress and complete mutation bodies, and resume the same Requirement/Task,
same branch/worktree and frozen execution base. Reserve a fresh attempt/WorkItem/claim
using one ordinary work allowance. Do not refund the unknown preparation or fabricate a
provider-transient event. Approval first leaves execution PAUSED; a distinct existing
RESUME operation starts further delivery. Independent Coder/QA/Review gates remain intact.

## Typed contracts and authority

Add `BaselinePurpose.KNOWLEDGE_PREPARATION_ISOLATION` with wire value
`knowledge_preparation_isolation`. It is available only for the exact nonterminal
IMPLEMENTING Task / inactive Coder WorkItem in SERVICE_PAUSED wait. Target base is fixed
by the trusted collector; target and coder_reapply cannot be supplied by callers.

Add a typed `KnowledgePreparationIsolationProof` in a new manager helper. Bind:

- Exact EngineeringScope, native and joint Requirement IDs, Task intent/revision,
  WorkItem/checkpoint/dispatch/attempt, complete original QueueClaim and queued step.
- Complete original KnowledgeInvocationIntent and KnowledgeInvocationOutcome,
  their SHAs, original context and its verified execution.claim SHA, frozen snapshot SHA.
- Explicit `historical_execution_status=UNKNOWN`, `ordinary_work_consumption=1`, and
  `no_transient_refund=true`; these are constrained literals, not caller controls.
- Trusted current boot observation and **two current local execution surveys for each
  exact repository root and exact Coder worktree**. Surveys use the existing OS observer,
  must be complete and idle, cover the same machine/boot/account/scanner boundary,
  have stable ordering, and are obtained under Task lock + queue idle fence. Paths come
  from trusted workspace binding, never from request parameters.
- A proof SHA over complete typed bytes. Keep the full old bytes, do not rewrite the old
  intent, outcome, context, wait, accepted artifact or invocation ledger.

Current surveys prove only their observed current local boundary. They do not prove
historical no-start, remote completion, or the attribution of an old claim to a service
PID. The production operator must use a distinct exact-plan confirmation
`confirm_current_knowledge_execution_isolated=True` with ENGINEERING duty and an auditable
`reference` describing the current maintenance decision, including any firsthand official
shutdown/READY/exit provenance. This is a **new current engineering containment decision**,
not a reuse of the October 14 historical declaration. It explicitly accepts UNKNOWN old
transport history and confirms that old execution/tool writers cannot now modify the
bound repository/worktree/knowledge lane. A generic Product approval, old stop boolean,
error text or user-selectable proof SHA grants no such authority.

The exact authorization is sealed through existing BaselineOperatorAuthorization and
HumanActionEvent recording. Do not pretend that service lifecycle JSON alone attributes
the old WorkItem or that a current config file freezes historical knowledge routes.

Add optional, absent-when-None proof fields to BaselineExecutionFacts,
BaselineExecutionReservation and ExecutionBaselineBinding. The new proof is exclusive
with all existing legacy/stopped/capacity/provider proof families. Add the exact original
claim to BaselineInvocationProof as a distinct `isolated_knowledge_preparation` family;
never put it into KnowledgeOnlyClaimProof, whose normal execution records remain required.

## Collection, preservation and queue transition

Revalidate the exact original intent/outcome from its lane, original frozen knowledge
snapshot and context, claim/step, scope, source, requirement identities, failure kind and
absence of other knowledge execution records or contradictory main invocation/result,
accepted output, native capture or completed route. This first implementation rejects
mixed or multiple unresolved preparations instead of inferring their safety. Revalidate
all other historical claims through existing accepted proof families.

Use existing baseline propose/execute/continue APIs. Propose retains complete dirty
capture, complete execution-base-to-current-tree patch, accepted progress IDs, inherited
patch inputs and full inventory. It must not supersede accepted progress merely because
the failed knowledge preparation had no main output. Require unchanged native rules,
source revision, branch, worktree, inventory and full frozen write policy.

Propose and execute each take two fresh current OS surveys; execute compares stable
boundary identity with the approved proof and validates exact current Task/queue/patch
facts. Observation timestamps may change; no cached idle survey authorizes execution.
An incomplete survey, current writer, changed boundary or changed input refuses recovery.

The reservation is a new explicit branch before the current `start is None -> uninvoked`
fallback: current attempt -> current+1, `retry_cause=knowledge_isolation`, ordinary
budget check, no retry_failure. Parent-owned queue consumption atomically preserves the
old waiting WorkItem/history, checkpoints the new attempt and creates a fresh paused
Coder WorkItem/step with exact binding. The Task identity, frozen Product/Design/Plan,
approved base and accepted progress remain unchanged. Separate RESUME uses existing
exact binding + inventory + idle-fence checks and produces a fresh claim/Run/Context.

Later baseline fact collection may recognize this historical claim only through the
immutable prior completed binding -> exact approved plan -> exact ENGINEERING
authorization -> original isolation proof chain. Re-read and validate the old
intent/outcome/context/claim bytes; do not demand old surveys become new historical
no-start evidence. This permits future legitimate work without widening the generic
missing-start fallback.

Knowledge sidecar publication is not universally claim fenced. Therefore this recovery
must not claim SQL Lease release alone prevents every late knowledge write. Actual
current local survey and the explicit current engineering containment decision are both
required; any newly observed original-lane facts or contradictory writer block recovery.

## Ownership proposed

This subagent owns new `manager/knowledge_isolation.py`,
`domain/execution_baseline.py`, `manager/baseline_models.py`,
`manager/baseline_production.py`, `manager/execution_baseline.py`, related focused tests,
and the new executable spec. Any composition wiring in TeamHost/Console/engineering
recorder will be reported early and coordinated before touching shared files.

Parent owns `domain/delivery_resolution.py`, `manager/delivery_wait.py`,
`work_queue/execution_store.py`, queue consumption integration and generated schemas,
forward pause-refusal implementation, production maintenance authorization/deployment,
and actual K1 controls. Parent will assign independent review; this implementer does not
author a QA/Review verdict for its own changes.

## Validation matrix and commands

| Input/fact | Required result |
| --- | --- |
| Exact legacy empty-execution pause; complete old claim/context; fresh idle dual-root double surveys; exact current engineering approval | Same Task/base/worktree, full progress/patch retained; ordinary attempt+1 paused reservation |
| Same data without explicit current engineering approval, or Product-only principal | Reject, no state/budget/write changes |
| Generic missing-start, different failure, mixed or unknown extra preparations | Reject; no generic legacy no-start inference |
| Missing/corrupt/foreign intent/outcome/context/snapshot/claim, wrong source or stale checkpoint | Reject before queue consumption |
| Native/HTTP/route observations or main invocation/result contradict scope | Reject this narrow path; retain actual facts |
| Live writer, incomplete survey, repository/worktree mismatch, boundary drift | Reject and preserve old wait/draft |
| Ordinary allowance exhausted | Reject; never transient refund or enlarge frozen policy |
| Different target base, changed native rules, changed dirty inventory/full patch | Reject; require a different explicitly authorized workflow |
| Execute approved plan | No model launch; complete binding and new paused reservation only |
| Distinct RESUME | Fresh WorkItem/claim/Run/Context; no old run reuse; normal QA/Review remain required |
| Exact execute/resume replay | Idempotent; no extra allowance, task or dispatch |
| Later collector reopens valid approved historical isolation | Old UNKNOWN retained; original claim covered only through full immutable approval chain |
| Old wire data has no new optional fields | Identical bytes/digests/store keys |

Focused tests should cover typed proof/authorization models; real immutable old knowledge
records/context/claim reader; proposal/execute pause with real Git complete capture and
inventory; fresh survey failures and changed facts; budget/no-refund/idempotency; historical
proof reopening and ordinary paused RESUME. Parent integration must use public Host APIs
with an isolated MySQL database and fake model ports, verify original data unchanged and
new Task identity equal, and validate all generated Schema contracts. Run Ruff/format,
strict Mypy and related existing baseline/legacy/service-pause/queue tests.

## Existing data, rollback and non-goals

Stored K1 intent/outcome and old investigation remain byte-for-byte immutable and UNKNOWN.
No direct SQL repair, fake no-start receipt, new Requirement/Task, rebase, transient
refund, historical permission expansion, verdict rewrite or candidate acceptance occurs.
The old accepted progress and required full patches remain readable by the next Coder.

Roll back only at a verified idle/paused boundary, keeping all proof/authorization/binding
records. Older code must refuse unknown purpose safely; it must not delete records or
resume via the missing-start fallback. New schemas, runtime and UI/API compatibility ship
as one platform version. Final delivery remains subject to independent QA and Review.
