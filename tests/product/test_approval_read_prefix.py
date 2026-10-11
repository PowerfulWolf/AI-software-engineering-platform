"""Complete real-store approval association reads and freshness regressions."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import weakref
from collections import Counter
from collections.abc import Callable
from datetime import timedelta
from pathlib import Path

import pytest

from ai_software_engineer.design import (
    DesignerAgentRequest,
    DesignerAgentResult,
    DesignerInputStale,
    DesignerService,
    FakeDesignerAgentAdapter,
    FakeDesignerBehavior,
    FakeDesignerScenario,
    FileDesignRecordStore,
)
from ai_software_engineer.domain import (
    ProductApprovalDecision,
    ProductSpec,
    ProductSpecApproval,
    ProjectRequest,
    ProjectRequestStatus,
)
from ai_software_engineer.domain.model import DomainModel
from ai_software_engineer.domain.project_delivery import _stage_digest
from ai_software_engineer.product import store as product_store
from ai_software_engineer.product.models import ProjectRequestRevision
from ai_software_engineer.product.store import (
    FileProductRecordStore,
    ProductRecordCorruption,
    ProductRecordPathError,
)
from tests.design.factories import approved_facts, design_for
from tests.product.test_store import NOW, _spec


def _publish(
    root: Path, category: str, request_id: str, filename: str, record: DomainModel
) -> Path:
    target = root / category / request_id / filename
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = record.to_wire()
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    target.write_text(
        json.dumps({"record": payload, "sha256": hashlib.sha256(encoded.encode()).hexdigest()}),
        encoding="utf-8",
    )
    return target


def _history(
    tmp_path: Path, *, requests: int = 3, versions: int = 3
) -> tuple[FileProductRecordStore, tuple[ProductSpec, ...], tuple[ProductSpecApproval, ...]]:
    root = tmp_path / "product"
    store = FileProductRecordStore(root)
    specs: list[ProductSpec] = []
    approvals: list[ProductSpecApproval] = []
    for request_index in range(requests):
        request_id = f"request_prefix_{request_index:03d}"
        request = ProjectRequest.create(
            request_id=request_id,
            repository_id="repository_product_001",
            preparation_sha256="a" * 64,
            title="Linear approval read",
            original_request="Preserve all approved historical facts.",
            status=ProjectRequestStatus.PRODUCT_DISCOVERY,
            created_at=NOW,
        )
        store.put_request_revision(
            ProjectRequestRevision.create(
                request, revision=1, supersedes_sha256=None, recorded_at=NOW
            )
        )
        previous: ProductSpec | None = None
        for version in range(1, versions + 1):
            prototype = _spec()
            spec = ProductSpec.create(
                spec_id=f"product_spec_prefix_{request_index:03d}_{version:03d}",
                request_id=request_id,
                repository_id=request.repository_id,
                version=version,
                status=prototype.status,
                summary=prototype.summary,
                goals=prototype.goals,
                requirements=prototype.requirements,
                acceptance_criteria=prototype.acceptance_criteria,
                supersedes=previous.id if previous else None,
                created_at=NOW + timedelta(minutes=version),
            )
            store.put_product_spec(spec)
            approval = ProductSpecApproval.create(
                spec,
                decision=ProductApprovalDecision.APPROVED,
                operator_id="user_prefix_owner",
                rationale="Exact version approval.",
                decided_at=NOW + timedelta(minutes=version + 20),
            )
            store.put_approval(approval)
            specs.append(spec)
            approvals.append(approval)
            previous = spec
    return store, tuple(specs), tuple(approvals)


def _count_decodes(monkeypatch: pytest.MonkeyPatch) -> Counter[str]:
    counts: Counter[str] = Counter()
    original = product_store._validate_record

    def counted(record: DomainModel) -> None:
        counts[type(record).__name__] += 1
        original(record)

    monkeypatch.setattr(product_store, "_validate_record", counted)
    return counts


def test_real_multi_request_history_decodes_each_record_once_per_lookup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store, specs, approvals = _history(tmp_path)
    counts = _count_decodes(monkeypatch)
    assert store.find_approval(approvals[0].id) == approvals[0]
    assert counts == {"ProductSpec": len(specs), "ProductSpecApproval": len(approvals)}
    assert store.find_approval(approvals[0].id) == approvals[0]
    assert counts == {"ProductSpec": 2 * len(specs), "ProductSpecApproval": 2 * len(approvals)}


def test_real_store_reopens_and_hashes_all_complete_raw_records_before_return(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store, specs, approvals = _history(tmp_path)
    paths: Counter[Path] = Counter()
    original = product_store._read_trusted_product_text

    def observed(root: Path, target: Path) -> product_store._TrustedProductText:
        paths[target] += 1
        return original(root, target)

    monkeypatch.setattr(product_store, "_read_trusted_product_text", observed)
    assert store.find_approval(approvals[0].id) == approvals[0]
    assert len(paths) == len(specs) + len(approvals)
    assert set(paths.values()) == {2}
    assert store.find_approval("product_approval_" + "0" * 64) is None
    assert set(paths.values()) == {4}


def _during_second_approval(monkeypatch: pytest.MonkeyPatch, mutation: Callable[[], None]) -> None:
    original = product_store._validate_record
    count = 0

    def intercepted(record: DomainModel) -> None:
        nonlocal count
        original(record)
        if isinstance(record, ProductSpecApproval):
            count += 1
            if count == 2:
                mutation()

    monkeypatch.setattr(product_store, "_validate_record", intercepted)


def test_append_after_spec_prefix_read_rejects_instead_of_using_old_association(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store, specs, approvals = _history(tmp_path, requests=1)
    target = tmp_path / "product" / "specs" / specs[0].request_id / "00000004.json"

    def mutate() -> None:
        target.write_text("broken", encoding="utf-8")

    _during_second_approval(monkeypatch, mutate)
    with pytest.raises(ProductRecordCorruption):
        store.find_approval(approvals[0].id)


def _replace_spec(spec: ProductSpec, **changes: object) -> ProductSpec:
    changed = spec.model_copy(update=changes)
    return changed.model_copy(
        update={"product_spec_sha256": _stage_digest(changed, "product_spec_sha256", "created_at")}
    )


@pytest.mark.parametrize("mismatch", ["missing", "request", "repository", "digest"])
def test_every_approval_association_remains_exact(tmp_path: Path, mismatch: str) -> None:
    store, specs, approvals = _history(tmp_path, requests=1, versions=1)
    spec = specs[0]
    choices: dict[str, dict[str, object]] = {
        "missing": {"id": "product_spec_missing_001"},
        "request": {"request_id": "request_foreign_001"},
        "repository": {"repository_id": "repository_foreign_001"},
        "digest": {"summary": "A valid but different exact spec body."},
    }
    changes = choices[mismatch]
    fake_spec = _replace_spec(spec, **changes)
    bad = ProductSpecApproval.create(
        fake_spec,
        decision=ProductApprovalDecision.APPROVED,
        operator_id="user_prefix_owner",
        rationale="A valid envelope with a foreign association.",
        decided_at=NOW + timedelta(hours=1),
    )
    original = tmp_path / "product" / "approvals" / spec.request_id / f"{spec.id}.json"
    original.unlink()
    _publish(tmp_path / "product", "approvals", bad.request_id, f"{bad.product_spec_id}.json", bad)
    with pytest.raises(ProductRecordCorruption, match="durable ProductSpec"):
        store.find_approval(approvals[0].id)


def test_referenced_duplicate_spec_and_queried_duplicate_approval_reject(tmp_path: Path) -> None:
    store, specs, approvals = _history(tmp_path, requests=2, versions=1)
    duplicate = _replace_spec(specs[1], id=specs[0].id)
    _publish(tmp_path / "product", "specs", duplicate.request_id, "00000001.json", duplicate)
    with pytest.raises(ProductRecordCorruption, match="duplicate ProductSpec identity"):
        store.find_approval(approvals[0].id)

    other = tmp_path / "other"
    other_store, other_specs, other_approvals = _history(other, requests=2, versions=1)
    duplicate_approval = other_approvals[1].model_copy(update={"id": other_approvals[0].id})
    duplicate_approval = duplicate_approval.model_copy(
        update={"approval_sha256": _stage_digest(duplicate_approval, "approval_sha256")}
    )
    _publish(
        other / "product",
        "approvals",
        other_specs[1].request_id,
        f"{other_specs[1].id}.json",
        duplicate_approval,
    )
    with pytest.raises(ProductRecordCorruption, match="duplicate approval identity"):
        other_store.find_approval(other_approvals[0].id)


def test_unreferenced_duplicate_spec_preserves_original_lookup_semantics(tmp_path: Path) -> None:
    store, specs, approvals = _history(tmp_path, requests=3, versions=1)
    for spec in specs[1:]:
        (tmp_path / "product" / "approvals" / spec.request_id / f"{spec.id}.json").unlink()
    duplicate = _replace_spec(specs[2], id=specs[1].id)
    _publish(tmp_path / "product", "specs", duplicate.request_id, "00000001.json", duplicate)
    assert store.find_approval(approvals[0].id) == approvals[0]


@pytest.mark.parametrize("tail", ["spec", "approval", "sequence", "supersedes", "schema", "inner"])
def test_found_approval_never_hides_corrupt_tail(tmp_path: Path, tail: str) -> None:
    store, specs, approvals = _history(tmp_path, requests=2, versions=2)
    spec = specs[-1]
    root = tmp_path / "product"
    target = root / "specs" / spec.request_id / "00000002.json"
    if tail == "approval":
        target = root / "approvals" / spec.request_id / f"{spec.id}.json"
        target.write_text("{", encoding="utf-8")
    elif tail == "sequence":
        target.rename(target.with_name("00000003.json"))
    elif tail == "supersedes":
        invalid = _replace_spec(spec, supersedes="product_spec_foreign_001")
        _publish(root, "specs", spec.request_id, target.name, invalid)
    elif tail == "inner":
        invalid = spec.model_copy(update={"summary": "Changed without updating the inner digest."})
        _publish(root, "specs", spec.request_id, target.name, invalid)
    elif tail == "schema":
        payload = json.loads(target.read_text())
        payload["record"]["surprise"] = "Not allowed by the actual model."
        payload["sha256"] = product_store._digest(payload["record"])
        target.write_text(json.dumps(payload))
    else:
        target.write_text("{", encoding="utf-8")
    with pytest.raises(ProductRecordCorruption):
        store.find_approval(approvals[0].id)


def test_no_actual_approval_does_not_inspect_unrelated_bad_specs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store, specs, approvals = _history(tmp_path, requests=1, versions=1)
    (tmp_path / "product" / "approvals" / specs[0].request_id / f"{specs[0].id}.json").unlink()
    (tmp_path / "product" / "specs" / specs[0].request_id / "00000001.json").write_text("{")
    counts = _count_decodes(monkeypatch)
    assert store.find_approval(approvals[0].id) is None
    assert counts == {}


@pytest.mark.parametrize(
    "mutation",
    [
        "spec_bytes",
        "approval_bytes",
        "delete",
        "rename",
        "new_request",
        "directory",
        "symlink",
        "directory_symlink",
    ],
)
def test_final_complete_observation_rejects_mid_lookup_changes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mutation: str
) -> None:
    store, specs, approvals = _history(tmp_path, requests=1)
    root = tmp_path / "product"
    request_dir = root / "specs" / specs[0].request_id
    spec_path = request_dir / "00000001.json"
    approval_path = root / "approvals" / specs[0].request_id / f"{specs[0].id}.json"

    def mutate() -> None:
        if mutation in {"spec_bytes", "approval_bytes"}:
            target = spec_path if mutation == "spec_bytes" else approval_path
            before = target.stat()
            content = target.read_bytes()
            changed = (
                content.replace(b"Export", b"EXPORT", 1)
                if mutation == "spec_bytes"
                else content.replace(b"Exact", b"EXACT", 1)
            )
            assert content != changed and len(content) == len(changed)
            target.write_bytes(changed)
            os.utime(target, ns=(before.st_atime_ns, before.st_mtime_ns))
        elif mutation == "delete":
            spec_path.unlink()
        elif mutation == "rename":
            spec_path.rename(spec_path.with_name("00000004.json"))
        elif mutation == "new_request":
            (root / "approvals" / "request_new_001").mkdir()
        elif mutation == "directory":
            backup = tmp_path / "backup"
            request_dir.rename(backup)
            shutil.copytree(backup, request_dir)
        elif mutation == "symlink":
            outside = tmp_path / "outside.json"
            outside.write_bytes(spec_path.read_bytes())
            spec_path.unlink()
            spec_path.symlink_to(outside)
        else:
            backup = tmp_path / "backup"
            request_dir.rename(backup)
            request_dir.symlink_to(backup, target_is_directory=True)

    _during_second_approval(monkeypatch, mutate)
    with pytest.raises((ProductRecordCorruption, ProductRecordPathError)):
        store.find_approval(approvals[0].id)


@pytest.mark.parametrize("bound", ["_APPROVAL_PREFIX_MAX_ENTRIES", "_APPROVAL_PREFIX_MAX_BYTES"])
def test_capacity_overflow_restores_complete_lookup_without_new_validity_limit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, bound: str
) -> None:
    store, specs, approvals = _history(tmp_path)
    monkeypatch.setattr(product_store, bound, 1)
    counts = _count_decodes(monkeypatch)
    assert store.find_approval(approvals[0].id) == approvals[0]
    assert counts["ProductSpec"] == len(specs) * len(approvals)
    assert counts["ProductSpecApproval"] == len(approvals)


def test_partial_capacity_fallback_releases_full_models_and_raw_content_before_old_scan(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store, _, approvals = _history(tmp_path, requests=1)
    model_references: list[weakref.ReferenceType[ProductSpec]] = []
    raw_references: list[weakref.ReferenceType[product_store._TrustedProductText]] = []
    original_validate = product_store._validate_record
    original_read = product_store._read_trusted_product_text
    original_fallback = FileProductRecordStore._find_approval_unindexed
    fallback_count = 0

    def observed_validate(record: DomainModel) -> None:
        original_validate(record)
        if isinstance(record, ProductSpec):
            model_references.append(weakref.ref(record))

    def observed_read(root: Path, target: Path) -> product_store._TrustedProductText:
        content = original_read(root, target)
        raw_references.append(weakref.ref(content))
        return content

    def observed_fallback(
        target_store: FileProductRecordStore, approval_id: str
    ) -> ProductSpecApproval | None:
        nonlocal fallback_count
        fallback_count += 1
        assert len(model_references) >= 2 and raw_references
        assert all(reference() is None for reference in model_references)
        assert all(reference() is None for reference in raw_references)
        return original_fallback(target_store, approval_id)

    monkeypatch.setattr(product_store, "_APPROVAL_PREFIX_MAX_ENTRIES", 9)
    monkeypatch.setattr(product_store, "_validate_record", observed_validate)
    monkeypatch.setattr(product_store, "_read_trusted_product_text", observed_read)
    monkeypatch.setattr(FileProductRecordStore, "_find_approval_unindexed", observed_fallback)
    assert store.find_approval(approvals[0].id) == approvals[0]
    assert fallback_count == 1
    assert all(reference() is None for reference in model_references)
    assert all(reference() is None for reference in raw_references)


def test_prefix_clears_on_success_and_held_exception_without_retaining_spec_models(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store, specs, approvals = _history(tmp_path, requests=1)
    references: list[weakref.ReferenceType[product_store._ApprovalReadPrefix]] = []
    model_references: list[weakref.ReferenceType[ProductSpec]] = []
    original_init = product_store._ApprovalReadPrefix.__init__
    original_validate = product_store._validate_record

    def observed_init(prefix: product_store._ApprovalReadPrefix) -> None:
        original_init(prefix)
        references.append(weakref.ref(prefix))

    def observed_validate(record: DomainModel) -> None:
        original_validate(record)
        if isinstance(record, ProductSpec):
            model_references.append(weakref.ref(record))

    monkeypatch.setattr(product_store._ApprovalReadPrefix, "__init__", observed_init)
    monkeypatch.setattr(product_store, "_validate_record", observed_validate)
    assert store.find_approval(approvals[0].id) == approvals[0]
    assert references[-1]() is None
    assert all(reference() is None for reference in model_references)
    target = tmp_path / "product" / "approvals" / specs[-1].request_id / f"{specs[-1].id}.json"
    target.write_text("{", encoding="utf-8")
    with pytest.raises(ProductRecordCorruption) as held:
        store.find_approval(approvals[0].id)
    assert held.value is not None
    retained = references[-1]()
    assert retained is not None
    assert retained.specs == {} and retained._files == [] and retained._directories == []
    assert all(reference() is None for reference in model_references)


def test_held_bad_spec_tail_error_releases_previously_valid_complete_spec_models(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store, specs, approvals = _history(tmp_path, requests=1)
    target = tmp_path / "product" / "specs" / specs[-1].request_id / "00000003.json"
    target.write_text("{", encoding="utf-8")
    references: list[weakref.ReferenceType[ProductSpec]] = []
    original = product_store._validate_record

    def observed(record: DomainModel) -> None:
        original(record)
        if isinstance(record, ProductSpec):
            references.append(weakref.ref(record))

    monkeypatch.setattr(product_store, "_validate_record", observed)
    with pytest.raises(ProductRecordCorruption) as held:
        store.find_approval(approvals[0].id)
    assert held.value is not None and len(references) == 2
    assert all(reference() is None for reference in references)


@pytest.mark.parametrize("failure", ["changed_final_raw", "bad_spec_tail"])
def test_held_failure_does_not_retain_new_raw_snapshot_wrappers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    store, specs, approvals = _history(tmp_path, requests=1)
    references: list[weakref.ReferenceType[product_store._TrustedProductText]] = []
    original = product_store._read_trusted_product_text

    def observed(root: Path, target: Path) -> product_store._TrustedProductText:
        content = original(root, target)
        references.append(weakref.ref(content))
        return content

    monkeypatch.setattr(product_store, "_read_trusted_product_text", observed)
    if failure == "changed_final_raw":
        target = tmp_path / "product" / "specs" / specs[0].request_id / "00000001.json"

        def mutate() -> None:
            target.write_bytes(target.read_bytes().replace(b"Export", b"EXPORT", 1))

        _during_second_approval(monkeypatch, mutate)
    else:
        (tmp_path / "product" / "specs" / specs[-1].request_id / "00000003.json").write_text("{")
    with pytest.raises(ProductRecordCorruption) as held:
        store.find_approval(approvals[0].id)
    assert held.value is not None and references
    assert all(reference() is None for reference in references)


class _MutatingDesignerAdapter(FakeDesignerAgentAdapter):
    def __init__(self, scenario: FakeDesignerScenario, mutation: Callable[[], None]) -> None:
        super().__init__(default=scenario)
        self.mutation = mutation
        self.calls = 0

    def run(self, request: DesignerAgentRequest) -> DesignerAgentResult:
        self.calls += 1
        self.mutation()
        return super().run(request)


@pytest.mark.parametrize("changed_fact", ["request", "approval"])
def test_real_designer_model_window_retains_fresh_product_fences_and_no_prefix(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, changed_fact: str
) -> None:
    command, store, advancer = approved_facts(tmp_path)
    references: list[weakref.ReferenceType[product_store._ApprovalReadPrefix]] = []
    original_init = product_store._ApprovalReadPrefix.__init__

    def observed_init(prefix: product_store._ApprovalReadPrefix) -> None:
        original_init(prefix)
        references.append(weakref.ref(prefix))

    monkeypatch.setattr(product_store._ApprovalReadPrefix, "__init__", observed_init)

    def mutate() -> None:
        assert references and all(reference() is None for reference in references)
        if changed_fact == "request":
            newer = ProjectRequestRevision.create(
                command.request_revision.request,
                revision=command.request_revision.revision + 1,
                supersedes_sha256=command.request_revision.request_revision_sha256,
                recorded_at=command.submitted_at,
            )
            store.put_request_revision(newer)
        else:
            changed = ProductSpecApproval.create(
                command.product_spec,
                decision=ProductApprovalDecision.REQUEST_CHANGES,
                operator_id="user_owner_001",
                rationale="Scope changed while the offline model was running.",
                decided_at=command.submitted_at,
            )
            _publish(
                tmp_path / "product-records",
                "approvals",
                changed.request_id,
                f"{changed.product_spec_id}.json",
                changed,
            )

    adapter = _MutatingDesignerAdapter(
        FakeDesignerScenario(
            behavior=FakeDesignerBehavior.READY, technical_design=design_for(command)
        ),
        mutate,
    )
    design_store = FileDesignRecordStore(tmp_path / "design-records")
    service = DesignerService(
        design_store=design_store, product_store=store, adapter=adapter, stage_advancer=advancer
    )
    with pytest.raises(DesignerInputStale):
        service.run(command)
    assert adapter.calls == 1 and advancer.calls == 0
    assert design_store.find_run(command.run_id) is None
    assert design_store.find_checkpoint(command.run_id) is None
    assert all(reference() is None for reference in references)
