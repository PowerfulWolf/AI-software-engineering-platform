# Design

`Gap + optional exact Resolution -> typed KnowledgeGapView -> Console GET / TeamSnapshot
-> status, blocker and clarification card`.

Use one shared read projection with `gap`, `resolution`, `is_current`; verify content hashes,
gap/run lineage and Requirement ownership. The Team snapshot includes the current view so
polling sees a resolution change without a new checkpoint. The knowledge listing retains
history with explicit current ownership. No persistent gap schema changes.

UI derives an approved waiting presentation from that view, filters obsolete knowledge-wait
Operation text, and keys clarification cache by checkpoint plus resolution ID. Successful
approval immediately replaces the form with the returned resolution and refreshes visible
guidance; GET after reload independently reconstructs the same state. Pending drafts retain
their cache key. Errors remain errors and do not fabricate resolved state.

Add the read contract to TeamSnapshot JSON Schema and docs; existing snapshots without the
optional view remain valid. Backend changes require a Console restart; refresh assets after it.
