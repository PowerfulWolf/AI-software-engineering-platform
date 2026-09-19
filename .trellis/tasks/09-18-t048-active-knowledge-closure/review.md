# T048 independent review — 2026-09-19

Reviewer: `/root/review_knowledge`. Review is read-only except this report. No production
code, QA files, runtime artifacts or verdicts were edited. This report is not merge approval.
Scope: uncommitted T048 changes in `/private/tmp/ase-t047-t049-20260918`, with T049 fix re-review.

## Current findings

**No unresolved findings in the reviewed T048/T049 scope.** All findings below were repaired
and independently re-reviewed. This is a bounded development review, not a production verdict,
live-provider quality claim, deployment verification or merge authorization.

The final review exercised the original three negative probes: later candidate B now references
the first exact candidate-A recovery; wrong-revision/run/context proof reuse is rejected; and a
legacy implementation checkpoint resumes through new QA/Reviewer runs without changing old
artifacts or Contexts. NEW admission stays empty and later artifacts cannot expand it.

Stage receipts now execute at intake, architecture, complexity classification, completed planning,
Gap recovery and failure recovery boundaries. Native repeated child failures trigger break-loop
without changing role verdicts. Historical rejected-plan feedback no longer masks a later
integration/native failure. Knowledge recovery checks the exact committed Gap/Resolution in its
owning store. Stage proofs recompute checkpoint identities, bindings and acceptance coverage;
missing receipts stop stage advancement.

## Historical findings — all closed by final re-review

- Severity: high
- File: `src/ai_software_engineer/knowledge/agents.py` (`consult`, resolved-gap loop)
- Issue: Every subsequent role run tries to resume every historical resolved gap. The matching
  filter omits source revision, while `KnowledgeGapService.resume` requires the original revision.
  Reproduction: QA gap on candidate A; exact approval; same-candidate recovery succeeds; QA on
  candidate B after Coder rework raises `RESUME_REQUIRES_NEW_RUN_CONTEXT`. Thus a resolved gap
  prevents ordinary later candidate retries.
- Recommendation: Distinguish the exact first recovery transition from later Requirement-scoped
  reuse of the approved resolution. Preserve the original resume chain and explicitly bind reuse
  to the later candidate/context. Add the resolved-gap → QA failure → new candidate regression.

- Severity: high
- File: `src/ai_software_engineer/knowledge/delivery.py:before_transition`
- Issue: Unconditionally requiring consultation sections breaks immutable artifacts produced
  before this feature. Reproduction: legacy Context builder; persist plan and implementation;
  interrupt immediately before transition to QA; restart with the new gate. Task remains
  IMPLEMENTING and throws `WORKFLOW_CONSULTATION_MISSING` with zero new Agent calls. The retry
  engine reuses the already durable implementation and cannot produce the missing receipt.
- Recommendation: Pin gate applicability to a new Requirement/runtime contract version, or
  provide an explicit safe recovery mechanism that retains the old chain. Cover the existing-data
  recovery procedure; do not rewrite old Contexts or backfill fictitious consultation evidence.

- Severity: medium
- File: `src/ai_software_engineer/knowledge/delivery.py:DeliveryWorkflowProof` and
  `src/ai_software_engineer/knowledge/workflow.py:invoke`
- Issue: A valid proof is bound to Task and target status but lacks candidate revision and
  consultation run/context/snapshot coordinates. Reproduction: obtain a real DONE proof, create
  another valid manifest for the same Task with different revision/run/context, and invoke
  `code-review` with the old proof: PASSED. The ordinary production caller generates a fresh proof;
  this probe demonstrates a reusable gate contract hole, not an observed production state skip.
- Recommendation: Bind proof and gate facts to exact candidate/consultation/final Context lineage;
  validate that the consultation input Context underlies the delivered artifact Context.

- Severity: medium
- File: `src/ai_software_engineer/knowledge/workflow.py` and upstream/Manager stage boundaries
- Issue: `architecture-check`, `plan`, `start`, `planning-gate`, `recovery` and `break-loop` are
  registered but have no actual stage-bound callers. Pre-consultation invokes `before-dev` or
  `knowledge-facts`; delivery invokes implementation/QA/review/finish gates. Designer→Planner,
  Planner→dispatch and recovery therefore do not require the requested Workflow Skill receipts.
  Existing stage/schema validators still apply; this is explicit T048 acceptance incompleteness.
- Recommendation: Generate bounded receipts from existing verified design, plan, checkpoint,
  gap/resolution and repeated-failure facts and require them at their corresponding transitions.

