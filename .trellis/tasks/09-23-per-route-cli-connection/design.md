# Design contract

`ProviderRouteConfig.connection_mode` is optional `direct | proxy`, and valid only for
`kind=codex_cli`. `ProductionConfig.effective_connection_mode(route)` returns the explicit
value, or the legacy default (`proxy` when the global loopback URL exists, else `direct`).
`proxy` requires the existing validated `codex_cli_proxy_base_url`; the existing write-only
`codex_cli_proxy_api_key_env` is passed only to proxy routes. Multiple proxy routes share this
one endpoint/credential; this task does not add arbitrary per-route URLs or secrets.

The exact route identity becomes `(provider, model, reasoning_effort, kind,
effective_connection_mode)`. New Agent references, ModelPolicy/Selection, AgentDefinition,
fallback attempts and structured call observations freeze the mode. Optional fields retain old
wire/digest compatibility. Old references without a mode resolve only against one matching
route; old attempts without the mode retain their original digest and display as unknown.

UI normalizes the editable draft to explicit modes, displays the mode on route/Agent choices,
and keeps the shared proxy URL/Key in a connection section. The read-only status and completed
call views show a mode only from their typed facts, never from the current Settings draft.

Validation matrix:

| Case | Expected result |
|---|---|
| Legacy config, URL absent/present | direct/proxy respectively, unchanged behavior |
| Explicit direct plus proxy URL/Key | route uses ordinary CLI and receives neither override nor Key |
| Explicit proxy, loopback URL and Key | route uses the proxy; Key remains write-only |
| Explicit proxy, URL absent | reject before save or Agent construction |
| Responses with `connection_mode` | reject; use its own Endpoint |
| Same model/type/effort, distinct modes | both selectable and frozen independently |
| Old untyped/unmoded reference with two matching modes | reject as ambiguous |
| Old completed call without mode | display unknown, never infer from current config |

No existing Task, Operation or approval is rewritten. Existing mode-free facts and SHA-256
remain immutable; recovery must preserve their history and use normal approval/dispatch paths.
