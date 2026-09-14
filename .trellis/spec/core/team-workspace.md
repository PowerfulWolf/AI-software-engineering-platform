# Team, Project and Repository workspace contract

## 1. Scope / Trigger

Apply this contract when changing `team_workspace.py`, `project_workspace.py`,
`repository_workspace.py`, production configuration, knowledge routing, workspace discovery or any
path persisted in a manifest. The platform has exactly one long-lived Team. The Team and all
Projects are sibling aggregates below one external `platform_root`; a Project owns its knowledge,
specs, Repository catalog and Requirement facts. Source code is referenced, never copied into a
sidecar.

```text
<platform_root>/
├── team/
├── projects/<project_id>/
└── worktrees/
```

## 2. Signatures

```python
TeamWorkspace.initialize(
    platform_root, *, team_id, name, read_only=False
) -> TeamWorkspace
TeamWorkspace.project_registry() -> ProjectWorkspaceRegistry
TeamWorkspace.knowledge_sources(relative_paths) -> tuple[ContextSource, ...]
discover_team_workspaces(platform_root) -> tuple[TeamWorkspace, ...]

ProjectWorkspaceRegistry(team).create(*, name) -> ProjectWorkspace
ProjectWorkspaceRegistry(team).register(*, project_id, name) -> ProjectWorkspace
ProjectWorkspaceRegistry(team).open(project_id) -> ProjectWorkspace
ProjectWorkspaceRegistry(team).discover() -> tuple[ProjectWorkspace, ...]
ProjectWorkspaceRegistry(team).locate_repository(repository_id) \
    -> tuple[ProjectWorkspace, RepositoryWorkspace]

ProjectWorkspace.repository_registry() -> RepositoryWorkspaceRegistry
ProjectWorkspace.knowledge_sources(relative_paths) -> tuple[ContextSource, ...]
ProjectWorkspace.requirements_root -> Path

TeamKnowledgeDocumentStore(team).import_document(...) -> KnowledgeDocumentManifest
ProjectKnowledgeDocumentStore(project).import_document(...) -> ProjectKnowledgeDocumentManifest
TeamKnowledgeDocumentStore(team).read_content(document_id) -> str
ProjectKnowledgeDocumentStore(project).read_content(document_id) -> str
TeamKnowledgeSelectionStore(team).save(selected_paths) -> KnowledgeSelection
ProjectKnowledgeSelectionStore(project).save(selected_paths) -> KnowledgeSelection
effective_team_knowledge_paths(team, fallback=()) -> tuple[str, ...]
effective_project_knowledge_paths(project, fallback=()) -> tuple[str, ...]
TeamSpecDocumentStore(team).create(command) -> SpecDocument
ProjectSpecDocumentStore(project).create(command) -> SpecDocument
TeamSpecDocumentStore(team).activate(spec_ids) -> SpecActivation
ProjectSpecDocumentStore(project).activate(spec_ids) -> SpecActivation
ProjectLearningStore(project).collect() -> tuple[LearningProposalView, ...]
ProjectLearningStore(project).decide(proposal_id, command) -> LearningProposalView

ProductionConfig.schema_version: Literal["v0.2"]
ProductionConfig.team_id: TeamId = "team_ai"
ProductionConfig.team_name: TeamName = "AI Team"
ProductionConfig.default_project_id: ProjectId | None = None
ProductionConfig.default_project_name: ProjectName | None = None
```

Public persistent contracts are `team-workspace.schema.json`, `project-workspace.schema.json`,
`repository-workspace.schema.json`, `runtime-workspace-binding.schema.json` and
`production-config.schema.json`. Knowledge records additionally use
`knowledge-document.schema.json`, `project-knowledge-document.schema.json`,
`knowledge-selection.schema.json` and `knowledge-retirement.schema.json`. Strict specifications and
learning facts additionally use `spec-document.schema.json`, `spec-activation.schema.json`,
`spec-retirement.schema.json`, `learning-proposal.schema.json`,
`learning-authorization.schema.json` and `learning-decision.schema.json`.

## 3. Contracts

- `<platform_root>/team` is the only Team workspace. `team_id` remains a stable manifest identity;
  it is not another path segment and the runtime must never recreate `teams/<team_id>`.
- `<platform_root>/projects/<project_id>` is a sibling of `team/`. A Project manifest binds the
  exact `team_id + team_manifest_sha256`; Projects never own or copy AgentProfile records.
