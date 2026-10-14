# Faulted Host retirement into inspection only

## Repeated maintenance epochs

`FaultRetirementPlan.previous_maintenance: PreviousMaintenanceEpoch | None` binds a completed and
normally admitted predecessor. None is omitted from serialization to preserve old plan bytes/digests.
The exact 3 fixed control filenames, complete byte SHA/count, terminal completion/admission digests,
and sorted bounded completion file inventory are collected internally. No caller supplies paths/PIDs.
An incomplete/unadmitted/foreign epoch refuses prepare. Prepare preserves all active records and
publishes immutable copies in `<new-plan archive>/previous-maintenance/`.

`maintenance_epoch.begin_epoch(root, archive, plan)` revalidates exact predecessor and frozen Host,
then seals `MaintenanceEpochTransition` in the plan archive and atomically compares/replaces the
active marker with this typed pending record before any signal or anchor mutation. Pending fails
all startup authority parsers. In the same replacement lock, only exact archived copies permit
removal of the previous completed/admitted fixed anchors; the full private completion directory is
inventory-checked and renamed into `previous-maintenance/`. Each phase fsyncs its directories.
The completion directory move keeps old plans/receipts in their own epoch, preventing old receipts
from being reinterpreted as new anchors. The ordinary completion executor retains its existing rules.

`finalize_epoch` first seals the new immutable `marker.json` in its archive, then exact-CAS replaces
pending with the new inspection pointer. A pointer is mutable only through this typed local action;
previous and new marker bytes stay immutable in their archives. No marker-free publication window
is permitted. `_verified_marker` recursively verifies predecessor controls, complete linear
completion chain and exact admission, plus the old retirement chain. The reader allows 128 epochs;
cycles or a 129th node refuse. Prepare and execute reserve one new node and reject capacity before
active pending publication, anchor cleanup or signals.
The new epoch needs an independent completion and normal admission; old authorization never applies.
Normal Host composition holds replacement lock through writer construction, including reused admission.

The service launcher's `launch_detached` forwards the proven FD with `Popen(pass_fds=(fd,))` only for
the Console launch. An environment FD number alone is no ownership proof: Popen otherwise closes it.
Supervisor/caffeinate launches receive neither this FD nor its environment selector. Console `main`
calls `release_inherited_startup_lock` after construction, validating root/inode/uid/mode/lock before
closing its borrowed FD; the parent launcher still holds the same lock until startup acknowledgement.
The selector is removed from both the process and TeamHost runtime environments. Keeping it open
would indefinitely block stop/restart. A direct embedded factory retains caller-owned descriptors.
`test_service_child_receives_then_releases_verified_startup_lock` reproduces the original EBADF and
proves actual child admission and subsequent stop can both acquire the correct lock.

| Input/failure | Required behavior |
| --- | --- |
| Prior exact admitted epoch and current frozen REFUSED Host | new inspection epoch, all old bytes preserved |
| Pending publication/anchor removal/directory move/final pointer interruption | same plan resumes exact phase; writers refused until finalization |
| Prior live or archived control/plan drift, symlink, incomplete or unadmitted predecessor | no signal or normal authority |
| Old completion plan replay after rollover | refuse; new completion/admission retained |
| Concurrent normal writer construction/replacement | same lock prevents crossing, including old admission fast path |

Tests: `test_second_maintenance_epoch_preserves_history_and_retries_every_phase`,
`test_previous_epoch_drift_never_grants_new_authority`,
`test_normal_writer_cannot_construct_during_maintenance_replacement`,
`test_next_epoch_depth_is_refused_before_prepare_or_any_signal`.

## Scope and signatures

This is an independent local engineering action, never ordinary READY, delivery approval, old Run
completion, all-tool stop proof or datastore consistency. The fault-retirement successor is **inspection** until separately confirmed maintenance completion:
no TeamHost, dispatch/index workers or HTTP mutations. Unknown historical execution and scope remain
UNKNOWN. The earlier unconnected `service_maintenance.py` prototype is not part of this implementation.

