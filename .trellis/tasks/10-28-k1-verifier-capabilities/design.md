# Proposed heterogeneous verifier contract

Status: design for independent review, not executor registration. The exact current K1 Plan
identity is recorded in `prd.md`. Existing lossless partitioning and truthful unavailable-row
diagnostics are Stage 1. This design begins where Stage 1 stops.

## 1. Authority and row selection

Keep the original `PlannedVerificationRequirement` wire and the frozen Task
`EngineeringPolicy` byte-for-byte. Add two *new* controlled capability kinds with generic
semantics, for example `isolated_browser_node_v1` and `isolated_live_ase_v1`; neither is an alias
for `PYTHON_MYSQL_SANDBOX` or macOS `NATIVE_UI_SANDBOX`. An unmarked e2e row is eligible only when
a code-owned executor descriptor plus a separate exact engineering decision match its complete
original argv, verification levels and row wire digest. Do not route on command prefix, filename,
model prose or a diagnostic hint.

Proposed typed interfaces (names are provisional until the feasibility gate is passed):

```python
class MixedVerificationAuthorization(DomainModel):
    # Immutable trusted decision; exact Plan, candidate, ordered row digests,
    # scope, actor, Console Operation reference, executor profile/image/runtime
    # digests, fixed resource limits, allowed effective roles and SHA-256.
    ...

class MixedRoleAdmission(DomainModel):
    # Exact frozen Task policy digest + supplemental decision digest, current
    # role request/Context/claim/lease/attempt/candidate, fixed deadline and SHA.
    ...

discover_mixed_verification(task, plan, scope, candidate, authorization) -> Discovery
prepare_mixed_verifier(request, claim, authorization, guard) -> MixedReceipt
validate_mixed_output_current(request, contract, guard) -> None
```

The `MixedVerificationAuthorization` is created only through a claimed public Console
Operation by a trusted `LocalOperatorPrincipal` with `ENGINEERING` duty. It records a
`HumanActionEvent` and an immutable reference to the reviewed executor profile. It authorizes
controlled execution of the *five exact rows* on one candidate. It is not Product approval,
QA PASS, Review APPROVE, a generic shell grant, or a mutation of the frozen Task policy. The
decision may permit both QA and Reviewer roles, but each role independently forms a new
`MixedRoleAdmission` under its current owner-fenced queue claim. Changed candidate, Plan row,
profile/image/runtime, resource bound, role or scope requires a new decision. Repeated exact
Operation intent is idempotent; a changed body under the same key is rejected. The public read
side shows decision ID/SHA and current eligibility, not keys or secret material.

Registration checks the complete original group before any resource, command or model start.
For the current K1 fallback, Reviewer reads the exact original QA tuple under its *own*
effective role and claim; it never rewrites row role fields or borrows QA's receipt. Duplicate
argv may share one physical command only if the authorization explicitly maps every original
row ID and criterion to that command. The four live mappings are retained separately; source
and document inspections are distinct from executable coverage.

## 2. Browser executor proof and containment

Do not register a browser executor until one fixed image/browser/Node/Playwright/profile set
has candidate- and claim-bound positive and complete negative evidence. The independently reviewed
2026-10-22 synthetic v2 profile already rendered, clicked and captured PNG with file/network/socket
denials and cleanup (result SHA-256 `7bf3688d5194526fcadf40ddbf9d6159507155e845e3e19c6780296801271d35`).
It deliberately disabled Chromium's inner sandbox and relied on a narrowed Docker outer boundary;
this is a useful feasibility baseline, not production registration. Reproduce its exact fixed
profile on an isolated candidate and extend the proof to role claim, source and lifecycle binding.
Any changed profile requires a new positive and negatives. Record exact image
manifest/config/rootfs, browser and Node binaries, profile bytes, Docker daemon/context,
runner source digest and dependencies. If no profile passes, preserve `WAIT_ENGINEERING`.

The final execution boundary must mount a byte-verified, bounded, read-only dependency closure
from the candidate: the frozen browser test, `tests/team_view/browser/fixture.cjs`,
`tests/team_view/console-capabilities-fixture.cjs`, and
`src/ai_software_engineer/team_view/{index.html,style.css,app.js}` at minimum. Any additional
candidate import or asset requires an explicit reviewed entry; do not mount the whole mutable
repository or Git metadata. Give a private writable scratch, no host home/Keychain/production
sidecar, no Docker socket, no
ambient provider key or DB DSN, fixed uid/gid, dropped capabilities, `no-new-privileges`,
read-only rootfs, finite CPU/memory/PIDs and an isolated network namespace. A loopback-only test
server may exist within that namespace; `network=none` does **not** deny loopback. Prove actual
external TCP refusal, unauthorized Unix/host socket refusal, host sentinel read refusal,
source/rootfs write refusal, renderer child confinement, and exact cleanup after timeout/abort.
The command is the original `node --test ...` argv, not an arbitrary script chosen at claim time.
Capture bounded/redacted stdout/stderr, process identity, actual start/final status and browser
interaction evidence. For `ac_011_001`, require independent review of the exact candidate test
source and an interaction trace covering operation/status feedback, Project switching, refresh,
malicious-text `textContent` rendering and the public GET path. Compare trusted API/store facts
before and after GET to prove no write side effect; a DOM assertion alone cannot do that.
Test-produced JSON, screenshots and counters are untrusted diagnostics; they do not certify
that every planned acceptance assertion ran.

