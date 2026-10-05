# Design

Use two separate read-side facts. Permanent membership comes from every validated parent journal
record; current scopes come only from its latest children or a latest unattached plan projection.

`_joint_scopes` owns native ID derivation and exact committed-child validation. For each historical
or current child it checks known unit, code/reference scope, repository root and the exact native
checkpoint as a prefix of the fully validated stored native chain. Missing, replaced/future or
cross-scope observations fail closed. A native store is read before membership resolution, including
retired parents, so hiding retired work cannot conceal conflicting ownership.

`_native_requirement_ownership` folds those observations into immutable typed owner values. Repeated
observations must keep the same parent, unit and scope. Title and next-action text never establish
membership. Unattached planned identities can establish ownership before native publication; an
attached child retains its already committed identity through replanning.

Historical TaskView status, blocker, assignments, role queue, documents and timestamps remain audit
facts; only their parent request ID/scope membership is corrected. `_current_requirement_work`
excludes old native IDs, also through verification/remediation `source_delivery_id`, before live
parent state composition. `_agent_views` receives the resulting historical work IDs so they remain
history but cannot be assigned/current work. Frontend current helpers must likewise filter against
latest Request scopes while preserving the full history query.

No persisted model, Schema, mutation service or authorization changes. No user action needs to
re-create or delete the Requirement; refreshing the fixed reader uses the existing lineage.
