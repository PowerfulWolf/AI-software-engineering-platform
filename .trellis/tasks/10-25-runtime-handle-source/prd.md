# Preserve stopped Coder source handles without changing secret boundaries

## Goal and observed failure

The original K1 Coder run8 stopped at its local execution limit. Public HANDLE
could verify the owned stop but could not seal all retained work because the
source-body guard classified two runtime handles as literal credentials:
`job, source, token = claimed` and a proven standard-library `ContextVar.set`
return token. Complete original Git BEFORE bodies also receive the same check.

Maintain source revision `5547815464a04991f50a2e0532d6f2f13d8daa69`, original Task,
all drafts, complete patch, stop, UNKNOWN history and frozen execution budget.
Maintenance baseline is `6bb73537c5bb7414564cc1b161bbabd32123118a`.

## Allowed changes

- `src/ai_software_engineer/redaction.py`: pure bounded AST source classification.
- Focused source/context and real Git mutation-capture regression tests.
- `.trellis/spec/core/dynamic-credential-source.md` and this task contract.

No K1 source edit, schema/policy permission expansion, outcome fabrication, direct
production SQL update or mixed-verification capability registration.

## Acceptance and verification

1. Both immutable original and current source bodies pass exact full capture and
   verify without changing bytes, hashes, index, HEAD, permissions or patch.
2. Only complete parseable Python bodies can use the new source-handle rule;
   partial patch hunks, strings/comments, generic logs/configs remain conservative.
3. Literal/fake/rebound/aliased/reflective provenance, strong keys and unrelated
   credentials remain rejected. No path/name special case exempts an entire file.
4. Focused new tests go red before the fix, green afterward; existing source,
   dynamic credential, patch, mutation-capture and continuation rejection tests
   pass. Ruff, format and strict Mypy pass on the changed Python files.
5. An independent reviewer checks the exact maintenance diff. A read-only replay
   of the original stopped run verifies full inventory, permissions, retained
   paths, before/after bodies, patch and capture coverage before publication.

## Existing data and rollout

No stored records are rewritten. Controlled stop releases the idle serving main,
then reviewed maintenance code is fast-forwarded, pushed and started through the
official service lifecycle. Public HANDLE recollects the complete actual draft;
only its fresh exact evidence can authorize ordinary same-Task continuation. The
previous collection rejection and failed/UNKNOWN history remain intact.

## Rollback

Before publishing a new complete receipt, an idle rollback may return to the
previous release. After receipts use the new source classification, retain reader
compatibility or pause safely; never delete/rewrite receipts or alter their hashes
to satisfy an older guard. K1 has no automatic merge or production deployment.
