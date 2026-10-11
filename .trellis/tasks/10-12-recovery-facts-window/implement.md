# Implementation record

The standard modern FAILED path now owns the existing original Task Worker lock for
two synchronous complete observations. `NativeRecoveryFactsVerifier._inspect_window`
performs source, target and terminal reads twice; its last terminal read follows the
last source and target. `_RecoveryTargetPreflight` separates target preparation from
the remainder of the unchanged full target validation. The independent public terminal
wrapper still performs its original two source reads and final stop/capture/inventory.

`_TerminalWorkspaceWindow` enforces thread/async owner, open lifetime and exactly two
successful observations. It acquires no new global authority, creates no original Worker
lock and retains no authorization result. The lock exit still validates file and directory
identity. Every terminal read loads fresh stop/routes/invocation/consistent read-only SQL,
then verifies capture, actual owned process stop and complete inventory. Full facts and
inventory/ignored/tracked sets are compared, and both snapshots must match the Plan.

The optimization is selected only for the definition-time standard `_inspect`, a complete
Plan snapshot and no quarantine. Legacy/progress plans retain their independent wrapper;
instance/class/subclass stronger inspectors keep the original complete path. The fixed
standard Native validate reference remains compatible with the separate authorized-facts
builder optimization. No Schema, wire, approval, queue or SQL changes were introduced.

The real fixture demonstrates six source reads before the repair and two after it. Root
also verified the actual authorization service and Task builder together: four complete
Native inspections yield eight sources, and a stop removed after pure Task derivation
causes final rejection without publishing a Task or changing approval/Plan bytes. See
`verification.md` for commands, exact results, independent review and overlapping counts.

The repair is integrated and pushed on the isolated maintenance branch. Production still
uses the previous version while its original authorized K1 Operation runs. Deployment
requires genuine idle/controlled shutdown; neither this code nor its test fixture cancels
that Operation, changes its approved source, or counts as K1 delivery.
