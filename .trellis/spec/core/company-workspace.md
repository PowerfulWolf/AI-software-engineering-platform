# Company sidecar contract

## Scope and ownership

The platform organization owns Agents and general capabilities. A Company owns one external sidecar:
`<platform_root>/companies/<company_id>/{knowledge,projects,requests}`. Project modules retain native
per-repository artifact/workspace contracts inside `projects/`; user-facing setup does not require
one independent sidecar per code repository. Code is neither moved nor copied.

## Signatures and configuration

```python
CompanyWorkspace.initialize(platform_root, *, company_id, name) -> CompanyWorkspace
CompanyWorkspace.project_registry() -> ProjectWorkspaceRegistry
CompanyWorkspace.knowledge_sources(relative_paths: tuple[str, ...]) -> tuple[ContextSource, ...]
CompanyWorkspace.requests_root -> Path
ProductionConfig.company_id: CompanyId = "company_default"
ProductionConfig.company_name: str = "Default company"
ProductionConfig.company_knowledge_paths: tuple[str, ...] = ()
UnifiedProjectEntryService(..., delivery_namespace: str | None = None)
```

`company_id` is a stable identifier, not a mutable directory name; changing the display name does not
silently rewrite its manifest. The manifest is immutable, hashed, and reopened with exact identity
and path checks. No migration/deletion of older top-level `projects/` is implicit.

## Contracts

- Project registration validates the entire platform root is external to the target code root.
- Project IDs and production delivery IDs include company identity so shared MySQL facts cannot
  collide for the same source path and requirement registered under two companies.
- AgentProfile stays under `organization/`, not inside a Company or project module.
- Company knowledge selection is explicit and read-only, relative to `knowledge/`; no recursive
  scan or automatic loading of other projects/companies. Reject traversal, symlinks, missing files,
  non-UTF8, private-key/credential file names, and oversized content. Redact supported secret forms.
- Selected company knowledge is opaque context, bound by digest in the project baseline; it is
  not a higher-priority engineering rule and cannot override project-native rules. Natural-language
  conflicts still require human resolution, not automatic precedence inference.
- Requirement Project journals live under the company's `requests/` and bind company identity and
  manifest digest. Input code scopes cannot overlap platform storage.
- Company path names alone are not OS/multi-tenant access control. Strong tenant isolation remains
  out of scope; explicit routing, path guards, and separate run contexts are enforced here.

## Validation matrix

| Case | Required result |
|---|---|
| Two repositories in one company | Two modules under one company sidecar; no code writes |
| Same repository in two companies | Distinct project IDs and delivery IDs; no cross-company catalog search |
| Same company reopened | Exact manifest replay; no overwrite |
| Manifest drift, missing directory, symlink | Fail closed, preserve files |
| Selected company document | Redacted content and digest-bound source only |
| Unselected project/company document | Not loaded |
| Company knowledge changed after prepare | Existing preparation drift rejection, not silent context replacement |
| Scope overlaps platform root | Reject before registering a module |

## Required tests

Company workspace replay/corruption/path isolation; selected knowledge/redaction/budgets;
production config Schema; company-scoped delivery identity; production Host binding; existing
single-repository delivery regression. Multi-directory production execution uses the separate
`multi-directory-delivery.md` contract and real MySQL/Git joint E2E tests.

## Good / Base / Bad cases

- Good: one company prepares two code roots under `projects/`, the selected company document is
  included in Product's verified baseline, and each source checkout remains unchanged.
- Base: `company_default` and an empty document selection work without extra per-project setup.
- Bad: use one global project/delivery ID for multiple companies, recursively load all company
  files, or resume an old preparation with silently changed company context.

## Wrong vs Correct

```python
# Wrong: ownership is only a folder label; global IDs may collide in shared MySQL.
registry = ProjectWorkspaceRegistry(platform_root / "projects")

# Correct: company-scoped identity and registry, shared organization-owned workforce.
company = CompanyWorkspace.initialize(platform_root, company_id="company_acme", name="Acme")
registry = company.project_registry()
module = registry.register(absolute_code_root)
```

The Host includes an opaque `context.company` record in the baseline, authored by platform
composition (`PLATFORM_ENGINEERING`, `platform://companies/...`). This is provenance for a selected
context snapshot, NOT a semantic parser or a company-rule precedence mechanism. Same-process
knowledge drift is rejected by `preparation_guard`; after Host restart, baseline/preparation digest
checks reject changed knowledge before Product/Design/Delivery can continue.

Verification: `tests/project_manager/test_company_workspace.py`, `test_company_host.py`,
`tests/contracts/test_json_schema_contracts.py`, and the existing real MySQL/Git
`tests/project_manager/test_production_backend.py`.
