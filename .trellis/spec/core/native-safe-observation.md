# Native execution activity diagnostics

## Scope / Trigger

`SubprocessCodexCommandRunner` already drains the original stdout/stderr and proves
owned-session stop. A local timeout previously retained bounded text and stop facts,
but discarded safe activity counters. Preserve prospective Coder diagnostics without
reading provider logs or changing failure classification, work budget, continuation,
command receipts, artifacts, or QA/Review gates. These are private Python contracts;
they do not extend the public Schema inventory or any agent tool.

## Signatures

- `agents.native_observation.NativeStreamObservation`: `raw_bytes`, `saturated`,
  `first_byte_seconds`, `last_byte_seconds`, `eof`.
- `NativeEventObservation`: `observed_lines`, `thread_started`, `turn_started`,
  `turn_completed`, `turn_failed`, `item_started`, `item_completed`, `error`, `other`,
  `invalid_lines`, `saturated`, `stream_valid`, `stdout_eof`, `partial_line`.
- `NativeOutputObservation`: `schema_version=v1`, `elapsed_seconds`, `stdout`,
  `stderr`, optional `events` only when explicit `output_protocol=codex_json`.
- `CodexInvocationResult.output_observation: NativeOutputObservation | None` and
  `observation_persisted: bool | None` are private adapter metadata.
- Optional `NativeObservationRecordingControl.record_native_observation(request,
  root, *, output) -> None` follows the mandatory `record_native_stop` call.
- `orchestration.native_observation.NativeExecutionObservation.from_capture(*,
  start, stop, output, recorded_at)` creates the independent immutable record.
- `FileContinuationStore.put_native_observation(record)` and
  `native_observation(run_id) -> NativeObservationRead` use
  `native-observation-<run_id>.json` in the existing private Task continuation directory.

## Contracts

The runner captures one monotonic epoch before prompt preparation/Popen. Both pipes
and the final `elapsed_seconds` share it; drain creation cannot reset it. Require
`0 <= first <= last <= elapsed`, absent first/last iff `raw_bytes=0`, and actual empty
reads on both original pipes. Counters saturate at `2**63-1`; an overflow flag retains
the cap. Timings are finite, nonnegative, bounded relative seconds.

Count only fixed recognized root JSONL types, plus `other`; retain no body, arguments,
commands, paths, URLs, secret, prompt, or arbitrary event name. Existing strict parser
rules still poison the invocation on malformed, duplicate, overlong, non-UTF8 or
incomplete JSONL. Fixed category counts describe the parsed prefix after poisoning;
`invalid_lines` records only the first poison, while `observed_lines` counts every
complete LF line. A trailing partial line remains explicit even after earlier poison.
These native-reported events do not establish tool execution or provider authority.

Publication ordering remains original-byte drain -> actual EOF -> owned stop -> local
resource close -> mandatory capture-stop -> optional diagnostic write -> registry
completion. A mandatory stop error still propagates. Only the independent diagnostic
write is caught; no exception text is retained. Failed publication clears runtime
stats and adds fixed `UNAVAILABLE` interruption prose. Missing durable records return
`availability=UNAVAILABLE, record=None`; never manufacture zero values. Corruption,
unsafe paths and identity drift still raise `ContinuationRejected`. A later strict
read can validate an immutable file surviving a failure after atomic publication.

The new record binds scope, Task, Run, original WorkItem/Lease, full source revision,
Context, request digest, capture-start SHA and capture-stop observation SHA. Its
private envelope and self-digest use existing dirfd/O_NOFOLLOW/private-mode/atomic
append I/O. Every read reopens and compares original capture-start/stop; rehashing a
foreign binding does not make it acceptable. Exact replay retains first bytes.
Existing stop and receipt wire layouts/digests are unchanged. The original Task lock
permits this fact-only publication even after lease loss; it grants no new authority.

## Validation & Error Matrix

| Observation | Required result |
| --- | --- |
| Valid explicit JSONL + stderr + actual EOF/stop | exact bounded bytes and fixed counters |
| No explicit event protocol | bytes available, event stats absent |
| Chunked Unicode or discarded text middle | count raw bytes before decoding/truncation |
| Body with secret/nested forged type/unknown root name | no text/name survives; only fixed root counts |
| Malformed/duplicate/overlong/non-UTF8/partial | poisoned prefix; no restored completeness |
| Counter overflow | cap plus saturation flag; no wraparound |
| Zero bytes with times, decreasing/excess/nonfinite time | model rejects, including rehashed stored record |
| Unknown stop, incomplete EOF, local close failure | no complete observation published |
| Optional write error | original mandatory stop and interruption preserved; stats unavailable |
| Missing historical record | unavailable, no backfill and no inferred counts |
| Rehashed scope/Run/Task/claim/source/Context/request/start/stop mismatch | strict read/write rejection |
| Physical Requirement deletion | validate exact new record then remove whole sealed Task directory |
| Foreign, unknown, changed or late-added continuation file | preserve/refuse deletion |

## Good / Base / Bad Cases

- Good: real timeout after two JSONL root events and stderr bytes; reopen an exact
  independent record and retain unchanged timeout/WORK_INTERRUPTED and stop facts.
- Base: an old stopped invocation lacks the new file. Read UNAVAILABLE and retain
  its immutable original stop/receipt/history.
- Bad: a diagnostic record has a recomputed digest but a different Lease or elapsed
  shorter than its last byte. Reject it rather than downgrading corruption to absence.

## Tests Required

`tests/agents/test_native_output_observation.py` asserts raw split-UTF8 bytes, root
counts, body-free serialization/repr, genuine EOF/partial behavior, saturation and
shared-epoch time inequalities. `tests/agents/test_native_observation_runner.py`
asserts real no-provider timeout, explicit protocol selection and adapter fault
injection ordering: mandatory stop before optional write; mandatory failure propagates;
optional failure preserves WORK_INTERRUPTED and contains no exception secret.
`tests/orchestration/test_native_observation_store.py` asserts reopen/exact replay,
unchanged old bytes, missing-vs-corrupt behavior and rehashed binding/time negatives.
`tests/manager/test_native_observation_deletion.py` asserts exact scope/name/capture
closure, foreign Task retention and unknown-file refusal. Existing parser, owned-session,
timeout, continuation/budget and deletion regressions remain required.

## Wrong vs Correct

Wrong: add event bodies/counters to `ExecutionCaptureStop`, make their write mandatory,
or derive missing historical activity from retained stdout text.

Correct: keep the old stop/receipt bytes, write a separate exact-bound body-free record
after the stop succeeds, and return typed UNAVAILABLE when no statistics were sealed.

## Stock data and rollback

No SQL migration or historical rewrite is needed. Existing Requirements continue via
their original stop/receipt/approval path; statistics do not participate in recovery
admission. Do not backfill old runs. Parent integration and production activation are
separate from this isolated implementation. Before any new records exist, reverting
code suffices; after publication preserve reader/deletion compatibility and immutable
diagnostics, even if disabling future writes.
