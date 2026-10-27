# Native QA/Review receipt binding

## Scope
Controlled verification already produces candidate-bound immutable execution receipts before
the independent model evaluates them. Model-authored evidence arrays cannot authenticate their
own URI/SHA references. Native output admission must bind required verification claims to the
specific trusted receipt delivered in the exact prepared request.

## Contract and seam
The implementation adds an internal typed output contract between trusted verification
providers, `VerificationEvidencePromptBuilder`, `PromptPayload` and `_PreparedNativeInput`.
Exact helper signatures are recorded in the implementation task before source changes.
This metadata is excluded from provider serialization and durable artifact/public Schema wire.
It binds complete request identity, exact task/run/role/attempt/context/candidate, receipt URI/
SHA and required criterion coverage. Native registered execution additionally binds its real
admitted claim identity. Providers derive these values from typed validated Plan/receipt facts.

```python
verification_output_contract(
    request: AgentRequest, *, receipt_uri: str, receipt_sha256: Sha256,
    authority_sha256: Sha256, receipt_covered_required_criterion_ids: tuple[str, ...],
    command_returncodes: tuple[int, ...], claim_sha256: Sha256 | None = None,
) -> TrustedVerificationOutputContract
validate_verification_output(
    request: AgentRequest, artifact: Artifact,
    contract: TrustedVerificationOutputContract,
) -> None  # VerificationOutputRejected with a fixed safe rule

class VerificationOutputCurrentValidator(Protocol):
    def validate_output_current(
        self, request: AgentRequest, workspace_root: Path,
        execution_guard: ExecutionGuard | None,
        contract: TrustedVerificationOutputContract,
    ) -> None: ...
```

`VerificationEvidence.output_contract` and `PromptPayload.verification_output_contract` are
optional internal excluded fields; `_PreparedNativeInput` keeps the exact bound contract.
`TrustedVerificationOutputContract` binds request_sha256, task_id, run_id, role, attempt,
source_revision, context_manifest_id, receipt_uri, receipt_sha256, authority_sha256,
claim_sha256, receipt_covered_required_criterion_ids and actual command_returncodes.
The required criterion set is the receipt's actual approved execution coverage intersected
with required Task criteria. Source-only inspection criteria must not be falsely attributed
to a machine test receipt. Derive coverage from typed selections/requirements/UI steps and
trusted Task facts, never from prompt text or an all-Task fallback.

After ordinary Artifact validation and before successful native result acceptance, compare the
report's required top-level receipt references to this trusted contract. QA current tests and
required PASS criterion coverage must cite the actual receipt; Review's evidence list must cite
its current controlled receipt. A forged matching evidence ID within the model's own array is
insufficient. Background evidence may refer to genuine upstream artifacts. Machine command
success does not imply a criterion PASS or Review APPROVE; roles still judge independently.
An actual failed required command cannot support an overall QA PASS or Review APPROVE. Current
controlled runners execute exact pytest nodes or build/test checks and have no expected-nonzero
command contract; negative tests assert a refusal and then exit zero. A receipt containing both
successful and failed commands can support an honest mixed QA FAIL report; do not reject every
individual PASS solely because a different command failed. Per-command comparisons require an
actual exact machine-command mapping; model prose or a shared receipt alone cannot create it.

The contract carries immutable provenance, never cached authorization/READY. Existing fresh
claim/permission/workspace and execution guards remain in force. Output checking cannot call a
test executor again or reinterpret lease release as process-stop proof. Wrong/missing references
fail safely before publication; do not rewrite the model's report or substitute its verdict.
The prompt-builder seam delegates `validate_output_current` to the real provider. That provider
freshly checks existing Plan/facts/invocation/claim and rereads the original completed receipt;
it never calls `evidence_for` or executes tests again. A nonempty contract without a supported
current-facts validator fails closed. Preserve ordinary typed waits if facts changed. Protocol
implementations remain trusted composition; no arbitrary closure is serialized into a model.

## Matrix and executable checks
| Input | Required result |
| --- | --- |
| Exact current trusted receipt and independent report | Preserve existing verdict and lineage gates |
| Missing URI, wrong digest, forged current claim/request/candidate | Reject without successful output |
| Receipt listed but missing from required QA/Review output claims | Reject without adding references |
| Mixed real command results, honestly reported QA FAIL | Permit normal failure/remediation routing |
| Failed required command but overall QA PASS or Review APPROVE | Reject contradictory execution claim |
| Genuine ancestor background evidence | Permit; do not claim it is this Run's test execution |
| No controlled test, ordinary source inspection, legacy fixture | Existing behavior; no invented receipt |
| Real Python/MySQL, Swift or UI controlled provider | Derive contract from typed actual receipt |
| Prepared contract or request mismatch | Reject, no executor replay or authority reuse |
| Claim/receipt changes during model invocation | Fresh output check rejects with executor call count still one |
| Mixed test and source-inspection coverage | Receipt applies only to actually executed covered criteria |

Good: QA evaluates a newly executed exact candidate test and cites its actual receipt. Base:
ordinary read-only inspection still reads source. Bad: a model declares PASS and supplies its own
command URI/hash, then the platform treats array membership as independent machine evidence.

