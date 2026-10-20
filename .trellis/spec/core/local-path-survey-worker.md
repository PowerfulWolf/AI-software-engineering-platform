# Bounded local path survey worker

## 1. Scope and trigger

Production baseline recovery now uses the complete isolated observer described in
[isolated-local-execution-survey.md](isolated-local-execution-survey.md). Its owned interpreter
calls this module's pure complete lsof parser directly. The standalone captured-lsof worker
retains the narrow contract below and gains no process-query capability.

Apply when changing the macOS cwd/open-file interpretation used by
`TrustedLegacyLocalExecutionObserver`. Under competing Python work in the Host, a real
profile remained in `_mac_paths → Path.resolve`; complete lsof path processing on the Host's
Python thread could exhaust the existing survey budget. Move that parsing work into an
owned fixed child process so it has its own interpreter. Do not increase deadlines, skip
paths, infer idle from an error, or weaken recovery admission.

This is a private transient execution protocol, not a persisted artifact or public Schema.
`LegacyLocalExecutionSurvey`, its canonical digest, `scanner_version=local-execution-v1`,
the five existing blocker values, historical UNKNOWN and exact engineering authority remain
unchanged. Read this with [legacy-execution-rescue.md](legacy-execution-rescue.md),
[knowledge-preparation-isolation.md](knowledge-preparation-isolation.md) and
[owned-session-stop.md](owned-session-stop.md).

## 2. Signatures and fixed launch boundary

```python
inspect_mac_paths(
    body: bytes, root: Path, ignored_pids: frozenset[int],
    cwd_blocker_pids: frozenset[int], deadline: float,
) -> tuple[set[int], set[Literal["WORKTREE_PROCESS_ACTIVE"]]]

observe_mac_paths_in_process(
    body: bytes, root: Path, ignored_pids: frozenset[int],
    cwd_blocker_pids: frozenset[int], deadline: float,
) -> tuple[set[int], set[Literal["WORKTREE_PROCESS_ACTIVE"]]]

MacPathObservationRequest.create(body, root, ignored_pids, cwd_blocker_pids, deadline)
MacPathObservationRequest.encode() -> bytes
MacPathObservationRequest.decode(raw: bytes) -> MacPathObservationRequest
MacPathObservationResult.encode() -> bytes
MacPathObservationResult.decode(raw: bytes) -> MacPathObservationResult
```

`manager/local_path_observation.py` owns the typed protocol and parent launch adapter;
`manager/local_path_worker.py` owns the fixed stdin/stdout entry. The worker receives only
already captured lsof bytes and their exact interpretation inputs. It does not collect a
new process inventory, execute ps/lsof, launch subprocesses, read process environments,
signal discovered PIDs or decide recovery authority. It still resolves filesystem aliases
when interpreting paths; isolation must not replace resolution with lexical matching.

The trusted parent uses `spawn_owned_query` with exactly:

```python
argv = (sys.executable, "-I", "-S", "-B", fixed_local_path_worker_file)
cwd = Path("/")
environment = {"PATH": "/usr/bin:/bin:/usr/sbin:/sbin", "LANG": "C", "LC_ALL": "C"}
```

No root, PID list, lsof body, shell command or import path goes into argv. The worker starts
without environment/user/site imports. It directly adds only its fixed checkout source and
the selected interpreter's `lib/pythonX.Y/site-packages` to the isolated standard-library
search path. Do not call `site.main`, `site.addsitedir` or process `.pth`/`sitecustomize` code.
Import roots cannot come from survey input, `PYTHONPATH`, caller cwd or discovered processes.

## 3. Protocol, coverage and lifecycle contracts

- Request protocol is exactly `ase-mac-path-request-v1`. The canonical ASCII JSON digest
  covers protocol, complete UTF-8 lsof body, absolute root, sorted unique ignored/cwd-blocker
  PID sets and the original finite monotonic deadline; exclude only `request_sha256` itself.
  The parent encodes and the worker independently decodes/recomputes that SHA-256.
- Result protocol is exactly `ase-mac-path-result-v1`. The worker echoes the request SHA and
  returns sorted unique `covered_pids` plus at most the existing
  `WORKTREE_PROCESS_ACTIVE` blocker. The parent decodes the complete result and checks its
  SHA reference before returning any coverage. No raw process data enters durable surveys.
- All fields, including protocol tags, must be present. Unknown/duplicate keys, invalid UTF-8,
  trailing garbage, nonfinite constants, wrong protocol/hash, bool or negative PID values,
  duplicate PID coverage and unknown blockers reject. A typed parsing exception is not idle.
- Fixed bounds: lsof body **8 MiB**; encoded request **64 MiB**; result **256 KiB**;
  processes **4096**; file descriptors **65536**. Reject before returning partial coverage.
- The original lsof NUL terminator and `p/f/t/n` interpretation remain mandatory. Missing
  PID/descriptor, malformed cwd/type, unknown field or `(stat:`/`(readlink:` uncertainty
  rejects. Preserve all observed coverage and the caller's existing cwd-vs-file policy.
