# Actual owned session stop and durable finalization

## Scope and failure mode

The native, structured, policy-bound command and currently registered verification/query runners
share one trusted stop boundary. A spawned leader may exit while a same-SID child moves into another
PGID and closes both inherited output pipes. Leader reap, original PGID absence and EOF can then all
be true while that child remains alive. None is a complete owned-session stop.

`OwnedSessionController` binds only a real, successfully created isolated `subprocess.Popen` object.
It is private trusted composition, absent from Agent tools; no supplied PID selector, shell process
survey, general signal permission or new Agent capability is introduced. It observes the original
positive SID and every process birth it has already observed. An observed birth leaving that SID
causes uncertainty. An **unobserved** descendant escaping through `setsid()` is outside this proof;
this is not full process-tree containment. Retained output pipes still independently fail EOF.

## Signatures and ownership

```python
# owned_sessions.py
_DarwinInspector.identity(pid: int) -> OwnedProcessIdentity | None  # private read seam
OwnedSessionController(process: subprocess.Popen[str] | subprocess.Popen[bytes])
controller.observe_session()  # active owner polling, read only
controller.stop(timeout_seconds=1.0) -> OwnedSessionStopProof
controller.require_empty() -> OwnedSessionStopProof  # read only
require_recorded_session_empty(proof: OwnedSessionStopProof) -> None  # no signal authority

# owned_processes.py
ownership = capture_owned_process(process)  # immediately after actual Popen, before reap
ownership = observe_owned_process(process, kind="native", observation=ownership)
finish_owned_process(process, ownership, output_drained=False,
                     timeout_seconds=1.0, complete_observation=True)

# trusted durable application boundary, never an Agent tool
with owned_record_finalization() as finalization:
    execute_and_observe_real_stop()
    typed_store.put(exact_record)  # or the actual run manifest seal
    finalization.confirm_saved()
```

Ownership capture requires `PID == PGID == SID`, kernel birth identity and current boot identity
before leader reap. Missing/failing capture can clean the actual `Popen` leader, but cannot reconstruct
session ownership or publish a stronger stop. Capture errors retain only a failure flag, not an
Exception/traceback that could keep a complete caller payload alive.

Darwin uses `libproc.proc_listallpids`, exact `PROC_PIDTBSDINFO` birth records and `kern.boottime`;
Linux uses `/proc` kernel start ticks, boot UUID and SID membership. Enumeration is bounded to 16,384
processes and one second per scan; saturated/partial/denied inspection is unknown. System/kernel
processes with zero SID are excluded before constructing a positive owned identity. The controller
retains at most 16,384 observed PID/birth identities and hashes at most 1,000,000 observations in
constant memory. The latter supports legitimate long native polling; it does not retain scan bodies.

Darwin's initial SID read and BSD birth query are separate OS calls. If the birth query returns a
short result with errno 0/ENOENT or another non-ESRCH failure, recheck current SID once: only a fresh
kernel `ProcessLookupError` (ESRCH) proves that this queried PID disappeared. A still-living PID,
changed/recycled SID or denied/invalid SID query remains unknown. The unreadable birth result itself
never proves absence, and no birth identity is reconstructed. Initial kernel absence and an actual
BSD ESRCH keep their existing absence semantics; complete birth records still require the second
matching SID check. The controller, signals and recorded-proof reader all use this same inspector.

This defensive disappearing-process seam has deterministic errno 0/ENOENT red/green tests plus
real Darwin exit coverage. It does not establish the first cause of the integrated public delivery
fixture that once stopped after QA with only `OwnedProcessesUncertain`; a diagnostic rerun and
bounded real command/process-churn probes did not reproduce that original error. Preserve this
distinction in delivery reports instead of claiming that an unknown original cause is resolved.

Each signal checks current boot, original leader identity and all known births, then freshly verifies
the exact target PID/PGID/SID/birth. Signals go to individually verified members, never an unchecked
reused PGID. Finite TERM then KILL phases repeatedly scan; success requires leader reap and two
complete empty observations. Peer PGID changes inside the original SID are tracked. A reused peer
PID with a different birth is the old process absent, never authority to signal the recycled process.
Leader/SID reuse is conservatively rejected. OS observation-to-signal is not atomic containment.