## 3. Real live A-to-B executor

The trusted runner provisions a fresh isolated SQL database, Team/Project/Repository sidecar
and candidate checkout, then constructs the **production Configured delivery composition**
under exact bounded routes. It must not substitute `ScriptedAgentAdapter` or a test-only Host
factory for the target path. The candidate pytest process receives no production secret, host
workspace or direct provider network. A separate trusted broker retains the provider credential,
exposes only the fixed model transport route to the isolated candidate process, imposes request/
token/deadline limits and seals actual route/request/response facts without returning secrets.
Its private socket and SQL credentials are scoped to this one owned fixture; nothing is written
to the production DB or K1 sidecar.

The trusted observer, rather than candidate assertions or pytest counters, validates the
scenario's durable chain: A has a real allocation/claim/Run and accepted artifact; collection
automatically creates the actual pending proposal without a manual collect call, including a
bounded crash/backlog reconciliation path; a trusted exact human decision is recorded through
the normal publication/selection service; B is a distinct Requirement and allocation/claim/Run,
with current selected knowledge, actual search/read/citation evidence and independent result.
The exact human decision is a test-scope `HumanActionEvent` bound to a prior human-approved
scenario, not a fabricated production approval. The runner executes the frozen pytest node once,
but keeps all four original row identities distinct. Its trusted pre-model criterion evidence
matrix is:

| Original criterion | Independent observations available to the role before its model call |
| --- | --- |
| `ac_004_001` | Accepted A triggers automatic registration/proposal, and bounded owned-worker crash compensation clears a healthy backlog without a manual collect or browser GET. |
| `ac_012_001` | Exact publication/selection decision plus separate B claim, real provider transport and same-Run search/read/citation linked to document/chunk SHA. |
| `ac_012_002` | A snapshot, Context and report bytes/SHA remain frozen; actual pre-publication/unselected, cross-Project, wrong-role, wrong-Run and wrong-citation queries refuse, while authorized B succeeds. |
| `ac_013_001` | Complete original row matrix, real browser and live children, current role identity/claim, unchanged candidate/source linkage and inspectable independent-verification policy; the live command alone cannot establish this aggregate criterion. The actual QA/Reviewer verdict chain is a later completion check. |

Each row references its own trusted evidence URI/SHA. QA and Reviewer perform their own source
reviews under separate claims; one role's later verdict cannot be evidence in an earlier role's
pre-model receipt.
The observer records actual model transport and store hashes separately from candidate output,
then the independent QA/Reviewer evaluates adequacy. A fake citation, changed selection, same
claim, missing provider call or only a scripted/composition path cannot yield a successful receipt.

Candidate code is untrusted even when it passes `pytest`. Direct SQL access within its sandbox
may be needed for the isolated Host, but no candidate-produced SQL row alone proves the chain;
the broker's actual transport and trusted external observer must match it. The design review
must prove the broker does not become an arbitrary network or credential oracle before release.

## 4. One mixed receipt and independent role output

Create a new versioned mixed journal root, leaving `NativeRoleVerificationStore` v1 and all
historical hashes readable. Before each resource/process start, seal a per-child INTENT/STARTED
record under the current `MixedRoleAdmission`; after real process stop and cleanup, seal a
FINISHED or explicit blocked/unknown final. Child records bind candidate, original Plan row
digests, role/Run/claim, exact argv, executor profile/runtime, resource owner and actual return
code. The 55 Python rows retain their current v1 isolation and validation, but execute as a
child of the mixed Run. The browser child owns one row; the live child owns four mappings to one
actual command. The document row is presented for source inspection and has no machine result.

A `MixedRoleReceipt` is published only after every required executable child has a validated
final record and all owned resources have a verified terminal state. It names the ordered 61
original row identities, exact child SHA/URI, per-row command mapping and criterion evidence
matrix. For `ac_013_001` it binds the browser and live children, current role/Run/claim and
candidate/source lineage, not a future QA or Reviewer verdict. The aggregate SHA is
computed from already sealed child digests; children do not contain the aggregate SHA, avoiding
a cycle. Missing child, stale claim, foreign candidate, changed profile, STARTED without final,
partial cleanup or unrecognized row keeps the role in a typed wait; no subset READY or model
start. Read-side history, service shutdown, requirement close/delete/purge and crash
reconciliation must understand every new root/resource before publication.

`TrustedVerificationOutputContract` remains an internal trusted seam. Extend its mixed form
with the aggregate receipt URI/SHA, current authority/claim SHA and a criterion-to-child-command
result map. The provider prompt includes bounded evidence but does not carry the internal
validator. At output admission, reread current Task/Plan/candidate/claim and every child/final
receipt without executing commands again. QA may honestly report FAIL with mixed command
results; QA PASS and Review APPROVE require every required command successful and role-authored
criterion assessment with the current receipt. A criterion PASS cannot cite an unrelated child.
Return code zero and a candidate-produced pass count alone never create a verdict.

