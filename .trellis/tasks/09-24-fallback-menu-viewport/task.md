# Bottom-edge fallback selector

Goal: at the bottom of Model Routing Settings, the last Agent's “添加备用模型” menu must show a
reachable, scrollable list without crossing the sticky save bar or clipped panel. Preserve exact
route identity, selection order and Settings draft semantics.

Scope: `team_view/app.js`, `team_view/style.css`, the focused browser layout regression and this
Trellis spec/task record. No Settings API, Schema or production configuration change.

Acceptance: the menu opens into available space on desktop and 390px viewport; its final option
can be selected; existing route selectors and Settings layout tests pass. Rollback: revert the
menu positioning handler/CSS together; no data migration or stored state repair is required.

Verification: run only `tests/team_view/browser/settings-layout.test.cjs` and related Node UI
tests, then check the diff. The reproducer failed with menu bottom 974px and sticky save bar top
780px in a 900px viewport before the fix; after the fix the menu fits above the bar.