## Wire and digest contract

`NativeProcessStop.session_proof: OwnedSessionStopProof | None` is additive. Absent/null proof is
omitted by ordinary `model_dump` and wire serialization, preserving the original stop and enclosing
record digests. Existing records keep their original leader/group scope and are never upgraded.
New stops retain `kind=completed → returncode=0` and `kind=failed → returncode!=0` guards in both
the canonical generated Schema and typed validation.

`OwnedSessionStopProof` carries version `v1`, fixed `proof_scope=owned_session_empty`, boot identity,
isolated leader, sorted unique observed PID/birth identities, bounded observation count, streaming
observations SHA-256, aware observation time and proof SHA-256. The proof leader must exactly match
the stop leader and observation cannot postdate the stop. Unknown fields and corrupted digests fail.
`require_recorded_session_empty` validates this proof and rechecks current boot, conservative leader
occupancy, every observed original birth (including a living birth now in another SID), and original
SID absence twice. This read never signals. Legacy proof reads retain the old group check.

`scripts/sync-owned-session-schemas.py` synchronizes only `NativeProcessStop` and its new definition
closure in exactly ten embedded Schemas, preserving enclosing handwritten guards. Fresh repair
generation obtains the same canonical stop guards; repeated generation must be byte stable.

## Durable responsibility and Host registry

Stop, EOF, pipe-worker completion and actual publication are distinct conjuncts. A registry snapshot
may be `running`, `finalizing` or `uncertain`; all remain present and prevent Host drain READY.
`finalizing` means actual execution stopped while its required record has not yet finished saving.
An ended thread, locally closed descriptor or missing registry Operation context is not stop proof.

| Trusted consumer | Required completion before registry removal |
|---|---|
| Native Codex runner | complete SID stop + true EOF + reap, exact observer stop save, then independent recheck |
| `RunEvidenceSession.capture_command` | complete command stop and actual `EvidenceStore.put` return |
| `EvidenceCapturingAgentAdapter` | all nested command evidence, actual result evidence and run manifest `seal` |
| Swift verification binding | resource/command cleanup and exact COMPLETED/BLOCKED verification receipt put |
| Python/MySQL verification | owned command/proxy/resource cleanup and exact verification receipt put |
| Read-only Git/OS query or DEVNULL helper with no publish contract | actual session stop and relevant pipe/thread completion |

Nested saved scopes transfer their stopped observations to the outer scope; they cannot clear them
before the outer run seal. Trusted proxy workers explicitly inherit both operation and finalization
contexts and finish pipe workers before adding stopped observations. Finalization retains at most
4,096 deduplicated observations, clears all references/parent links on exit, and rechecks the stop
facts before removal. Store/seal failure, omitted `confirm_saved`, late/duplicate confirmation or
scope overflow preserves uncertainty. It never fabricates a failed provider result or verdict.

## Validation matrix and test points

| Case | Required result |
|---|---|
| Same SID/different PGID child closes stdout/stderr; including TERM resistance | stop peer before successful publication; escalate to KILL within finite bound |
| Observed child uses setsid and closes both pipes | unknown; no successful stop/registry clear; stored original birth also rejects read-side reuse |
| Unobserved setsid child closes pipes | explicitly outside owned SID proof; no whole-tree claim |
| Denied, partial, oversized or saturated enumeration; boot/birth drift | no unchecked signal, no registry clear, Host cannot READY |
| Short Darwin birth query after an initial live SID; fresh kernel ESRCH | queried PID absent; two full empty sweeps, known-birth, EOF and save gates still required |
| Short Darwin birth query while SID remains live/changes or its recheck is denied/invalid | unknown; no absent process, signal or successful stop is inferred |
| Leader already reaped before capture | no retrospective stronger ownership proof |
| Stop/evidence/receipt put or run seal fails after real process exit | all affected snapshots uncertain; drain stays blocked |
| Multiple nested successful commands before outer seal | snapshots stay finalizing until actual seal completes |
| Old absent/null proof and nested historical digest | original bytes/digest unchanged |
| Wrong scope/leader/time/digest/extra proof field | typed/static contract rejects |

