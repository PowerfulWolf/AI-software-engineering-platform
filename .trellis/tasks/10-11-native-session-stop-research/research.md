# Native stop coverage: independent static research

Status: research only; no implementation, production action, accepted stop-policy change,
or new verdict. Source revision: `8c7cafa4a11617ec3e32169549233919dd4ee99a` from the
isolated `ase-k1-maintenance-integration` checkout. This note is held in a separate
research checkout, not the main checkout. Research date: 2026-10-11.

## Supported conclusion

The current native runner proves that its spawned leader was reaped, both inherited
output pipes reached actual EOF, and the original leader process group is absent.
It does not inventory or prove absence of every process group that remains in the
original session. Existing model/schema terminology sometimes calls this a session;
the executable checks use the leader PGID. This is a coverage limit, not a claim that
any particular completed run published a false stop, or that a process currently exists.

Primary source references below are relative to the source checkout/revision above.

## Source evidence

| Owned fact | Executable source | Practical scope |
| --- | --- | --- |
| Trusted runner starts an isolated session | `src/ai_software_engineer/agents/codex_cli.py:246` (`Popen`, `start_new_session=True`, inherited Task lock) | Initially PID = PGID = SID for the leader |
| TERM/KILL and absence probes select `process.pid` as PGID | `agents/codex_cli.py:292`, `:317` | Only the original leader group is signalled and probed |
| Stop publication follows local pipe cleanup and registry recheck | `agents/codex_cli.py:355` | Actual output cleanup cannot be skipped by a completed operation thread |
| Both pipes require true empty reads; then leader wait | `agents/_native_output.py:67` | Local descriptor close is not EOF proof |
| Registry records each actual Popen leader | `owned_processes.py:97` | No descendant/group/session inventory is registered |
| Registry clearing checks leader poll, original PGID absence, and output-drained input | `owned_processes.py:147` | A different group in the same SID is outside this recheck |
| Host drain waits for registry entries to disappear | `owned_processes.py:85` | No supplementary session scan |
| Downstream recovery rechecks `stop.group_id` | `orchestration/continuation.py:762` | Recovery preserves the same PGID proof scope |
| Typed stop holds PID and PGID, requires equality | `agents/execution.py:27` | No explicit SID, birth identity, group inventory, or proof-scope field |

The current comment at `agents/codex_cli.py:318` says session absence proves stopped
descendants, but its next operation is `os.killpg(process.pid, 0)`. POSIX process-group
absence and session absence are different facts. A child can enter another process group
while retaining the same SID. If it also closes both inherited output pipes, the current
EOF and original-PGID predicates do not observe that child. This is a static counterexample
to the proof's intended coverage; it has not been run against production or as a fixture here.

The existing escaped-child fixture in `tests/execution/test_owned_processes.py:122`
starts a new session and retains the inherited pipes. Its native test at `:138`
correctly expects uncertain drain and refuses service-ready. That is useful retained-pipe
coverage. It does not cover a separate same-SID group that closes both pipes. No test
or model invocation was run during this research.

## Observed production fact boundary

Earlier root inspection reported leader PID/PGID/SID `75117` and code-mode-host
PID/PGID `78622` with SID `75117`. This establishes that multiple groups in one native
session are possible in this setup. The observation was supplied by root; this note did
not repeat a production process read. It does not establish their later state, escaped
descendant state, or the correctness of a later stop record.

## Separate follow-up contract proposal

The following is a proposal for a maintenance task, not an approved change:

1. Add an executor-owned typed session identity captured immediately after actual spawn.
   Bind operation/run, leader PID/PGID/SID, OS boot identity and high-resolution process
   birth identity. Request/model text cannot supply ownership or a stop assertion.
2. Provide a bounded OS inspection seam that enumerates all groups and process identities
   currently in that exact owned SID; revalidate identities before signalling. Return
   typed observation failures and uncertainty, never an arbitrary PID kill capability.
3. Terminate the confirmed owned groups with finite TERM/KILL/recheck windows. Include
   cancellation, owner-loss and setup-failure cleanup. EOF and leader reap remain separate
   requirements; a silent child must not be inferred stopped from output closure.
4. Publish an explicit proof scope and complete observation digest. A stronger new stop
   must not silently reinterpret old records or mutate their digest. Legacy readers must
   continue verifying the original wire bytes and original scope.
5. Reuse the current Host registry and Task lock as ownership seams; keep process inspection
   and termination outside Agent tools. A failed observation retains uncertainty and blocks
   new workspace reuse/service-ready instead of manufacturing a success proof.

The six current embedded `NativeProcessStop` definitions are in:

- `schemas/execution-capture.schema.json`
- `schemas/execution-continuation.schema.json`
- `schemas/knowledge-execution-record.schema.json`
- `schemas/knowledge-invocation-outcome.schema.json`
- `schemas/structured-execution-observation.schema.json`
- `schemas/rejected-coder-output-checkpoint.schema.json`

These definitions, regeneration guards and compatibility fixtures must change together
if the future accepted contract changes. Do not implement a cross-Schema stop change
mid-execution. The root explicitly stopped that implementation during the active run.

## Residual limits and required verification

PID/SID/PGID reuse, PID query-to-signal races, stale process inventories and denied OS
inspection are material limits. Birth/boot identity and bounded rechecks reduce ambiguity;
they do not provide an atomic kernel containment guarantee. A descendant that calls
`setsid()` leaves the original session; without a stronger OS supervisor/container job
scope, a same-SID proof cannot claim that every possible descendant has stopped.

A follow-up test matrix must cover ordinary one-group completion; silent same-SID
separate-group children; retained-pipe escaped children; setsid escape with closed pipes;
leader exit before children; TERM-resistant groups; permission/query failures;
identity reuse; cancellation/deadline; and old digest compatibility. Negative cases must
retain uncertain registry state and never publish a broader stop proof.

## Existing data and permissions

No database, sidecar, Task, Operation, journal, stop record or artifact was modified.
Do not backfill a stronger scope onto historical stops. Existing records retain their
auditable meaning. Any target existing recovery requires independently established current
stop facts, existing idle/Task/queue fences and the ordinary exact approval chain; this note
grants none of those permissions. Any future rollout occurs only at the controlled idle
restart boundary. Rollback for this research is removal of this uncommitted note; no runtime
or durable-data rollback is required.

## Follow-up review at completed-output integration

The completed-output capability preserves the historical stop's original PID/PGID meaning.
It does not claim a complete SID-empty proof. Root's separate exact maintenance audit checked
SID 75117 absence, Task/queue idle and unchanged original facts; these are new local maintenance
observations, not amendments to run7's stop. Recheck them before the public baseline approval.

There are now ten embedded `NativeProcessStop` Schemas: the six listed above plus
`completed-coder-output-unavailable`, `execution-baseline-plan`,
`execution-baseline-queue-consumption` and `console-operation`. A future optional versioned
`session_proof` must use `exclude_if=None`: the current stop digest does not exclude None,
so a bare `default=None` would change historical stop and enclosing record digests.

The critical real-process regression must create a child in the original SID, a different PGID,
and with both inherited output pipes closed. Leader reap and EOF must not produce a broader
success while that child survives. Cover TERM-resistant groups, denied/bounded OS inspection,
birth/boot drift, owner loss, cancellation and stop-save failure. Use one trusted owned-session
controller for native, structured, tool, verification and UI subprocess cleanup; do not grant
Agent tools an arbitrary PID signal operation. A SID-empty scope cannot by itself cover an
unobserved descendant that created a different SID. This contract remains unimplemented.
