# Preserve complete inputs across chained Coder recovery

## Goal
An interrupted recovery must retain both the current draft and every still-required complete
historical coder_reapply patch. Restore the existing K1 Requirement through ordinary exact
scope/Plan approval without rewriting its failed Tasks, accepted progress or owned-stop facts.

## Observed defect
K1 Task3d26 completed two accepted progress checkpoints, then its third invocation reached
the local limit and failed the full-draft policy gate on work_queue/mysql.py. Its 15-file
draft does not contain all content from the original 31-file, 225678-byte required patch.
Current recovery captures only the latest worktree and rebuilds the approved Product/Design/
Plan context; it does not inherit that older required reapply input. Do not execute a new
Plan until the complete input chain can be authenticated and delivered.

## Scope and ownership
- Implementation worker: necessary recovery models/services/context/admission, synchronized
  generated Schemas, architecture contract and focused unit tests.
- Independent test worker: public recovery integration regression and fixture validation.
- Root: this task's contracts/spec, integration, deployment and real K1 recovery.
- Independent reviewer: read-only code/spec review and focused verification.
All work is in /tmp/ase-fix-legacy-ignored; maintainers share this checkout. Real K1 worktrees
are read-only. No production SQL edits, counter resets, verdict changes or fabricated facts.

## Acceptance
- New Plans explicitly freeze inherited patch identities and full content in their digest.
- Trusted immutable approved Plan/Task/dispatch/seed/invocation/Context facts authenticate
  ancestry; Context text or model claims alone never establish authority.
- Two and three generation recovery retains all complete required Coder-only inputs,
  independently of the new capture. No loss, truncation, silent replacement or duplicate input
  from the same origin. Different approved origins retain separate identities even if their
  patch bodies happen to match.
- Missing/tampered/cyclic/cross-scope/over-budget ancestry refuses before provider execution.
- Initial entry, seed-before-invocation reentry and ordinary later Coder Context construction
  enforce the same input contract. QA/Reviewer receive no historical source patch.
- Historical Plans without inherited inputs preserve exact wire/digest and read compatibility;
  legacy source ancestry is freshly detected for new proposals.
- Public fixture covers propose, separate exact approval and new claimed Coder Context;
  candidate acceptance still requires independent QA and Review.

## Validation, stored data and rollback
Run focused source/model/Schema tests and one necessary public Git/MySQL regression serially
against the explicitly identified isolated test database. Run Ruff/format, strict Mypy and
independent review. Record failures honestly; fake fixture DONE is not real K1 acceptance.
Deploy only at an idle controlled boundary. Preserve old records/worktrees unchanged, propose
a fresh exact scope supplement and Plan, then separately approve execution under the user's
existing engineering delegation. Rollback while idle reverts source but must retain compatible
readers once a Plan containing inherited inputs has been published.
