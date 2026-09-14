# Design

The Console uses one visual grammar:

```text
page title
  -> ownership context (Team / Project / Platform)
  -> page-specific navigation or actions
  -> primary work
  -> secondary evidence/detail
```

## Page ownership

| Page | Owner | Project control |
|---|---|---|
| Team | Team | workload filter only |
| Requirements | Project | active work context |
| Knowledge | Team or Project | shown only for Project Knowledge |
| Settings | Platform Host | none |
| Status | Platform Host | none |

The existing `ProductionTeamReader` remains Project-scoped. The Team page must therefore describe
its counts as the selected Project workload instead of inventing organization-global utilization.

Requirements keep durable operations and delivery details together. On wide screens the Requirement
list is the master column and the existing detail surface is the detail column. On small screens they
stack without changing behavior.

Knowledge and Settings use local section navigation. Creating documents/specs remains explicit but
the long forms are collapsed by default so the inventory is the primary content. Settings remains a
single draft and save transaction even when only one section is visible.
