# Project Navigation During Background Refresh

## 1. Scope / Trigger

Applies to `team_view/app.js` Project pickers, Knowledge Project tabs, manual refresh and completion-based
polling. Navigation is an explicit user intent; polling is a replaceable read. Both share one refresh
pipeline, but must not share a busy-means-discard policy. See [web-console.md](web-console.md) for
delivery readiness and [live-team-view.md](live-team-view.md) for read-only Project isolation.

## 2. Signatures

```javascript
refresh(projectId, includeRuntimeStatus = false) // Promise<void>; undefined target means poll/refresh
refreshSnapshot(target, includeRuntimeStatus)    // one bounded snapshot/system read
scheduleTeamRefresh()                          // one delayed automatic Team observation
pollTeamSnapshot()                             // consumes that timer and enters refresh
recordTeamReadOutcome(issue)                    // success resets, busy/timeout backs off
currentProjectId()                              // authoritative snapshot identity, never intent
projectSwitchPending()                          // requestedProjectId differs from currentProjectId()
```

HTTP remains `GET /api/v1/team?project_id=<encoded-id>`. No API, Schema, environment or database change.

## 3. Contracts

- `requestedProjectId` retains the latest accepted explicit target; timer calls never overwrite it.
  `refreshFlight` shares one promise. Explicit queued requests are drained immediately after the
  current read settles; ticks during a read are coalesced, not appended to a queue.
- Automatic Team polling waits five seconds after the complete serial refresh owner settles,
  including independent auxiliary branches and any explicit latest-intent drains. There is one
  pending timer and no fixed-clock catch-up read. Starting a manual/navigation refresh cancels
  that timer; completion schedules exactly one new timer. Consecutive current Team busy/timeout
  observations delay automatic retries by 10, 20, then at most 30 seconds. A validated Team
  publication resets five seconds; an auxiliary Operations/Knowledge failure cannot back off a
  successful Team observation. This is scheduling metadata, never a snapshot or authority cache.
- Manual refresh and explicit Project navigation bypass the automatic delay. Do not postpone the
  current owner's latest-intent drain, replace a user click with a timer, or abort shared reads.
  The independent recovery-preparation lane remains on its existing five-second timer.
- A→B→C converges to C. Selecting the active read's A cancels queued B. Explicit runtime-status
  requests survive Project selection/coalescing; unchanged polling does not request expensive status.
- Validate `schema_version`, snapshot collections and exact `selected_project_id === target` before
  publishing. Check intent again after awaiting the response body. A superseded read cannot relabel
  the visible data or overwrite failure/progress feedback for the latest target.
- Keep shared Console/Operations reads serial. Do not cancel them just to speed navigation: their
  failure handlers update global readiness, so cancellation would falsely revoke availability.
- Snapshot identity and its rendered Project scope must change together. On the Knowledge page,
  render the accepted Project with a loading view before awaiting its administration/knowledge read.
  Never show the old Project's assets under the new identity. Existing knowledge context/serial
  fencing still applies. If another click arrives after publication, finish rendering the already
  accepted Project while explicitly showing the newer destination as pending.
- While intent differs from the accepted snapshot, `canControlCurrentTeam()` is false and existing
  delivery controls are disabled in place. The current Project is not optimistically renamed.
- Preserve `mayCloseComposer()` guards. Busy commands and rejected draft-discard confirmations must
  not change intent, trigger a Project read or destroy the composer.
- A failed target remains the retry target. Clear it only when accepted, or replace it on a later
  explicit selection. `finally` releases timeout/read state and restores the refresh button.

## 4. Validation & Error Matrix

| Condition | Required result |
|---|---|
| Click B while A poll is in flight | Show destination immediately; retain A data; drain B once A settles |
| B then C while A is held | Skip queued B, request C; ticks do not add reads |
| B then A while A is held | Keep A; do not read discarded B |
| Old body resolves/fails after newer selection | No old snapshot publication or misleading old error |
| Target network failure / wrong Project response | Preserve accepted data; show switch failure; refresh retries target |
| Old read times out | Release lane and attempt latest explicit target; automatic retries back off |
| Read lasts eight seconds | No catch-up GET; next automatic Team read begins five seconds after completion |
| Consecutive busy/timeout, then success | Automatic delay 10→20→30 seconds, bounded; success restores five seconds |
| Manual refresh/navigation during automatic delay | Start immediately, preserve latest target and exact controls |
| Slow Team or automatic backoff | Recovery preparation continues independently; no extra Team GET |
| Knowledge slow after B accepted, then C fails | Visible B identity/assets remain coherent; failure names C |
| Dirty or busy composer rejects navigation | No read, intent mutation or lost draft |

## 5. Good / Base / Bad Cases

- Good: hold an A poll, click B once, release A; B becomes current without another click or timer.
- Base: slow B continues displaying A with a destination/loading message and disabled delivery actions.
- Bad: return early for all requests when busy; label A's data as B before a validated response; let
  Knowledge's internal Project change while its selector still displays A; abort global readiness
  reads as if they were target-only reads.

## 6. Tests Required

`node --test tests/team_view/*.test.cjs` executes the shipped JS with fake HTTP, DOM and timers.
`readiness.test.cjs` must cover held-poll picker clicks, latest intent after success/failure,
cancellation, late response bodies, wrong Project/network failure and retry, timeout, runtime-status
coalescing, Knowledge loading/failure identity, and dirty/busy composers. Assert actual selected
Project, outgoing GET targets/counts, progress text and delivery gate—not just handler invocation.
`browser/polling-scheduler.test.cjs` uses the shipped script and Chrome's controlled clock to assert
actual GET counts across an eight-second held read, busy retries, retained drafts and independent
preparation GETs. Other browser fixtures disable only the automatic Team callback and intervals;
read deadlines and ordinary UI timers still execute. Deterministic fake timer fixtures must distinguish
Team polling from configuration-success timers with the same delay. Also verify a real localhost
click while Refresh is disabled and the Knowledge Project selected tab.

## 7. Wrong vs Correct

```javascript
// Wrong: a polling optimization discards user navigation.
if (refreshing) return;

// Correct: remember explicit intent before coalescing; the serial owner drains it.
if (projectId) requestedProjectId = projectId;
if (refreshFlight) return refreshFlight;
// The refresh owner performs the latest queued target after the current read settles.
```

Root cause: an implicit assumption that refresh reads finish between clicks, plus tests without
overlapping navigation/polling. API latency exposed the bug but was not the navigation defect.
