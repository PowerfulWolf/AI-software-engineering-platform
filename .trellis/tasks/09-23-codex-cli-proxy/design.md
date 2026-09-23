# Design

`ProductionConfig.codex_cli_proxy_base_url: str | None` is a host-level
operator-owned input. It is not a route endpoint: every `codex_cli` route uses
the same local Codex transport, while `responses` routes remain unchanged.
The URL must be an absolute loopback HTTP URL (localhost, 127.0.0.1 or ::1),
without userinfo, query or fragment. In URL-only mode the proxy API key stays
in Codex's supported login cache and never enters agent argv/environment or
ProductionConfig. The operator signs in under the same `CODEX_HOME` as the
service. Remote providers remain out of scope.

Both Codex adapters receive the frozen setting from ProductionConfig. A shared
builder emits fixed `-c` overrides for provider ID `ase_local_proxy`, name,
`base_url`, `wire_api=responses`, and URL-only `requires_openai_auth=true`. The URL is
encoded as a TOML string; no arbitrary Codex key or free-form CLI argv enters
configuration. `--ignore-user-config` remains mandatory. The existing role
sandbox, worktree and output-schema arguments are unchanged.

| Input / state | Result |
|---|---|
| Setting absent | Byte-equivalent direct CLI provider selection |
| Valid loopback URL | Explicit local provider selected in upstream and delivery |
| Invalid URL | ProductionConfig validation rejects before save or invocation |
| Proxy stopped / wrong protocol / missing key | Existing typed CLI failure and retry routing; no fallback to direct provider |
| Settings changed | Save then restart Host; already persisted facts remain intact |

Good: `http://127.0.0.1:8317/v1` reaches the explicit Responses provider.
Base: no URL keeps historical direct-login behavior. Bad: dropping
`--ignore-user-config` imports uncontrolled user provider/hooks and can change
execution policy.

No Task/Artifact schema or database migration. This configuration affects only
new CLI invocations after the Host restart. Prior 504/CLI failures remain
auditable and the operator explicitly continues the existing Requirement.

## Follow-up design: write-only managed API key

`ProductionConfig.codex_cli_proxy_api_key_env: EnvVarName | None` defaults to
`None`. Non-null requires `codex_cli_proxy_base_url`; the Settings UI uses the
fixed name `ASE_CODEX_PROXY_API_KEY` and a password input. The field is only an
environment-variable reference. `LocalConsoleAdministration` adds that name
to the submitted-config allowlist and `secret_status`; the existing atomic
`runtime.env` store and restart token handle the secret value. Empty input
preserves the current value. An explicit "use CLI login" action clears the
reference, and the next save prunes the stored value.

When no key environment name is configured, the previous proxy command with
`requires_openai_auth=true` is unchanged. With a key name, the shared CLI
override builder instead sets `requires_openai_auth=false`, `env_key=<name>`
and a fixed `shell_environment_policy` exclusion for that variable; each
adapter passes only the referenced key to the Codex process. Factories reject
a missing runtime value before launching a CLI. Structured-model diagnostics
must not copy raw stderr when a managed key is in use. No fallback to direct
OpenAI or cached CLI login is permitted in managed-key mode.

Good: a write-only Settings key reaches the local proxy in both upstream and
delivery runs, while the tool shell lacks that variable. Base: a proxy URL
without a managed key retains CLI-login mode. Bad: keep
`requires_openai_auth=true` with `env_key` (Codex ignores the latter), put a
literal token in `-c`/config, or inherit every host secret into the CLI.
