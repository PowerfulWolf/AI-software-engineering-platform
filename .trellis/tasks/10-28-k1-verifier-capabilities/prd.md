# Complete mixed verification for the original K1

## Goal

Enable ASE to finish the already approved K1 through its original Coder, independent QA and
independent Reviewer path. This task concerns the five executable end-to-end rows that the
current registered verifier cannot run. It does not replace the K1 Requirement, rewrite its
frozen ProductSpec/Design/Plan/Task, change its source revision, or convert a process result
into a role verdict.

## Fixed input and current state

- Parent Requirement: `delivery_multi_bb78e2316afca47d005384542f685174535b69db`.
  Current successor Task: `task_recovery_b06bffe70284000da954ea92ef7196a2`.
- Frozen Plan: `art_plan_82a991587e999e9eb68e24fd`, integrity SHA-256
  `11cb3095a21abe119779621a270116a3800694a541c89d3b6db8e1b761f1633b`,
  source `58fed894a0e98854974b47a2ed4aa0d9115d469b`.
- The Plan has 61 original QA rows: 55 explicit `codex_sandbox_pytest_mysql_v1` rows,
  five executable e2e rows with no registered capability, and one document inspection.
  The five are one `node --test tests/team_view/browser/learning-collection.test.cjs`
  browser row and four mappings to the same exact
  `python -m pytest -q tests/learning_collection/test_live_a_to_b.py::test_production_a_to_b_live`
  command. The four mappings have distinct original row IDs and acceptance criteria.
- Both candidate test files are absent at the approved source revision. Coder is expected to
  create them. No candidate SHA, independent QA PASS, or Reviewer APPROVE is available yet.
  Coder can run despite the later verifier gap; its present capacity wait is handled separately.
- The 2026-10-22 v1 Docker browser experiment failed its full negative gate, but the independently
  reviewed fixed synthetic v2 profile did render, click and capture PNG, reject file/network/socket
  access, and clean up its owned resources (result SHA-256
  `7bf3688d5194526fcadf40ddbf9d6159507155e845e3e19c6780296801271d35`). Chromium's
  inner sandbox was explicitly disabled; the fixed Docker profile was the isolation boundary.
  This proves synthetic feasibility only. Candidate/claim binding and production registration
  remain absent. A scripted Host, Python subset, document check, or installed executable cannot
  satisfy the five missing rows.

## Acceptance criteria

- [ ] A real candidate contains the exact planned test entries. Missing entries follow the
  existing proof-bound static QA FAIL route; no executor reports them as passed.
- [ ] A versioned browser executor reuses or replaces the reviewed synthetic v2 isolation profile
  only after proving candidate- and claim-bound real render, click and observable UI state.
  Host/home/secret read, source write, external network, unauthorized socket and process escape
  probes fail; owned processes and scratch have a verified final state.
- [ ] A distinct versioned live A-to-B executor runs the exact frozen pytest node against an
  isolated **Configured** ASE Host and isolated SQL. A accepted output yields a real proposal;
  an exact human engineering decision publishes/selects it; a separately claimed B Run actually
  searches, reads and cites it. Trusted observations also verify automatic proposal/backlog
  recovery, A's unchanged snapshot/Context/report bytes, pre-publication retrieval refusal,
  cross-Project and wrong-role denials, and wrong Run/citation rejection. Real provider transport
  is observed through a credential-isolating broker. No production DB, provider key or host
  workspace enters candidate test code.
- [ ] A typed supplemental engineering authorization records the exact Plan, candidate, original
  row identities/argv/criteria/levels, executor versions/runtime digests and resource limits.
  It cannot edit the Task's frozen `EngineeringPolicy`. Each QA and Reviewer admission binds
  that decision to its own current claim, Run, candidate and budget.
- [ ] One complete mixed-role receipt binds all 55 Python rows, the browser row, the four live
  mappings, real child start/final records and cleanup. The document row remains an inspection,
  not a machine-command claim. Each of the five e2e rows retains criterion-specific trusted
  observations or an explicit independent source-review gate; one process return code cannot
  certify all four live mappings. No partial subset may become READY or start the role model.
- [ ] QA and Reviewer each execute and assess the complete group under separate real claims,
  on the same candidate SHA, with fresh output evidence checks. A failed/unknown command cannot
  support QA PASS or Review APPROVE; no model-authored receipt authenticates itself.
- [ ] A guarded isolated public fixture demonstrates original K1-style candidate → exact
  authorization → QA → Reviewer, including stale candidate, changed runtime, missing child,
  STARTED-without-final, lease expiry and crash recovery negatives. Actual K1 continuation uses
  the public Console/queue path and preserves all earlier history.

## Boundaries and prerequisite

The fixed synthetic browser v2 profile has a real Chrome positive and listed denials, but the
candidate/claim-bound production execution boundary is **not yet proven**. Implementation must
stop at that proof gate until the exact final profile is reproduced against an isolated candidate
and its owned resources. The concrete executor and aggregate contract in `design.md` are a proposal for independent
review, not current authorization or a claim of readiness. A candidate SHA is needed before the
supplemental production authorization can be sealed. The existing Stage 1 partition contract in
`.trellis/spec/core/verification-environment.md` remains active meanwhile.

The only files authorized for this planning slice are the three documents in this task
directory. `implement.md` lists a proposed implementation path inventory for a later exact
review and authorization. No K1 sidecar, SQL, Task, worktree, Plan, verdict or runtime setting
is modified by this planning slice.

## Stored data and rollback

Before any new execution record is consumed, a controlled idle rollback may disable new
capability admission. After supplemental decisions or mixed receipts exist, readers must remain
compatible and defects must be fixed forward. Preserve all old unsupported prerequisite
receipts, waits, budgets, claims and UNKNOWN execution facts. Do not reset SQL or recreate K1.
