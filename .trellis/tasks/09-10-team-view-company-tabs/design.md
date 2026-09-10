# Design

- Extend `TeamSnapshot` with a small `{id, name}` company catalog.
- Keep `/api/v1/team` backward compatible and add `/api/v1/team/<company_id>`.
- Discover only direct prepared company workspaces, validate their manifests, and read one company per
  request. Do not combine task facts across companies.
- Derive member display status and three task groups in the browser from committed assignment/task
  facts. Keep `execution_liveness=UNKNOWN` as the runtime truth.
- Preserve text-only rendering and the existing loopback security checks.
