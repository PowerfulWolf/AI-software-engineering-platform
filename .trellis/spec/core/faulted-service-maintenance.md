# Faulted Host retirement into inspection only

## Scope and signatures

This is an independent local engineering action, never ordinary READY, delivery approval, old Run
completion, all-tool stop proof or datastore consistency. The successor is permanently **inspection**:
no TeamHost, dispatch/index workers or HTTP mutations. Unknown historical execution and scope remain
UNKNOWN. The earlier unconnected `service_maintenance.py` prototype is not part of this implementation.

`prepare_fault_retirement(environment) -> FaultRetirementPlan` collects actual fixed current facts;
`execute_fault_retirement(environment, plan_sha256, confirm_fault_retirement=True) -> Receipt` executes
only the collected Host/controller identity. The CLI does not accept caller-provided Plans/receipts,
PIDs, arbitrary paths, idle booleans, commands or JSON evidence. Local OS user is the maintenance principal.
Both steps hold the existing `console-service-replacement.lock`; only a trusted local operator calls
this executor after explicit engineering authorization. It is not an Agent/HTTP/tool capability.

`inspection_required(environment: Mapping[str,str]) -> bool` verifies the fixed private
`console-inspection.json` and complete immutable archive chain. Missing marker returns False; malformed,
foreign, link, changed chain/log or unsafe permissions raises fixed `FaultRetirementError` before any
writer is created. `ASE_CONSOLE_MODE=inspection` also permits explicit readonly startup. A marker always
forces inspection even if the environment says normal; no marker deletion/exit-inspection API is provided.

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
The stable full log is streamed through SHA-256; startup revalidates complete log bytes, not only stat.
Inspection start has a120s lifecycle publication window to allow bounded large archive validation.

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
| Archive log same-size edit, symlink, bad marker/receipt | refuse startup before writer creation |
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
binary against this state. Exiting inspection and safely continuing a retained demand needs a separate
reviewed engineering recovery; this change does not grant it.
