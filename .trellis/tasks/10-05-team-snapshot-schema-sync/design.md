# Design

The runtime model already owns the correct read-side contract. Regenerate the entire published
TeamSnapshot schema from that model, recursively preserving the file's sorted JSON presentation
and retaining its current `$id`/`$schema` values. This adds the missing Task revision/intent fields,
RoleQueue disposition/hash fields and reachable DeliveryDisposition definitions; existing contracts
remain byte-for-byte stable apart from additions.

Validate complete generated parity and a real deterministic waiting-disposition payload. Test
nullable/omitted legacy fields and invalid shape/unknown properties at snapshot, Task, queue,
disposition and facts boundaries. Domain model validators still own semantic digest binding.
No model, runtime authority, persisted fact or business approval changes.
