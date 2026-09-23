# Design

`ProductionConfig.codex_cli_proxy_base_url: str | None` is a host-level
operator-owned input. It is not a route endpoint: every `codex_cli` route uses
the same local Codex transport, while `responses` routes remain unchanged.
The URL must be an absolute loopback HTTP URL (localhost, 127.0.0.1 or ::1),
without userinfo, query or fragment. The proxy requires an API key; it stays
in Codex's supported login cache and never enters agent argv/environment or
ProductionConfig. The operator must sign in with that key under the same
`CODEX_HOME` as the service. Remote providers remain out of scope.

Both Codex adapters receive the frozen setting from ProductionConfig. A shared
builder emits fixed `-c` overrides for provider ID `ase_local_proxy`, name,
`base_url`, `wire_api=responses`, and `requires_openai_auth=true`. The URL is
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
