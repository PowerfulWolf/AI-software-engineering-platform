# HTTP knowledge recovery repair and original K1 recovery

Status: platform repair integrated and deployed; the original K1 is running its next real
main Coder invocation. K1 has no new candidate or independent QA/Review verdict at this
observation. This document records execution facts, not an acceptance verdict.

## Implementation and independent verification

Runtime repair: `b238906a349e71a5a6dfb4de3cfef56fc1b9709e`, pushed to `origin/main`.
Rollback code reference: `07eae9b` (see consumed-decision limitation below).

- HTTP-only completion and HTTP/native fallback now rederive exact semantic rejection
  observations from independently stored admissions and completion receipts. Native routes
  retain actual owned-session stop and current liveness checks. Original bad citations stay bad.
- An already-persisted PLATFORM_BUG/empty-evidence wait is recoverable only after complete
  independent proof of its exact rejected knowledge preparation. No error-text authorization.
- When historical progress lacks a full after-inventory, a separate complete present draft
  observation requires explicit exact ENGINEERING acceptance. It does not invent past facts.
  Consumption and new provider admission both recheck complete bytes/modes/index/ignored files.
- Typed physical deletion includes original semantic observations, carry refusals and current
  drafts while preserving foreign scope. An independent reviewer found a historical-reader
  versus current-kernel coupling; explicit historical verification now permits deletion after
  reboot/PID reuse while retaining immutable lineage checks and separate inactivity guards.
- Independent read-only review finished with the finding resolved and no additional findings.

Relevant verification (all passed):

| Scope | Result |
| --- | --- |
| HTTP/semantic observation and physical-deletion regressions | 88 passed, 1 MySQL case deselected |
| Complete current draft and admission regressions | 17 passed |
| Native receipt, prior guard, delivery entry and wait regressions | 121 passed |
| Schema, idempotent generation, contract and parity checks | 66 passed |
| Isolated MySQL original wait/current draft/replacement/native supervisor recovery | 62 passed |
| All 19 changed Python files | Ruff check/format, strict Mypy and git diff --check passed |

The real red cases covered the original HTTP/native-stop mismatch, legacy wait shape,
accepted-progress inventory rejection, and historical native deletion after reboot/PID reuse.
One SQL assertion was corrected to inspect the immutable WAITING/WAIT_RESOLVED events: CLOSED
items correctly clear their current wait; the durable original wait remains unchanged.
The new SQL supervisor case ran fresh native knowledge and independent Coder/QA/Reviewer to
fixture DONE. That fixture result does not establish production K1 completion.

Commands used the project .venv, PYTHONPATH=src, PYTHONDONTWRITEBYTECODE=1, pytest -q
-p no:cacheprovider. MySQL tests used the identity-checked ASE_TEST_MYSQL_DSN and ran serially:
`tests/work_queue/test_rejected_knowledge_current_draft_mysql.py`,
`tests/manager/test_rejected_knowledge_native_entry_mysql.py`,
`tests/work_queue/test_rejected_knowledge_mysql.py`,
`tests/work_queue/test_rejected_knowledge_replacement_mysql.py`,
`tests/work_queue/test_knowledge_preparation_retry_mysql.py`,
`tests/work_queue/test_wait_resolution_mysql.py`.
Strict typing used `MYPYPATH=src python -m mypy --strict --no-incremental` with a private /tmp cache.

## Controlled deployment

Official `scripts/ase-console-service.sh stop` obtained READY and actual old-process exit.

- Old PID: `67060`; instance `console_instance_9f7dc6e121c84738f0076a24b1c35dd2`.
- Shutdown request: `console_shutdown_8878d2e66ca6bec4bd8f3238b8468d39`.
- READY recorded: `2026-10-21T06:18:29.040642Z`.
- New PID: `47254`; instance `console_instance_abb2bb862c943aaf57c2a7896960be11`.
- New RUNNING recorded: `2026-10-21T06:19:10.624930Z`.

The target clone and K1 worktree remain at approved source
`5547815464a04991f50a2e0532d6f2f13d8daa69`. Updating platform runtime does not rebase K1.
No recurring automation was created; a bounded foreground read-only observation ended after
finding the real main invocation.

## Existing data treatment

Exact public Requirement: `delivery_multi_bb78e2316afca47d005384542f685174535b69db`.
Native child: `delivery_c833c3235d0bb73adba67937d16ea66c`.
Task remains `task_recovery_6c7e369928a23df6e2ccf8ba32d6f816`.

After upgrade, the current original wait was inspected and handled through public operations:

