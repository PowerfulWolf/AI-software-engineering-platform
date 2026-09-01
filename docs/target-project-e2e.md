# T025 Target-project serial delivery fixture

T025 is the first cross-language acceptance seam for the platform.  It demonstrates that the
target repository can be any local project while AI metadata remains in an external sidecar.

## Fixture matrix

| Fixture | Profile facts | Optional probe | Source read |
|---|---|---|---|
| `python` | Python / Python build | `python3 --version` | `src/hello.py` |
| `java` | Java / Maven | `java -version` | `src/main/java/example/App.java` |
| `go` | Go / Go modules | `go version` | `main.go` |
| `typescript` | TypeScript / npm | `node --version` | `src/hello.ts` |

The probe is run only when the executable is already installed.  Tests never install packages or
contact a registry, so offline CI stays deterministic.  A missing toolchain does not skip profile,
sidecar, typed source-read, evidence setup, or the serial delivery assertions.

## What the test proves

1. `ProjectProfile.discover` reads language/build/native-rule facts without writing the target.
2. `ProjectWorkspaceRegistry` and `RuntimeWorkspaceBinder` place state, contexts, artifacts,
   evidence, runs, and SQLite outside the target source directory.
3. `PolicyBoundToolRegistry` exposes only typed file/argv operations.  A command probe is adapted
   to `RunEvidenceSession`, which persists command and test records plus a sealed run manifest.
4. `SerialOrchestrator` consumes explicit `FileContextStore` and `FileArtifactStore` records and
   drives independent orchestrator/coder/QA/reviewer identities through
   `PLANNING → IMPLEMENTING → QA → REVIEW → DONE`.
5. The implementation report's candidate SHA is echoed by QA and Reviewer; all four artifacts and
   context manifests are durable and replayable.

Run it locally with:

```bash
PYTEST_ADDOPTS='-p no:cacheprovider' .venv/bin/pytest -q tests/e2e
```
