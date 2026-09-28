# Continuation knowledge wait

## 1. Scope / Trigger

A source-changing recovery or prerequisite repair may finish Coder and stop in the QA/Reviewer
knowledge consultation. This is a Manager-owned wait, not MANAGER_FAILURE, a business verdict,
or permission to rerun Coder. Applies to first execution and fresh-process continuation.

## 2. Signatures

- `recovery.context.approved_parent_context(config, scope, parent_id, parent_sha)` returns the
  verified parent sources shared by fresh recovery and prerequisite repair.
- `multi_directory.production.approved_joint_context_sources(checkpoint, unit_id)` is the single
  source projection for ordinary delivery, fresh repair/recovery and restart: parent context plus
  the unit's sealed native/Team/Project sources. Do not copy its filtering into each caller.
- `knowledge.legacy_scope.retain_legacy_snapshot(current, gap, contexts=..., records=...)` verifies
  a narrowly scoped historical native-body omission and returns the original snapshot unchanged.
- `context.native.rebind_native_rule_sources(repository_root, profile, sources)` resolves existing
  native source bodies against the successor's sealed profile, preserving URI/roles/priority.
- `ChildKnowledgeGapRaised(gap: KnowledgeGap, child: ChildDelivery)` transports the durable
  native checkpoint with a knowledge wait; it validates exact Task/repository and checkpoint hash.
- `TeamHost.resume_delivery(ResumeProjectDelivery)` hands a verified child wait to the normal
  Requirement coordinator using a new command without the consumed repair/verification approval.
- Existing `GET .../requirements/{id}/knowledge-gaps` and
  `POST .../requirements/{id}/knowledge-resolutions` remain the only human resolution facade.

## 3. Contracts

- Fresh successor context includes the exact approved parent, Team/Project manifests and unique
  repository child. Parent context is a separately approved input; do not rewrite the historical
  continuation-context digest or an old plan to add it.
- The successor preparation can differ from the original parent preparation. At native dispatch
  composition, Continuation/Recovery allocations bind native bodies to their own frozen profile:
  read exact Git objects with replacement refs disabled, verify size (at most 256000 bytes) and
  raw SHA, then redact. Never combine old parent native bodies with a newer approved baseline,
  read mutable HEAD, or relax the legacy snapshot guard. No new permissions or environment keys.
  Missing historical bodies remain explicit; unknown URIs, missing objects or SHA mismatch reject.
- After successor admission raises a knowledge wait, Manager reconstructs the child runtime from
  its newly durable preparation before reading status. The pre-admission child backend can be stale.
- Native `deliver` catches only `KnowledgeGapRaised`, reads `service.status`, and transports the
  current child. Joint service saves that planned child before WAITING_HUMAN. A stale parent child
  must not invalidate a legitimate approved knowledge resolution after restart.
- Legacy task-scoped gaps are recognized only for `task_continue_*` QA/Reviewer, with
  `requirement_id == task_id`. Current parent membership, native child Task/repository/root,
  Team/Project identity, and sealed implementation candidate must prove ownership. Caller-supplied
  Task IDs or matching names are insufficient. Read-only lookup never edits old gap bindings.
- The same legacy Task/role/candidate resumes under its original knowledge scope. Recomputed
  snapshot must equal the sealed snapshot, except materialized native bodies already attested by
  URI/hash in the gap's original context baseline. Verify that context's Task/role/revision, no
  historical joint source, exact baseline repository/URI/digest, same snapshot owner and every
  original document unchanged. Each added document must be repository-scoped and exactly match
  an opaque native reference. Keep the original retrieval snapshot, while current role context
  carries full approved rules. Unknown additions, redacted/nonmatching bytes and missing history
  remain `LEGACY_KNOWLEDGE_SCOPE_CHANGED` or the underlying integrity error; never guess equivalence.
  Changed knowledge selection cannot erase an old gap.
  New Tasks use the parent scope. The recovery stage proof still binds exact gap/resolution/run,
  Team/Project/repositories, and the current immutable parent child Task.
- Approval answers only the question. It neither grants generic commands nor supplies a QA verdict.
  Controlled UI capability, candidate-specific plan approval and independent acceptance remain
  distinct. No SQL migration, old approval replay, historical rewrite or new runtime env key.
- Context description text is part of the immutable dispatch digest. Reconstruct either the
  current description or the one explicitly supported legacy QA description, accepting only an
  exact complete `continuation_context_sha256` match. Do not accept arbitrary stored prose or
  regenerate a historical digest. Failed-Coder recovery preserves the same supported description.
