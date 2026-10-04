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
