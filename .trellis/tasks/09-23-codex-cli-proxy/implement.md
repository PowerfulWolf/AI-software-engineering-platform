# Implementation

Added the optional `codex_cli_proxy_base_url` to the secret-free production
configuration, JSON Schema, example config and Settings model-route page.
The URL is constrained to a loopback HTTP base URL and is applied to both
upstream structured and delivery Codex CLI adapter factories. Both adapters
share fixed TOML overrides selecting `ase_local_proxy` with the Responses
wire API and `requires_openai_auth=true`; `--ignore-user-config`, sandbox,
worktree, output schema and role policy remain unchanged.

The first URL-only smoke reached the local CLIProxyAPI but returned `401 Missing
API key`, then the current ChatGPT login failed refresh. The URL-only mode
continues to use Codex's saved API-key credential.

The follow-up adds a write-only managed-key mode in Model Routing. The browser
sends the key as a request-only `runtime_variables` entry. Typed config and
Schema keep only the fixed environment-variable reference, and the existing
atomic store writes the value to sibling `runtime.env` with mode `0600`.
Both upstream and delivery Codex CLI routes use `env_key` with
`requires_openai_auth=false`, pass only the named secret to the CLI process,
and exclude it from model-invoked shell environments. Missing runtime values
fail before CLI launch; the structured client hides raw provider stderr in
this mode. Empty password input preserves the stored value; the explicit CLI
login action removes the reference and prunes the stored value on save.
Proxy `401`/`403` and `Missing API key` failures are classified as
non-transient authentication errors instead of repeatedly spending a transient
retry budget.
The delivery adapter's Git inspection subprocess now has its own minimal
environment allowlist, so it does not inherit the managed proxy key.
The shell exclusion does not make the same-user `runtime.env` file unreadable;
this remains the project's trusted-local storage model. No real credential
was copied into source, fixtures or task records, and no authenticated live
model response is claimed.

No Task, Artifact, Operation, approval or database fact is migrated. Historical
failure evidence stays intact; after saving and applying proxy settings,
the operator resumes the existing Requirement explicitly.