## Re-review evidence

T049's four earlier findings are resolved in the reviewed paths: bounded metadata claim plus one
source read; old/new verified generation publication before replacement selection; shared scope
mutation locking; independent per-scope ticks. Independent index/administration run: **42 passed**.

T048 Context-before-request, native-rule retrieval, typed gap propagation, independent delivery
gates, actual consultation evaluation fixtures and the new HumanAction ADR bridge were inspected.
Targeted independent run: **28 passed** across `test_delivery_context.py`,
`test_runtime_recovery_qa.py`, `test_effectiveness_qa.py`, and `test_audit_qa.py`. No additional
blocking issue was found in the ADR bridge: exact approved resolutions create idempotent ordinary
HumanActionEvents after case start and before the next Agent, preserving non-autonomous attribution.

All executable probes used temporary directories and no deployed data.

## Final executed verification

```text
PYTHONPATH=src /Users/zhangjunshuai/workspace/code/AI-software-engineering-platform/.venv/bin/python -m pytest -q tests/knowledge/test_stages.py tests/knowledge/test_revision_upgrade_qa.py tests/knowledge/test_audit_qa.py tests/knowledge/test_delivery_context.py tests/knowledge/test_runtime_recovery_qa.py tests/knowledge/test_effectiveness_qa.py tests/e2e/test_joint_delivery.py tests/manager/test_joint_planner_feedback.py
64 passed, 4 skipped in 11.20s

git diff --check
passed
```

The four skips require `ASE_TEST_MYSQL_DSN`, which was not configured for this independent run.
This report therefore does not claim independent MySQL-backed joint delivery execution. Earlier
independent T049 index/administration verification remains **42 passed**. Parent and QA verification
are separate records and are not substituted for this review's executed checks.

### Final recovery composition follow-up

The final `production_backend.py` factory-selection correction was independently inspected.
Default production delivery and an explicitly supplied `ConfiguredDeliveryRouteAdapterFactory`
both enable `KnowledgeRunContextBuilder` and `KnowledgeDeliveryGate`. In particular, the real
recovery entry's `ConfiguredDeliveryRouteAdapterFactory(initial_workspace_admission=seed)` is
no longer mistaken for the custom offline fixture seam. The effective-factory precedence matches
the adapter composition. The same factory instance and Coder-only seed admission still reach
`CodexCliAgentAdapter`; no seed authorization or workspace permissions changed. No new finding.

Independent follow-up command:

```text
PYTHONPATH=src /Users/zhangjunshuai/workspace/code/AI-software-engineering-platform/.venv/bin/python -m pytest -q tests/manager/test_production_backend.py tests/recovery/test_remediation_context.py
6 passed, 2 skipped in 0.71s
```

The two composition test skips also require `ASE_TEST_MYSQL_DSN`. Parent's isolated MySQL run
is separate evidence. `git diff --check` passed again after this composition correction.

## Final reviewed production digests (SHA-256)

| File | SHA-256 |
| --- | --- |
| `knowledge/gaps.py` | `b0ae0259642466337a6e5d1d6ebaa9b87fdb7bc7745c706f88627c145bb7310b` |
| `knowledge/delivery.py` | `cb013e33125403ecfd7eb80bade191956eecfd82299d01a1f5ede8b30189776f` |
| `knowledge/workflow.py` | `093669a2885d17d8becccbdbb248f5dc3efa4616a20526cf207bc078d41e62c0` |
| `knowledge/stages.py` | `0bed15c2836dd6912a9bfe6eef62e55c1a6ac3c8016717dc74fda7dc477a91f6` |
| `knowledge/audit.py` | `ad4c1eabf11c5bc0dbbb5522e3f8edfcf13b1088f37b0b82ae6a9ed4ffa614df` |
| `multi_directory/service.py` | `95a3ea02366af7c019cc460814319f5efd8ce769dcd62f29d730389aafa8a859` |
| `knowledge/index.py` | `b6a73e6680e6adf2b856eb290bb44488b3c002cd260127739f0ef39905ec4acf` |
| `knowledge/index_store.py` | `daa64480745ed1a96754c9a6e04e6e207f88046a6342942f0c0d37bef2d58679` |
| `manager/production_backend.py` | `f54748a1889fb18de23140aaecc15e1aeaaf2c098a5053e00f1dacf60cd72543` |
| `manager/production_delivery.py` | `9add6a59f33db4983f55bdc7cad1ce92e0d9d6ea34865604af252f2fad6b3dfa` |

Paths in the digest table are relative to `src/ai_software_engineer/`.
