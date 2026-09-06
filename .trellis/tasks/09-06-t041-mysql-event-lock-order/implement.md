# Cause, fix and verification

Cross-layer/concurrency assumption: two missing event IDs acquired gap locks before contending
for the same Task. Adjacent UUID-prefixed IDs reproduce MySQL error 1213 in 10/10 rounds.
Locking the Task first removes this same-Task cycle. Keep idempotency lookup before reporting
TaskNotFound, preserving changed-event conflict precedence. No retry/error-to-success conversion.

- Red: 10 failed / 0.65s, exact numeric underlying error 1213.
- Green: full repository suite 19 passed / 0.66s, including 10 competing-connection rounds.
- Combined full MySQL suite with T040: 759 passed / 61.94s.
- Ruff/Mypy/build/diff checks passed. Production spec records required lock order.

Original random IDs often occupied different gaps, hiding the race in isolated tests. Prevention:
keep adjacent IDs and check exactly one event/revision plus one InvalidStateEvent, not merely
one successful write. Other independent-task contention may still return infrastructure errors;
this repair does not claim universal deadlock freedom.
