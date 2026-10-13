# Implementation and validation

Implement typed purge plan/completion and Operation cleanup with JSON Schema parity. Use the existing cancellation and native resource reconciler, real current time, exact CLEANED receipts and expected-SHA Git deletion. Validate every remaining byte on replay; refuse drift and additional files.

Run public Console and service regressions with isolated MySQL and real Git: draft, closed/cancelled, partial deletion/restart, foreign scope, writer closure, branch collision and removal provenance. Run Ruff and strict Mypy, independent Standards/Spec review, then idle main deployment and existing-data cleanup through public typed services. Rerun original HTTP/browser refresh measurements. K1 and automation remain paused.


Validation (2026-10-13): 286 related pytest cases passed against the dedicated isolated MySQL fixture; 77 frontend Node tests passed. Ruff format/check and strict Mypy passed for all 32 changed Python files; git diff --check passed. Independent Standards review reported no outstanding findings (14 local cases passed); independent Spec review reported no outstanding findings (22 local cases passed). Original main had 18 transitive JSON-narrowing errors in the imported context-capacity test fixture; explicit dictionary assertions corrected these without changing its negative schema cases.

## Deployment and existing-data disposition (2026-10-13)

The generic fixes were fast-forwarded into main and pushed to origin: `1be5327`,
`766d09f`, `26e3afd`, and `5384d52`. The production Console was stopped and restarted
through the controlled service script; PID 7387 is serving the deployed code. The
business checkout remains clean on its existing branch. K1 delivery stays paused;
no new Requirement, approval, or delivery execution was started.

All eight previously deleted Requirements (seven in the AI Project and one legacy
initial PREPARING draft in the Codex Project) were physically purged through
`TeamHost.requirement_entry(project_id)` and the public typed
`delete_requirement(DeleteRequirement(exact ID/digest))` service. Five stopped
independent-verification reservations were released through
`MySqlDispatchAuthority.abandon_verification`; no Task/verdict was fabricated.
The nine unmerged old branches explicitly authorized by the user were removed with
expected-SHA CAS, and their exact empty removal markers were reconciled before
replaying the sealed purge. Same-scope historical continuation aliases are accepted;
foreign holders still reject. PREPARING compatibility is limited to an exactly
revoked sequence-one checkpoint without a predecessor or approved downstream facts.

Postchecks confirmed:

- 6,788 Requirement-owned files / 949,330,693 bytes removed; 1,188 SQL rows removed.
- 42 audited old Task identities absent; every audited old Git ref absent, including
  the nine explicitly authorized unmerged branches. The 24 planned refs include
  references already absent before replay and are not an actual-deletion count.
- 85 exact legacy operator/archive files / 131,932,210 bytes removed, including the
  old K1 compressed archive; no Requirement-body backup is retained there.
- 206 current-user-owned K1 temporary diagnostic files / 111,542,118 bytes removed
  after exact path, type, SHA/size, full directory inventory and stopped-monitor
  checks. Their body-free cleanup plan and receipt are retained. One clean detached
  K1 seed-precheck worktree was removed through Git, including its registration.
- Total measured removed file content is 1,192,805,021 bytes (about 1.19 GB), excluding
  the precheck checkout and test database storage.
- All 692 independently hashed files of the surviving Requirement were unchanged;
  its complete detail, 83 Operation records, candidate and QA/Review entry remain
  readable. Shared Team/Project knowledge and merged main code were preserved.

The dedicated fixture container `ase-physical-delete-test-20261013` was removed
only after checking its exact ID and `ase.operator-test=requirement-physical-delete`
label. The production `ase-mysql` container remains healthy.

Body-free verification and measurement files are `/tmp/ase-cleanup-verification.json`,
`/tmp/ase-refresh-latency-after.json`, `/tmp/ase-conditional-latency-after.json`,
`/tmp/ase-concurrent-latency-after.json`, and
`/tmp/ase-k1-temporary-cleanup-result.json`. The final read-only production postcheck
repeated successfully after service restart and temporary-resource cleanup.

## Performance and browser validation

Root cause: retirement visibility decoded and validated 271 historical JSON files /
328,576,222 bytes on every read, adding 3–5 seconds CPU before the existing summary
cache. Conditional 304 avoided response transfer but still executed this dependency.
Physical purge replaces deleted bodies with small verified revocation/completion
facts. Tests must measure the whole endpoint dependency chain and realistic concurrent
reads, rather than the operation projection alone.

| Read | Before | After cold / warm | Concurrent after |
| --- | --- | --- | --- |
| Team summary | 4.374–5.093 s | 0.989 / 0.621 s | 0.309 s |
| Operation summary | 3.068–4.670 s | 0.285 / 0.072 s | 0.196 s |
| Settings | — | 0.005 / 0.002 s | 0.036 s |

