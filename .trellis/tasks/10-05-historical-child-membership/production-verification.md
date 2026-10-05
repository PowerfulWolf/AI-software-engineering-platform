# Production verification and existing data

## Release and evidence

- Source and canonical runtime checkout: historical ownership fix `8356d57`, compatible static
  snapshot schema sync `bc69ebc`, both pushed to origin/main.
- Verified no QUEUED/RUNNING operation, fast-forwarded the clean canonical runtime checkout, then
  used the trusted service script to reload Host. It safely stopped managed development PID 31131
  and launched canonical deployment PID 56439. No secret file was inspected or sourced manually.
- Before authorized continuation, all 4,461 Project files had identical SHA-256 inventories across
  release and public read verification: zero new/changed/deleted facts. No SQL/journal/Task/verdict
  mutation, deletion or new business Requirement was used to fix the display.
- Independent typed public GET confirmed exactly one K1, original parent ID
  `delivery_multi_8a5103309c232515bcf733947d32830365dd02c6`; old native
  `delivery_197e43958545579951b26746f2d837f3` remains BLOCKED with no Task, now referencing the parent.
  Parent current scopes contain no delivery ID and current-task/unfinished counts remain zero.
- Chrome read-only audit at `2026-10-05T15:52:54.916Z` confirmed the same list, original historical
  Task navigation and Plan interruption display. Product/Design gates were green, Plan red and later
  gates pending; no running animation remained on the interrupted operation. Write requests,
  pageerrors and failed API responses were all zero. Local notification acknowledgements were only
  read-state interaction; no delivery controls were clicked by the browser audit.

Evidence under `/Users/zhangjunshuai/workspace/code/.ase/maintenance/k1-delivery-20261005/`:

- `historical-membership-pre-deploy-inventory.json`
- `historical-membership-post-deploy-inventory.json`
- `historical-membership-get-20261005T154541408391Z.json`
  SHA-256 `251cc93510c77bd005c37a007e5f6f9013c8e948c52dfef166b3d33824a8c9b3`
- `historical-membership-ui-2026-10-05T15-52-54-916Z.json` and matching PNG

Initial concurrent maintenance snapshot GET timed out at 30 seconds; a serial independent GET
completed in 27.3 seconds. A read-only filesystem profile measured new historical ownership at
0.0295 seconds, with four DerivedStageInputs calls; the retained joint inventory is 218 records and
244,268,250 bytes. This does not establish the entire cause of public read latency. The final Chrome
check used controlled GET reads, and existing browser polling regression tests remain passing.

## Same-Requirement continuation

The original approved business Requirement remains usable; do not delete or recreate it.
Before continuation its exact checkpoint was
`fcefd77d3db9aa1d8dd66c62158abe880d66687dbca03c9a093f74d624d22ecf` (PLANNING),
with Planner work budget 2/5, transient 0/5, capacity timeout 0/3 and a 1,800-second next window.
Product, approval, source and the corrected Design remained unchanged.

Through the public typed Console API, submitted ordinary CONTINUE_DELIVERY using new key
`k1-20261005-plan-after-interruption-01` at `2026-10-05T15:53:14.782515Z`.
Operation `operation_367151601fbf78f14d8036ba35858be3` was accepted QUEUED and verified RUNNING.
No CREATE, new Product approval, budget reset/refund, recovery Task or store edit was performed.
The previous INTERRUPTED operation and old failed design child remain intact.

This completes the display repair. K1 business implementation/QA/Review are not delivered yet;
Planner continuation is real ongoing work and must still pass the normal independent gates.

## Rollback

When execution is idle, revert the read-side code, reload through the trusted service script and
refresh the browser. Keep every durable fact and approval. Reverting the static schema restores
its formerly known parity failure; do not remove runtime fields to fit the former declaration.
