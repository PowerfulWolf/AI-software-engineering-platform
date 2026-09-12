# brainstorm: Web Project Delivery Console

## Goal

Turn the current read-only team dashboard into the daily workspace for the AI software engineering
team: users create a requirement project from one or more code directories, discuss and approve the
requirement, follow execution, handle safe continuation gates, and receive the final candidate
delivery without using product CLI commands.

## What I already know

- The existing Team View is a loopback-only, read-only projection. Its HTTP transport deliberately
  rejects all writes and must not become scheduling or verdict authority.
- `OrganizationTeamHost` already composes the real Project Manager entry modules for single- and
  multi-directory work and exposes the unified `resume_delivery` interface.
- `JointDeliveryService` already supports requirement-project creation, Product dialogue, exact
  approval and delivery status; the browser module should delegate to it instead of reproducing
  checkpoint logic.
- Long model runs can last many minutes and must remain observable while executing. Browser refresh
  or HTTP disconnect must not cancel or duplicate a delivery operation.
- The UI already projects companies, organization Agents, requests, task scopes, role assignments,
  artifacts, runs and final candidate revisions.

## Assumptions

- “No command line” applies to every daily product operation. Installation may perform a one-time
  host setup; afterward a macOS/Linux user-level service starts the console automatically.
- v0.1 remains a trusted local single-user application bound to loopback; remote/multi-user access,
  RBAC and SSO are not part of this increment.
- Users may paste/select absolute code-directory paths. The platform validates and discovers their
  Git repository grouping exactly as the current application module does.

## Requirements (evolving)

- Create a named requirement project from one to 32 absolute directories, including multiple paths
  from one repository and paths from multiple repositories.
- Display preparation and discovered scope before Product discussion.
- Send Product dialogue messages and render the latest ProductSpec and clarification request.
- Approve only the exact current ProductSpec/checkpoint through an explicit user action.
- Start or resume long-running delivery asynchronously and expose durable operation progress.
- Render current Coder/QA/Reviewer stage, affected directory scope, failures, required human action,
  QA/Review outcome and final candidate branch/commit.
- Hide internal checkpoint hashes and plan hashes from ordinary UX while preserving exact binding
  inside the command module and audit artifacts.
- Keep the existing read-only projection module independent from the new command module.

## Acceptance Criteria (evolving)

- [ ] A browser user can create a requirement project with multiple directory inputs and receives a
      visible prepared workspace or a safe actionable error.
- [ ] A browser user can complete Product dialogue and approve the exact displayed ProductSpec.
- [ ] A delivery operation returns immediately with a durable operation identity; refresh does not
      duplicate or cancel it.
- [ ] The UI exposes only the action valid for the latest checkpoint and rejects stale/replayed form
      submissions safely.
- [ ] QA failure routes to remediation through the existing unified resume module; no verify CLI is
      exposed to the user.
- [ ] DONE displays repository, candidate commit/branch and verification evidence suitable for
      test-environment integration or later merge.
- [ ] Existing read-only Team View behavior and security tests remain valid through its interface.

## Definition of Done (team quality bar)

- Focused unit/integration/browser-contract tests pass; user runs the full suite before final push.
- Ruff, format, strict Mypy and frontend tests pass.
- README usage, Workspace responsibilities and executable Trellis specs match the implementation.
- Failure, idempotency, secret handling, startup and rollback behavior are documented.

## Out of Scope (explicit)

- Remote Internet exposure, multiple human accounts, RBAC/SSO and cloud hosting.
- Automatic merge, deployment or production release.
- Complex DAG editing or direct low-level Task/Agent manipulation in the browser.
- Replacing MySQL, Git worktrees, existing Product/Designer/Planner/Delivery modules or the read model.

## Technical Notes

- Candidate interface: a small Project Manager command surface (`create`, `reply`, `approve`,
  `continue`) plus read-only snapshot/operation queries. Internal adapters own exact typed commands.
- Likely affected paths: `team_view/` or a sibling Web Console package, production host composition,
  typed web command/operation models, tests, static assets, README and live-team/production specs.
- A plain browser cannot safely reveal arbitrary native filesystem paths through standard file upload;
  directory selection needs typed path entry, a constrained local chooser adapter, or a later desktop
  wrapper.

## Research Notes

### What established interfaces imply

- Python documents `http.server` as a basic server that is not recommended as a production Web
  server. It remains adequate for the separately constrained read-only loopback projection, but
  growing its handwritten handler into a state-changing application would increase security and
  protocol risk.
- ASGI frameworks can return `202 Accepted` before an operation completes, but their ordinary
  in-process background-task helpers are not durable execution queues. Delivery work must therefore
  be represented by persisted operation facts and executed through the platform's queue/dispatcher
  lifecycle, not an HTTP worker thread.
- Browser `showDirectoryPicker()` returns an origin-scoped directory handle rather than the native
  absolute path required by the Git discovery module, and browser availability is limited. A pure
  browser UI cannot provide a portable native path chooser for this local platform.

### Constraints from this repository

- MySQL and immutable company sidecar facts already provide persistence; adding Redis/Celery only to
  serve the browser would duplicate queue authority.
- The current Product/Designer/Planner/Delivery implementation is synchronous at its public entry
  interface, while role work and checkpoints are already durable and observable.
- `team_view` is intentionally a read-only module. Its small interface and tests should remain
  unchanged; a sibling command module can compose it into one browser experience.

### Feasible approaches

**Approach A: local Web Console plus durable operation dispatcher (Recommended)**

- Add a typed ASGI control module with four intent-level commands and operation/snapshot queries.
- Persist accepted operations, return `202`, and let one Project Manager dispatcher execute them
  idempotently through existing application interfaces.
- Keep absolute-path entry in v0.1; add a native chooser adapter later.
- Best balance of reliable long-running work, small browser interface and future remote adaptability.

**Approach B: extend the existing stdlib Team View server**

- Add POST parsing and worker threads directly to `BaseHTTPRequestHandler`.
- Lowest dependency cost, but mixes read and command authority, is hard to test deeply, and a server
  restart loses in-flight HTTP worker state unless most of Approach A is rebuilt inside it.

**Approach C: desktop shell now**

- Wrap the Web Console in a macOS/Linux desktop process and expose a native directory chooser and
  one-click startup.
- Delivers the strongest no-terminal UX immediately, but adds GUI packaging/signing/platform work
  before the delivery command lifecycle has been proven through a browser interface.

The recommended sequence is Approach A now, preserving a launcher/chooser adapter seam so Approach C
can wrap the same console without changing Project Manager semantics.

## Decision (ADR-lite)

**Context**: The read-only Team View cannot own delivery writes, model calls may run for many minutes,
and users should not handle checkpoint or verification-plan hashes in a terminal.

**Decision**: Build Approach A. A sibling Web Console module exposes a small intent-level interface,
persists accepted operations, delegates only to the existing Project Manager application interfaces,
and composes the existing projection into one UI. Daily operations are browser-only. The installed
host is shaped for a macOS `launchd` or Linux `systemd --user` adapter; a native desktop chooser may
be added later without changing command semantics.

**Consequences**: The read model remains independently safe and testable. Browser refresh cannot
duplicate accepted work. We accept one additional Web transport dependency and an explicit operation
journal. v0.1 uses validated absolute path entry; a desktop wrapper is deferred.
