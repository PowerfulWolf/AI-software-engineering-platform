# Coder reapply patch input deduplication

## Scope

A `coder_reapply` recovery may already provide the complete immutable historical
patch as `source:recovery.patch`. The typed `execution.baseline` section must
not copy that body a second time. It now uses schema `v3` as a reference to the
unique recovery section, while preserving the complete binding, retained patch
SHA-256/byte count, and native-rule epoch.

## Validation

- `execution_baseline_from_context` requires the independent baseline verifier,
a unique non-truncated `source:recovery.patch`, exact URI, byte count and SHA-256.
- Missing, changed or mismatched recovery patch is rejected before candidate
source admission.
- If no recovery patch section exists, coder reapply retains the historical full
baseline body behavior. Preserve-draft and historical v1/v2 contexts are byte
compatible.

Focused checks:

```text
PYTHONPATH=src python -m pytest -q tests/context/test_baseline_projection.py
PYTHONPATH=src python -m pytest -q tests/manager/test_execution_baseline_context.py
```

No production database or existing context was migrated. Existing v1/v2 records
remain readable; new v3 contexts are additive and can be disabled while retaining
v3 read support for rollback.
