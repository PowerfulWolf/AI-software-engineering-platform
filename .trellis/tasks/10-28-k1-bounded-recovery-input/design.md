# Bounded complete recovery input design

## Decision

Use **serial full-source Contexts**, not an MCP stream or a deterministic patch pre-apply. The
three source patches are independently approved, overlap heavily, and do not apply cleanly to
the approved target revision `58fed894a0e98854974b47a2ed4aa0d9115d469b`. An isolated
`git archive` plus `git apply --check` failed for all three patches on that exact revision;
`git apply --3way --check` also failed for the latest patch. Automatically applying a subset or
choosing conflict resolution would reinterpret the approved `coder_reapply` task. Coder must
adapt source intent and QA/Review must verify the final code.

Each complete patch fits the Context window separately. A new ENGINEERING decision schedules
the three full sources in approved ancestry order. The frozen Task allows up to 10 Coder work
attempts and 40 execution identities, sufficient for three accepted progress/candidate runs
with bounded retries. A single run may still hit its actual final-input limit; the ordinary
`CONTEXT_CAPACITY` wait remains authoritative and never starts a provider.

## Exact typed contract

Define `RecoveryInputSchedule` v1 with immutable digest over:

- `plan_sha256`, `task_id`, Task intent digest, target `base_revision`, dispatch and seed digests;
- current `work_item_id`, exact `CONTEXT_CAPACITY` disposition digest, current Task revision;
- ordered `source_id`, `uri`, `sha256`, UTF-8 `bytes` for each of the three original sources;
- `mode=one_complete_source_per_accepted_coder_run`, maximum sources `3`, engineering actor,
  signed human resolution/reference, and platform runtime revision.

Only the trusted Manager/engineering resolution service may create this record. It first proves
that the old Context assembly failed before any Coder Context, invocation, accepted output or
model start; the current Task/WorkItem and exact sealed Plan/approval/dispatch/seed are still
current; and the target worktree has no unreceipted mutations or current writer. The decision
is stored atomically outside the target repository and records `HumanActionEvent`. A duplicate
same-body replay is idempotent; changed-body reuse rejects. It neither edits the Plan nor
reclassifies the old capacity wait.

`RecoveryContextSourceSelector.build(task, agent, attempt, input_artifacts)` derives the source
index from the **accepted CoderProgress chain**, not the attempt number. With zero accepted
progress, include source 0; with one, source 1; with two, source 2. A rejected/failed Run keeps
the same source. Context always includes a required `recovery.input_schedule` section binding
the decision and all three source identities. It includes one untruncated full patch section.
All other required Task/Product/Design/Plan/feedback/native-rule sections remain unchanged.
The historical `coder_reapply` Context shape remains valid for previously sealed runs.

At initial and every later Coder admission, re-open the original sealed Plan, all three complete
source bytes, decision, current Task/WorkItem/claim and selected Context. Compare raw UTF-8 byte
length and SHA-256 for every source. A selected Context must contain exactly the scheduled full
source and none of the other full sections; the schedule manifest cannot stand in for bytes.
The `execution.baseline` projection binds the full retained patch SHA and URI without duplicating
the body; older Contexts continue to validate under their original rule.

The accepted CoderProgress chain supplies `context_manifest_id` and producer Run ID. For every
source already advanced, read its sealed artifact and Context; require same Task/Plan/decision,
actual accepted `coder_requested_continuation` event, legal supersedes lineage, same Git input
revision and a real prior claim/invocation. The final Coder implementation can be committed only
after sources 0 and 1 have such accepted progress and source 2 is fully present in its current
Context. This is an **input coverage** gate, not an assertion that code semantics are correct;
QA and Review still decide that independently.

The final Coder may need more than one run for source 2. Later accepted progress can repeat the
last source, with coverage retaining all three. It may never skip a source, borrow another Task's
Context, or count an unaccepted output. Existing work-slice, worktree inventory and candidate
commit gates still run.

## Boundaries and error matrix

| Case | Required outcome |
| --- | --- |
| Exact decision, source 0 full Context, accepted progress | Next claim selects source 1 |
| Failed or invalid source 0 output | Next claim selects source 0 again |
| Exact source 0/1 progress, source 2 complete current Context | Candidate may reach independent QA |
| Any missing, truncated, foreign or mutated source/Context/progress/claim | Reject before model or candidate; preserve worktree and wait |
| No new decision | Original strict three-full-source `coder_reapply` contract remains; capacity wait continues |
| Existing historical full Context | Validate and replay by original contract; no migration |
| Model cannot fit even one scheduled full source plus required inputs | Retain `CONTEXT_CAPACITY`, no provider call or receipt fiction |
| Source content conflicts with newer base or prior progress | Coder adapts within permissions; unresolved conflict returns a blocker, no automatic patch application |

Good: three accepted serial Coder runs each see one entire source, followed by QA and Review on
one final candidate. Base: old full-input `coder_reapply` records remain byte-compatible. Bad:
turning the three patches optional, raising the budget beyond the actual model window, counting
model text as a receipt, or applying conflicting patches in the Manager.

## Test order

1. Pure selection and coverage tests: exact three sources; failed/rejected Run repeats a source;
   accepted progress advances once; foreign Context, missing bytes, wrong order and SHA drift fail.
2. Context/Schema tests: selected required patch is full and untruncated; all other required
   sections preserved; legacy Context unchanged; final serialized payload fits or retains wait.
3. Candidate and role tests: no commit before full accepted coverage; Coder cannot alter
   verdict/permissions; QA/Review remain separate identities.
4. Guarded isolated MySQL public fixture: no-start capacity wait → exact engineering decision →
   claimed Run 1 progress → Run 2 progress → Run 3 candidate → QA → Review. Reboot after Run 1,
   stale-claim and tampered decision/source negative cases. Assert old UNKNOWN/Plan/Task bytes.

## Implementation slices

1. Versioned decision/Schema/store and immutable source inventory.
2. Context selector and strict legacy-compatible admission.
3. Candidate coverage gate, same-Task queue continuation and public resolution action.
4. Guarded end-to-end fixture, Console projection, documentation, controlled release.

Do not publish slice 1 or 2 alone: it cannot safely activate K1 and could make the UI imply a
recovery path that is not yet executable. The earliest safe release is all four slices with the
public fixture passing.
