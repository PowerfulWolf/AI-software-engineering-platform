# Implementation

The Request detail reader selects only native work that can contribute to the selected
Request after validating every joint/native ownership edge. Both independent observations
use this selection. Current SQL Task, engineering and verification reads remain fresh in
both; full, summary and Task detail keep their previous behavior.

Verification reservation envelopes, release/order/source/repository checks run before any
historical body is omitted. There is no authority cache, read-gate change, persistent model
change or data migration. Existing raw records and K1 execution workspaces remain untouched.

## Follow-up — 2026-10-19

Added explicit `_DetailJournalReads` ownership for one synchronous detail call. Its two
independent snapshots share only the existing exact-byte Journal decoder; `finally` clears
the one owned Journal and drops the reference. The ordinary decoder/chain loop is unchanged,
and all public returns retain deep copies. The private snapshot signature's two test wrappers
now forward the owner rather than accidentally creating independent replacement decoders.

`JointJournal.clear_verified_reads()` avoids filesystem work during cleanup. `history()`
clears completed traceback frame locals on failure so the warmed generator and tuple
genexpr cannot retain private cached models through a caller-retained error. This is not
an exception suppression, validation bypass or successful-result cache. Original exception
types, args and traceback positions remain available.
