# Implementation and validation

Implement typed purge plan/completion and Operation cleanup with JSON Schema parity. Use the existing cancellation and native resource reconciler, real current time, exact CLEANED receipts and expected-SHA Git deletion. Validate every remaining byte on replay; refuse drift and additional files.

Run public Console and service regressions with isolated MySQL and real Git: draft, closed/cancelled, partial deletion/restart, foreign scope, writer closure, branch collision and removal provenance. Run Ruff and strict Mypy, independent Standards/Spec review, then idle main deployment and existing-data cleanup through public typed services. Rerun original HTTP/browser refresh measurements. K1 and automation remain paused.


Validation (2026-10-13): 286 related pytest cases passed against the dedicated isolated MySQL fixture; 77 frontend Node tests passed. Ruff format/check and strict Mypy passed for all 32 changed Python files; git diff --check passed. Independent Standards review reported no outstanding findings (14 local cases passed); independent Spec review reported no outstanding findings (22 local cases passed). Original main had 18 transitive JSON-narrowing errors in the imported context-capacity test fixture; explicit dictionary assertions corrected these without changing its negative schema cases.

Existing-data production preview validated seven stopped inventories; the large historical Requirement includes 2966 files / 463585869 bytes / 350 SQL rows / 6 refs. The remaining oldest Requirement requires typed abandonment of five stopped verifier reservations. Deployment, production deletion and after-latency validation are pending this commit.
