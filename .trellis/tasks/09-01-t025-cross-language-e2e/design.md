# T025 Design

```text
fixture project (language/build marker)
        │ read-only discovery
        ▼
ProjectProfile + external ProjectWorkspace + RuntimeWorkspaceBinding
        │
        ├── PolicyBoundToolRegistry (read source, optional local runtime probe)
        │       └── RunEvidenceSession → evidence/ + runs/
        │
        └── FileContextStore + FileArtifactStore + SQLite state
                └── SerialOrchestrator(FakeAgentAdapter)
                    PLAN → IMPLEMENTATION(candidate SHA) → QA PASS
                    → REVIEW APPROVE → DONE
```

The fixture matrix intentionally uses an offline fake adapter.  It verifies the public contracts
and independent role identities without pretending that a provider response or an uninstalled
toolchain is available.
