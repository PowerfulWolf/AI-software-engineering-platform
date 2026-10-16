# Ownership and milestones

- Backend worker owns native adapter/helper and native/route/outcome regression tests.
- Display worker owns blocker_text.py/app.js and Python/Node display regressions.
- Root owns task/spec/production recovery documentation, final checks and controlled deployment.
- Independent reviewer remains read-only; no native Coder source is edited by maintenance.

1. RED: actual adapter `Error: unclassified native exit` loses selected diagnostic in durable message.
2. Implement ordinary-provider-only safe JSON string marker, complete redaction and unchanged flags.
3. Real offline native child → real route store → durable invocation outcome → fresh readers.
4. RED: both humanizers discard detail; summary text containing TIMEOUT can alter old reason.
5. Separate summary from fixed metadata before classification/display; preserve old hash-only wording.
6. Independent review found escaped exact proxy-key leak in plain/nested summaries. Add negative
   tests and conservatively hide summaries whose remaining escapes cannot be proven safe.
7. Targeted validation and independent cross-layer review; commit/push and idle controlled restart.
8. Public new exact same-Task PAUSE/independent RESUME; inspect new durable native cause without
   rewriting the old two hash-only failures or consuming work in an unknown retry loop.

Proxy fail-closed behavior may hide useful Windows-path or other escaped diagnostic text. This
is an explicit privacy boundary; the original rc/cause/hashes remain and classification is unchanged.