Tests must exercise real native adapter decoding/acceptance with temporary Git and offline model
responses, not just a helper that mirrors its implementation. Red regression must demonstrate
wrong/missing receipt accepted before the guard, then rejected. Include correct, negative verdict,
legacy/background and each controlled provider composition. Run Ruff/format and strict Mypy.

## Stored data and rollback
No SQL/Schema/artifact migration or old report rewriting. K1's previously accepted progress is
valid draft/continuation data; its four unverified native Coder test references remain historical
claims. They cannot be relabeled as machine facts. New final-candidate verification uses new real
receipts and exact approved independent Runs. Deploy only at a controlled idle boundary; preserve
all old failures, permissions, budgets, claims, worktrees and proofs. Rollback reverts this guard
without erasing any existing evidence or granting replay permission.

The native Coder's general tool path currently lacks a trusted per-command durable capture
channel. Its sealed test declarations alone are not machine Evidence; missing historical output
cannot be recovered from a claimed digest. This admission fix binds existing independent
controlled-verification receipts. It does not claim complete native Coder command capture or
retroactively satisfy that broader evidence requirement.


## Invocation scope and untrusted test summaries (2026-10-22)

`receipt_covered_required_criterion_ids` pins approved invocation scope for exact receipt citation;
it does not authenticate execution of every candidate test body. Candidate plugins/conftest run
in the same process as pytest observers and can spoof collected/passed counters or remove tests.
`test_native_verification_summary_trust.py` preserves an actual offline counterexample: no tests
ran and the test-body marker is absent, yet rc0 and a unique complete summary claim passed1.
Schema, index, nonce or candidate-writable result-file checks cannot establish independent test
coverage. Such summaries remain bounded diagnostics. Independent QA/Reviewer evaluate actual
coverage and can honestly return FAIL/REJECT despite rc0. Existing nonzero contradiction and
current candidate/claim/receipt gates remain intact; no verdict or artifact is rewritten.


## Complete mixed prerequisites and ordinary Responses compatibility (2026-10-24)

`RegisteredNativePythonVerifier.discover_partitioned` retains every original row and its
identity digest under each independent effective role. Original-Plan preflight projects each
original row once; QA fallback is not duplicated into the public receipt. A mixed Python subset
above the unchanged64-selector limit becomes per-original-row `UNSUPPORTED_ENTRYPOINT` facts
while browser/live missing-capability details and inspections remain present. No partial group
is prepared; homogeneous v1 global-limit behavior and hashes stay unchanged.

`is_ordinary_verification_requirement(requirement)` selects existing precise ordinary Responses
semantics before applying registered-host prerequisites. It allows only source/document
inspection or already-supported incremental test commands without an explicit capability or
unmarked e2e/acceptance obligation. This selector grants no permissions or result: whole-group
role/criterion coverage, current command/read/deny policy, exact candidate and actual executable
checks still apply. A native host-discovery failure cannot block unrelated ordinary Go/npm/
Maven/unittest/legacy focused pytest. Unknown entries, explicit unsupported capability, e2e or
any mixed unsupported row cannot fall back to ordinary tools; Codex/fallback retains independent
registered preparation. Cache reads recheck the same complete mode and current facts.

Executable checks include ordinary non-Python production preflight and pre-model preparation,
failed unrelated host discovery, unknown/e2e/explicit capability and foreign-scope refusals,
Codex mode separation, mixed65-selector discovery and public wait/handle preserving all exact
browser/live remedies without starting resources/models or consuming recovery authority.
No existing Task/Plan/receipt/approval is rewritten. Existing waits require a fresh public
investigation after reviewed deployment; original browser/live acceptance remains required.
# Static QA missing-entry output

`TrustedStaticQaMissingEntryOutputContract` is distinct from a command receipt.
It binds the fresh current QA `AgentRequest`, current claim and consumed
`STATIC_QA_MISSING_ENTRY` decision to the sealed candidate-tree observation.
The prompt may describe the missing frozen test paths, but the output gate must
independently re-read the current decision, claim, accepted Plan/implementation
receipts and candidate Git tree before accepting the report. Only one QA-authored
`qa-report` with overall `FAIL`, no `tests_run`, proof file evidence, FAIL for
affected criteria and one `MISSING_PLANNED_TEST_ENTRY` finding per missing path
is valid. PASS, command claims, changed proof/claim/candidate, or unrelated
criterion PASS fail closed. Responses routes cannot consume this authority
until they implement the same current-output validation as Codex CLI.
The QA request carries both frozen Plan and accepted implementation as inputs,
but the QA report's direct `parent_artifact_ids` is exactly the implementation
artifact, as required by `RetryingOrchestrator`; the Plan remains authenticated
through the Task's durable `plan_validated`/`plan_recovered` StateEvent and
the request/observation lineage. Requiring both input IDs as direct report
parents rejects a valid QA output and must not be used as the static gate.
`tests_run=()` and the original controlled verifier's `NOT_STARTED` observation
do not prove that the QA model made zero read-only source-inspection tool calls;
the role's existing read-only tool policy continues to govern those calls.
