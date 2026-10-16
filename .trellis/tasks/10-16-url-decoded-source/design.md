# Capture gate and decoder provenance

Existing seam: `source_secret_occurrences(content, source_path=...)` performs bounded Python
syntax/token inspection before a complete independent strong-secret scan. It is used by
`MutationTextBody` and wire readers. Extend its narrow source expression recognition; do not
skip the old base body and do not treat trusted Git history as a secret-scan exemption.

Good: an observed `urllib.parse.unquote` import, used only as an exact decoder callee on a
same-field attribute reference, with no static credential argument, captured as original bytes.
Base: the existing `password=settings.password` source reference still passes.
Bad: unknown decoder, literal secret, import rebinding or no proven import in a partial patch
remains sensitive. Generic redaction still sees the original assignment in all cases.

The isolated regression must change an unrelated line after committing the legal decoder
reference, so it reaches the same BEFORE-body rejection as K1. Existing full-body, patch,
wire, index-only and final inventory checks continue to run. No new persisted contract.
