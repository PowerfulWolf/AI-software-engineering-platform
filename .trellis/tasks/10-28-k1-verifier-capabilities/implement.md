# Implementation sequence and review gates

This is a proposed follow-up implementation plan. This planning change writes only this task
directory. The paths below are an impact inventory, **not** permission to edit them before the
browser/live boundary and exact supplemental authorization design are independently accepted.

## Milestone 0: prove feasibility without production registration

1. Reproduce the independently reviewed 2026-10-22 synthetic Docker browser v2 profile
   (result SHA-256 `7bf3688d5194526fcadf40ddbf9d6159507155e845e3e19c6780296801271d35`)
   with real render→click→state and host-file, source-write, network, unauthorized socket,
   renderer and cleanup denials. Then prove the same profile against a byte-verified isolated
   candidate and exact role claim, including the frozen browser test's byte-verified fixture/UI
   asset dependency closure and criterion-specific interaction trace. Retain image/config,
   rootfs/profile and stop evidence; the earlier failed v1 result remains historical, not the
   final feasibility verdict.
2. Prove a credential-isolated transport broker with real configured model requests and a
   disposable A/B Host/SQL. Observe distinct real claims, automatic A proposal/backlog recovery,
   public exact publication/selection, B search/read/citation and the frozen A/negative scope
   checks for `ac_012_002`. Bind separate trusted evidence to all four live criteria, including
   the cross-child QA/Review requirement for `ac_013_001`. Validate key/DSN invisibility to
   candidate code. Do not run against production K1/SQL during this proof.
3. Obtain independent security and contract review. If either proof fails, retain the precise
   `WAIT_ENGINEERING` facts and do not publish a mixed executor or aggregate schema.

## Milestone 1: exact contracts and authorization

Define typed supplemental authorization, two capability descriptors, mixed admission and
child/aggregate records. Record the trusted Console Operation and `HumanActionEvent`; require
candidate and original Plan row identity. Add schema/generator byte-sync, stale decision, role,
scope, runtime, duplicate row and idempotent replay tests before executor integration. Preserve
v1 readers and the frozen Task policy.

## Milestone 2: real executors and whole-role preparation

Implement browser and live runners with owned resource ledgers, shared executable work deadline,
single finalization budget, bounded outputs and actual stop proof. Execute existing Python/MySQL
as a child without changing its standalone v1 receipt. Compose the complete ordered group in
`PreflightInvocationControl` before model start, seal aggregate only after every child final,
and add fresh current-facts validation for the mixed output contract. Wire read-side history,
controlled service stop and physical Requirement deletion/purge before enabling registration.

## Milestone 3: guarded public verification and K1 continuation

- Run pure model/schema/authorization tests, fake child ordering and crash tests, real Docker
  browser positive/negative, real isolated SQL/provider A/B, and a public Console/queue fixture
  through candidate→QA→Reviewer. The fixture must assert different Agent IDs and claims,
  unchanged original Plan/Task/source, same candidate and no verdict bypass.
- Run Ruff, format, strict Mypy, unit/contract suites and resource-leak probes. Have a reviewer
  who did not implement the executors inspect the exact diff and execution receipts.
- Confirm a current K1 candidate includes both planned test files. Seal the candidate-bound
  supplemental engineering decision via the public operation. Let ASE claim QA then Reviewer;
  inspect each real receipt and role verdict. If QA FAIL/Review REJECT, route findings to Coder
  under original remaining budget. Only after DONE/handoff consider a separately reviewed
  integration into the latest `main`; the platform must not auto-merge.

## Proposed code/spec/test path inventory for exact review

- Authority and wire: `src/ai_software_engineer/domain/{engineering_authority,native_verification}.py`,
  new typed mixed models, `schemas/{engineering-authority,native-role-verification-plan,native-role-verification-admission,delivery-preflight}.schema.json`, new exact mixed authorization/child/aggregate Schemas, and their reviewed generation scripts.
- Discovery and role composition: `src/ai_software_engineer/manager/{native_verification_partition,native_verification,native_verification_store,delivery_preflight,production_backend,production_delivery,preflight_gate,verifier_preparation}.py` plus new mixed/browser/live runner modules. Reuse current `VerificationOutputCurrentValidator` seam in `src/ai_software_engineer/agents/verification_output.py` and its Codex/Responses adapters.
- Final-chain admission: `src/ai_software_engineer/orchestration/retry.py` must verify the
  accepted same-candidate QA PASS, independent Reviewer APPROVE, complete 61-row mixed
  receipts and direct artifact parentage before its Review→DONE transition. Add focused
  tests in `tests/orchestration/test_retry.py` and
  `tests/orchestration/test_verification_lineage.py`; handoff construction in
  `src/ai_software_engineer/evaluation/handoff.py` and
  `tests/evaluation/test_handoff.py` must reject an incomplete final chain too.
- Existing Python resource/deadline support: `src/ai_software_engineer/manager/{python_mysql_execution,python_mysql_resources,python_mysql_proxy,verification_process}.py` and a new trusted principal helper/broker with exact environment and transport policy.
- Public/audit/lifecycle: `src/ai_software_engineer/web_console/{models,manager,transport}.py`,
  `src/ai_software_engineer/team_view/engineering_history.py`,
  `src/ai_software_engineer/multi_directory/{purge,purge_resources,purge_state}.py`,
  and controlled service-stop composition where the new resource owner is tracked.
- Contracts: `.trellis/spec/core/{verification-environment,delivery-preflight,native-verification-output,engineering-authority,requirement-deletion,controlled-service-restart}.md`, the core index, and matching `docs/architecture/contracts.md` / operations guide.
- Tests: `tests/manager/{test_native_verification_partition,test_native_verification,test_delivery_preflight,test_verifier_preparation,test_python_mysql_boundary,test_python_mysql_resources,test_purge_record_closure}.py`, `tests/agents/test_verification_output_binding.py`, new exact authorization/browser/live/mixed fixture tests, and one guarded public same-Requirement QA→Reviewer fixture.

Before code starts, replace this forecast with an exact per-file allowlist tied to the then-current
platform Git revision and candidate SHA. Any generated or transitive protected path outside it
requires renewed review. No test may simply mirror a fake executor or accept rc0/pytest counts
as proof of real browser interaction or A/B lineage.

## Stop and rollback conditions

Stop registration if the browser profile still cannot create/interact with a page, the live
broker exposes secrets or a generic network path, the mixed reader cannot validate old v1
records, a child remains STARTED without a trustworthy stop, or cleanup ownership is unknown.
Preserve all historical K1 facts. Before a new decision is consumed, roll back at an idle
service boundary. Once decisions or mixed receipts exist, retain compatible readers and fix
forward; do not delete evidence or reclassify a failure as PASS.
