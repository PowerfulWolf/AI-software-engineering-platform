# Implementation and checks

1. Add persisted query/API regression covering pending -> approve -> reopened GET and no
   checkpoint writes; corrupted/mismatched resolutions must fail closed.
2. Add shared typed query view and optional current knowledge view to TeamSnapshot/schema.
3. Render approved answer/source, explicit resume status and consistent blocker guidance;
   preserve draft/single-flight behavior, isolate subsequent gaps and historical results.
4. Run focused pytest for knowledge/Console/Team/contracts and Node UI tests; Ruff format/check,
   strict Mypy, diff check and offline build where required. Broaden only on actual failures.
5. Record verification and executable spec, commit/push, load new Console code with no active
   operation, then check read-only API/page state. Leave real continuation to the user.

Local repository supplies a minimal Trellis workflow but no task.py; task artifacts are
maintained directly with apply_patch, matching existing local tasks. The user explicitly
requested implementation and approved proceeding; no additional planning decision is open.