- Resolve every applicable absolute observed path with `Path.resolve(strict=False)`, including
  aliases such as `/var` and `/private/var` and the existing ` (deleted)` suffix convention.
  Do not use lexical root prefixes to skip resolution; a differently named alias can point
  into the retained tree. Similarly named neighboring directories do not match the root.
- The survey still sets one absolute `started + 5.0s` deadline. Every OS query keeps its
  existing `min(1.5s, remaining)` budget. The parser receives the same absolute deadline;
  serialization, spawn, waiting and decode do not create a new 5-second window. Check the
  deadline between fields, before/after each resolve and before accepting the complete result.
- Parent stdin/stdout/stderr are private temporary files. Accept only exit code zero, empty
  stderr, complete bounded typed output, exact request SHA and unexpired deadline. No partial
  output, exception text, PID, argv, environment or path body is logged or returned on failure.
- Always call `finish_owned_process` on the exact startup ownership observation, including
  timeout/error paths, with file output drained. Missing ownership or uncertain finalization
  refuses the survey. Cleanup uses the existing bounded owned-session lifecycle; reaching a
  deadline does not authorize abandoning an unconfirmed child or declaring it stopped.
- `LocalPathObservationError` contains only the fixed summary; the observer maps parser or
  child uncertainty into its existing incomplete-survey path. Nothing signals a PID merely
  because lsof discovered it. No new PID, process-name or ancestry exemption is introduced.
- Knowledge isolation fails immediately after the first non-idle observation. Its successful
  path still collects **repository, repository, worktree, worktree**, then validates the same
  machine/boot/account/scanner boundary. A fresh current check uses the same four surveys.

## 4. Validation and error matrix

| Input or observation | Required result |
|---|---|
| Complete captured body, matching request/result, owned child finalized within accepted budget | Return complete coverage and existing blockers |
| Symlink alias or deleted open-file reference inside retained root | Preserve `WORKTREE_PROCESS_ACTIVE` |
| Idle terminal cwd policy or existing ignored PID set | Preserve current classification; do not add exemptions |
| Invalid field, truncation, unreadable-path marker, UTF-8 failure or fixed bound exceeded | Incomplete survey; no idle result |
| Stale/missing/changed request field or digest, duplicate/extra result key, unknown blocker | Reject complete child result |
| Expired/nonfinite deadline before spawn | Do not start the child |
| Timeout during resolve, startup, wait, output validation or acceptance | Reject; finalize exact owned child |
| Child stderr/nonzero exit, uncertain stop or missing ownership | Incomplete survey with safe fixed error |
| First repository/worktree survey non-idle | Stop collecting further surveys; keep original wait |
| All four surveys idle | Preserve exact four-observation proof and independent engineering authorization |

## 5. Good, base and bad cases

- Good: under competing Host Python work, the fixed owned interpreter parses the complete
  captured lsof stream, resolves aliases, returns a matching bounded result and finalizes its
  ownership before the original deadline. Four successful current surveys still precede recovery.
- Base: an alias points to the retained worktree and yields the same active-process blocker
  as before; the worker's performance does not convert an active process into an idle fact.
- Bad: run new process queries in the worker, inherit site startup code or secrets, restart the
  deadline, omit expensive aliases, ignore worker failure, exempt an entire maintenance process
  tree, or treat a current idle survey as historical stop/no-start evidence.

## 6. Tests and evidence

- `tests/manager/test_local_path_observation.py`: exact argv/cwd/env; full digest-bound protocol;
  request/result limits, duplicates/types/hash/truncation; deadlines between fields and around
  resolve; alias/deleted paths; owned finalization on failures; real small worker; no execution
  of planted `.pth` or `sitecustomize` code.
- `tests/manager/test_legacy_local_execution.py`: production seam uses the real owned worker
  with the original deadline; failure stays incomplete; existing native/kernel identity,
  desktop attribution, actual worktree access, account/inventory drift and safe warnings remain.
- `tests/manager/test_knowledge_isolation.py`: each first-failure position short-circuits;
  success still performs four surveys; original exact proof/claim/context/history and ordinary
  budget invariants remain.
- Real performance observations are aggregate measurements, not K1 QA/Review. Keep only
  root kind, duration, blocker list, survey SHA and probe completion in task evidence. Do not
  persist raw lsof, discovered PIDs/argv/environment or cwd/open-file lists.

## 7. Existing data and rollback

No persisted/public Schema, scanner-version or SQL migration is required. Existing survey and
proof digests remain readable; the fixed parser supplies fresh current observations through
the same observer. Recover an existing Requirement only through its original exact-plan
public PAUSE and separate RESUME, with all original immutable history and dirty progress
preserved. Do not edit SQL, old stop/outcome, budget, approvals or the K1 worktree.

Deploy or roll back only via official controlled stop, proven predecessor exit, code update
and restart. Preserve original wait/history and any already written authority/binding. If a
current process or incomplete observation still blocks, retain the wait; performance success
alone supplies no authority to resume or bypass independent candidate QA/Review.
