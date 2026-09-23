# Implementation

- Added optional `connection_mode=direct|proxy` to Codex CLI catalog routes and exact role
  references. Old configs inherit the previous global proxy URL behavior; Settings freezes that
  effective value in its editable draft before the operator changes the shared proxy address.
- Extended frozen ModelPolicy, ModelSelection, AgentDefinition, worker/recovery route checks and
  immutable delivery attempts with the connection dimension. Old facts omit the optional field
  in canonical wire data, preserving their original digest. Ambiguous old references fail closed.
- Both structured and delivery Codex adapters receive proxy URL/Key only for a proxy route.
  Direct routes do not require the proxy Key even when the shared Key is configured.
- Model Routing, Agent choices and runtime status label the selected connection. Completed
  structured and delivery calls read their recorded mode; old calls explicitly show unknown.
  Responses routes keep their own Endpoint/API Key and do not accept Codex connection mode.
- No production credentials, Task/Operation/approval facts or database rows were edited.

The five-field identity is `provider/model/reasoning_effort/kind/effective_connection_mode`.
This does not make CLIProxyAPI a provider type or introduce per-route arbitrary endpoints.
