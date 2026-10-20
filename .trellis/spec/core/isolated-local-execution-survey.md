# Isolated complete local execution survey

## 1. Trigger and scope

Use this contract for production current-account legacy recovery investigation. Read it with
legacy-execution-rescue.md, owned-session-stop.md, knowledge-preparation-isolation.md and
local-path-survey-worker.md. Multiple short owned-query lifecycles on the Host Python
interpreter still exhausted the original deadline under three competing CPU threads, after
native identities and captured arguments had each been isolated. Do not solve this failure
by enlarging the deadline, omitting aliases or accepting partial inventory.

`LocalBootObservation`, `LegacyLocalExecutionSurvey`, scanner local-execution-v1, the existing
five blocker values and all public/persisted schemas stay unchanged. These facts describe
the current boundary only; no historical UNKNOWN becomes a proved old stop or no-start.

## 2. Production interface and private protocol

```python
# manager/local_survey_observation.py
IsolatedLegacyLocalExecutionObserver.observe(
    *, worktree_root: Path, boot: LocalBootObservation
) -> LegacyLocalExecutionSurvey

LocalSurveyRequest.create(...) -> LocalSurveyRequest
LocalSurveyRequest.encode() -> bytes
LocalSurveyRequest.decode(raw: bytes) -> LocalSurveyRequest
LocalSurveyResult.encode() -> bytes
LocalSurveyResult.decode(raw: bytes) -> LocalSurveyResult

# manager/legacy_local_execution.py: complete testable engine
TrustedLegacyLocalExecutionObserver._observe_with_deadline(
    *, worktree_root: Path, boot: LocalBootObservation,
    started: float, deadline: float, observer_pid: int
) -> LegacyLocalExecutionSurvey
```

The production baseline composition defaults to the isolated facade. Explicit injected fake
observers remain supported; production must not choose an in-process fallback after a child
error or infer a fixture using type(self). The original complete engine is reused by the fixed
worker with pure native/path/argument inspectors, preserving the same domain algorithm.

Request protocol `ase-local-survey-request-v1` binds canonical absolute root, original boot,
strict account UID, actual parent native boot identity and OwnedProcessIdentity, original
finite monotonic started/deadline, and canonical request SHA. Every field is mandatory. The
facade obtains parent identity only from actual os.getpid(); no public caller PID is accepted.
The original deadline remains exactly started + 5.0 seconds. Inputs and outputs are bounded
to 64 KiB each. Reject duplicate, extra or missing keys, bool integers, malformed identity,
nonfinite times, truncation, trailing data, changed root/deadline or wrong SHA.

Result protocol `ase-local-survey-result-v1` binds request SHA, the actual owned worker PID,
complete typed survey and an optional phase from a fixed internal enum. No discovered PID,
argv, environment, raw native response or inventory leaves the worker. Worker PID is only a
private correlation to the exact Popen and never appears in the durable survey. Parent checks
complete survey integrity and exact root/machine/boot/account/scanner before acceptance.

## 3. Launch, identity and complete survey order

The facade starts exactly one fixed manager/local_survey_worker.py via spawn_owned_query:
selected sys.executable, -I -S -B, cwd /, PATH=/usr/bin:/bin:/usr/sbin:/sbin, LANG=C, LC_ALL=C.
Use private stdin/stdout/stderr files and no shell. The worker adds only its own fixed source
root and selected interpreter dependency directory, without site.main, addsitedir, .pth or
sitecustomize execution. No input controls imports, executable, cwd or environment.

The actual outer worker has PID=PGID=SID and is captured before release by the existing owned
launch gate. It validates getppid against the exact parent, real/effective UID equality and
the parent's fresh native boot/birth identity before, after and at final identity validation.
Reuse owned_sessions.observe_current_process, including its fresh native boot checks. PID
reuse, changed parent/boot/UID, unknown birth or reparenting refuses the complete result.

Preserve the complete order: before ps/native inventory; desktop chain/native path/full argv
attribution; full lsof/path coverage; after ps/native inventory and desktop attribution;
supplemental file coverage for new or changed processes; then independent final native birth
validation. No after observation may stand in for final. Preserve changed-PPID/exec/PID,
account/state uncertainty, high-resolution birth and relative/missing/alias path treatment.

