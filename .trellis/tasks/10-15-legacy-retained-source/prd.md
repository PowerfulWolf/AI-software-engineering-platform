# Legacy retained ignored source recovery

Goal: restore the existing K1 execution through the public same-Task engineering recovery flow, while retaining the original UNKNOWN execution and all audit history.

Root cause: an unanchored `artifacts/` ignore rule hides a new permitted Python module under `src/.../artifacts/`. Initial complete recovery capture rejected it; merely including it in that capture would omit it from preview trees, later interruptions and candidate commits.

Scope / allowed paths: `.gitignore`; Git mutation capture, baseline preview/apply, candidate commit; baseline resolver/admission/production publication; production route factory and backend wiring; idle/rejected/stopped reconciliation; relevant Git/adapter/continuation/manager tests; `.trellis/spec/core/{legacy-execution-rescue,workspace-inventory}.md`; this task directory.

Acceptance:
- Initial legacy capture includes only frozen-policy-authorized bounded nonsensitive regular ignored source, excluding execution caches. Unknown ignored input remains a blocker.
- Exact additions from immutable validated rescue lineage reach preview, admission, progress, continuation and candidate finalization. A report cannot omit the retained file; fresh independent QA/Review checkouts contain it.
- Defaults and historical serialized bytes/digests remain compatible. No Task/SQL rewrite, source/index modification during rescue, fabricated stop/outcome, permission expansion, or QA/Review bypass.
- Public Host fixture completes the original Task including retained ignored source and preserves original UNKNOWN facts.
- Production recovery uses normal API and exact engineering authorization, with before/after checks.

Verification: original venv with `PYTHONPATH=<maintenance-worktree>/src`; focused Git, agent, continuation and baseline tests; public MySQL legacy rescue fixture; Ruff, mypy, diff checks; independent review.

Rollback: revert this fix commit, controlled pause/restart using `scripts/ase-console-service.sh`; never delete preserved K1 source or immutable new recovery records. A published recovery is append-only and cannot be undone by rewriting old facts.
