# Verification

- `uv run --no-sync pytest -q tests/recovery/test_workspace_snapshot.py --tb=short` — 54 passed in 41.41s.
- `uv run --no-sync ruff check src/ai_software_engineer/recovery/workspace_records.py src/ai_software_engineer/recovery/workspace_snapshot.py tests/recovery/test_workspace_snapshot.py` — passed.
- `uv run --no-sync mypy --follow-imports=silent src/ai_software_engineer/recovery/workspace_records.py src/ai_software_engineer/recovery/workspace_snapshot.py tests/recovery/test_workspace_snapshot.py` — passed.

The suite covers legal inherited dirty files, ignored `.venv` files/symlinks, terminal fact drift,
missing locks/stops/outcomes, stable repeated audits, scope supplement identity, strict snapshot
wire tampering, no-follow inventory, timeout-vs-admission-failure separation, and a SQL read-only
seam that rejects active claims without authority initialization.

Independent review found and implementation fixed two compatibility boundaries:
exact accepted SUCCEEDED progress uses the existing verified recovery contract rather than
requiring a failure capture-stop; raw SQL Task/claim/event/item indexes must agree with typed
payloads, and complete claim-row/event digests detect owner/status drift. Negative tests cover
12 raw-index inconsistencies. A separate baseline case proves the actual failed Run source and
approved capture base may differ without changing the original Task approval.

## Production read-only confirmation

Root confirmed the formal current K1 source and terminal audit pass using the actual stores;
the retained business capture contains 27 files, the complete no-follow inventory has 2,283
entries, and 18 ignored environment entries remain as metadata in the original workspace.
This probe performed no ASE operation, approval, Task/database mutation, restart, copying,
cleanup or model invocation. The source epoch and full capture were checked together;
the old terminal Task and failed history remain unchanged. A new precise plan approval is
still required through the public recovery path; this audit is evidence, not authority.

## Independent integration review

The independent baseline reviewer confirmed the accepted-progress compatibility branch,
FAILED-with-prior-progress audit, raw SQL/payload consistency, complete claim digest, and
the `entry/current/models` exact snapshot revalidation. No new blocking finding remains.
Its affected workspace snapshot, plan and baseline wire selection passed 77 tests; an
additional real `PRESERVE_DRAFT` case with differing execution source and capture base
passed separately. Ruff, strict Mypy and diff-check passed. The review performed no
production ASE operation or model invocation. This task is ready for root integration.

Final source/current-audit probe after raw claim hardening: terminal revision 18, effective base
4bf596d5ed487b96c1fbfbee892bdfba58457e1d; 27 captured business files; 2,283 complete inventory
entries; 18 source-only environment entries. Capture SHA remained
4c56b9587a3027a6841d9e3e179e60f2438a9ebb44de30cb03970afaf72cf75d; fresh snapshot SHA is
e5184952c21a1d2745ee50fc33a5a8d73ef7c0b319676c9ea574500a21cdf298. This is a read-only
observation, not an approval; a deployed public plan must revalidate all facts.