Executable coverage lives in `tests/execution/test_owned_session_stop.py`,
`test_owned_session_inspection.py`, `test_owned_record_finalization.py` and
`tests/contracts/test_owned_session_stop_schema.py`, plus existing adapter/executor/evidence/continuation
regressions. Real subprocess coverage was run on Darwin. Linux parsing and identity logic have unit
coverage; no real Linux host or MySQL runtime is claimed by this task.

## Existing-data treatment and rollback

### Controlled verification discovery diagnosis

`manager.python_verification_discovery._read_command(argv, ...)` maps only
`OwnedProcessesUncertain` from the actual bounded command to
`PythonMysqlDiscoveryError(NativeVerificationCapabilityDetail.PROCESS_STATE_UNCONFIRMED)`.
Its wire value is `VERIFICATION_PROCESS_STATE_UNCONFIRMED`; it is a capability-discovery
detail, not a QA/Review verdict or a new execution/recovery authorization.
Docker context, daemon and image exception boundaries must rethrow this typed discovery
error before handling their ordinary stage-specific errors. A generic `RuntimeError` must
never be accepted as proof of this specific owned-process uncertainty.

The existing `NativeVerificationWaiting(CAPABILITY_UNAVAILABLE, detail_code=...)` and
`DeliveryPreflightObservation.native_wait_detail` preserve the exact fixed reason into the
digest-bound preflight receipt and its published Schema. Engineering-wait text must state
that original probe stop or record finalization remains unverified, that inspecting/pulling
an image cannot supply the missing facts, and that reinspection is appropriate after the
platform execution service has verified the original stop/finalization facts. The text must
not offer a false successful-stop claim, arbitrary kill instruction or repeated image repair.

| Observation | Required diagnosis and unchanged safety gate |
|---|---|
| Actual owned capture/finish uncertainty at context, daemon or image command | fixed process-state detail; preserve original registry unknown |
| Ordinary context/daemon/image failure with no owned uncertainty | retain corresponding existing capability detail |
| Two later successful image inspections after one failed original capture | later image fact can be READY; original registry unknown still blocks drain |
| Native verifier → preflight → Chinese engineering-wait rendering | preserve typed detail and receipt integrity; no extra approval or state mutation |
| New enum wire value, absent/null legacy optional detail | published Schema matches model; legacy bytes/digests unchanged |

Required incremental tests are `tests/manager/test_owned_verification_discovery_diagnosis.py`
(real registry, subprocess and inspector seam), `test_python_verification_discovery.py`
(all three stage boundaries and negatives), `test_native_verification.py`,
`test_delivery_preflight.py` (including Schema parity) and `test_delivery_wait.py`.
The real reproduction establishes a possible code path, not the unobserved initial cause of
production PID 802's earlier stop failure. Do not infer that cause from later successful probes.

Good: a real image probe loses owned capture and the platform presents the fixed missing-stop
detail while retaining its unknown registry entry. Base: an ordinary missing image still uses the
original image-unavailable detail. Bad: report every `RuntimeError` as process uncertainty, advise
pulling an image to clear a lost stop proof, or use later successful probes to erase an old unknown.

No historical records are rewritten and no missing stop proof is backfilled. The new reason
is recorded only by new observations under the fixed binary; an already-running old instance
keeps its own registry and must follow the separately verified service maintenance route.

No migration, MySQL access, historical stop backfill, Task/queue/approval rewrite or K1 resume.
Old records retain their original scope and current-fact recovery gates. New code changes do not
prove that an already-running old binary or historical execution stopped. Root integrates only after
independent review and deploys at an idle verified controlled restart boundary. If an old unknown
execution lacks facts, use its existing exact authorized recovery route rather than republishing a
new proof for it.

Rollback the implementation before starting new invocations, after verified controlled stop. Preserve
all optional proof bytes and original evidence/history; do not strip a proof to change its digest.
A reverted binary must not read new proof-bearing records unless its reader supports the extension.
No `src/templates/markdown/spec` template tree exists here; no parallel template sync applies.
