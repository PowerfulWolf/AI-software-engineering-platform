# Implementation and validation plan

Base: 67daf0ecc8341e5c81b54b4d14187d86090ead4a. Mirror only:
/private/tmp/ase-native-safe-observation-20261024.

1. Define pure typed stats and write failing observer/drain/runner tests.
2. Extend existing single-thread drain and strict parser without new reader loops.
3. Add separate private exact capture-linked record and optional recorder hook;
   preserve old wire and digest definitions. Write explicit availability read.
4. Extend strict continuation deletion closure and adversarial store tests.
5. Run focused checks; report real OS rejections to root, never count as passing.
6. Produce scoped patch, baseline/file hashes and actual red/green evidence. No commit,
   merge, push, production mutation, restart or provider execution by this worker.

Status: implementation code frozen; prospective private diagnostic record, exact
read/replay, optional publication, deletion closure and negative tests implemented.
Focused checks and root's authorized real OS tests passed; see verification.md for
commands/results, sandbox limits and stock-data/rollback handling. No deployment,
main checkout edit, production data mutation or commit was performed by this worker.
