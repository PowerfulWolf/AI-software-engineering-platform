# Implementation

Added the optional `codex_cli_proxy_base_url` to the secret-free production
configuration, JSON Schema, example config and Settings model-route page.
The URL is constrained to a loopback HTTP base URL and is applied to both
upstream structured and delivery Codex CLI adapter factories. Both adapters
share fixed TOML overrides selecting `ase_local_proxy` with the Responses
wire API and `requires_openai_auth=true`; `--ignore-user-config`, sandbox,
worktree, output schema and role policy remain unchanged.

The first live smoke reached the local CLIProxyAPI but returned `401 Missing
API key`, then the current ChatGPT login failed refresh. The implementation
therefore deliberately relies on Codex's supported stored API-key credential
for proxy authentication. The platform neither reads the existing personal
`experimental_bearer_token` nor passes a key through Agent argv/environment.
The operator must complete API-key login in the same CLI credential
environment as the service before live acceptance.

No Task, Artifact, Operation, approval or database fact is migrated. Historical
failure evidence stays intact; after applying settings and authenticating,
the operator resumes the existing Requirement explicitly.