Only the exact actual parent observer and worker receive the original open-file self
exclusion. Their argv remains classified. Never exempt an ancestor, sibling, descendant,
whole session, process-name match or supplied/discovered PID. Other processes' real file
descriptors continue to block recovery, including desktop/control processes.

## 4. Fixed queries and complete owned cleanup

The full worker has a private fixed OS-query port. It accepts only the engine's exact ps
current-UID inventory or exact lsof current-UID full/strict PID subset query. It runs actual
Popen with shell=False, cwd=/ and the same three-value environment. Query processes inherit
the already captured outer SID; they may not call setsid, start a new session, daemonize or
execute request/discovered argv. This is not a role Agent tool or a generic command port.

Each query retains min(1.5s, original remaining). A timeout cleans only its actual Popen,
never a discovered PID. Local tool exit is not an outer stop proof. On all result/error paths
the parent calls finish_owned_process on the exact initial ownership observation and must
prove the entire original SID empty, including any query still present after leader exit.
An uncertain stop remains incomplete; no accepted idle result precedes this proof.

One absolute five-second window covers serialization, isolated import/startup, all child
work, complete result decoding, owned cleanup and final acceptance. No phase restarts it.
Cleanup may take the existing bounded time to establish safety after failure; elapsed cleanup
past the original deadline refuses success. Nonzero child exit, stderr, malformed output or
LocalSurveyObservationError maps to the existing incomplete survey, with fixed safe phase
logging only. Never return raw validation or OS exception text.

## 5. Validation matrix and required tests

| Case | Required behavior |
|---|---|
| Complete exact result, original deadline, whole outer SID proved empty | Accept complete survey with existing blockers |
| Active process or alias/deleted-file reference in target | Preserve active blocker; isolation grants no recovery authority |
| Wrong request SHA, actual worker PID, root, boot, account or scanner | Refuse complete child result |
| Missing/extra/duplicate field, nonfinite clock, incomplete response | Incomplete; no partial inventory accepted |
| Parent PID/getppid/UID/boot/birth drift | Refuse original self exclusion and complete survey |
| Sibling/descendant reads retained files or execution argv is active | Block using unchanged original classification |
| Query timeout, unknown stop, still-live query after leader exit | Finalize exact outer SID; uncertainty stays incomplete |
| Success-shaped output but cleanup crosses original deadline | Refuse success after cleanup |
| Worker startup error or unsupported platform | Fixed safe incomplete; never in-process fallback |

Good: under three competing Host CPU threads, one isolated complete observer preserves all
phases and is accepted inside the original five seconds after owned cleanup. Base: an actual
worktree user remains a blocker. Bad: reuse stale final birth, nominate another parent PID,
ignore a process tree, open a second query SID, inherit secrets or relax the original deadline.

Focused tests must cover protocol/identity/deadline/whole-SID cleanup, fixed launch/query
tokens and no-site startup, production default wiring, engine phase order and unchanged
knowledge-isolation repository/repository/worktree/worktree collection. Real measurements
retain only root kind, durations, blocker list, survey SHA and all-probes-exited. Test/profile
results are not native K1 QA/Review or proof of candidate completion.

## 6. Existing data, deployment and rollback

No SQL or schema migration is required. Preserve the exact original Task, source, worktree,
complete patches/checkpoints, sealed continuation authorization and all failed Operations.
After official controlled stop/actual exit/update/start, retry the original public RESUME with
unchanged complete intent/reference and a fresh operation key. Do not reset attempts, edit
old outcomes, fabricate stop facts or replace candidate QA/Review. If fresh facts still block,
keep the exact wait. Rollback uses the same official controlled exit before reverting code.

## 7. Native disappearance is fresh, never stale errno

The reused engine's `_darwin_info(pid)` clears ctypes errno immediately before the fixed
proc_pidinfo call. Only a zero count and that call's fresh ESRCH can mean the PID is currently
gone. Require the complete 136-byte response, embedded PID equal to the requested PID and
effective UID equal to the observer's current account. A stale ESRCH from a prior call, short
response, permission failure or wrong PID/UID stays incomplete. Before/after/final sampling
remains independent. Regressions must exercise stale and fresh ESRCH plus wrong PID and UID.
