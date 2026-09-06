# T040 — Preserve immutable project baseline versions

User authorizes workflow repair and fresh verification against latest main. New intake of an
updated source repository fails because the first ProjectProfile/binding/preparation occupies a
single immutable filename. Real Git/MySQL reproduction fails in 0.82s at the same binder seam.

Production preparation must support additional content-addressed baseline records under the same
company project module and project ID. Legacy records remain byte-identical; exact replay keeps
the first timestamps. Existing requests must still reject source/profile/approval drift. Do not
reuse old approvals or rewrite journal/history to make new preparation pass.

Scope: runtime profile/binding record lookup/publication, opt-in versioned ProjectManager
preparation used by production Host, exact production profile reads, CLI typed workspace errors,
targeted tests and specs. Low-level legacy default behavior stays compatible. No model calls or
default-platform-root feature implementation in this repair.

Acceptance: prepare two committed baselines, preserve all old JSON, restart/replay, old-request
drift rejection, legacy replay, symlink/tamper rejection, no target writes, MySQL/full/typing/build.
Rollback: parent4f97deb retained; new versioned records are additive, never delete/migrate history.
