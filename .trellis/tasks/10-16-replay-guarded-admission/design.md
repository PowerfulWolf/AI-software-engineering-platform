# Exact incoming-admission exception

Keep the current no-start scanner and PriorInvocationFence entry point. A complete fence with
capture-start/stop may recognize only the native admission for its original request's Run.
Require equality of scanned and canonical admission, exact new_request to the prior invocation
and capture request, exact next WorkItem/lease to the original capture claim, and a different
current guard lease. Validate the original receipt's digest/scope/policy/continuation inputs
and original parent WorkItem using existing typed store/read validators. No caller-supplied
claim or natural-language assertion expands this boundary.

Admission is published after immutable invocation-start and before capture-start. Verify the
actual ordered timeline:
prior.claimed_at <= invocation.started_at <= admission.created_at <= capture.started_at
< current.claimed_at. Do not incorrectly require admission before invocation-start.
The record must not be an outgoing admission from the proven old Run or a native fact for the
current marker. Other receipts/admissions keep their original conflict checks.

The existing Task/queue fence, no route/outcome/raw artifact checks, full inventory checks,
final-consumption callback, separate PAUSE/RESUME and ordinary work charge remain unchanged.

| Input | Expected result |
| --- | --- |
| Exact original incoming admission + full prior fence + complete receipt/claim chronology | May prove only current guard claim did not call main Coder |
| Missing/incomplete fence or incoming receipt | Refuse |
| Wrong request/context/source/work/lease/digest/scope/parent or alias | Refuse |
| Late admission or current/outgoing admission | Refuse |
| Route/outcome/native execution/receipt for current guard claim | Existing refusal |
| Real public repeated recovery with history | Exact proposal, PAUSE/RESUME, honest old history and independent delivery |
