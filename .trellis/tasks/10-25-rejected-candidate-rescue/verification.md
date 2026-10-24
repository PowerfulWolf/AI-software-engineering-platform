# Verification

## Scope

This change repairs the platform path for a Coder invocation that produced a real
clean candidate and a real successful native outcome, but whose implementation
report was rejected because its artifact schema version was unsupported. It keeps
the original Requirement, Product approval, Task/base revision, branch, candidate,
outcome, stop evidence, claims and budget history intact. It does not publish or
merge the retained candidate.

## Verification evidence

- Final focused delta: `26 passed in 71.61s`; log:
  `/private/tmp/ase-candidate-target-final-delta-20261025.log`.
- Isolated MySQL recovery suite: `9 passed in 72.50s`; log:
  `/private/tmp/ase-candidate-target-mysql-20261025.log`.
- Target Ruff and strict mypy on affected Python files: passed; log:
  `/private/tmp/ase-candidate-target-static-20261025.log`.
- Target Node suite: `155 passed`; log:
  `/private/tmp/ase-candidate-target-node-20261025.log`.
- Public Requirement recovery through the real TeamHost path, real Git, real
  owned subprocess and isolated MySQL: `1 passed in 40.36s`; log:
  `/private/tmp/ase-public-rejected-candidate-recovery-20261025.log`.
- The broader target regression was `251 passed, 1 failed`; the one failure was
  reproduced on clean main and was an existing read-instrumentation mismatch.
  The test now observes the shared `_read_payload` path without changing its
  assertions. The independent review recorded 7/7 Git fixtures passed and no
  assertion weakening in:
  `/private/tmp/ase-baseline-read-reuse-independent-review-20261025.json`
  (SHA-256 `4fc1704026b4e3719a96e54a5f270eefcdebcff9d6a41126064448c267be7e79`).
- Independent rescue review:
  `/private/tmp/ase-rejected-candidate-baseline-independent-review-20261025.json`
  (SHA-256 `95ee1110247cadecaeb6e64c991b2d0299caec58598c6073640682abaafa6855`).
  It reports no correctness finding in the reviewed rescue scope. Its MySQL
  result is explicitly root-owned evidence, not an impersonated independent run.

## Stored-state handling

The affected K1 Requirement remains the original
`delivery_multi_bb78e2316afca47d005384542f685174535b69db`; its Task remains
`task_recovery_3a4325237347c8caf434d94379cce745`, with base
`5547815464a04991f50a2e0532d6f2f13d8daa69` and retained candidate
`308bf36b7e225e875e5e84c1eb893fdd6e52f360`. No historical JSON, verdict,
Product approval, Task revision, budget or branch is rewritten. Recovery uses the
typed public proposal, exact ENGINEERING PAUSE, and a separate exact RESUME. No
SQL backdoor, refund, reset, rebase, artificial commit or automatic merge is used.

## Risks and rollback

Before the new recovery binding is consumed, the maintenance commit can be
reverted at a service idle boundary. After append-only recovery records exist,
retain compatible readers and forward-fix; do not delete audit records or revive
the retired owner. Remote push is intentionally not part of this operation.

## Remaining delivery gate

The retained candidate still has the original K1 acceptance work to complete. The
public recovery test proves the platform path and the three-role handoff, not that
the K1 candidate satisfies every frozen acceptance node. After recovery, the new
Coder must perform the missing acceptance work, then independent QA and Review
must validate the resulting candidate before any handoff or merge decision.

## Final reentry verification (2026-10-25)

- Final target public compatibility run: 3 passed, 1 failed in 119.24s; log
  `/private/tmp/ase-candidate-final-public-compatibility-20261025.log`. The two
  public rejected-candidate child paths and the stopped `blocked-raw-owned` path
  passed. The remaining failure is the pre-existing post-feedback recovery
  expectation (`WAITING_HUMAN` vs `VERIFICATION_APPROVAL_REQUIRED`); the same test
  fails on clean `main` in a serialized isolated-database control run
  (`/private/tmp/ase-post-feedback-main-serial-control-20261025.log`, 1 failed in
  11.25s), so it is not attributed to this rescue change and is not hidden.
- Final focused reentry tests: 14 passed; final no-MySQL reentry/mutation/owned-stop
  set: 43 passed in 64.27s (`/private/tmp/ase-reentry-focused-mirror-green-20261025.log`).
- Independent review of the final source scope found no findings. Report:
  `/private/tmp/ase-rejected-candidate-independent-review-20261025.json`, SHA-256
  `aa6b2e582133c5c4ff0cb8b675c3ded38da3674131e4070efa51226766c912e2`.
  The review records the wider compatibility limitations and does not claim a
  green full-suite result.
- The final target branch contains no mixed verification implementation; mixed
  production/catalog work remains outside this maintenance commit.
