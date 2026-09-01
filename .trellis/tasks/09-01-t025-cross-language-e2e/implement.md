# T025 Implementation

- Added four dependency-free target fixtures under `fixtures/target-projects/`.
- Added one parametrized e2e matrix covering ProjectProfile language/build discovery, external
  project sidecar and organization binding, typed source read/tool command, redacted evidence
  records and run manifest, and the durable serial Orchestrator artifact chain.
- Runtime probes use `shutil.which`; no dependency installation or network access is attempted.
  Missing Go/Java/Node/Python executables do not mask profile or delivery assertions.
