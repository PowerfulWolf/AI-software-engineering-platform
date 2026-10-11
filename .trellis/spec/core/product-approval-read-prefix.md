# Product approval lookup: complete call-local prefix

## 1. Scope / trigger

Apply when reading a ProductSpecApproval by approval ID from a large append-only Product
history. `FileProductRecordStore.find_approval` previously called `find_product_spec` for
every approval, repeatedly decoding all ProductSpec versions. A approvals and S versions
caused A × S complete spec validations even when only one exact approval was requested.
This CPU cost can occur before recovery dispatch or model admission; it is separate from
current Git/SQL/process observation and from a long-running memory leak.

## 2. Signatures and private facts

Implementation: `src/ai_software_engineer/product/store.py`.

```python
FileProductRecordStore.find_approval(approval_id: ProductApprovalId | str) -> ProductSpecApproval | None
FileProductRecordStore._find_approval_prefix(
    validated_id: ProductApprovalId, prefix: _ApprovalReadPrefix
) -> ProductSpecApproval | None
FileProductRecordStore._find_approval_unindexed(
    validated_id: ProductApprovalId
) -> ProductSpecApproval | None
_ApprovalReadPrefix.revalidate(root: Path) -> None
_ApprovalReadPrefix.clear() -> None
```

The private association is only `ProductSpecId → _SpecAssociation(request_id,
repository_id, sha256, duplicate)`. `_SpecVersionIdentity(id, request_id, repository_id,
version, supersedes)` carries version-chain facts between streamed spec reads. Neither
stores a complete ProductSpec, raw body, current request head, approval authority, verdict,
or successful admission decision. Record fingerprints carry trusted absolute path, complete
raw SHA-256, device and inode; directory fingerprints carry path, device/inode and complete
sorted inventory names. Root observation checks identity without inventorying unrelated
Product categories.

## 3. Contracts

- Every independent lookup owns a new private prefix. The first actual decoded approval
  lazily reads **all** ProductSpec request directories and all numbered versions. No actual
  approvals means no ProductSpec read, preserving existing empty-history behavior.
- The fixed original decoder validates the complete envelope (`record`, `sha256`), canonical
  envelope digest, Pydantic schema and inner record integrity. Its input is the same complete
  trusted UTF-8 content whose raw SHA enters the fingerprint; never hash one read and decode
  a second read or accept caller-supplied association/decoder results.
- Spec request identity, contiguous version/filename, first supersedes and repository/
  supersedes chain use the same lightweight sequence validator as `list_product_specs`.
  Approval request directory, spec filename and exact request/repository/spec digest still
  match. Every approval validates, including later approvals after a requested ID is found.
- An ID duplicated anywhere in the complete spec prefix is marked, not immediately rejected.
  Reject when an approval actually references that duplicated spec ID. Unreferenced duplicate
  IDs keep the original `find_product_spec` lookup semantics. Reject duplicate queried
  approval IDs; do not introduce a new global duplicate-approval rule.
- Before a successful return, recheck every captured root/category/request directory identity
  and full inventory, reread every complete observed approval/spec through trusted directory
  descriptors with no symlink and regular-file checks, compare raw SHA and file device/inode,
  then repeat directory/inventory checks. No mtime/size shortcut, partial history, cached
  full models or early success can replace those fresh observations.
- The temporary association **and** all fingerprints share an aggregate budget of 512 entries
  and 2 MiB canonical UTF-8 serialized accounting. Raw record bodies are transient; they are
  not charged to this retained-fact budget and existing valid record size is unchanged.
  This is not a heap/RSS or total read-size limit. If either budget is exceeded, clear the
  prefix, leave the overflow handler/finally, and run the unchanged complete per-approval
  lookup. Large valid history remains valid; overflow does not silently truncate history.
- Exit the overflow exception handler **before** fallback. Its traceback would otherwise
  retain an in-progress complete spec/raw body throughout the expensive original scan.
  Index traversal releases current full record in `finally` and keeps only a lightweight
  version predecessor. New read/final-revalidation wrappers release full content in `finally`.
  Success, corruption, path failure and overflow clear all prefix-owned facts. Do not force
  garbage collection or manipulate another component's diagnostic traceback.
- This helper is a finite read observation, not a filesystem transaction or approval cache.
  Public `find_product_spec`, `get_approval`, `put_approval`, request heads and application
  authorization/current-facts fences remain independent fresh reads. In particular the real
  `DesignerService.run` checks Product facts before and after its offline/model window and
  before publication; no prefix survives into model execution.
- No wire Schema, persistent data, state transition, role permission, retry budget or exact
  human Product/engineering approval changes. Do not expand the separate synchronous recovery
  immutable-model cache with approval authority to address this cost.

## 4. Validation and error matrix