`qa-report.criteria_results` still covers every frozen criterion with `PASS`, `FAIL` or
`NOT_TESTED`. For `ac_013_001`, QA may report `PASS` only for the evidence and contract observable
at its stage: the complete real child group, candidate/source binding, its own independent claim,
and a source inspection showing that later Reviewer admission and verdict remain separate. The
QA notes/evidence must state that no Reviewer verdict existed or was asserted by QA. If this
stage evidence is incomplete, QA reports `FAIL` or `NOT_TESTED` with its reason; overall QA PASS
still requires every required criterion to be PASS. Reviewer then evaluates the accepted QA
report and its own fresh receipt/claim and may independently APPROVE or REJECT; Reviewer cannot
pre-certify acceptance of its own future artifact. Only after both reports are independently
accepted does the final Task/DONE and handoff gate verify the actual distinct Coder/QA/Reviewer
identities, QA PASS, Review APPROVE, direct artifact parentage, complete original row mapping and
same candidate/source SHA. A missing or mismatched final chain blocks DONE/handoff without
rewriting either role's receipt or verdict. This staged interpretation keeps the frozen
`ac_013_001` ID and Plan unchanged while avoiding a future-verdict dependency at model admission.

## 5. Executable deadline and resource ownership

Start one absolute monotonic work deadline before the first child setup, bounded by the original
role request. Pass its actual remaining float timeout through Python/MySQL setup, SQL principal
verification, broker, browser, command supervisor and between-child cleanup. A separate single
frozen finalization budget covers all child teardown; it cannot renew per child or on restart.
Every blocking operation must be cancellable under that deadline. If the work deadline expires,
no further child or model starts. If a stop/cleanup remains unproved, retain owned intent and
UNKNOWN evidence; lease expiry is not a stop proof. The concrete code changes for Python resource
and principal timeouts described in the earlier Stage 2/3 design are mandatory before claiming
this aggregate deadline, not optional performance cleanup.

## 6. Validation matrix

| Input or observation | Required result |
| --- | --- |
| Exact approved candidate, five exact rows, current QA claim, all executors ready | Run each child under one bounded window; seal aggregate; then permit QA model |
| Same candidate and later independent Reviewer claim | Fresh child executions and distinct aggregate; no QA receipt reuse |
| QA prepares `ac_013_001` before Reviewer exists | Receipt binds current QA claim and real children only; QA may assess the observable stage without claiming a Reviewer verdict |
| Accepted QA PASS plus Reviewer APPROVE, same candidate and independent identities | Final DONE/handoff gate verifies the complete verdict/artifact chain before delivery |
| QA or Reviewer output claims its own future acceptance, or final chain is missing/mismatched | Reject unsupported claim or block DONE/handoff; do not backfill a receipt or verdict |
| Candidate lacks either planned test file | Existing exact static QA missing-entry route; no fake e2e PASS |
| Missing/changed decision, row, argv, level, criterion, image or profile | `WAIT_ENGINEERING`; no child resource or model start |
| Browser launches Node but Chromium aborts before page/click | Browser blocked receipt; no aggregate READY or QA model |
| Live pytest rc0 but no actual A/B claim, transport or citation | Live verification blocked; candidate summary cannot authenticate it |
| Python child passes while browser/live is absent | No partial readiness, no aggregate, no model start |
| Child STARTED without verified final or cleanup | `EXECUTION_UNCERTAIN`, retain owner/resource and require investigation |
| Role claim expires or candidate changes during execution | Stop/fence; preserve exact actual records, no stale output acceptance |
| Any required command nonzero with complete final | Honest QA FAIL may be emitted; QA PASS/Review APPROVE rejected |
| Aggregate/child/claim digest tampered or foreign | Fail closed before output or replay; preserve files for audit |

Good: real isolated browser interaction and A→B chain, complete per-role receipts, independent
QA PASS and Reviewer APPROVE on the same candidate, then a final complete-chain gate. Base: no proven browser profile leaves
exact unavailable rows and the original WorkItem waiting. Bad: treat `node` or `pytest` prefix,
an image pull, a scripted fixture, a Python subset, or a model-written evidence URI as the
missing capability.

## 7. Existing data, release and rollback

No SQL migration or historical record rewrite is necessary for the proposed new append-only
sidecar facts. Before deployment, add read/close/delete/purge and service-stop support for the
new journals and owned resources, plus static Schema/generated-contract tests. Release at a
controlled idle boundary only after independent code/security review and real negative probes.
After the original K1 candidate exists, seal one exact supplemental decision through the public
operation, then let separate QA and Reviewer claims execute normally. If the candidate changes,
the decision expires for admission and a new exact authorization is required. Rollback before
consumption can disable admission; after consumption retain compatible readers and fix forward.
Do not mark old unsupported receipts READY, refund work budget or replace the original K1.
