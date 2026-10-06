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
| Current Requirement title/status changes with operation history expanded | Retain outer fold and unchanged sealed row DOM | Same fold/row nodes; open state remains true |
| Non-Product baseline action and older Product discussion both exist | Current action stays outside historical disclosure | Visible current engineering summary; old discussion remains closed |

`buildDetail()` positions current Requirement facts and controls ahead of reference/history.
`productExecutionSummary(item, {guidance = true} = {})` may suppress duplicated guidance only
when the same current blocker/next action is visibly rendered in `requestBlockerSection`.
`requestOperation()` still owns every existing readiness/checkpoint/role gate and event callback;
`appendDiscussionContent` routes controls into discussion only for `productDiscussionStages`.
An event-free `current-actions` group may relocate those controls, never synthesize authorization.
Current product knowledge has exactly one placement, including legacy facts without execution.

Requirement historical discussion/operations/repository deliveries default to closed disclosures
keyed by Project/Requirement. Group outer history containers and their lists so unchanged rows and
loaded inner disclosures survive reconciliation. Full record count/data remains present in DOM;
do not truncate to improve layout. Sealed record next actions are explicitly historical.

Good: a new Task heartbeat updates its activity while a user continues selecting an artifact paragraph.
Base: repeated identical polling changes only the connection/read timestamp.
Bad: restore every old button by matching its label, or preserve old action handlers using HTML equality.

## Verification and operations

`tests/team_view/browser/polling-state.test.cjs` exercises real Chrome with intercepted API facts.
`tests/team_view/browser/requirement-detail.test.cjs` checks current/historical hierarchy, complete
history and node preservation, current action visibility, Product drafts, legacy knowledge placement,
no rendering-triggered POST and no detail/page overflow at 1440px/1024px/390px. Browser history tests must
open the outer disclosure before reading `innerText` or clicking nested engineering summaries.
Also run affected interactions, async-boundaries, settings-layout, notification and lightweight
readiness/UI contracts. Use `node --check` and `git diff --check`. No full repository suite required.

Existing data: no migration or journal rewrite. Refresh the browser once to load the compatible
frontend; normal polling then preserves in-tab state. A full browser reload still starts a new view.
Rollback the frontend change and refresh; original polling behavior returns, persistent facts remain.

## Task reading and Requirement chapters (2026-10-06)

```javascript
taskDetailScopeKey()                  // Team + page + Project + selected Task
syncTaskReadingToolbar(panel)         // only toolbar text/pressed state, only when changed
taskReadingFold(title, key, open = false)
taskFeedbackSection(history, taskId)   // latest saved QA/Review artifact per kind
requestChapter(key)                   // current / outputs / history / reference
taskChapter(key)                      // same grouping with Task-specific names and facts
detailChapter(chapters, prefix, key)   // shared read-only chapter structure
requestChapterNavigation(request)     // read-only scroll controls
```

### Contracts and presentation

- Requirement detail has exactly four primary `h2` chapters: 当前进展、产物与交付、完整交付记录、
  工程参考. Each `.request-chapter` owns an independent card and `.request-chapter-heading`;
  existing modules become `h3` subsections. Stage documents are peer `.artifact-document` items.
  Historical discussion/operations/repository records belong to history, not the document chapter.
  Current business/engineering decisions and Product reply stay visible in current; navigation only
  scrolls. Reparenting must retain the original action gates, exact signatures and fresh callbacks.
  Any `knowledge_gap.is_current` belongs to current, including team/engineering responsibility;
  only historical gaps belong to reference. Never move an actionable current knowledge decision
  into engineering reference merely because it is not assigned to Product.
  The masthead title and current status share a keyed `.request-title-row`: the title may wrap,
  while the status remains visible on its right without shrinking or horizontal overflow.
  The status block signature includes both `deliveryPhase(item)` and `requestNodeExecution(item)`;
  unchanged RUNNING facts cannot retain an old phase label after the Requirement advances.
  Requirement masthead groups its context label/management controls and title/status inside one
  card. Context label and controls share compact typography; title/status remain adjacent rather
  than filling opposing ends. Scoped close styling must not override primary/danger action colors.
- The chapter, fold and list ancestors must all be `viewGroup` for descendant keys to preserve DOM.
  `appendExecutionEntry` binds `{entry, currentTaskId}`; Task model rows bind full `run` facts and
  `run_id/source_uri`. A heartbeat or added history row cannot rebuild unchanged sealed text.
- Task modal is read-only and may pause its displayed facts. `pausedTaskDetailKey` belongs only to
  its exact Team/page/Project/Task. Backend snapshot polling remains live; new facts show a pending
  progress notice. Both incremental and default `renderDetail()` respect pause: delayed unrelated
  command completion cannot silently replace paused text. Explicit resume renders latest facts;
  entity/scope change, navigation or missing Task clears pause. Requirement approval never pauses.
- Task overview preserves a known typed engineering `WAITING.reason/next_action`; `UNKNOWN` still
  requires execution verification. Latest saved QA/Review feedback names current/historical Task
  and is not a verdict for a later candidate. No role success is inferred from document presence.
- Task dialog and Requirement detail each have one main vertical reading surface. History/report
  bodies have no inner max-height clipping; long text wraps. Document source URI/hash is accessible
  after the body in a collapsed identity disclosure. Empty activity regions render no blank card.
