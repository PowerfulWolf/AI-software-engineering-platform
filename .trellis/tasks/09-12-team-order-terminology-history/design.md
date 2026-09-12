# Design: ordered team, presentation vocabulary and safe cleanup

## Presentation order

The browser owns a fixed `TEAM_ROLE_ORDER` keyed by durable role identity, not by localized display
name or current status. Sorting uses `(known order, original index)` so a future role remains stable
after the seven known roles. The read projection remains authoritative for member existence and work.

## Target domain vocabulary

The requested correction is cross-layer and versioned:

- `Company` → `Team`: long-lived collaboration, Agent, model-policy, capacity and Team-knowledge
  boundary;
- new `Project`: a stable business/product context served by the single Team, with Project knowledge
  and Project Specs;
- `Requirement Project` → `Requirement`: one user objective and its joint delivery lifecycle beneath
  one Project;
- current repository-level `RepositoryWorkspace`/`RepositoryProfile` → stable `Repository`/
  `RepositoryProfile` records beneath one Project;
- `Project Manager` → `Manager`: the Team leader, independent of any one Project;
- Repository/Directory scopes: the code locations selected by one Requirement.

The target external layout is:

```text
<platform_root>/
├── team/
│   ├── team.json
│   ├── agents/
│   ├── model-policies/
│   ├── knowledge/
│   ├── specs/
│   └── skills/
└── projects/<project_id>/
        ├── project.json
        ├── knowledge/
        ├── specs/
        ├── repositories/<repository_id>/
        └── requirements/<requirement_id>/
```

Team and Projects are sibling aggregate roots. A Project references the Team identity it is served by,
but is not physically nested inside the Team workspace. The cutover is versioned and fail-closed. No
reader treats an old Company manifest as a Team manifest,
or a repository workspace as a business Project, without an explicit validated migration.

This requires an explicit migration of configuration, MySQL identities, sidecar paths, recovery
journals and public schemas. It must not be implemented as an ambiguous global string replacement.

## Delivery wording

Only a durable DONE result with a concrete `candidate_branch` is called a merge-ready requirement
branch. The platform presents it for human review/merge and does not claim to merge or push it.

## Cleanup boundary

Cleanup is a separate operator operation, not a UI filter. First inventory Team/request journals,
MySQL Task/StateEvent/queue/dispatch records, console operations and worktrees, joining them by trusted
Delivery/Task IDs. Retain completed requirements and their evidence. Remove only the fully joined
non-DONE closure, preferably through a purpose-built typed cleanup command or script; never run broad
filesystem or SQL deletion against unresolved roots.
