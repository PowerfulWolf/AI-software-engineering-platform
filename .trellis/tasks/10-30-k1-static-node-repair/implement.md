# Implementation and validation plan

1. Add a red-capable Git fixture for the exact import-only candidate shape and
   negative fixtures for direct binding, alias reexport, dynamic/uncertain code,
   changed Git blob and historical missing-file digest.
2. Implement the narrow observer and propagate node identity into the trusted
   QA contract and knowledge/prompt projection. Preserve the current no-start
   collector and `STATIC_QA_MISSING_ENTRY` resolution fences.
3. Run focused domain/agent/manager tests, generated Schema parity, Ruff and
   strict Mypy. Run the isolated public MySQL fixture with the exact nonterminal
   wait and verify only a genuine QA FAIL routes to Coder.
4. Independently review the changed authority and output boundary. Commit,
   publish and controlled-restart the platform only when the service is idle.
5. Inspect and resolve the current K1 wait through public Console Operations,
   then observe the independent QA result and ASE Coder continuation. Keep all
   old UNKNOWN and no-start facts intact.

Rollback point: before the public decision, revert the platform commit and
restart at an idle boundary. After the decision, retain its reader and fix
forward; no direct SQL or sidecar rewrite.