- A native BLOCKED projection with `INVARIANT_VIOLATION`, `failed_stage=DELIVERING` and retained
  candidate/Task revision at QA or REVIEW may append DELIVERING and resume the same native runtime.
  This repairs platform pre-model interruptions, not terminal Task failure. It preserves Task,
  revision, candidate, stage attempts, dispatch and original error history; ordinary runtime role
  and knowledge gates still run. BLOCKED/FAILED Tasks and inconclusive verdicts cannot use it.

## 4. Validation & Error Matrix

| Condition | Required result |
| --- | --- |
| Exact durable QA gap after repair | Parent WAITING_HUMAN, latest native child retained |
| Legacy gap with wrong Task/candidate/repository/Project | `GAP_NOT_FOUND`; no resolution |
| Legacy scope snapshot drift | `LEGACY_KNOWLEDGE_SCOPE_CHANGED`; no role invocation |
| Previously attested but omitted native bodies become readable | Preserve exact old retrieval snapshot; full current role context, no history rewrite |
| Approved successor preparation differs from parent | Exact successor Git/profile bodies; re-open child runtime on knowledge wait |
| Mutable checkout drift or missing/mismatching sealed native object | Ignore current checkout; reject unavailable/mismatching sealed bytes |
| Unplanned child or gap/child mismatch | Reject typed handoff before parent update |
| Resolution with wrong run/gap or unowned child | `STAGE_RESOLUTION_BINDING` / committed-resolution rejection |
| Approved exact gap, fresh Host | Resume QA/Reviewer; Coder count unchanged |
| Supported historical context wording | Exact old dispatch digest required; no record rewrite |
| Arbitrary context drift | Reject before model invocation |
| Platform failure projection while Task remains QA/REVIEW | Same-runtime resume; no Coder dispatch |
| Terminal Task or non-platform verdict failure | No nonterminal recovery shortcut |

## 5. Good / Base / Bad Cases

- Good: repair Coder produces candidate; QA asks about UI authority; Manager records wait, exact
  answer is approved, fresh Host resumes QA then independent Reviewer and completes parent.
- Base: no knowledge gap; ordinary serial delivery and existing prerequisite approval stay unchanged.
- Bad: catch every exception as WAITING_HUMAN, rename old gap requirement_id, return synthetic QA
  PASS, replay repair approval, or restart the repair Coder to avoid recovering the QA checkpoint.

## 6. Tests Required

- `tests/recovery/test_prerequisite_repair_mysql.py`: both normal and omitted-parent-context
  historical cases must exercise real Git/MySQL, repair approval, visible current gap, approved
  answer, fresh Host and parent DONE; one Coder per repository, exact independent role order.
- Same fixture rejects foreign candidate, Task, repository and Project ownership; existing four
  source-kind/restart cases retain repair authority and old terminal Task history.
- Legacy fixture freezes the original QA-description bytes and injects an actual context-read
  failure through the backend, then resumes the nonterminal QA without checkpoint manufacture.
- `tests/recovery/test_delivery_continuation.py` covers QA/REVIEW vs terminal Task and invariant
  error vs inconclusive verification; original error checkpoint and attempt counters remain intact.
- `tests/knowledge/test_legacy_continuation_scope.py`: exact scope reuse and snapshot-drift denial.
- The real Git/MySQL fixture must include README plus multiple native Trellis rules, not only
  `hello.txt`; assert all three sources in the FIRST repair Coder context and successful historical
  gap resolution/restart. Native-body unit cases cover both QA/Reviewer and modified-rule rejection.
- Commit changed native rules between parent intake and repair approval; assert first Coder uses
  the approved new rules, legacy gap recovery keeps the original snapshot, and restart reaches
  DONE without duplicate Coder. `tests/context/test_native_sources.py` covers mutable checkout
  isolation, source role preservation, foreign URI and mismatching frozen profile rejection.
- `tests/manager/test_team_host.py`: child knowledge wait reaches coordinator, consumed approval
  omitted; `tests/knowledge/test_stages.py` retains exact proof and resolution validation.
- Run MySQL fixtures serially using only the isolated `ASE_TEST_MYSQL_DSN`, never production DSN.

## 7. Wrong vs Correct

Wrong: `except KnowledgeGapRaised: raise ManagerFailure()` or publishing WAITING_HUMAN while
the parent still names the pre-repair Task.

Correct: validate durable gap ownership → reconcile latest native child → journal Manager wait →
approve exact resolution via normal API → resume the original QA checkpoint with frozen scope.
