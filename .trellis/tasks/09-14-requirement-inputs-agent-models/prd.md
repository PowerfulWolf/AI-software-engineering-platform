# Improve Requirement inputs and per-Agent model routing

## Goal

Make the browser the complete daily entry point for creating Requirements, discussing visual
requirements with Product Agent, and assigning suitable model routes to each long-lived Team Agent.

## What I already know

- Requirement creation currently accepts newline-separated absolute Repository directories.
- Product discussion currently accepts text only.
- Production model routes are global ordered fallbacks rather than Agent-specific assignments.
- The user wants browser interactions instead of routine CLI work.

## Confirmed design

### Repository directory selection

- The trusted loopback Console exposes one injected `DirectoryChooser` port.
- Production uses a fixed-argument native chooser: macOS `osascript`, Linux
  `zenity`/`kdialog`. Browser code never supplies a command or server-side path.
- The chooser returns canonical absolute directories. Requirement creation renders removable path
  chips and no free-form path textarea.
- Cancellation is not an error. Unsupported/headless hosts return one safe error and perform no
  Requirement mutation.

### Product screenshots

- PNG, JPEG and WebP screenshots are uploaded as bounded immutable Requirement attachments under
  the Project Requirement sidecar.
- A Product reply references exact attachment IDs and checkpoint; the dialogue hash chain binds the
  attachment manifests. Text may be empty only when at least one screenshot is present.
- The Product structured-model invocation receives verified local image paths. Codex CLI uses its
  native `--image` input. Routes which cannot accept images are not silently treated as if they had
  read them.
- The browser accepts screenshots pasted directly into the Product discussion, then shows previews,
  filename/size and removal before submission. It does not require a screenshot file picker.

### Per-Agent model routing

- `model_routes` remains the provider/model/credential catalog.
- A new role-policy configuration assigns an ordered subset of enabled catalog routes to Manager,
  Product, Designer, Planner, Coder, QA and Reviewer.
- Product/Designer/Planner construct their structured fallback clients from their own role policy.
  Coder/QA/Reviewer dispatch and provider fallback use the same role policy and keep the chosen
  provider/model in durable run facts.
- Manager currently executes deterministic Skills and has no direct model invocation; its policy is
  still configured and displayed so the roster contract is complete.
- Legacy config without role policies means every Agent inherits the current global enabled route
  order. The Settings UI materializes explicit policies on save.
- Status presents the same seven-Agent policy as read-only runtime facts: primary route, exact
  reasoning effort, ordered fallbacks and route readiness. The route catalog remains visible as a
  separate dependency view and is not mislabeled as an active model call.

### Knowledge maintenance dialogs

- Team and Project Knowledge pages show existing knowledge/spec assets by default.
- Importing general/background knowledge or development Specs starts from a clear action button and
  opens the existing focused modal pattern used by Project/Requirement creation.
- Closing a modal must discard only the unsaved form state; uploaded assets and existing edit/delete
  interactions remain unchanged.

## Requirements (evolving)

- Create Requirement through a directory-selection dialog instead of typing paths manually.
- Product discussion accepts one or more screenshots alongside text.
- Settings can configure different model policies for Manager, Product, Designer, Planner, Coder,
  QA and Reviewer.
- Status shows those Agent-specific policies and readiness without implying that a route is currently
  executing.
- Knowledge import forms are modal actions; the default workspace is the current asset inventory.

## Rejected alternatives

- Browser `webkitdirectory` upload: it uploads file contents and exposes relative paths, not the
  absolute external code root required by Project preparation.
- Base64 screenshots inside `PRODUCT_REPLY`: it bloats the 64 KB durable Operation and mixes binary
  storage with command facts.
- Concrete model fields on `AgentProfile`: a model is run-scoped organizational policy, not the
  long-lived Agent identity.

## Acceptance Criteria (evolving)

- [x] Selected code directories are visible, removable and submitted as typed absolute roots.
- [x] Unsupported/cancelled directory selection changes no Requirement draft.
- [x] Screenshot bytes are bounded, typed, persisted and digest-bound before Product Agent use.
- [x] Product Agent context contains only the exact approved discussion attachments.
- [x] Each long-lived Agent can select its own primary model and ordered fallbacks.
- [x] Invalid/disabled Agent routes fail before a model run starts.
- [x] Status shows each Agent's exact primary/fallback route and reasoning effort.
- [x] Team/Project knowledge and Spec imports use focused modal flows.
- [x] Focused UI, administration, persistence, context and routing tests pass.

## Definition of Done

- Tests, Ruff, Mypy and JavaScript checks pass.
- Cross-layer contracts and README usage are updated.
- Human full regression is ready to run.

## Out of Scope

- Remote browser filesystem access.
- General-purpose file attachments beyond screenshots.
- Per-Requirement ad-hoc model configuration.
- New provider integrations or credential storage mechanisms.

## Technical Notes

- Applicable contracts: `web-console.md`, `production-team-host.md`,
  `multi-directory-delivery.md`, `contracts.md`, `context-routing.md` and Agent/ModelPolicy schemas.
