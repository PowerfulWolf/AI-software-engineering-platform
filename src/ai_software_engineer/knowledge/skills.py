"""Run-bound search/read skills and immutable evidence, without ambient authority."""

from ai_software_engineer.knowledge.models import (
    KnowledgeError,
    KnowledgeEvidence,
    KnowledgeReadRequest,
    KnowledgeRunBinding,
    KnowledgeRunManifest,
    KnowledgeSearchRequest,
    KnowledgeSnapshot,
    digest,
)
from ai_software_engineer.knowledge.retrieval import KnowledgeRetrieval, MarkdownKnowledgeRetrieval
from ai_software_engineer.knowledge.store import KnowledgeRecordStore
from ai_software_engineer.redaction import redact_text


class KnowledgeSkillRegistry:
    def __init__(
        self,
        binding: KnowledgeRunBinding,
        snapshot: KnowledgeSnapshot,
        retrieval: KnowledgeRetrieval,
        records: KnowledgeRecordStore,
    ) -> None:
        snapshot.validate_integrity()
        if (
            binding.team_id,
            binding.project_id,
            binding.requirement_id,
            set(binding.repository_ids),
            binding.snapshot_sha256,
        ) != (
            snapshot.team_id,
            snapshot.project_id,
            snapshot.requirement_id,
            set(snapshot.repository_ids),
            snapshot.snapshot_sha256,
        ):
            raise KnowledgeError("BINDING_SCOPE")
        self.binding = binding
        self._snapshot = snapshot
        self._retrieval = retrieval
        self._records = records
        records.put("bindings", binding.run_id, binding)

    def _allowed_snapshot(self, scopes: tuple[str, ...] = ()) -> KnowledgeSnapshot:
        return KnowledgeSnapshot.create(
            team_id=self._snapshot.team_id,
            project_id=self._snapshot.project_id,
            requirement_id=self._snapshot.requirement_id,
            repository_ids=self._snapshot.repository_ids,
            documents=tuple(
                doc
                for doc in self._snapshot.documents
                if (not doc.roles or self.binding.role in doc.roles)
                and (not scopes or doc.scope in scopes)
            ),
        )

    def search_knowledge(self, request: KnowledgeSearchRequest) -> KnowledgeEvidence:
        old = self._prior(request)
        if old is not None:
            return old
        result = self._base(request, "search_knowledge")
        if request.binding != self.binding:
            return self._publish(result.model_copy(update={"error_code": "IDENTITY_DENIED"}))
        try:
            hits = self._retrieval.search(
                self._allowed_snapshot(request.scopes), request.query, request.limit
            )
            # Adapter output is untrusted: verify every citation against frozen bytes.
            for hit in hits:
                exact = MarkdownKnowledgeRetrieval().read(
                    self._allowed_snapshot(request.scopes), hit.citation
                )
                if hit.snippet != exact.content[:800]:
                    raise KnowledgeError("ADAPTER_OUTPUT")
            result = result.model_copy(update={"status": "HIT" if hits else "MISS", "hits": hits})
        except (KnowledgeError, ValueError):
            result = result.model_copy(update={"error_code": "RETRIEVAL_REJECTED"})
        return self._publish(result)

    def read_knowledge(self, request: KnowledgeReadRequest) -> KnowledgeEvidence:
        old = self._prior(request)
        if old is not None:
            return old
        result = self._base(request, "read_knowledge")
        if request.binding != self.binding:
            return self._publish(result.model_copy(update={"error_code": "IDENTITY_DENIED"}))
        try:
            search = self._records.get("evidence", request.search_evidence_id, KnowledgeEvidence)
            search.validate_integrity()
            if (
                search.binding != self.binding
                or search.status != "HIT"
                or request.citation not in tuple(h.citation for h in search.hits)
            ):
                raise KnowledgeError("READ_WITHOUT_SEARCH")
            chunk = self._retrieval.read(self._allowed_snapshot(search.scopes), request.citation)
            if chunk != MarkdownKnowledgeRetrieval().read(
                self._allowed_snapshot(search.scopes), request.citation
            ):
                raise KnowledgeError("ADAPTER_OUTPUT")
            result = result.model_copy(update={"status": "READ", "chunk": chunk})
        except (KnowledgeError, ValueError):
            result = result.model_copy(update={"error_code": "READ_REJECTED"})
        return self._publish(result)

    def _prior(
        self, request: KnowledgeSearchRequest | KnowledgeReadRequest
    ) -> KnowledgeEvidence | None:
        key = self.binding.run_id + ":" + request.operation_id
        prior = self._records.find("operations", key, KnowledgeEvidence)
        if prior is not None:
            prior.validate_integrity()
            if prior.request_sha256 != digest(request.to_wire()):
                raise KnowledgeError("OPERATION_CONFLICT")
            # The operation receipt is the commit point. Repair an interrupted
            # second publication without performing the query again.
            self._records.put("evidence", prior.evidence_id, prior)
        return prior

    def _base(
        self, request: KnowledgeSearchRequest | KnowledgeReadRequest, operation: str
    ) -> KnowledgeEvidence:
        return KnowledgeEvidence(
            binding=self.binding,
            operation_id=request.operation_id,
            operation="search_knowledge" if operation == "search_knowledge" else "read_knowledge",
            request_sha256=digest(request.to_wire()),
            query=redact_text(request.query).text
            if isinstance(request, KnowledgeSearchRequest)
            else "",
            scopes=request.scopes if isinstance(request, KnowledgeSearchRequest) else (),
            status="REJECTED",
            evidence_id="0" * 64,
        )

    def _publish(self, record: KnowledgeEvidence) -> KnowledgeEvidence:
        sealed = record.model_copy(
            update={"evidence_id": digest(record.model_dump(mode="json", exclude={"evidence_id"}))}
        )
        sealed.validate_integrity()
        self._records.put("operations", self.binding.run_id + ":" + record.operation_id, sealed)
        return self._records.put("evidence", sealed.evidence_id, sealed)

    def manifest(self) -> KnowledgeRunManifest:
        records = tuple(
            item
            for item in self._records.list("operations", KnowledgeEvidence)
            if item.binding == self.binding
        )
        for item in records:
            item.validate_integrity()
            self._records.put("evidence", item.evidence_id, item)
        provisional = KnowledgeRunManifest(
            binding=self.binding,
            snapshot_sha256=self.binding.snapshot_sha256,
            evidence_ids=tuple(sorted(item.evidence_id for item in records)),
            citations=tuple(
                item.chunk.citation
                for item in sorted(records, key=lambda r: r.operation_id)
                if item.status == "READ" and item.chunk is not None
            ),
            manifest_sha256="0" * 64,
        )
        sealed = provisional.model_copy(
            update={
                "manifest_sha256": digest(
                    provisional.model_dump(mode="json", exclude={"manifest_sha256"})
                )
            }
        )
        return self._records.put("manifests", sealed.manifest_sha256, sealed)
