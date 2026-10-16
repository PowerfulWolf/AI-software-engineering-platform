# Work ownership

Author owns the explicit source/test allowlist; root owns this task and spec updates.
The fixed independent reviewer only reads/tests. Run isolated MySQL serially and coordinate
before use. Main checkout remains read-only for implementation; the maintenance checkout is
/tmp/ase-fix-legacy-ignored. No agent writes original K1 business code or verdicts.

Initial independent facts: native and parent checkpoints BLOCKED, actual Task IMPLEMENTING,
Run6 original stopped proof valid and current EMPTY_CONFIRMED; absent outcome/route/receipt;
original claim ACTIVE but expired. Original195 immutable records unchanged.

Implementation uses one shared read-only stopped-execution reader, a trusted backend context
manager holding the original Task flock, and a narrowly gated entry method. Reconcile finishes
before fresh proof collection. The checkpoint append happens before releasing the flock; normal
Worker reacquires it afterward. Existing Dispatcher performs expiry/reclaim and the immutable
invocation guard prevents a repeated main Coder. Same-base stopped rescue binding construction
preserves accepted progress without changing historical retirement readers or source rebind.

Production changes are limited to the six allowed source files. Tests extend the existing public
native/MySQL fixture and service-to-real-next-request progress cases. Full affected regression:
68 passed, plus the final unexpired-original parameter1 passed; independent review public7 and
history/progress10 passed. Static checks pass and the fixed reviewer reports no blocking issue.
