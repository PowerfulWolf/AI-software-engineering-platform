# Project Switching During Refresh

## Goal

Project switching must work on the first accepted click even when a background poll is in flight.
Keep the selected Project, data and write authority consistent and make actual loading visible.

## Confirmed facts

- Actual localhost UI reproduced: ai-project → codex during a disabled Refresh button leaves
  ai-project selected even after that read and several later polls complete.
- `app.js:6504` returns immediately when `refreshing`; the picker at `app.js:4657` shares this
  function with five-second polling (`app.js:6626`). No pending selection is stored.
- Direct codex GET returns the correct `selected_project_id`, but took 7.4–8.0s in the diagnosis.
  Latency enlarges the race window; it is not an excuse to discard the user's intent.
- User-requested prior changes were committed/pushed first as 321f15e; this task starts clean.

## Requirements / acceptance criteria

1. A click during an in-flight poll is retained and read immediately after that bounded read settles,
   without requiring another click or waiting for the next interval.
2. Rapid A→B→C selections converge to C. Polling does not override the latest explicit target;
   obsolete responses cannot publish a different Project. Selecting A again can cancel queued B.
3. At most one refresh pipeline runs at a time, preserving global Console/Operations readiness
   semantics. Explicit manual status refresh is retained; timer ticks do not create an unbounded queue.
4. While switching, show the destination and explain that current data is still the prior Project.
   Do not label old data as new. Disable delivery commands against stale visible Project data.
5. Read failure/timeout releases the refresh lane, preserves old data with clear failure feedback,
   and allows retry of the intended Project. Wrong-project responses are rejected. Draft/command
   guards continue to refuse navigation when closing the current composer is not permitted.
6. Cover held promises, rapid selection, old failure, target failure/retry, manual refresh, and
   composer rejection in deterministic shipped-JS regressions; verify the actual localhost UI.

## Boundaries

No backend cache redesign, API/Schema changes, model calls, approvals, delivery resumes or data
migration. Do not rewrite business state. Keep the new fix separate from the prior published commit.
Use normal read-only browser actions for live validation. The slower API remains a separate
performance consideration; this task corrects lost navigation and misleading feedback.
