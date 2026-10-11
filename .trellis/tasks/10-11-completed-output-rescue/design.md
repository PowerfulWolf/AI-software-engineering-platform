# Minimal contract design

`BaselineProposeCommand.target_base_ref` becomes an absent optional field only for
purpose `completed_output_rescue`; validators require absent target and
`preserve_draft` for that purpose and a full target for every existing purpose.
`ProductionBaselineFactCollector.collect(None)` is permitted only for this purpose:
it resolves `source.execution_base_ref` under its current execution scope and
validates the bound public identity before sealing facts. Service then derives
the same base from the verified previous binding/Task and rechecks all facts.

The purpose is separate from ordinary SOURCE_REBIND. Its Plan requires exact
completed proof, no legacy containment, native-rule change or accepted implementation,
same target execution base, unchanged original source revision, unchanged complete
dirty patch and nonconflicted preserve mode. It performs the existing complete
workspace checks. Execution verifies the preserved workspace without rebase/reset.

Binding includes optional `completed_output_sha256` only for the new purpose.
The binding validator requires same base/source, preserve mode, engineering human
authority and PAUSE. Store reopening checks the exact proof and saved authority.
Execution never changes old outcome/output facts; existing reservation charges the
next ordinary work attempt and existing PAUSE/RESUME creates/releases the successor.

The UI uses a separately matched proof/purpose plan. Before preparation it offers
an always-visible target-free prepare action for an eligible waiting Coder. The
backend alone establishes proof eligibility. Current plans explain stopped native
execution separately from unknown report content, show the normal work cost, and
offer exact PAUSE approval. Technical source-rebind controls remain separate.

Active RESUME copy requires exact current intent binding, then states the platform
is preparing continuation and main role execution has not started. Unmatched
operations never establish execution state. Actual queue RUNNING remains authoritative.
Task navigation only follows a current scoped owning requirement from the snapshot.
