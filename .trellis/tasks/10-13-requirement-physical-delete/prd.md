# Requirement physical deletion and refresh regression

## Goal
User explicitly requires deletion to physically remove Requirement-owned data and release resources; close remains a stopped, retained Requirement. K1 delivery and automation remain paused.

## Requirements
- DELETE checks exact Project/Requirement/checkpoint, complete historical ownership, inactive execution and independent verification, then removes Requirement, native child, Task/queue, execution metadata, Operation histories and release archives.
- Retain only a bounded body-free identity revocation marker to prevent stale commands and same-name identity revival; no deleted Requirement body/verdict/diff/log retained as a product archive.
- Existing deleted Requirements use the same typed service after controlled idle deployment; no bulk SQL bypass or revival.
- Scope-exact cleanup is resumable after interrupted SQL or file deletion. Check every selected path/row SHA before mutation; reject symlinks, foreign owners, active work and drift. Preserve unrelated Requirements, shared Team/Project knowledge, repository catalog and main code.
- Original refresh harness must be rerun against production; inspect team-summary, operation-summary including conditional 304 and page actions.

## Acceptance
- Draft, stopped execution and completed Requirement disappear physically; related Operation GET returns 404 after transient deletion completion acknowledgement expires.
- Same-name creation has a new ID; old native recovery rejected; mutation and detail cannot reuse removed lineage.
- Stop/lease/drift/symlink rejection and interruption replay tested at actual store/service seams.
- Existing-data counts/bytes and real HTTP before/after captured without secrets or production payloads.

## Allowed paths / validation / rollback
src/ai_software_engineer/{multi_directory,web_console,team_view}/**, src/ai_software_engineer/manager/{delivery_wait,native_verification_store}.py, scripts/sync-requirement-purge-schemas.py, schemas/{requirement-purge*,console-deletion-cleanup}.json, related tests (including typed narrowing of the imported tests/recovery/test_context_capacity_input.py fixture), docs and .trellis/spec/core.
Run targeted pytest (including isolated MySQL), Ruff, strict Mypy, schema contracts and browser deletion/refresh cases; independent review before merge.
Rollback code only at idle; physical deletion is irreversible. Keep body-free revocation compatibility; never reconstitute deleted data to roll back.

## Diagnosis baseline
Sequential team-summary 4.374–5.093s, operation-summary 3.068–4.670s. Direct visibility alone 3.133s CPU 3.113s; warm operation without visibility 0.222s. Selected Project retired histories 271 JSON / 328,576,222 bytes. Browser polling team 6–7s and 304 operation reads 5–6s. Whole histories are decoded, validated and copied on each request; concurrent CPU reads amplify delay. Earlier tests measured operation projection but omitted the new retirement dependency.

User explicitly approved permanently removing the 9 audited unmerged old Task branches on 2026-10-13. Exact refs and current SHA must still pass the sealed CAS plan and idle/worktree validation.
