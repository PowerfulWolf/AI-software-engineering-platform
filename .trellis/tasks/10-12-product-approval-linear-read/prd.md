# Product 审批历史线性读取

## Problem and goal

`FileProductRecordStore.find_approval` validates every persisted approval by calling
`find_product_spec`. With A approvals and S ProductSpec versions this repeats complete
ProductSpec decoding A × S times. Recovery repeatedly invokes this gate and can spend most
of its time decoding old Product facts before any model starts.

Optimize one lookup only: each complete spec and approval decodes once, while all bytes,
directories, filenames, hashes, versions, supersedes and exact approval associations still
validate. No authority or successful decision survives the synchronous call.

## Scope / allowed paths

- `src/ai_software_engineer/product/store.py`
- `tests/product/test_approval_read_prefix.py`
- `.trellis/spec/core/product-approval-read-prefix.md`
- `.trellis/tasks/10-12-product-approval-linear-read/`

The core index is owned by the integration agent. No production SQL, Host, service, source
checkout, schema, role permissions, approval identity or retry ledger is modified.

## Acceptance

1. A real multi-request/version history decodes S specs and A approvals in each lookup;
   another independent lookup repeats the complete work.
2. Preserve full-tail corruption, missing/bad associations, referenced spec duplicates and
   queried approval duplicates. Empty approvals do not inspect unrelated spec history.
3. Before return, reread/hash all observed complete records and recheck complete inventories
   and directory identities. Mid-read append/delete/rename, same-length content mutation and
   symlink/directory replacement reject.
4. Retain only private typed spec association/digest and bounded fingerprints, at most
   512 entries / 2 MiB of serialized accounting. Overflow restores the original full lookup,
   without truncation or a new validity limit. Success and failure clear temporary state.
5. Existing Designer offline-call request/approval freshness fences still reject drift.
6. Run incremental store, Designer, lint and strict type checks; no full suite or MySQL.

## Existing data and rollback

No durable migration is required. Existing records retain original bytes and audit history.
Load code only in an idle controlled restart window, then continue the same Requirement
through the public entry. Revert this read optimization while idle to restore original cost;
never reset Tasks, approvals or drafts as rollback.
