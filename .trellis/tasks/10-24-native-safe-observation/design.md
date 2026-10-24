# Private observation contract

## Existing evidence and feedback loop
The native drain already sees original bytes and actual EOF, but only retains bounded
text. The JSON observer retains one complete terminal diagnostic. Coder timeout capture
seals stop/inventory and WORK_INTERRUPTED, discarding safe event activity statistics.
The regression loop will drive the existing runner with fixed JSONL+stderr then sleep;
it must obtain real timeout/owned stop and reopen the exact independent statistics.

## Signatures and fixed fields
- `NativeStreamObservation`: raw_bytes (saturated unsigned63), saturated flag,
  first_byte_seconds/last_byte_seconds (finite relative monotonic or null), eof.
  Every pipe uses the same monotonic epoch captured once by the runner before prompt
  preparation/Popen; drain construction never starts a new epoch. The enclosing
  output record seals `elapsed_seconds` from that same epoch after real EOF, and
  enforces `0 <= first <= last <= elapsed`, with both times absent iff raw_bytes=0.
  Saturation means an observed increment exceeded unsigned63 and retains that bound;
  event saturation likewise requires at least one fixed counter at its bound.
- `NativeEventObservation`: observed_lines and fixed counts for thread.started,
  turn.started/completed/failed, item.started/completed, error and other; invalid_lines,
  saturated, stream_valid, stdout_eof, partial_line. Counts represent only the parsed
  prefix when poisoned; `stream_valid=false` explicitly prevents complete-count claims.
- `NativeOutputObservation`: stdout/stderr observations, optional explicit-protocol
  event observation. Construct only from actual EOF drains and a real owned stop.
- `CodexInvocationResult.output_observation: NativeOutputObservation | None` is private
  runtime metadata. Existing injected fake runners default absent. No public Schema field.
  Its optional `observation_persisted` bit records publication success for the current
  adapter invocation. Failed publication clears runtime statistics and marks interruption
  prose UNAVAILABLE without storing exception bodies. A later strict read may validate
  an immutable file that survived a failure after its atomic publication.
- `NativeExecutionObservation`: v1 private immutable record with scope, Task, Run,
  work item, lease, source revision, Context, original request digest, capture-start SHA,
  capture-stop observation SHA, safe output observation, recorded time and own digest.
- `FileContinuationStore.put_native_observation(record)` / `native_observation(run)`
  validate digest plus exact reopened original capture start/stop and filename. New
  `native-observation-<run>.json` uses existing private dirfd atomic envelope I/O.
- An explicit typed availability read returns AVAILABLE(record) or UNAVAILABLE(no stats)
  when no record exists. Missing old telemetry is unknown, never synthetic zero counts.
- A separate optional recorder seam follows successful durable stop recording under
  the original Task lock. Telemetry failure is caught without retaining exception bodies;
  interruption/failure display marks unavailable, and missing durable record reads
  UNAVAILABLE. It cannot change classification, stop, outcome, budget or continuation.

## Ordering and identity
Drain bytes -> actual stdout/stderr EOF -> actual owned-session stop -> close local
pipes/selector -> existing durable capture stop -> independent observation write ->
existing registry completion. A local close/unknown stop failure cannot publish a
complete observation. Exact publication/replay retains original first bytes and digest.
Stats do not make native-reported events command receipts or provider authority.

## Validation matrix
| Input | Required result |
| --- | --- |
| Valid complete fixed JSONL, stderr, actual timeout/stop | bounded exact stats, unchanged TIMEOUT/WORK_INTERRUPTED |
| Chunked UTF8 / many bytes in discarded text middle | exact raw bytes, root fixed counts, constant storage |
| Secret/command/URL in item body or nested forged event | no text retained; nested event not root count |
| Duplicate keys, malformed/overlong/partial/invalid UTF8 | invocation event trust poisoned; never restored |
| Saturated counters | max bounded count plus saturation flag |
| No explicit codex_json protocol | event stats absent, byte observations still exact |
| Missing output EOF, unknown stop, local close failure | no complete observation publication |
| Missing old/new record or telemetry write error | explicit unavailable, original stop/outcome preserved |
| Wrong Task/Run/claim/source/Context/start/stop/scope or changed replay | strict private store rejection |
| Exact known record in deletion closure | validate/recurse/remove with original Task only |
| Unknown/foreign/late-added/changed file | deletion refuses, original data retained |

## Test points
Pure observer tests assert fixed names only and full secret-free serialization/repr.
Real subprocess runner tests assert accurate bytes/counts/times and actual watchdog/stop,
including dual-stream flooding, ownership loss and close/EOF negatives. Real Git/SQLite
continuation tests reopen independent record, preserve byte-identical original start/stop/
receipt, reject rehashed binding tamper and keep one-use continuation/budget semantics.
Deletion closure test admits only new validated name and rejects foreign/unknown records.
