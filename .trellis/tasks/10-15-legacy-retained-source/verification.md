# Verification

Baseline deployed before this fix: `caa8227`.

Red/green public reproduction: `tests/manager/test_legacy_rescue_delivery.py -k False-False-True-False-True` against baseline source fails with the real production error `旧现场包含未纳入完整草稿的忽略文件`; the same test with maintenance source passes (41.53s). It retains the same Task/unknown execution, checks the prepared tree's ignored module, pauses, performs an approved source/rules rebind, resumes, and reaches native Coder/independent QA/Review on the exact candidate with the module present.

Commands below use original project `.venv/bin/python` and `PYTHONPATH=/tmp/ase-fix-legacy-ignored/src`:

- `pytest tests/manager/test_legacy_rescue_delivery.py tests/web_console/test_legacy_rescue_acceptance.py -q --tb=short`: 23 passed; 2 existing Starlette deprecation warnings.
- `pytest tests/git/test_mutation_capture.py tests/git/test_worktree.py -q --tb=short`: 67 passed (includes ignored-only cleanup preservation and explicit-cache cleanup).
- `pytest tests/manager/test_legacy_snapshot.py tests/manager/test_legacy_containment.py tests/git/test_mutation_capture.py -q --tb=short`: 91 passed before adding the two cleanup tests.
- `pytest tests/manager/test_execution_baseline.py tests/manager/test_paused_baseline_service.py tests/manager/test_baseline_wait_fact_collection.py tests/manager/test_wait_fact_collection.py tests/manager/test_rejected_coder_output.py tests/manager/test_stopped_budget_settlement.py -m 'not mysql' -q --tb=short`: 78 passed.
- Native/Responses/candidate/factory suite: 105 passed, with final constructor/type refinements retested in the 36-case focused subset.
- Native v1/v2/idle reconciliation suite: 82 passed, 4 expected v1 skips. Additional exact-base restoration/deletion matrix: 12 passed + 6 expected v1 skips; clean-base behavior: 2 passed + 1 expected skip. Final type-narrowed affected subset: 16 passed + 10 expected skips.
- Ruff check + format check and full mypy on all 20 changed Python source/test files: passed.
- `git diff --check`: passed.

Independent read-only reviewers identified and verified fixes for preview-tree omission, candidate omission, continuation omission, ignored-only cleanup loss and tracked-edit reversal. Final review reports no blocking findings. Reviewer separately exercised exact-base byte/mode/untracked/deny refusals.

No Schema or SQL migration; historical serialized record bytes/digests remain unchanged. Production existing-data recovery must use the public exact engineering plan/decision and preserve the old UNKNOWN start/outcome gap. Rollback: revert the maintenance commit, controlled pause/restart; do not rewrite published immutable recovery facts or delete retained source.

## Production acceptance and existing-data disposition (2026-10-15)

Fix `a7b8864` was fast-forward merged into `main`, pushed to `origin/main`, and loaded by
`scripts/ase-console-service.sh restart` using the self-iteration configuration. The controlled
stop reported that operations/writes were saved and execution/indexing finished before exit.
Fresh public Console reads after restart report `delivery_ready=true`, `mode=normal`, and
`operation_contract_version=8`. No scheduled task was created.

The original Requirement `delivery_multi_bb78e2316afca47d005384542f685174535b69db` and Task
`task_c833c3235d0bb73adba67937d16ea66c` remain in place. Public proposal operation
`operation_94793263c6582aa53c9f92fefc59bcab` succeeded and returned a fully validated,
nonconflicted `legacy_workspace_rescue` plan:

- Plan SHA-256: `d5a025c56ca33477e81f60ad72e52e826b265e7aaeaf713c02d2d67dfb61ab25`.
- Method: `operator_confirmed_local_stop`; task revision 5.
- Target remains `cfa43ebfe038f31637336e6849ceff43fd8f03f5` for the exact initial rescue.
- Complete before-inventory SHA-256:
  `b4e20239d770b326a1e5c98c34e4bb24f615fd843944b7281107cc408c2ade1f`, identical to
  the predeployment read-only inventory of 2771 files.
- All 15 draft paths are sealed, including `src/ai_software_engineer/artifacts/accepted.py`.
  Prepared tree SHA is `3b65e0b1c7ccdcab94877023f853e3ad8c72ab4b`.

No SQL was edited; no old outcome, stop record, checkpoint, or verdict was fabricated. The old
failed proposal and UNKNOWN invocation remain in history. The successful proposal is preparation,
not execution approval; no successor K1 Coder run was launched by this maintenance step.

At this initial acceptance snapshot, before the user's confirmation, production recovery was
waiting for the missing factual declaration required by
`.trellis/spec/core/legacy-execution-rescue.md`: the original invocation remained on this
computer/account without remote execution or migration, and it and all derived tools have ended
and cannot write the original workspace again. The user's existing delegated approval authority
does not establish that missing historical fact. Controlled service restart and a current clean
process survey also do not establish it. An exact factual question has been sent to the user.