- Task uses four `.task-chapter` cards: 当前进展、产物与报告、完整执行记录、工程参考.
  Current status/feedback precedes source reports and complete history. Model calls belong to
  history, identity/queues/assignments to reference. Chapter titles are `h2`, internal titles `h3`,
  peer disclosures share summary size/padding/borders; only nested source metadata is smaller.
  Task documents live under keyed `.task-artifact-list`; style this actual parent, not only
  chapter-direct `details`. Grid gaps prevent adjacent fold margins from collapsing together.
  Sticky header keeps close/reading controls; nonsticky title/status may wrap fully without
  filling the viewport. Overview signature includes raw `item.status` as well as presentation,
  since a changed delivery phase can have an unchanged WAITING/RUNNING presentation.

### Validation and error matrix

| Trigger | Required behavior / assertion |
| --- | --- |
| Task heartbeat or appended history | Same history/text/report/model nodes, selection/open/scroll retained; all rows present |
| Pause then fresh snapshot or default render callback | Snapshot current, Task text frozen; pending progress notice remains |
| Resume, scope change or Task disappears | Latest same-scope facts or missing-record view; pause cannot survive |
| Product checkpoint changes | Requirement remains live; old approval control removed and cannot submit |
| Requirement title updates with document selected | Same document/text nodes and selection through keyed chapter ancestry |
| Stage docs mixed names / history exists | Four main chapters; all documents peer style; history only inside history card |
| 390 / 1024 / 1440 px | No horizontal overflow; chapter borders/spacing visible; navigation targets visible |

Good: pause a Task report while the team snapshot progresses; resume explicitly to review new facts.
Base: real-time heartbeat only patches changed activity, leaving selected evidence untouched.
Bad: freeze approval callbacks, replace paused text on an async completion, or key rows under an
unkeyed list/chapter. Correct: pause only Task read facts and group every ancestor, not just the row.

Required coverage: `browser/task-detail-reading.test.cjs`, `browser/requirement-detail.test.cjs`,
`browser/polling-state.test.cjs` and affected interaction/state contracts. Fixtures intercept all API
traffic; no production action or migration is needed. Existing facts remain usable after loading the
new frontend. Roll back assets and refresh without changing Task, Operation or approval history.

## Live progress inside an immutable Operation row (2026-10-05)

`currentOperationProgress(operation, request)` is a pure read-side derivation shared by the
active operation history and its visible notification. Its `title`, `reason`, `responsibility`
and `nextAction` use `deliveryPhase(request)` and `requestNodeExecution(request)`. A live
projection requires the exact Requirement/Project and current RUNNING delivery operation;
`activeOperation(deliveryId, projectId)` performs the scoped match. Input checkpoint digests
identify the version at command submission, not the latest phase after that command advances.

The original history renderer contained no current-phase display; its list also lacked a
`viewGroup`, so the row keys alone did not enable child reconciliation. The reported fixed
action label must not be attributed to an already-running row cache. Once the list is a
keyed group, nested blocks have their own dependencies: invalidating `pollingDetailFacts()`
is insufficient if a retained child only includes immutable command facts. The new row
must include `{record, progress}`. Do not change Operation bytes, timestamps or hashes to
trigger rendering. Native role phase changes must also participate even when the command
remains RUNNING throughout.

| Input change | Required result | Regression assertion |
| --- | --- | --- |
| Same Operation object, DESIGNING → PLANNING | Current row changes from technical design to planning | Original serialized Operation identical; row title and signature change |
| Same command, Coder → QA → Reviewer | Current phase follows the actual current Task | Implementation, testing and review titles update without invented verdicts |
| Current wait while command is RUNNING | Show real blocked phase, responsibility and next action | Product decision is not replaced by a generic request to wait |
| Sealed history, queued command or unrelated scope/action | No current-phase overlay | Historical outcomes unchanged; foreign Project cannot steal active match |
| Visible ACTIVE notice changes stage | Update its content; preserve acknowledgment key | Closed notice does not reopen during later phase changes |
| Opaque ID and command-input digest | Default collapsed engineering troubleshooting details | Product text describes progress; disclosure identifies the submission version |

Good: a single Continue advances from Designer to Planner; the product user sees the current
planning phase and next step, while the initiating action and input version remain auditable.
Base: completed, failed or interrupted records keep their own command outcome without borrowing
today's Requirement stage. Bad: label a new stage only during a full reload, stamp the current
checkpoint onto old input facts, infer model liveness from the Operation, or replay notifications
under a new per-stage acknowledgment key.

### Bug analysis and prevention

- **Root cause (C/D/E):** the Operation-history renderer treated the command label and status
  as complete progress, leaving the product user with only an action and opaque IDs. It omitted
  the shared Requirement phase. Row signatures also omitted derived facts, but the ungrouped
  list meant this was a latent incremental-rendering defect, not proof of the observed old label.
- **Earlier scope:** node/card fixes introduced shared execution facts, but did not update the
  separate Operation-history renderer or test one unchanged command across multiple phases.
- **Prevention:** shared live progress, complete nested signatures, and real Chrome polling
  tests with unchanged Operation bytes. Review every `viewBlock` that renders derived cross-entity
  values for dependencies on those entities; keep immutable history distinct from live overlays.
- **Related surface:** the active notification consumes the same progress and retains the
  original ACTIVE key. This does not introduce durable stage events, backend execution authority,
  invented completion time, or a model heartbeat.

Executable coverage: `tests/team_view/operation-progress.test.cjs` and
`tests/team_view/browser/execution-history.test.cjs`, plus affected polling and product-state
regressions. No template mirror exists in this repository; the maintained spec and tests are
the prevention boundary. Existing data needs no migration: update frontend assets and refresh;
rollback assets without modifying history or restarting an active role.