- Team owns `agents`, common `knowledge`, `specs`, `skills`, `model-policies`, `work-items`, `leases`
  and `metrics`. Project owns `knowledge`, `specs`, `repositories` and `requirements`.
- A Repository sidecar is stored at
  `projects/<project_id>/repositories/<repository_id>` and binds one absolute source directory plus
  exact Project lineage. Repository identity derives from Team + Project + resolved source path.
- A Requirement belongs to one Project and selects 1–N Repositories from that Project. Cross-Project
  Repository lookup fails; ambiguous Repository identity fails instead of guessing.
- Team, Project and Repository manifests are immutable and content-hashed. Reopen validates identity,
  location, lineage, required directories, regular files and symlink-free ancestry.
- `platform_root` and every source scope must be disjoint in both directions. Source checkouts must
  not receive `.ase`, sidecar, Agent or Requirement files.
- Team stores immutable documents below `team/knowledge/documents/` and its current selection at
  `team/knowledge/selection.json`. Each Project owns the same two-part layout below its own
  `projects/<project_id>/knowledge/`; Project manifests and selections bind exact Team + Project IDs.
- Knowledge update publishes a new content-addressed document and may transfer the old selection to
  the replacement. Delete removes the document from selection and records its ID in digest-bound
  `knowledge/retirement.json`. Retired documents are excluded from current inventory and future
  context, but their immutable files remain for historical delivery provenance.
- `read_content(document_id)` exposes only one active document's normalized Markdown after owner,
  path, size and digest validation. Retired, missing, tampered or non-UTF-8 content fails closed; the
  original source file is never returned through this editing seam.
- Team and Project knowledge selections are explicit, unique, sorted, bounded, safe relative paths. Reads
  reject traversal, hidden/path-like entries, symlinks, non-regular files, invalid UTF-8 and size
  overflow; selected content is redacted and digest-bound in Context.
- Selection publication is atomic and live for future runtime access. An absent selection record may
  use the corresponding `ProductionConfig` list as a compatibility fallback; a present empty record
  explicitly means no selected knowledge. This is not a process-level configuration mutation.
- Team knowledge has common scope; Project knowledge and Repository-native rules refine the selected
  Project. Natural-language conflicts stop for human resolution; path location never silently decides
  semantic precedence.
- `knowledge/` is descriptive context. Mandatory engineering rules belong to `specs/`: immutable
  `documents/<spec_id>/spec.json` records plus one atomic `activation.json` per Team/Project scope.
  Creating a Spec never activates it. One scope may activate at most one version per stable `spec_key`.
- Spec update reuses the stable internal key and publishes the next immutable version. Logical delete
  removes any active reference and records the key in digest-bound `specs/retirement.json`; it never
  erases historical versions. Publishing that key again restores it to the current library.
- A Spec declares exact Team/Project ownership, version, roles, stages, optional Repository IDs,
  safe root-relative path globs and optional human-authored verification guidance. An empty
  verification value means the Team has not defined a proof method yet; it does not weaken the Spec
  body or the platform's mandatory QA/Review gates. Active Team Specs apply
  across Projects; active Project Specs are isolated to their owner and filtered by Repository ID.
- `projects/<project_id>/specs/learning/` stores evidence-backed QA/Review proposals and one immutable
  human decision per proposal. Approval may publish Project background knowledge, a Project Spec, or
  a non-executable Team Skill design proposal. Collection never mutates an executable Skill.
- The default Project pair is optional for the Web flow and must be configured together for the
  compatibility CLI. Creating a Project is an explicit administration action.
- `discover_team_workspaces()` returns zero or one item. Catalog callers keep a tuple seam, but this
  is not authorization for multiple Teams or cross-Team switching in v0.1.

## 4. Validation & Error Matrix

