# Contract

`preserved_continuation_prompt(receipt: ExecutionInterruptionReceipt) -> str` is a prompt-only renderer used after NativeCoderContinuation._prepare has validated the complete receipt, process stop, actual WorkspaceMutationCapture and current complete inventory, request, claim and policy. v2 accepts only CapturedMutations. v1 keeps the original full patch prompt.

The internal typed preserved_worktree_continuation_input v1 includes full scope, original request digest/source, receipt/capture/patch hashes and byte count, complete mutation path inventory with before/after byte SHA/mode/size and deleted markers. It states that current files are the actual retained progress, not accepted artifacts or a candidate, and that hash references are not a substitute for original before-body audit/replay. Coder uses existing scoped tools to inspect current files and exact source Git differences. All original full reapply input remains untouched.

| Case | Result |
| --- | --- |
| Complete v2 capture and matching current workspace | bounded manifest, same authorized one-use admission |
| Historical v1 | unchanged full patch |
| Any stop/claim/source/capture/inventory/policy drift | existing refusal before renderer/provider |
| Final complete input remains too large | existing ContextCapacityReceipt and zero provider invocation |

No durable Schema or SQL migration; old contexts and hashes stay immutable. Rollback prompt generation only when idle, retaining complete capture and all readers. No production authority derives from this reading manifest.
