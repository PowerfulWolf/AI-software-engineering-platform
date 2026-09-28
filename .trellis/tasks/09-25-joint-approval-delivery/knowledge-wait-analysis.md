# Bug Analysis: prerequisite repair loses the QA knowledge wait

## 1. Root Cause Category

B/C/D: cross-layer contract, propagation failure and missing integration coverage. Fresh repair
used the generic backend without joint.approved_context; Host let KnowledgeGapRaised escape;
native/joint handoff did not carry the successor child checkpoint when delivery paused mid-call.

## 2. Why Fixes Failed

Fixing only the Host catch left the historical gap invisible (GAP_NOT_FOUND). Recognizing its exact
native ownership then exposed stale parent child facts (STAGE_RESOLUTION_BINDING). Real Git/MySQL
tests reproduced both and required full repair → QA wait → answer → restart coverage. Catching the
exception or a unit-level green result alone did not verify recovery.

## 3. Prevention Mechanisms

- DONE: shared approved-parent context composition for fresh recovery and repair.
- DONE: typed native checkpoint-plus-gap handoff; only the existing coordinator owns parent wait.
- DONE: fail-closed historical lineage/snapshot proof, without data migration or approval replay.
- DONE: two real Git/MySQL normal/legacy wait fixtures; candidate/Task/repository/Project negatives;
  isolated scope drift tests; no repeated Coder assertion through parent DONE.
- PENDING: deploy after remaining regression gates; recover real requirement via normal APIs.

## Live upgrade correction

First deployment (PID 39751) exposed a missed historical formatter boundary. Operation
6a66895e failed before models: native context reconstruction rejected the original repair
description digest. It appended INVARIANT_VIOLATION while the real Task remained QA, after which
candidate inspection correctly refused to treat a nonterminal Task as a terminal verification
source. The earlier legacy fixture omitted parent context but still used the new formatter, so
it did not reproduce production bytes. Added the original description to the integration fixture;
it failed with BLOCKED instead of DONE before the exact-digest compatibility fix. Added an injected
backend context failure plus nonterminal resume; unit QA/REVIEW cases failed before correction.

Repair: support only both known formatter variants under the complete original context digest;
resume a retained nonterminal verifier after a platform invariant interruption without resetting
Task/attempts or altering verdicts. Terminated Tasks and verification-inconclusive outcomes remain
ineligible. This is an ASE upgrade compatibility defect, not an environment or business defect.

## 4. Systematic Expansion

Mid-role waits must preserve both delivery checkpoint and knowledge scope across every alternate
entry path. Environment/authority questions go to Manager, while exact execution approval and
independent verdict remain separate. The platform must expose a wait even if the native call has
not returned a final ChildDelivery. Do not turn missing future UI observations into claimed results.

## 5. Knowledge Capture

Executable seven-part contract: .trellis/spec/core/continuation-knowledge-wait.md. Operations guide,
design and implementation state updated. This repository has no src/templates/markdown/spec tree
to synchronize. Existing unrelated work is preserved; no automatic bulk commit of the dirty tree.