| Case | Required result |
|---|---|
| Fresh external platform root | atomically create one `team/` and its fixed directories |
| Same Team reopened | exact manifest replay; no overwrite or renamed identity |
| Second Team identity at same root | reject identity mismatch; preserve existing Team |
| Create two Projects | two siblings under `projects/`, both bound to the same Team digest |
| Same Project name created again | deterministic idempotent reopen |
| Existing Project ID with another name | reject; do not rewrite manifest |
| Register one source in two Projects | distinct Repository IDs and sidecars |
| Locate missing/ambiguous Repository | reject; never select by path guess |
| Source contains platform root, or inverse | reject before sidecar publication |
| Manifest/path/lineage drift or symlink | fail closed and preserve records |
| Explicit selected knowledge | return redacted, digest-bound ContextSource only |
| Project document/selection copied into another Project | reject owner identity even if content/digest is otherwise valid |
| Team/Project selection saved | atomic sidecar publication; next new/re-prepared Requirement sees it without restart |
| Replace selected knowledge | publish replacement, transfer selection, retire old ID; immutable old file remains |
| Delete selected knowledge | remove selection before retirement; future context excludes it |
| Retirement record owner/digest/unknown ID drift | fail closed; do not reinterpret the current library |
| Read active normalized content | return exact verified UTF-8 Markdown; never return unchecked source bytes |
| Read retired/missing/tampered normalized content | reject; do not expose stale or unverified text |
| Changed selected knowledge after prepare | reject old preparation; never replace context silently |
| Create a new Spec version | preserve all older versions; do not activate implicitly |
| Delete active logical Spec | deactivate its key, retire it and preserve every version |
| Activate two versions of one `spec_key` or unknown/cross-owner ID | reject; prior activation remains |
| Active Spec changes after prepare | reject old preparation; require a new exact baseline |
| Team/Project/Repository rules disagree on one field | produce conflict and route to human; never choose by priority |
| QA FAIL/Review REJECT collected twice | same proposal identity and first observation; no duplicate publication |
| Approve exact Learning proposal | persist immutable authorization before publication, then one completion decision; stale digest is rejected |
| Only one default Project field set | configuration validation error |

## 5. Good / Base / Bad Cases

- Good: one Team serves two Projects; one Requirement in Project A selects its backend and frontend
  Repositories, while Project B knowledge and repositories never enter the Context.
- Base: a prepared Team with no Project is valid; the browser can create the first Project. An empty
  Team/Project knowledge selection is valid.
- Bad: store Projects under `team/projects`, create one Agent roster per Project, or infer a Project
  by scanning all registered source paths.
- Bad: upload a mandatory rule as descriptive knowledge, auto-enable a draft Spec, or let a Learning
  proposal rewrite an executable Skill without human approval and implementation review.

## 6. Tests Required

- `tests/team_workspace/`: atomic initialization, immutable reopen, read-only discovery, path and
  symlink guards, knowledge selection/redaction/budgets.
- `tests/project_workspace/`: deterministic create/register/open/discover, Team lineage, Project
  knowledge, Project-owned Repository registration and missing/ambiguous lookup.
- `tests/knowledge/`: immutable Team/Project documents, owner binding, atomic selection/retirement,
  replacement selection inheritance, verified normalized-content reads, explicit empty selection,
  legacy fallback and integrity failure.
- `tests/specs/`: immutable Spec versioning/activation/provenance, Project isolation, repository
  filtering, evidence-backed Learning collection, exact decisions and safe publication.
- `tests/repository_workspace/` and `tests/runtime_workspace/`: Repository manifest and
  Team/Project/Repository runtime lineage.
- `tests/config/test_production.py`: v0.2 schema, singleton Team defaults and optional/default Project
  pair validation.
- Manager/Web/E2E focused tests must prove a Requirement is created inside its selected Project and
  cannot consume another Project's Repository or knowledge.

## 7. Wrong vs Correct

```python
# Wrong: Team contains Projects and creates per-code-root "projects" implicitly.
registry = RepositoryWorkspaceRegistry(platform_root / "teams" / team_id / "projects")

# Correct: Team and Projects are siblings; Repository registration is Project-owned.
team = TeamWorkspace.initialize(platform_root, team_id="team_ai", name="AI Team")
project = team.project_registry().create(name="Payments")
repository = project.repository_registry().register(absolute_code_root)
```

```python
# Wrong: one global mutable knowledge list silently applies to every Project.
config.project_knowledge_paths = selected_paths

# Correct: selection is owned by the exact Project sidecar.
ProjectKnowledgeSelectionStore(project).save(selected_paths)
```

```python
# Wrong: treat descriptive background text as an enforceable rule.
ProjectKnowledgeDocumentStore(project).import_document(filename="rules.md", content=body)

# Correct: create a versioned Spec, then explicitly activate the exact version.
store = ProjectSpecDocumentStore(project)
spec = store.create(CreateSpecDocument(...))
store.activate((spec.spec_id,))
```

```python
# Wrong: Requirement searches every Project and takes the first matching source path.
repository = next(item for project in projects for item in project.repositories)

# Correct: the typed Project identity is required before selecting its Repositories.
project = team.project_registry().open(project_id)
repository = project.repository_registry().register(absolute_code_root)
```
