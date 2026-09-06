# Bug analysis and boundary

1. Root cause B/E: broad project command facts were presented without the narrower executable
   integration-test contract. The guard itself correctly rejected a non-supported test command.
   Original live argv is unavailable; do not infer it was Ruff or a particular uv invocation.
2. Initial verification caught WirePayload list invariance and a private import re-export; use the
   repository's WirePayload type and import the new shared predicate directly in tests.
3. Prevention: one immutable predicate/policy, fresh context copies, safe typed check-index/hash
   diagnostics, service/journal restart regression, all prefixes and forbidden flags tested.
4. Adjacent limits: arbitrary schema/provider/authorization failures still use existing paths;
   rejected raw responses are not a new artifact store. Existing exhausted run budgets are never
   reset. Starting on a new source revision requires a fresh prepared/approved lineage, not editing
   the existing journal or reusing old candidate QA/Review evidence.
5. Knowledge captured in multi-directory-delivery spec. No template mirror exists in this repo.

No hard permissions, canonical schemas, default platform-root behavior, roles or verdicts changed.
