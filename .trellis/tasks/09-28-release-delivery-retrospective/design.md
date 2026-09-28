# Design

Separate three identities: ASE release commit/tag, business accepted candidate/main, and installed
App binary. Existing formal QA/Review remain authoritative; this task performs authorized integration
and local installation, not a replacement verdict. Use clean fast-forward for main when possible so
the installed source remains the exact accepted SHA. Check remote tips before pushing; never force.

Read previous task analyses/specs and current facts; report historical intermediate BLOCKED records
as preserved history, not current delivery failure. Documentation is the durable review output.

Installation uses the existing build script and ad-hoc signature. Move the existing App to a dated,
validated backup before replacing it, preserve Application Support, and verify binary/signature plus
normal launch. A rollback restores the backup bundle; Git rollback must preserve released history.

Only the navigation fix is in v0.1.2. Follow-up release/retrospective records can be a separate docs
commit; the release tag must not be moved to hide subsequent documentation work.