Conditional Operation summary returned 304 in 0.119 s. The original less-than-two-
seconds endpoint budget passed. Team summary does not advertise ETag, so no fabricated
conditional request is used for that endpoint.

Actual browser checks completed: reload and automatic refresh, Team members/empty
pending queues, Requirement list and complete existing detail, refresh during navigation
to Knowledge, Settings and Status. Status shows MySQL and the runtime ready. The
initial fast navigation showed one transient Operation-read notice and recovered;
subsequent navigation/refresh checks did not reproduce it, and browser error/warning
logs were empty. Read-only browser performance globals are unavailable in the current
browser bridge; timing evidence comes from the actual HTTP harness, while UI checks
verify completion and rendering.

## Final checks and reproduction commands

Supplemental real Git/MySQL branch-scope tests passed (12); PREPARING, retirement and
public Console tests passed (30); final initial/revoked versus sequence-two/fresh
PREPARING matrix passed independently (4). These supplement the 286-case suite and
77 frontend cases above. Ruff, strict Mypy and diff whitespace checks also passed for
the final compatibility patch. No broad test rerun is needed for this documentation-
only completion record.

Reproduce the affected contracts with a newly isolated test database (the former
fixture has been removed):

```sh
ASE_TEST_MYSQL_DSN='<isolated-test-dsn>' .venv/bin/python -m pytest tests/manager/test_requirement_physical_delete.py tests/manager/test_requirement_resource_release.py tests/manager/test_requirement_retirement.py tests/manager/test_requirement_deletion.py tests/manager/test_requirement_cancellation.py tests/manager/test_waiting_requirement_close.py tests/manager/test_purge_record_closure.py tests/web_console/test_deletion_cleanup.py tests/web_console/test_requirement_deletion_entry.py
node --test tests/team_view/ui.test.cjs
.venv/bin/ruff check src/ai_software_engineer/multi_directory/purge*.py src/ai_software_engineer/web_console/deletion_cleanup.py
.venv/bin/mypy --strict src/ai_software_engineer/multi_directory/purge*.py src/ai_software_engineer/web_console/deletion_cleanup.py
git diff --check
```

The old production purge scripts must not be rerun: their exact source inventories
have been removed. Fresh deletion uses the public service and current checkpoint.

## Known limits and rollback

Physical deletion is irreversible. An idle code rollback can revert the four commits
above in reverse order after verifying revocation compatibility; it cannot restore
removed Requirement bodies, rows or unmerged refs. Do not reset terminal Tasks or
revive a deleted identity. Git objects already reachable from main remain; unreferenced
objects are reclaimed by normal Git maintenance, not aggressive GC or manual object
removal. This is a generic platform contract, not a K1-specific exception.

## Follow-up: unapproved Product close/delete (2026-10-13)

The user recalled that K1 had a Product document awaiting review, but not the old error
text/time. Current frontend and service both permit CLOSE and DELETE in
WAITING_PRODUCT_APPROVAL; existing active-execution/ownership/current-checkpoint guards
remain. The old Requirement and its Operation bodies have intentionally been physically
purged, so the historical error cause is unknown.

Extended the public HTTP fixture to four actual paths: idle draft and Product awaiting
approval, each deleted directly or closed first. All four passed (2.27 s). CLOSE keeps
the exact ProductSpec and no approval, then DELETE binds the new CLOSED digest. DELETE
GET returns SUCCEEDED through the bounded transient acknowledgement, the earlier CLOSE
Operation returns 404 after purge, and no Requirement/journal survives. The existing
fake backend rejects model execution, so these paths cannot quietly start delivery.

Commands/results:

- `python -m pytest -q tests/web_console/test_requirement_deletion_entry.py tests/manager/test_waiting_requirement_close.py -m 'not mysql'`: 25 passed, 3 MySQL cases deliberately deselected; no production DSN.
- Extended `python -m pytest -q tests/web_console/test_requirement_deletion_entry.py`: 4 passed.
- `node --test tests/team_view/waiting-requirement-close.test.cjs`: 13 passed.
- `node --test --test-name-pattern='team, multi-directory requests, detail, refresh preservation and stale errors' tests/team_view/ui.test.cjs`: 1 complete UI-flow case passed.
- Changed-file `ruff format --check`, `ruff check --no-cache`, `MYPYPATH=src mypy --strict --follow-imports=silent`, and `git diff --check`: passed. Explicit MYPYPATH binds local source contracts instead of the installed editable package.

Existing-data disposition: no additional production facts changed. K1 remains deleted;
no approval, Requirement recreation or automation resume. This follow-up adds regression
coverage and explicit knowledge only; production close/delete logic is unchanged. Code
rollback for the follow-up is a normal test/documentation commit revert; deleted bodies
are not recreated.