- Inspect: `operation_5d7774609ae818f554531c7a0dfb9902`, SUCCEEDED, no missing facts.
- Handle: `operation_9c8896071bd38637cddfb6777be0b6ea`, SUCCEEDED/NEEDS_AUTHORIZATION.
- Exact proof: `fd32d6612456a009d5f768a9cf06c509f32d53296725fdde65d18ca6e045f479`.
- Current complete 21-file draft: `37007626fa1fc2304d69a146f72d1968cd22cbab572bfe22f5b27f59c7d3da6c`.
- Original accepted progress: `art_coder_ad453ed626a141a52548c2bda1e11b11`.
- Resolve: `operation_13e0e74e595e2b946cecd640a2978312`, SUCCEEDED.
- Consumed operator decision: `0b087057e21f208686f1a5803ef46c2c93c0444094f7b4617b685c25af3b21ef`.

The root maintainer used the user's existing delegated engineering/approval authority and
recorded an explicit public Resolve for the exact proof. No frozen automatic admission
approved the present draft. SQL was not manually changed. Original outcomes, rejected citation,
first progress, approval history and old queue events remain intact.

Old work `work_2b17cd34f8e2bf4840df927102e82e841446642207fb1265cd32d89bfbd703ab`
closed; successor is
`work_0b087057e21f208686f1a5803ef46c2c93c0444094f7b4617b685c25af3b21ef`.
Ordinary attempts/work_attempt increased once from 2 to 3. The frozen max_attempts remains
40, budget is not exhausted, Task revision remains 5 and source is unchanged.

## Subsequent factual knowledge clarification

New claimed knowledge Run `run_knowledge_1376a59070cf46c3d1770357842c6b39` returned valid
intent and assessment. Exact READ membership passed; assessment reported a Git/document SHA
conflict for gap `591b5ed69c297d6f7476c2a7885a97a7b3df630ac2aea0777956e76d3534320d`.

Independent read-only comparison confirmed worktree HEAD, git show at the Task source and
frozen snapshot `a6d8ac61712986f90d5939da9c3f05c85f6fa88f18b6c783613c52423dca1cfd`
agree on both documents:

| Native rule | Current/source/snapshot SHA-256 |
| --- | --- |
| .trellis/spec/core/active-knowledge.md | 267795c156767a32fdd64d22f9cedc2c526675beb7524a8fb8969960bb57c57c |
| .trellis/spec/core/web-console.md | d706312f22684c8bf5644fc0b92628467d51ae38d0ba9ed5a7ae538faf18e286 |

The public knowledge-resolution API sealed the exact factual answer as REQUIREMENT_ONLY:

- Resolution: `d1c8b718c59f5243a995c14640a0150dea7da3825179c860ee501e2f64a03741`.
- HumanActionEvent SHA: `04cee71a8490b458885bbec484497b5dcf4636ae93a10c0c1f86f69b5e0c045f`.
- Continue operation: `operation_53cb1be3260c8a2d52388dce43b65904`.

This clarification selects the already-approved Task/source/snapshot facts. It changes no
ProductSpec, protected-path authority, budget, source, snapshot or verdict. No future QA result
was supplied. Knowledge resumed under fresh lease `lease_dcfd530f9b1d5ee7794694a5` without
another ordinary work debit. New knowledge Run: `run_knowledge_36a601f72aaac35e5abdfef9921e12f7`.

## Verified live main execution and remaining delivery

Main Coder start at `2026-10-21T06:44:28.322817Z`:

- Run: `run_9757269a50ad4bdab3ce3115e4bc73fa`.
- Context: `ctx_22ecaa68ca24056ee09b64f19daa0cf489001e753ebc25effe39060f3e22b017`.
- Start SHA: `265faf31395b15415bdd60dc858c5e3c4d91fd25a2776e36289fccc43f92a56f`.
- Lease: `lease_dcfd530f9b1d5ee7794694a5`, attempt 3.

Read-only OS process/cwd inspection additionally found real Codex PID `8211` parented by
service PID `47254`, plus code-mode host PID `11332`, in the exact K1 Coder worktree.
Only metadata was read; no argv, environment or secrets were inspected.

At this observation K1 is IMPLEMENTING. First accepted progress only completes step01;
step02 through step08 remain Coder work. There is no new candidate/QA PASS/Review APPROVE.
Final K1 acceptance still requires its approved 25 AC/61 test-level records, real browser and
real production A-to-B knowledge reuse evidence, same-candidate lineage and distinct roles.
The repaired platform must preserve any genuine missing verification capability as an
engineering wait, rather than substituting fixture results for real acceptance.

## Rollback and limits

Use the official controlled stop before any runtime backout; keep drafts and all immutable
receipts/events. Before a decision was consumed, code reference 07eae9b was the rollback point.
Now the decision has been consumed, reverting runtime does not undo it: retain compatible
readers for the new proof/draft field and history, and prefer a forward runtime fix. Do not
reset SQL counters, delete decisions or reclassify old failures to simulate a rollback.
