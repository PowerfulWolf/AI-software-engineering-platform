# Implementation and verification

## Change

Five synchronous entry points use the existing `source_inspection_scope` context decorator.
The cache keeps only immutable detection tuples keyed by scanner mode, source path and complete
text. It keeps no domain models, observations, permissions, plans or approvals. No read or gate
was removed; standalone leaf scopes can now share one outer proposal or approval scope.

## Focused RED evidence

For a complete 120-function Python body with ordinary `settings.token` field references:

| Synchronous boundary | Repeated AST parses before the envelope |
| --- | ---: |
| Direct proposal | 25 |
| Proposal with source discovery | 26 |
| Current facts double inspection | 2 |
| Terminal workspace audit | 13 |
| Approval and explicit offline fresh-facts sealing seam | 24 |

The terminal expected snapshot is calculated outside the measured call. The approval test uses
real authorization, capture and immutable receipt stores, while Task derivation/sealing is an
explicit offline seam. These are scanner contracts, not production SQL or model performance
claims. Each measured outer call must now parse that exact body once.

## Verification commands

```sh
.venv/bin/python -m pytest -q tests/recovery/test_terminal_source_inspection_scope.py --tb=short
.venv/bin/python -m pytest -q tests/context/test_source_inspection_scope.py tests/recovery/test_workspace_snapshot.py -k 'source_inspection or modern_composition_missing_facts_or_live_workspace or outer_recovery_fence' --tb=short
.venv/bin/python -m ruff check tests/recovery/test_terminal_source_inspection_scope.py src/ai_software_engineer/recovery/entry.py src/ai_software_engineer/recovery/current.py src/ai_software_engineer/recovery/workspace_snapshot.py
MYPYPATH=src .venv/bin/python -m mypy --strict tests/recovery/test_terminal_source_inspection_scope.py src/ai_software_engineer/recovery/entry.py src/ai_software_engineer/recovery/current.py src/ai_software_engineer/recovery/workspace_snapshot.py
```

Final results:

- New scanner contract file: **7 passed in 23.65s**.
- Existing bounded cache and modern missing/live-workspace/outer-fence checks:
  **14 passed, 48 deselected in 4.34s**.
- Ruff format/check, strict Mypy on the four changed Python/test files and `git diff --check`
  passed.
- Independent sibling reviewer checked all five exact envelopes, preservation of double reads,
  synchronous-only lifetime and the declared offline test seams; no blocking findings.

No full tests or model calls were run by this task.

## Existing data disposition

No durable bytes or schemas changed. Preserve the successful existing recovery proposal and its
history. Loading the optimization requires an idle code restart; existing plans and approvals
still require unchanged exact confirmation and fresh facts. A new public proposal can measure
latency after deployment, but a changed target baseline prevents a same-input acceleration claim.
