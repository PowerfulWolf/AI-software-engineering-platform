# Selected Request detail projection

## Existing dependency split

`ProductionTeamReader.detail(query)` deliberately performs two independent
`_read_snapshot` observations. The first returns the complete selected body; the
second recomputes its exact source after the body. Both independently discover the
Team/Project, verify retirement records, fully read every selected Project joint
journal and native checkpoint chain, check manifest identities and validate all
historical joint-to-native ownership edges. Those checks remain unchanged.

For Request bodies, current execution is derived only from current native scope
members and their verification descendants. Historical native members are currently
expensively hydrated and then discarded by `_current_requirement_work`; unrelated
Requirements are also hydrated. No such discarded Task contributes to the selected
Request's documents, dialogue, execution or source.

For Request source fences, `_request_detail_source` binds the verified real owner
checkpoint. Preserve the full independent current Task/engineering/verification SQL
observation nevertheless; a publication must still reject invalid current authority.
Apply the same current-native selection separately in each observation.

## Signatures and implementation

- Keep `ProductionTeamReader.detail` and `_read_snapshot` signatures unchanged.
- Compute an optional finite set of selected current native delivery IDs from real
  ownership plus current verified joint scopes. Never trust the query's `request_id`
  to establish ownership; standalone native owners must have no joint owner.
- Request body and source assembly skip only native IDs outside that set. Each
  independently opens its SQL snapshot and validates current Task/engineering/
  verification facts. Full/summary/Task detail retain their prior behavior.
- `_read_verifications(..., selected_source_delivery_ids: frozenset[str] | None)`
  continues to read and type-check all reservation envelopes, release consistency,
  order, registered source and repository identity, then omits full projections
  whose real native source cannot contribute to this Request.

No cached permission, successful model, current SQL fact or prior source observation
crosses the two snapshots. No new persistent model, schema or public capability.

## Validation matrix

| Case | Required result |
| --- | --- |
| Current + historical native children | Identical complete Request resource; only current native Task facts assembled |
| Another visible Requirement | Ownership/journal fully checked; its Task body is not assembled |
| Final Request source observation | Independently fresh current Task/SQL/engineering/verification and actual owner/checkpoint comparison |
| Changed checkpoint, retirement, manifest, native bytes or journal ancestor after body | Existing stale/not-found/integrity rejection |
| Corrupt foreign journal/native chain or ambiguous historical ownership | Reject before selecting body/source |
| Current Task engineering authority/receipt changes or corruption | Original real Task reader and validation still run for body and final source |
| Current verification, old verification, missing reservation source | Current verification retained; historical projection omitted only after source/repository checks; missing source still rejected |
| Full/summary/Task detail | Complete prior behavior and Task detail history retained |

Use real temporary stores and count actual `_read_task_details` or snapshot assembly
calls with only SQL fixture isolation. No portable elapsed-time threshold; production
read-only measurement is separate. Every durable temporary fixture byte remains
unchanged by the reader. No production writes, database reset or service operation.

## Existing data and rollback

No migration or K1 recreation is necessary. Root owns controlled deployment and real
read-only measurement. Revert this selective read assembly while idle to restore the
prior repeated projection cost without changing durable data or execution authority.
