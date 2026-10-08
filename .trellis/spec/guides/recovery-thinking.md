# Recovery decision checklist

Before adding another recovery exception, read
`docs/architecture/2026-10-04-delivery-direction-review.md` and
`.trellis/spec/core/delivery-recovery.md`.

- Separate cause from disposition: dirty work is not itself proof of policy violation;
  a local execution window is not a provider outage or a QA FAIL.
- Distinguish materialization, admission, model invocation, accepted progress, candidate and
  role verdict. None implies the others. Check claim ownership and stopped execution first.
- Can the same authorized Task/branch safely continue at its last checkpoint? Use WorkItem
  wait/retry for recoverable new work; do not create a terminal Task just to force a successor.
- Which authorization changed: business content, source/base, scope, permission, capability,
  or budget? Show that exact difference. A digest is evidence, not a user-facing reason.
- Runtime revision and target source revision are separate. Platform deployment is not
  automatic permission to rebase a candidate or silently refresh frozen knowledge.
- Keep complete old evidence and findings. Read-only capture is not write permission,
  a candidate, an independent verdict or permission to reapply protected rule edits.
- Locate all consumers of the invariant before editing: Task/role compiler, adapter/tool,
  candidate/progress gate, recovery proposal/current facts, Context, Schema, Console projection.
- Regress through the public Continue path and verify same Requirement, unchanged source
  history and complete UI record. Local classes alone do not establish production recovery.

This is a design checklist, not an authorization to change current state contracts. Historical
terminal Tasks remain immutable and use the verified successor compatibility path.

### Legacy missing facts and crash boundaries (2026-10-08)

Do not mistake a successful investigation report for a completed recovery path. Classify whether
trusted facts exist but were not found, or were never sealed. Fixing future recording cannot recover
old absent facts. Legacy rescue must explicitly separate new engineering evidence from historical
outcome/stop facts, require exact human provenance when old host identity is missing, and audit it
as supplied evidence. See `../core/legacy-execution-rescue.md`.

A complete current Git patch can still omit ignored files. With no trustworthy before inventory,
compare the full current inventory against Git plus captured mutation bodies; reject unknown ignored
inputs and links rather than bringing them into a new execution implicitly.

Test the boundary after immutable binding but before SQL consumption, both within the same boot and
after a later same-device boot. Do not create another binding for the same original start. Already
authorized containment remains a historical fact; new publication still rechecks exact live inputs.
Always provide a UI way to reprepare an unapproved stale plan. Validate a subsequent full collector
pass over the old UNKNOWN, not only the first successful restart.

The full collector pass must include the succeeding Coder, QA and Review calls. Their requests
inherit the baseline digest but their immutable queue boundaries may bind later candidate SHAs.
Authenticate the exact consumption epoch through the immutable parent chain; do not rewrite
verifier candidate sources to the rescued Coder input. A helper-only lookup can miss this seam.
