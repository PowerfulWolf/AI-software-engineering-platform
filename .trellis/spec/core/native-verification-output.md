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
