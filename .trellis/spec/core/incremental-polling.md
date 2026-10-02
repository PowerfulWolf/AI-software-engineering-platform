# Console incremental polling

## Scope and signatures

Applies to the five-second Console read loop in `src/ai_software_engineer/team_view/app.js`.
No API, schema, storage, Task state or authorization contract changes.

```javascript
render({preserveComposer = false, incremental = false} = {})
renderDetail({incremental = false} = {})
renderView(container, key, facts, build, incremental)
viewBlock(node, key, facts)  // source facts invalidate callbacks and rendered data together
viewGroup(node, key)        // only containers without event handlers
reconcileViewChildren(current, next)
pollingContentFacts()
pollingDetailFacts()
pollingKnowledgeFacts()
```

## Contracts

- Polling publishes validated facts via the existing serial Project refresh pipeline. Rendering is
  a read-side operation; DOM preservation cannot retain an obsolete approval or bypass readiness.
- `renderView` skips identical scoped facts. Matching page/Project/entity containers reconcile in
  place. Changed scope keys rebuild that surface, so identical local IDs in different scopes cannot
  share an editor or command closure. Settings/Status belong to Team, not Project.
- `viewBlock` retains a node only if its key and source signature match. Signatures live in WeakMaps;
  do not store configuration or secret values in HTML/data attributes. Mark only event-free layout
  containers as `viewGroup`. Replacing a changed action block installs fresh, validated callbacks;
  HTML equality alone cannot prove that its checkpoint/target/selected inventory is still current.
- Request and Team list entries use their stable identities. Immutable artifact bodies use URI and
  full document facts; Spec bodies use scope/version identity. Same-scope read-state remains open;
  changed documents are revalidated before replacing their body.
- Model-call bodies use Operation identity/facts, retain their loaded state on unrelated changes,
  and have a disclosure key for changed-record reopen. Task activity has its own facts/region and
  updates heartbeats without destroying diagnostic text or refetching completed calls.
- Settings refresh saved/process metadata while preserving the form by draft baseline, Section and
  contract version. Unsaved inputs, secret drafts, focus, selection and native help popovers survive.
  Explicit saves, navigation and version changes retain their existing validation behavior.
- Knowledge polling compares inventory, Spec, learning, index and error facts, not only index status.
  Asset-only changes must become visible even if Team/Operations and the index are unchanged.
- Preserve scroll offsets for surviving containers and text selections whose endpoints survive.
  Do not restore selection/focus over a new notification or editor. Changed checkpoint/scope may
  invalidate an old control and must take priority over preserving that control.

## Validation matrix and examples

| Change | Behavior | Executable assertion |
|---|---|---|
| Another Requirement changes while Settings is being edited | Keep input/form/help nodes and draft | Browser input identity, focus and selection |
| Saved restart flag changes | Update metadata and retain current draft | Badge text changes; input identity/value stable |
| Another Requirement or current next action changes | Patch list/overview, retain open artifact and diagnostic | Same nodes/open/body; only one model-call GET |
| Snapshot timestamp changes alone | No content/detail mutations | MutationObserver reports zero child-list mutations |
| Current Task phase changes | Update modal facts, retain its artifact | Same dialog/document; latest phase visible |
| Spec inventory changes without index/Team change | Show new asset, preserve existing body | New title visible; old details/body same node/open |
| Exact approval checkpoint changes | Remove old action | Old approval disconnected; no stale POST |

Good: a new Task heartbeat updates its activity while a user continues selecting an artifact paragraph.
Base: repeated identical polling changes only the connection/read timestamp.
Bad: restore every old button by matching its label, or preserve old action handlers using HTML equality.

## Verification and operations

`tests/team_view/browser/polling-state.test.cjs` exercises real Chrome with intercepted API facts.
Also run affected interactions, async-boundaries, settings-layout, notification and lightweight
readiness/UI contracts. Use `node --check` and `git diff --check`. No full repository suite required.

Existing data: no migration or journal rewrite. Refresh the browser once to load the compatible
frontend; normal polling then preserves in-tab state. A full browser reload still starts a new view.
Rollback the frontend change and refresh; original polling behavior returns, persistent facts remain.
