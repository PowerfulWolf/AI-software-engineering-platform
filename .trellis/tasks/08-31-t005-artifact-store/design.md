# T005 Technical Design

## Public Seams

| Seam | Input | Output | Failure behavior |
|---|---|---|---|
| `artifact_digest` | typed `Artifact` | lower-case SHA-256 string | deterministic over canonical payload without `integrity` |
| `seal_artifact` | typed `Artifact`, aware validation time | new typed `Artifact` | returns immutable copy with matching digest and `validated=true` |
| `ArtifactStore.put` | sealed typed `Artifact` | `ArtifactRef` | typed integrity, lineage, conflict, or I/O error; no partial write |
| `ArtifactStore.get` | `ArtifactId` | typed `Artifact` | `ArtifactNotFound` or `ArtifactCorruption` |

## On-Disk Layout

```text
artifacts/
└── art_<id>.json
```

The artifact ID is validated by the domain model before it becomes a filename; callers cannot choose arbitrary paths. The file body is canonical JSON, UTF-8 encoded, and ends with a newline only if the writer explicitly adds one (the digest is computed before this presentation detail).

## Integrity Algorithm

1. Serialize `artifact.to_wire()` with sorted keys and compact separators.
2. Remove the top-level `integrity` property.
3. SHA-256 the UTF-8 bytes.
4. `seal_artifact` writes that digest into `ArtifactIntegrity(sha256=..., validated=True, validated_at=...)`.
5. `put` and `get` recompute the digest and compare it to the stored value.

## Lineage Rules

- Every `parent_artifact_ids` entry must resolve through `get` before the child is written;
- parent and child must have the same `task_id`;
- `supersedes`, when present, must resolve to an existing artifact of the same Task and `kind`;
- exact replay of the same wire payload is idempotent, while a changed payload under an existing ID is immutable-conflict.

## Atomic Write

Create a temporary file inside the store root, write and flush canonical JSON, call `os.fsync`, then `os.replace(temp, target)`. Cleanup removes only the generated temporary path after an error. No index is updated before the rename completes.