| Case | Required behavior |
| --- | --- |
| A actual approvals, S valid spec versions, within budget | S spec decodes + A approval decodes; same exact original approval |
| Next independent lookup or unknown valid approval ID | Reopen/revalidate the complete prefix again; never reuse previous authority |
| Missing spec; request/repository/spec digest mismatch | `ProductRecordCorruption` |
| Referenced duplicate spec / queried duplicate approval | Original duplicate identity corruption |
| Unreferenced duplicate spec | Preserve original valid lookup behavior |
| Bad later schema/envelope/inner hash/version/supersedes | Reject complete lookup, even after target approval is found |
| Empty approval category/request directories and bad unrelated specs | `None`, no spec decoding |
| Mid-lookup raw replacement with equal length and restored mtime | Fresh complete raw SHA mismatch rejects |
| Append/delete/rename/new request or directory inode replacement | Full inventory/identity mismatch rejects |
| Record/directory symlink substitution | Trusted path rejection; no decoding an outside body |
| Capacity exceeded after partial valid spec decoding | Release prefix and complete model/raw references before original scan |
| Held later spec corruption or final raw mismatch exception | No earlier complete spec or new raw wrapper retained by prefix traversal |
| Request or approval changes during real Designer offline callback | Independent post-model fence rejects; no Design receipt/checkpoint/stage advance |

Corruption uses `ProductRecordCorruption`; untrusted paths use `ProductRecordPathError`.
Missing-file races retain the existing typed `ProductRecordNotFound` behavior. Internal capacity
overflow is not an externally visible validity error. Shared fixed-decoder error semantics and
application error sanitization remain unchanged.

## 5. Good / base / bad examples

Good: validate 9 specs once, bind all 9 approvals exactly, reread all 18 complete records and
recheck every inventory, then release the lookup state. A later lookup repeats those facts.

Base: there are no actual approvals, so return `None` without touching an unrelated damaged
spec prefix. Oversized valid history uses the original full lookup and remains correct.

Bad: cache approved spec models across requests, stop scanning after the requested approval,
reuse an mtime fingerprint, skip a corrupt unrelated tail, or continue the model using the
prefix's old association after Product facts change.

## 6. Incremental verification and limits

`tests/product/test_approval_read_prefix.py` drives real append-only filesystem histories,
full decoder/integrity counters, raw-read counters, injected actual byte/inventory changes,
partial-overflow weak references, held-error lifetimes and an actual `DesignerService` with
an offline fake adapter. Required deterministic assertions:

- 9 specs / 9 approvals: original 81 spec validations becomes 9; approvals stay 9. A second
  independent lookup repeats 9 + 9. Initial and final raw reads visit every record twice.
- Exact lineage and complete-tail negative fixtures reject; empty and unreferenced duplicate
  cases preserve behavior.
- All previously decoded full spec/raw wrappers are released **at fallback entry**, not only
  after fallback returns. Holding a later rejection cannot retain prefix-owned complete bodies.
- Model callback starts after prefix release; actual request/approval drift is rejected by
  post-model application fences and produces no design publication.

Also retain `tests/product/test_store.py`, `tests/product/test_service.py` and
`tests/design/test_service.py`, including concurrent revision advancement during the offline
model window. Incremental Ruff, formatting, strict mypy and `git diff --check` are required.
No MySQL or full test suite is needed for this file-store optimization.

The Trellis task records a finite isolated complete-store benchmark and validation results.
Do not infer complete recovery speed, model latency, or a long-term memory-leak resolution
from reduced ProductSpec decoding. Raw bytes still reread and all external live-fact fences
remain; aggregate-budget overflow intentionally restores the original cost.

## 7. Wrong vs correct: overflow lifetime

Wrong: start the original full scan while the overflow traceback still owns the partially
decoded large ProductSpec/text:

```python
try:
    return self._find_approval_prefix(validated_id, prefix)
except _ApprovalPrefixOverflow:
    prefix.clear()
    return self._find_approval_unindexed(validated_id)
```

Correct: release prefix facts on every exit and leave the handled exception before fallback:

```python
try:
    return self._find_approval_prefix(validated_id, prefix)
except _ApprovalPrefixOverflow:
    pass
finally:
    prefix.clear()
return self._find_approval_unindexed(validated_id)
```

The partial-capacity regression checks model/raw weak references at the actual fallback entry;
checking only after the scan returns would miss this lifetime defect.

## 8. 存量数据处置、部署与回滚

No SQL/journal/approval/schema migration or workspace rewrite. Existing Requirement, Task,
ProductSpec, ProductSpecApproval and retained draft bytes and hashes remain unchanged. Do not
create a replacement requirement to load this repair. Wait for active Operations/roles to
finish, deploy code through an idle controlled service restart, then use the same Requirement's
public recovery/continue path and its existing exact approvals. Runtime deployment does not
authorize rebinding its approved Task source baseline.

Rollback while idle by reverting the read optimization; it restores repeated decoding cost
without deleting, changing, or resetting any durable fact. Prevention: count complete decoding
at the actual repeated lookup, test full-tail corruption and independent freshness, and verify
partial fallback/held-error lifetimes rather than relying only on low RSS or clean success.
