# Implementation handoff

## Internal signatures

```python
class TrustedVerificationOutputContract(DomainModel):
    request_sha256: Sha256
    task_id: NonEmptyStr
    run_id: NonEmptyStr
    role: Literal[AgentRole.QA, AgentRole.REVIEWER]
    attempt: PositiveInt
    source_revision: NonEmptyStr
    context_manifest_id: NonEmptyStr
    receipt_uri: NonEmptyStr
    receipt_sha256: Sha256
    authority_sha256: Sha256
    claim_sha256: Sha256 | None = None
    receipt_covered_required_criterion_ids: tuple[AcceptanceCriterionId, ...]
    command_returncodes: tuple[int, ...]

def verification_output_contract(
    request: AgentRequest, *, receipt_uri: str, receipt_sha256: Sha256,
    authority_sha256: Sha256, receipt_covered_required_criterion_ids: tuple[str, ...],
    command_returncodes: tuple[int, ...], claim_sha256: Sha256 | None = None,
) -> TrustedVerificationOutputContract: ...

def validate_verification_output(
    request: AgentRequest, artifact: Artifact,
    contract: TrustedVerificationOutputContract,
) -> None: ...  # raises VerificationOutputRejected with a fixed safe rule

class VerificationOutputCurrentValidator(Protocol):
    def validate_output_current(
        self, request: AgentRequest, workspace_root: Path,
        execution_guard: ExecutionGuard | None,
        contract: TrustedVerificationOutputContract,
    ) -> None: ...

class VerificationOutputInputs(DomainModel):
    task: Task
    plan_artifact: PlanArtifact
    def validate_plan(self, plan: CandidateVerificationPlan) -> None: ...

def receipt_output_contract(
    plan: CandidateVerificationPlan, request: AgentRequest,
    receipt: VerificationExecutionRecord, inputs: VerificationOutputInputs | None,
) -> TrustedVerificationOutputContract: ...
```

`VerificationEvidence.output_contract` and `PromptPayload.verification_output_contract` are
optional internal fields with `exclude=True`; `_PreparedNativeInput` retains the contract for
exact output admission. Trusted providers construct it from already validated typed receipt and
Plan/invocation facts. Native registered execution includes the full immutable claim digest.
No output check calls `evidence_for` again, replays controlled commands, or caches current authority;
the adapter's original execution guard remains active at output admission.
The narrow read-only current validator retains existing current facts and Git candidate checks,
then rereads the original completed receipt. It never calls discovery, resource reconciliation,
cleanup, Docker, test or UI execution during output admission.

The new gate requires the exact current receipt in the top-level array, current `tests_run`
references and receipt-covered required PASS criterion coverage (or Review evidence list).
Coverage is the actual approved receipt execution mapping intersected with Task.required;
source-only criteria retain source evidence. Other background evidence is unchanged.
A nonzero required command result cannot support overall QA PASS or Review APPROVE. A mixed
receipt can support an honest QA FAIL with individual PASS results or Review REJECT;
individual command comparisons need an exact
trusted command mapping and cannot be inferred from a shared receipt or model prose.
Ordinary source-only verification and old fake/legacy providers without controlled receipts
retain their behavior. All real controlled Python/MySQL, Swift and UI providers derive contracts;
registered controlled preparation rejects a missing contract rather than silently using None.

Standalone provider constructors accept optional `output_inputs` for historical offline fixtures.
The production `CandidateVerificationEntry.execute` always supplies actual typed Task/Plan inputs
when a controlled capability is selected and validates their exact original digests before
reserving verifier capacity. Python coverage comes from approved capability selections; Swift
coverage comes only from exact executed structured Swift commands or the exact executed native UI
scenario. Old standalone Swift/UI Plans without structured mappings keep an empty covered set;
their receipt references, current facts and overall QA PASS/command outcome checks still apply.

Read prd.md/design.md and `.trellis/spec/core/native-verification-output.md` before source edits.
Worker records exact signatures, red command/result, green focused checks and limitations here.
No production deployment, SQL mutation, existing K1 draft edit or historical evidence repair.

## Red regression

`PYTHONPATH=src .../.venv/bin/python -m pytest -q tests/agents/test_verification_output_binding.py`
ran with approved sandbox escalation on 2026-10-19. Result: 1 failed in 2.11s at the intended
native acceptance assertion (`SUCCEEDED` instead of `FAILED`); controlled executor count was
exactly one. The report's model-only `command://pytest/...` reference had no trusted receipt.
The earlier sandboxed run failed before this seam at owned-process OS admission and was not
used as the red signal.

## Green verification

Using the repository venv with `PYTHONPATH=src`, the final focused command was:

```sh
python -m pytest -q \
  tests/agents/test_verification_output_binding.py \
  tests/agents/test_codex_cli.py \
  tests/agents/test_openai_compatible.py \
  tests/manager/test_native_verification.py \
  tests/recovery/test_verification_environment.py \
  tests/recovery/test_python_mysql_execution.py
```

Result: **163 passed, 2 skipped in 46.21s**. The skips are the existing explicit local
sandbox/toolchain opt-ins. Offline controlled-execution tests run with fake Docker/command/UI
ports, real receipt stores and temporary native Git worktrees. New native regressions cover
exact and wrong URI/SHA, missing required references, preserved ancestor evidence, QA FAIL and
Review REJECT, mixed source/test coverage, and claim/context/request/candidate/guard/receipt
changes during the model call. Their executor count remains exactly one. Standalone Python,
Swift and UI receipt tests explicitly check that output-current validation adds no execution.

`ruff check` passes for all 8 affected source files and 3 affected test files; `ruff format` was
applied. `MYPYPATH=src python -m mypy --strict` passes for all 8 affected source files.
Independent reviewer reports no blocking correctness findings, 8 new production-composition
tests passing, and 10 existing Reviewer-only proposal/resume tests passing. That reviewer owns
`tests/recovery/test_verification_output_composition.py` and its separate verification report.

No production K1 process was restarted or modified, no database was migrated, and no old
Artifact/verdict/evidence was rewritten. Deployment remains with the parent at an idle boundary.

## Review positive-verdict symmetry

Pre-commit independent review identified the missing symmetric Review gate. The existing exact
pytest/Swift executors have no expected-nonzero mechanism: negative test behavior must be asserted
inside a successful test process. Added real native adapter regression
`test_native_review_approve_cannot_override_failed_required_command`; before the new guard it
failed at the intended assertion (`SUCCEEDED` instead of `FAILED`, **1 failed in 1.21s**), with
the controlled executor invoked exactly once and an actual returncode of 1.
The guard now rejects Review APPROVE plus any actual required command nonzero with the same
safe `VERIFICATION_COMMAND_FAILED` rule used for overall QA PASS. A truthful Review REJECT is
tested for both actual returncode 0 and 1 and retains its original verdict.

Delta verification: `PYTHONPATH=src python -m pytest -q
tests/agents/test_verification_output_binding.py
tests/recovery/test_verification_output_composition.py` → **31 passed in 22.07s**.
Ruff check/format for the changed source/test files, strict Mypy for the changed guard source,
and `git diff --check` all pass. The previously green 163-case suite was not unnecessarily
rerun for this narrow positive-verdict symmetry change.
