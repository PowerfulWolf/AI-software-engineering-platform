# Knowledge-preparation pause implementation

## Root cause and implementation boundary

The structured client could observe a real Host pause before creating transport observations,
then raise an ordinary `SERVICE_PAUSED` error. The knowledge journal correctly retained a failed
outcome, but its empty execution tuple did not contain independent positive refusal evidence.
The delivery wait collector could not safely turn that historical absence into no-start proof.

The prospective implementation records the actual pre-admission refusal at its guard, publishes
the raw typed record independently, and binds it to the complete journal intent and outcome.
The alternative existing native admission-closed path still requires its independently sealed
admission/not-started pair. Generic provider errors and mixed or incomplete route histories
remain unknown. Neither path fabricates a main-role execution or a process-stop fact.

`KnowledgePreparationPauseEvidence` crosses the domain, Manager wait service, immutable
resolution and MySQL consumption boundary. The public collector reopens independent original
bytes, complete claims, scope, Context and frozen knowledge snapshot. It scans both legitimate
knowledge lanes and rejects contradictory main invocation/output or unresolved earlier phases.
The exact resolution makes the same WorkItem ready with dispatch sequence +1; the dispatcher
issues a new claim/Run/Context without changing the Task attempt, source or frozen work budget.
An unconsumed persisted resolution must re-read its positive proof before retrying consumption.

Historical empty-execution pauses use a separate current engineering decision. They retain an
UNKNOWN historical transport outcome. The narrow baseline purpose is
`knowledge_preparation_isolation`, with exact original claim/context/step/outcome, current
trusted double observations of both repository and Coder worktree, and explicit ENGINEERING
confirmation. Proposal and execution preserve the approved base, complete dirty inventory,
full patches and accepted progress. Execution consumes one ordinary work allowance, creates
a new paused WorkItem, then requires a distinct exact RESUME. This path grants no transient
refund, source update, verdict, candidate acceptance or permission to modify native rules.

## Cross-layer verification

| Dimension | Required association and check |
| --- | --- |
| Producer to journal | Real trusted pause epoch/request identity; independent immutable raw receipt; no inferred receipt for generic old errors |
| Journal to wait | Exact Task/role/claim/lease/dispatch/phase/request/source/Context/snapshot and Requirement scope; complete legal lane scan |
| Wait to public decision | Positive proof required in both directions; no mixed proof family or retry cause; unchanged original Run lineage |
| Decision to MySQL | Task lock and queue authority fence; current claim/generation/checkpoint/intent/source/attempt; no active role owner; once-only consumption |
| Legacy baseline | Exact current engineering confirmation and fresh dual-root observations; UNKNOWN history preserved; same Task/base/worktree; ordinary work attempt +1 |
| Baseline to next role | Completed binding/authorization/plan/proof chain reopens original bytes; paused execution needs separate RESUME and fresh claim |
| Schema and API | Canonical guards propagated to every embedded Console/cleanup/baseline schema; regeneration repeatability and old absent-optional wire compatibility |
| Deletion | Requirement-exact root indexes, lane receipts and orphan pre-outcome raw receipts removed without deleting foreign records |

Shared types remain in the domain or the existing typed baseline seam. No alternate SQL schema,
free-form shell permission, model-authored approval or second retry budget was introduced.
Console intents inherit the typed baseline command, including the exact maintenance confirmation.

## Independent review corrections

The independent review identified guards and collector checks before deployment. Their regression
coverage includes requiring positive pause proof for a pause URI, rejecting an isolation reservation
with an interruption receipt, requiring isolation proof when its reservation cause is selected,
and authenticating the original Requirement scope and all same-lease preparations. Review findings
and final source hashes are recorded in the verification document when the reviewed code is stable.

## Existing K1 data and rollback

Target only Task `task_recovery_711a755e5852a52346876a7b07376311`, its exact Run5 original
knowledge pause and owning Requirement. Preserve the first three accepted Coder slices,
the inherited complete patch, original source and all original outcomes, claims, failures and
investigations. Do not edit the Coder worktree or production SQL. After independent testing and
deployment, use the public baseline propose → exact current ENGINEERING execute(PAUSE) →
separate RESUME operations; record each immutable plan/authorization/binding/operation identifier
and verify the fresh claimed execution and subsequent independent QA/Review.

Rollback must occur only at a verified idle/paused boundary. Preserve all newly written typed
proof, plan, authorization, binding, resolution and queue records. A reader without the new
purpose cannot resume those records; restore compatible readers rather than deleting history
or invoking the old missing-start fallback. Fixture success is platform regression evidence,
not a real K1 candidate or delivery verdict.
