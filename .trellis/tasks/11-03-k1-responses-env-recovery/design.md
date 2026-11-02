# Design

The command policy currently admits `uv` by executable name. In the K1 role
worktree, `uv` created `.venv/` after the sealed start. The tool returned;
later `NativeCoderContinuation.finished()` compared the complete inventory and
correctly rejected the unapproved environment. Responses wrapped that concrete
policy error as a generic route failure and retained the lawful source edits.

At the tool boundary, reject environment-creating `uv` operations before the
command executor runs. Keep harmless version inspection available; do not
expand Task permissions or accept `.venv/` as a Coder write path. Add prompt
guidance that implementation checks use existing approved tooling and report
unavailable checks as NOT_RUN instead of installing dependencies. The machine
guard, not the prompt, enforces this restriction.

For the already failed K1 Run, add a distinct terminal snapshot version for
the exact sealed synchronous Responses workspace-policy result. It binds the
route completion SHA/time rather than claiming a native process stop. Require
one final Responses route equal to the sealed invocation outcome, terminal
Task/queue and no receipt; reuse the full two-pass source, target, SQL, Git and
inventory audit under the existing lock. The current capture must contain
only permission-authorized code files. Newly introduced `.venv/` entries must
all be ignored regular files/symlinks and are kept only in the old workspace;
the existing environment exclusion audit already enforces this. Require
`coder_reapply` so no dirty or ignored bytes are silently seeded.

Good: exact K1-shaped failure with three legal tests and ignored `.venv/`
proposes an independently approvable clean successor. Base: v1 native stop
and v2 clean Responses refusal keep their exact wire shape and digest. Bad:
an unknown route, tracked `.venv/`, unauthorized source path, changed inventory
or active tool cannot produce a Plan.