`prepare_fault_retirement(environment) -> FaultRetirementPlan` collects actual fixed current facts;
`execute_fault_retirement(environment, plan_sha256, confirm_fault_retirement=True) -> Receipt` executes
only the collected Host/controller identity. The CLI does not accept caller-provided Plans/receipts,
PIDs, arbitrary paths, idle booleans, commands or JSON evidence. Local OS user is the maintenance principal.
Both steps hold the existing `console-service-replacement.lock`; only a trusted local operator calls
this executor after explicit engineering authorization. It is not an Agent/HTTP/tool capability.

`inspection_required(environment: Mapping[str,str]) -> bool` verifies the fixed private
`console-inspection.json` and the immutable control-record archive chain. Missing marker returns False; malformed,
foreign, link, changed control chain or unsafe permissions raises fixed `FaultRetirementError` before any
writer is created. `ASE_CONSOLE_MODE=inspection` also permits explicit readonly startup. A marker forces inspection even if the environment says normal until the separate
[maintenance-completion](maintenance-completion.md) plan/receipt/admission gate succeeds.
The marker and control-record archive are retained; diagnostic logs have independent retention. There is no marker deletion or HTTP exit-inspection API.

`require_inspection_retirement(env, instance, request, result)` is the only dead/initial fallback:
exact original REFUSED objects/files, complete archive/receipt/marker and fresh original boot/PID absence
admit an inspection successor. Normal exact READY semantics remain independent. Subsequent readonly
restarts retain the marker and cannot silently acquire delivery authority. Script configuration apply
is refused in inspection; the host rejects every non-GET/HEAD request without constructing writers.

## Actual collection and execution contracts

Original instance/request/result must be exact matching REFUSED SHUTDOWN, with publication times and
safe fixed summaries. Original PID file is owner-controlled regular nlink1, non-writable by group/world
(legacy0644 allowed); archived copies are0600. All lifecycle originals remain unchanged by maintenance.
Kernel boot/birth/session identity, current frozen state and actual executable/argv are checked before
prepare and each signal. Kernel birth must be at/before the preexisting instance.started_at and within
60 seconds: this supports ordinary launcher/Host startup while refusing absent/recycled/foreign identity.
This new ownership observation is not a historical stop proof. Denied/unsupported facts refuse.
Host argv must be the exact PID-file ASE entry and its interpreter, kernel executable that interpreter.

The fixed controller supervisor, when present, is bound by its original PID bytes/hash/mtime, kernel
birth within60s before that file publication and exact `sh script supervise` argv. Darwin's actual
/bin/sh script execution can have kernel executable /bin/bash; only this observed versioned system
capability is accepted, with exact argv/script and birth still required. Linux uses resolved /bin/sh.
The frozen Host remains stopped while this exact supervisor receives TERM and real absence is observed.
Only then the exact Host receives SIGKILL. Historical child tools are never selected or signaled.

Config/catalog discovery uses ProductionConfig and typed Team/Project manifests. Incomplete catalogs
are explicitly CATALOG_UNAVAILABLE and execution completeness UNKNOWN; they never authorize delivery.
Config byte drift invalidates execute. No SQL rewrite, arbitrary scope input or old memory getter
injection occurs. Passive kernel reads do not execute Python/C functions in the faulted Host.

The original full log is same-filesystem moved into the private archive without truncation, preserving
its exact device/inode/size. Before any Host signal, either source or already-moved log must match that
identity. Chmod/fsync partial failure is repairable only on that exact inode. After Host/controller exit,
bounded trusted lsof checks the fixed archive directly and requires a positive own-PID/exactFD/au
sentinel. Actual Darwin lsof returns0 or1 when other closed files are unmatched; either code requires
empty stderr, bounded complete parsed fields and positive sentinel. Emptyrc1, rc2, unknown/malformed
fields, missing access/probe or log writers refuse. Each f resets access. Known ancillary holders may
exit naturally for up to3 seconds; persistent unknown writers block finalize, never get killed.
The stable full log is streamed through SHA-256 during retirement. Startup validates only control records; retained log bytes are independent diagnostics.
Inspection startup uses the lifecycle publication window; it does not scan large diagnostic logs.

## Durable phases and retry

