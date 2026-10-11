# Bounded Operation summary reading and exact full approval

## Scope and signatures

Applies to `team_view/app.js`. The server declares
`operation_summary_contract_version="v0.1"` in `/api/v1/console`. Old servers keep
the original complete `/api/v1/operations` compatibility path. New servers use:

```javascript
readOperationSummaryPage(projectId, deliveryId, {signal, cursor, publish})
verifiedOperationSummaryPage(value, projectId, deliveryId)
operationReadingRecords()       // reading projections + digest-matching loaded details
loadCurrentOperationDetails(signal)
readFullOperation(source, {signal, fresh})
recheckOperationWriteFacts(intent)
operationHistoryPage(projectId, deliveryId)
loadMoreOperationHistory(projectId, deliveryId, signal)
renderSummaryOperationHistory(panel, projectId, deliveryId)
```

## Wire and lifetime contracts

- GET `/api/v1/operation-summaries?project_id=P&delivery_id=D&page_size=25&cursor=C`
  requires the exact v0.1/team/scope, SHA identities, finite arrays, known statuses,
  bounded text, `has_details=true` and `active_complete=true`. Reject a summary
  containing `intent/result/patch/approval/execution_baseline_plan`. At most 50
  items, 64 active records and 256 KiB per page. A delivery filter requires its
  Project; cursor/ETag always belong to the same Team/scope. 304 without a prior
  same-scope verified page cannot restore control.
- Summaries contain only reading metadata and source locators. They never become
  a fake full Operation, original intent, proof, plan, READY decision or approval.
  `operations` holds only actual full current control-source records. General
  scope/action/target reading uses accessors, and full engineering predicates keep
  their existing typed complete facts and exact binding semantics.
- Page caches hold at most three scope pages; history holds at most two scopes,
  one current page plus four previous pages each. Explicit Next/Previous/Return
  latest lets every older page be reached without retaining the complete journal.
  Paging changes the render signature; expanded stable records preserve their DOM.
  The finite Previous buffer can be exhausted; Return latest lets the user start
  again. No fixed eight-row history limit or silent threshold replacement.
- Inventory change marks already-read history as old and stops its cursor. A stale
  cursor never merges pages from different inventories. Preserve the old page for
  reading and give an explicit Return latest control. An initial empty history
  placeholder is filled after its first scoped page completes.
- Full detail cache has at most eight records / 32 MiB serialized UTF-8 total;
  one record is at most 16 MiB. Every eviction also updates `operations`, and if
  any current control source is missing its exact digest the ready reading gate
  becomes unavailable. Count/bytes are shared across current and historical reads.
  Closing historical detail clears its DOM and releases non-current cache entry;
  closing before its GET completes also releases a late completed response and
  does not render errors or content into the closed/detached historical block.
  selection/page/Team switches release full records and old authority. Pure summary
  metadata is bounded separately; it never retains a large plan or complete body.
- A full detail requires exact ID/team/project/delivery/action/status/sequence and
  digest matching its verified summary source. A historical page can locate a full
  GET for reading only; it cannot enter the current `operations` authority array.
  Team filtering applies even if a different Team reuses Project/Requirement IDs.
  A Team change clears all summary/history/detail/ready facts. Late callbacks must
  recheck Team, selection revision, Project, scope and connected/open DOM.
  A separate owner generation changes only when read ownership is cleared,
  independently of normal full-read revision. Summary and full GET callbacks
  check captured owner after each await before admitting facts; 304 additionally
  revalidates the exact prior Team/scope and requires its cache entry still present.

## Current plans and writes

- For the selected Requirement, scan its verified summary pages to select latest
  action/approval sources matching its exact checkpoint/current Task. Only finite
  locator metadata is retained, not full historical plans. First/changed inventory
  loads each required full source freshly before showing an actionable approval.
  Ready requires every current source still in the bounded cache. Stable unchanged
  inventory polls may reuse those same loaded reading facts; they do not approve.
- Every public `submitOperation` on a summary-capable server runs
  `recheckOperationWriteFacts`. This covers recovery approval, wait resolution,
  stopped-provider/completed-output/legacy rescue, baseline execution and explicit
  continuation without duplicating new authorization policy in six entry points.
  Capture exact request/current Task/source signatures and selection/Project;
  also capture snapshot Team, Console Team, owner generation and capability
  manifest. Recheck them after each await and at the actual POST boundary, even
  when current sources are empty (for example, creating a Requirement).
  freshly GET scoped summaries (complete active set) and every required actual full
  Operation. After all awaits require those exact facts still unchanged and
  `canControlCurrentTeam` true before using the original typed intent. Existing
  entry-specific proof/plan predicates and server checkpoint/plan/role fences stay
  authoritative. A changed fact is rejected; never automatically adopt/approve a
  different plan after a user confirmed the previous one.
- Full read/digest failures clear current control, ready and native-rule review
  consent. Summary failure preserves historical reading but disables writes.
  History approval text has no action button and says it is a past record. The
  current exact approval remains at the top of Requirement details.
- A freshly accepted full Operation immediately denies duplicate work through a
  bounded reading projection; it does not start another polling/approval path.

## Validation matrix

| Scenario | Required result |
| --- | --- |
| Good: current exact plan, unchanged poll | Summary/304, one initial full GET, stable approval DOM; fresh full GET before POST |
| Base: old server or historical page | Original compatibility GET / explicit paginated reading and single detail GET |
| Bad: summary supplied as full/foreign scope/incomplete active/oversize page | Reject; no approval or partial current authority |
| Active Operation outside first 25 records | Complete active set still prevents duplicate submission |
| Full digest or current selection changes during fresh read | Zero POST, original approval not silently replaced |
| Empty-source create await changes Team or action manifest | Actual `submitOperation` issues zero POST |
| Late 200/304 or full GET after owner clear | No stale publication or new-owner control revocation |
| Older-page record expanded then closed | Full reason visible; released cache and `operations` references |
| Historical detail closed while its GET is pending | Late completion releases its full cache entry and keeps the closed body empty |
| Same Project/Requirement IDs in another Team | Old pages cannot qualify active work or approvals |
| Eight-count/32 MiB cache eviction of required source | No ready reading gate; budget stays bounded |
| Cursor stale / initial empty page / page navigation | Old page labeled retained / first page filled / real DOM moves to chosen page |

## Tests, stock data and rollback

`operation-summary-reading.test.cjs` runs shipped JS/fake HTTP and covers reading
separation, ETag, exact digest, active completeness, pagination, full-GET callback
fences, Team isolation and cache byte/count refusal. Its browser counterpart uses
isolated Chrome/fake HTTP to verify actual 61-record/three-page DOM navigation,
outside-page full reason, close release, unchanged polling and click-time drift.
Keep readiness/engineering/operation/notice/UI/polling-state regressions.

No SQL/journal/Task/approval/workspace migration or rewrite. Original full records
remain immutable and complete; the read-only backend projects them. Deploy only
when production work is idle through controlled restart, then refresh the original
Requirement. Roll back frontend reading code/assets with backend compatibility;
retain every durable fact. This reduces transfer/retention and does not alone
prove absence of a platform memory leak or complete K1 delivery.
