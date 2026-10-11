# Modern terminal facts window

## Problem and goal

One current Native facts inspection executes its two observations independently. Each
observation reads full Native source once and its terminal workspace wrapper reads that
source twice again. This yields six full SourceReader calls and nested terminal audits.
Use a synchronous old-Task-owned observation window to execute exactly two full source
passes and two complete target/terminal observations, without accepting an older supplied
source as a substitute for a fresh read.

## Scope and acceptance

- Optimize only modern failed terminal sources with a plan-bound complete workspace
  snapshot and no quarantine. Other paths keep the old public safe audit wrapper.
- Acquire the existing old Worker lock before source-before. Observe full source, full
  target, complete terminal SQL/owned stop/capture/inventory before and after.
- The final stop/capture/inventory check must occur after the final source and target pass.
- Compare both complete Native sources, complete target facts, terminal facts and complete
  workspace observations. Both snapshots must equal the immutable plan-bound snapshot.
- Do not reuse results across calls, callbacks, builder/dispatch/seed/claim boundaries, or
  turn a local result into approval. Preserve all existing raw SQL, path, native rule,
  knowledge, binding, permission, Git filter/HEAD/clean/ancestry, stop and inventory checks.
- Test actual Native inspection six-reader red to two-reader green; real typed native
  chain and real temporary Git/file/lock fixtures, using the exclusively owned test
  database or substituting only isolated SQL/OS transport ports.
- Source/target/SQL/stop/capture/inventory changes at either edge and lock failure reject.
  Unsupported/custom stronger inspector implementations retain their original checks.

## Validation scope

Root approved the design and necessary incremental real MySQL fixture/tests. Only the
exclusively owned `ai_software_engineer_test` database is allowed: verify the exact database
name, no other sessions and all 13 mutable tables empty before construction; finally stop
owned offline child processes and return the 13 tables to empty before releasing ownership.
Never connect, initialize, reset or write production `ase_self_iteration`; do not operate
production Host/service/model/registered repositories. The real Native fixture is mandatory;
a SimpleNamespace/cast replacement for the source or target gates is not acceptance. If a
complete fixture cannot be established, report the gap before claiming verification.