Private fixed archive: `console-fault-retirements/<plan_sha256>/` holds original bytes, plan,
optional supervisor PID original, termination-intent, optional signal-sent acknowledgement, full log
and receipt. Records are typed/extra-forbid, aware-time/digest/lineage-bound,0600 owner/nlink1, nofollow,
bounded, exclusive immutable publish with file/directory fsync. Static JSON Schemas and parity tests
cover plan/intent/signal/receipt/marker. Hashes prove integrity; the actual executor creates the facts.
Same-OS malicious arbitrary code/store access is outside this trusted local channel boundary.

Execute seals intent before a signal. Repeating the same exact plan after rename/chmod failure reuses
that exact log inode and frozen process. Once the Host identity is absent, retry never signals another
PID: it only completes the same archive/hash/receipt/marker. A lost signal acknowledgement stays
signal_sent=UNKNOWN and signal_sent_at=None; it does not fabricate the time or original result.
Receipt separately records maintenance_started_at, actual Host-absence observation and optional signal
ack timestamp. It always says historical REFUSED, historical outcome UNKNOWN, scope UNKNOWN, inspection.
Marker publication failure is retryable from the receipt; conflicting records refuse rather than rewrite.

## Validation matrix and executable tests

| Case | Required behavior |
|---|---|
| Exact frozen Host/controller, full original/log capture, actual exit | seal UNKNOWN/REFUSED receipt; inspection only |
| Wrong confirm/digest/config/oldbytes/executable/birth/unfrozen | no signal; refuse |
| Failure after rename/chmod/signal/hash/receipt/marker | same-plan bounded retry; never signal recycled or unrelated PID |
| Persistent logwriter, lsof empty/error/malformed/probe missing | refuse finalize; preserve complete archive |
| Bad control marker/receipt or control-record symlink | refuse startup before writer creation |
| Diagnostic log removed or changed after completed retirement | startup authority unchanged; explicit diagnostic audit rejects changed/missing bytes |
| Environment normal with durable marker | still inspection |
| Normal READY | unchanged lifecycle behavior |

`tests/web_console/test_fault_retirement.py` runs real isolated Host/controller retirement and CLI
admission, stage failure injection, current identity rejection, full-byte log/security negatives,
lsof strictness and Schema parity. Independent inspection tests cover actual marker→production app
without mocking the marker gate. No production maintenance or old K1 QA/Review success is claimed by tests.

## Existing-data treatment and rollback

Maintenance archives original lifecycle/PID/log bytes; no Task/Operation/approval/verdict/lease or Run
history rewrite. Unknown old tools and workspaces remain retained, and no demand resumes. The actual
service retirement is a new engineering action separate from normal controlled stop.

Rollback must retain compatible marker/receipt readers and the inspection-only gate. Never remove the
marker, delete archives, clear the old failure latch, manufacture READY or start an old normal-only
binary against this state. Exiting inspection uses the separate reviewed maintenance-completion gate. Safely continuing a retained
demand still requires its own recovery authorization; neither service action grants it.

## Diagnostic log retention

`fault_retirement._verified_marker(root)` validates control facts only. It never opens, hashes or
requires `ase-console.log`. Retirement execution still seals the full log digest before its receipt.
`verify_retired_log(environment)` is an explicit diagnostic audit, separate from startup authority.
`fault_log_retention.purge_archived_log(environment, confirm_delete_archived_log=True)` requires
the valid completed retirement and replacement lock. It selects only the marker-bound archive log,
checks exact original inode/private regular file/no writers, seals `log-purge-intent.json`, unlinks
the fixed retired log, fsyncs and appends `log-purge-receipt.json` with final_observation=ABSENT.
Historical log_sha256 describes bytes sealed at retirement, not a fresh audit claim. No log hashing
is required to delete diagnostic retention. The live state-root log and all control records remain.
An already absent log is recorded as ALREADY_ABSENT; partial publication retries the same intent.
Missing confirmation, corrupt control/retention records, symlink/new inode/live writer refuse deletion.
Tests assert missing/changed/unread logs permit inspection launch, corrupt control records still
refuse, exact purge idempotence, failed result publication retry, no current-log or marker mutation,
and static Schema parity.
