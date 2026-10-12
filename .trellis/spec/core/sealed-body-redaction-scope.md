# Sealed native body redaction in one synchronous read

## Scope and signatures

`redaction.redact_body_text(content: str) -> RedactedText` is used by
`NativeRuleEpochBody.bounded_redacted_body`. It runs the same complete static secret
patterns as `redact_text`; it does not grant source-language exceptions or execution
authority. Native body bytes/SHA/size and epoch/scope/approval checks remain unchanged.

## Contracts

The exact complete text and exact pattern tuple identify a pure no-match fact within
`source_inspection_scope`. Body facts use `generic-body`, ordinary short fields use
`generic`. Only clean complete inputs can register; no matched credential or redacted
replacement is retained. All results remain fresh immutable `RedactedText` values.

Body facts may evict opportunistic generic fields; source/patch admission may evict
both generic categories. All share the original aggregate 512 entries/16 MiB full
UTF-8 content budget. Body facts cannot evict source/patch or add a new cache pool.
At capacity, perform the complete scan without retaining a fact. A scope ends on
success/failure; no reader/global success or authority survives another HTTP request.

## Validation/error matrix

| Input | Expected result |
| --- | --- |
| Small fields fill entries; same complete clean epoch body repeated | One full scan, subsequent exact pure-fact reuse, original total limits |
| Source/patch arrives at body capacity | Original source/patch priority preserved |
| Any sensitive match | Same text/counts as ordinary redaction; no retained raw matched input |
| One character or pattern tuple changes | Full fresh scan; no old clean conclusion |
| Zero entries/bytes or oversized/non-UTF-8 input | Original complete scan/failure semantics, no optimization rejection |
| Unredacted native body passed to real Pydantic validator | Original validation failure |

Good: repeated immutable clean native bodies remain efficient after many timeline
fields. Base: no scope or exhausted capacity keeps ordinary full scans. Bad: retain
matched input, use content SHA alone without equality, or enlarge aggregate memory.

## Tests and wrong/correct

`tests/context/test_redacted_body_scope.py` covers saturation, shared accounting,
source priority, sensitive input and the real NativeRuleEpochBody rejection seam.
Keep existing `test_generic_redaction_scope.py`, `test_source_inspection_scope.py`
and epoch/recovery reader regressions for rule binding and teardown.

Wrong: make the 512-entry cache larger whenever a detail is slow. Correct: preserve
its bound and reserve effective priority for complete typed bodies, with measured
real reads and identical complete response hashes.

## Existing data and rollback

No durable Schema, SQL, Task, Operation, approval, journal, epoch or worktree changes.
Deploy at the normal controlled restart boundary and refresh the original K1. Revert
the redaction entry and its validator call to restore the previous scanning cost;
original facts, histories and approval digests remain valid.