Once that declaration is available, use only the public operations flow:

1. Refresh the parent checkpoint, execute the exact rescue plan with
   `continuation_mode=pause` and only `confirm_local_execution_stopped=true`, recording the
   declaration reference in the immutable engineering authority/HumanActionEvent.
2. Prepare and approve an exact `source_rebind` plan to the then-current target repository
   `main`, retaining all draft paths and remaining paused. Explicitly bind any native-rule
   change digest; if replay conflicts, prepare a new approved `coder_reapply` plan instead.
3. Refresh all Task/WorkItem/binding/disposition digests and submit
   `RESUME_EXECUTION_BASELINE`. Verify a distinct real claim and normal Coder, independent
   QA and Review outcomes before reporting delivery complete.

Do not repeat general product approval, recreate the Requirement, refund the unknown work,
infer a historical stop, or release the paused input through an ordinary Continue operation.

## Production recovery after the user's exact confirmation (2026-10-15)

The user answered `能确认上述全部事实` to confirmation card
`call_fa0e4709fda64a689b0b02396a71e9df`. The reference preserves the full same-computer/account,
no migration/remote execution, all-derived-tools-ended declaration and the user's existing
delegated engineering approval. Public rescue operation
`operation_4d931c49a62a5a146a9d7d0dbc880a41` succeeded:

- Rescue binding: `e2e03a656fe88bb0b25e75b2fc45904442199399426b6af52965de9c80f5d47a`.
- Exact authority: `b4d9a2c43a39cab23bdb25438d0beddbf2fa2c61fcc613c4422910806e958ec8`.
- A distinct Coder WorkItem was reserved once at attempt 4 and kept paused.

The registered repository's clean `main` was fast-forwarded to
`a837fa9c04ca89ac977ef534e519a27a31c80798`. A nonconflicted public `preserve_draft`
source-rebind plan retained all 15 draft paths. Independent read-only inspection verified all
101 old and 102 target immutable native rule bodies and the exact nine maintenance-rule changes;
frozen Task intent, permissions and denied paths are unchanged. Public operation
`operation_2b5d6e1d2ad982b80a277a10d7829a2d` successfully applied it while remaining paused:

- Rebind plan: `0364cad2107ecf48cb88a49353f1ad59b067457467568051a01f264a5487c62a`.
- Approved native-rule change: `59faa52219881c94362af0cd6dd388a2b69b61ead9d9600d14b0f056118c0062`.
- Accepted epoch: `73f08a09204f94ca9224c59b836287bf8fb39488f5190a0c4a61102b5f8c84aa`.
- Latest binding: `1382cbaa7662e0cea0dff1501286aba26fee516965f7559a3a67b6f6af388acf`.

The first explicit continuation (`operation_a01ecdd47c3c547fcc653ad3abadc236`) safely refused
`LEGACY_LOCAL_EXECUTION_ACTIVE` and retained the pause. A read-only trusted survey identified
only `CODEX_WRAPPER_ACTIVE`; after normally resetting the idle Node tool session created during
this maintenance, the same trusted survey returned no blockers. No discovered process was killed,
no scanner exemption was added and no old fact was changed. A new Operation idempotency key
reused the identical continuation intent and authority
`e6476b91834ac975a902bcefeff8985924c39b029f2e3a31e1cae121ee4f5175`.

Retry operation `operation_cfd569aa5713c1cbe745f03d515222c4` entered the ordinary runtime.
Fresh public summary confirms the original Task remains `IMPLEMENTING`, revision 5, and
`work_e2e03a656fe88bb0b25e75b2fc45904442199399426b6af52965de9c80f5d47a` is `RUNNING`,
attempt 4, assigned to `agent_team_coder`, with `LEASE_VALID` and
`execution_phase=KNOWLEDGE_PREPARATION`. No additional baseline binding or recovery reservation
was created by retrying the exact release.

The runtime also sealed
`evalevt_legacy_e2e03a656fe88bb0b25e75b2fc459044`, a `HumanActionEvent(SUPPLY_EVIDENCE)`
referencing the exact rescue authority. Independent typed inspection verified that the old Run's
invocation outcome, capture-stop and interruption receipt still do not exist: the original
UNKNOWN history is preserved. Maintenance recovery is complete; K1 business delivery still
requires its actual native Coder output and independent QA/Review. The knowledge-preparation
claim is not a claim that K1 is DONE or that the main Coder invocation has already started.

A later public summary confirmed the same attempt-4 WorkItem progressed to
`execution_phase=ROLE_EXECUTION`, `execution.reason_code=ROLE_RUNNING`, while its Lease remained
valid. This is actual Coder execution after successful recovery; candidate and independent
QA/Review outcomes still need to be observed before reporting K1 business delivery complete.
