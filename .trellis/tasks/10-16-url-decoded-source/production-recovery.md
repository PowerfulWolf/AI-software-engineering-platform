# Original K1 public recovery — 2026-10-16

## Platform deployment

Reviewed fixes `ab38311` (same-base accepted-progress continuity), `0338a96` (conditional
Python source-binding reporting) and `1c0af07` (proven decoder source references) were
fast-forwarded and pushed to main at `1c0af07e39229b400a0f659cadf9f45edb171d63`.
No K1 source rebase, Product/Design scope change, SQL repair or verdict edit occurred.

The public service script performed controlled restart. Exact request
`console_shutdown_5afd343b2578878899f76a798ec77da4` bound old PID14732 / instance
`console_instance_86c05e41f5a59145612c19d67d8364ac`, with READY at 05:37:56.246781Z.
Old PID actually exited. New PID5104 / instance
`console_instance_0f1479cfa069f79298eb44e0ef669529` entered RUNNING at 05:38:03.551341Z;
public Console returns normal, delivery_ready=true. All original 195 immutable files
remain unchanged in independent before/after audits. No old READY was reused.

## 存量数据处置

Fresh typed TeamSummary bound public HANDLE operation
`operation_dc5fff6ddd10ee1decce589f5d92de48` to the same original Requirement, Task revision8,
disposition25b2a22a… and frozen source774e0a6. Platform fact collection sealed Run5 receipt
`c91c406531e953a88b9e5e5b7179da422d4a96929deab66eca3ad5be399d8482`
at 05:39:46.003861Z under the real Task lock and idle fence. It retains the original
local_execution_limit, real owned stop, all 24 source/test files and 183,618 patch bytes:
capture `a6c0a5696f93f8f8078974124c9238c7666c7af35800346709fc28b35d49f760`,
inventory `2986dd5b6064221dc46367a277225de71dbbe69a85c32d44122749eecbb377d0`.
No maintenance probe published this receipt; only the public collector did so.

Handling is RESOLVED with collection_failed=false and missing=[], using
RETRY_FROM_CHECKPOINT. Old work_304ecb05… closed; a new work item
`work_ca3cd632d8d2b1f74a0204a77724229a75704b8dc3f3b0114dc3c9cefc97fc5b`
received a genuinely new claim `lease_df833d81c8ef27886117029e`. Original lease remains
released and Run5 has no invented final outcome. Accepted progress
`art_coder_05714ae8093596356e007b54dc42490b` and its original SHA640daf6e… remain immutable.

## Actual successor execution and limits

Run `run_d244856b1962415b8e386adac7bfbe73` attempt6 has invocation start
`e76f3cbe8f6c0009f16f9bf0e21a8dbad736d384875cca01e572da9221f6d481` at
05:43:45.283082Z, followed by native capture-start at 05:44:31Z. Context is
`ctx_e4043f0f5710fca2b5e62374a1db9ff24a56f6bda1d2c2d686893d2e4c2fcf11`.
Its actual work slice preserves completed01/02, selects03/04 and defers05–08 with five
ordinary work units left. Progress paths remain the original 16; the separate interruption
admission retains the full 24-file capture, rather than rewriting accepted progress.

Independent admission audit at 05:47Z also verifies `same_continuation_inputs=true`, exact
request/work/lease/parent agreement across admission/invocation/capture-start, and full
field equality of Run6 inventory_before to Run5 receipt inventory_after. All 24 retained
paths and digests enter the native prompt through the pure reading projection; they are
not appended to or substituted for the original ContextManifest. Original195 facts remain
unchanged. Audit SHA `2960b6e0c5556051c66c65fde8165a7368d312a2e52f571e6b03d146e3999916`.

This verifies resumed execution, not K1 delivery completion. Steps03/04 await an accepted
new result; no candidate, QA PASS or Review APPROVE is claimed. Continue following the
same native queue/artifact path; an independent verdict cannot be authored by maintenance.

Rollback follows controlled stop and compatible complete-body readers. Never delete new
receipt/admission/decision facts or overwrite old UNKNOWN/FAILED records to fit old code.
