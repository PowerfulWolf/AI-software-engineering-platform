"""Native upstream and Task-scoped state closure for physical deletion."""

from collections.abc import Mapping
from pathlib import Path

from pydantic import TypeAdapter

from ai_software_engineer.domain.model import DomainModel, WirePayload
from ai_software_engineer.knowledge.models import digest
from ai_software_engineer.knowledge.store import KnowledgeRecordStore
from ai_software_engineer.safe_files import _read_regular, _reject_symlinks


class StateDeletionScope(DomainModel):
    team_id: str
    project_id: str
    repository_id: str
    repository_root: str
    requirement_ids: frozenset[str]
    task_ids: frozenset[str]


def verified_state_record(
    path: Path, sidecar: Path, payload: WirePayload, expected: StateDeletionScope
) -> WirePayload:
    from ai_software_engineer.domain.delivery_resolution import (
        DeliveryResolution,
        DeliveryWaitHandling,
        DeliveryWaitInvestigation,
    )
    from ai_software_engineer.domain.engineering_authority import EngineeringAdmission
    from ai_software_engineer.domain.stopped_budget_settlement import StoppedFailureBudgetSettlement
    from ai_software_engineer.manager.context_capacity import ContextCapacityReceipt
    from ai_software_engineer.manager.delivery_preflight import (
        DeliveryPreflightCheckpoint,
        DeliveryPreflightReceipt,
    )
    from ai_software_engineer.manager.verifier_preparation import (
        VerifierPreparationCheckpoint,
        VerifierPreparationIntent,
    )
    from ai_software_engineer.orchestration.continuation_capture import CapturedMutations

    models: Mapping[str, type[DomainModel]] = {
        "stopped-budget-handlings": DeliveryWaitHandling,
        "stopped-budget-captures": CapturedMutations,
        "stopped-budget-settlements": StoppedFailureBudgetSettlement,
        "wait-investigations": DeliveryWaitInvestigation,
        "wait-handling-proofs": DeliveryWaitInvestigation,
        "wait-resolutions": DeliveryResolution,
        "wait-handlings": DeliveryWaitHandling,
        "wait-handling-resolutions": DeliveryWaitHandling,
        "wait-prerequisites": DeliveryPreflightReceipt,
        "preflight-receipts": DeliveryPreflightReceipt,
        "preflight-checkpoints": DeliveryPreflightCheckpoint,
        "context-capacity-receipts": ContextCapacityReceipt,
        "verifier-preparation-intents": VerifierPreparationIntent,
        "verifier-preparations": VerifierPreparationCheckpoint,
        "engineering-admission": EngineeringAdmission,
    }
    from ai_software_engineer.manager.rejected_output_checkpoint import (
        RejectedCoderOutputCheckpoint,
        read_rejected_checkpoint,
    )

    if path.parent == sidecar / "state/rejected-coder-output":
        rejected = KnowledgeRecordStore._decode_payload(
            _read_regular(path, 64 * 1024 * 1024), RejectedCoderOutputCheckpoint
        )
        work_id = rejected.outcome.start.work_item_id
        verified = read_rejected_checkpoint(sidecar / "state", work_id)
        if verified != rejected or path.name != KnowledgeRecordStore._name(
            "rejected-checkpoints", work_id
        ):
            raise ValueError("rejected checkpoint storage key differs")
        start = rejected.capture_start
        if (
            start.request.task_id not in expected.task_ids
            or start.claim.work_item.task_id != start.request.task_id
            or start.claim.work_item.repository_scopes != (expected.repository_root,)
        ):
            raise ValueError("rejected checkpoint Task/Repository differs")
        _validate_scope(start.scope.to_wire(), expected)
        return rejected.to_wire()
    if path.parent == sidecar / "state/rejected-knowledge":
        rejected_record = _rejected_knowledge_record(path, sidecar)
        from ai_software_engineer.knowledge.assessment_rejection import (
            read_historical_rejected_assessment,
        )
        from ai_software_engineer.manager.rejected_knowledge_preparation import (
            RejectedKnowledgeCarryRefusal,
        )

        # The claim alone has no Team/Project/Requirement identity. Reopen the
        # exact original semantic observation before accepting deletion scope.
        observation = read_historical_rejected_assessment(
            sidecar / "knowledge/runs", str(rejected_record.to_wire()["observation_sha256"])
        )
        record_task_id = (
            rejected_record.claim.work_item.task_id
            if isinstance(rejected_record, RejectedKnowledgeCarryRefusal)
            else str(rejected_record.to_wire()["task_id"])
        )
        if observation.binding.task_id != record_task_id or record_task_id not in expected.task_ids:
            raise ValueError("rejected knowledge Task differs")
        # The documented legacy knowledge/continuation lane may name this exact
        # verified Task as its Requirement. No sibling Task becomes an alias.
        exact = expected.model_copy(
            update={
                "task_ids": frozenset({record_task_id}),
                "requirement_ids": expected.requirement_ids | {record_task_id},
            }
        )
        validate_declared_scopes(observation.to_wire(), exact)
        validate_declared_scopes(rejected_record.to_wire(), exact)
        return rejected_record.to_wire()
    namespace = next((name for name in models if path.name.startswith(name + "-")), None)
    if namespace is None:
        raise ValueError(
            "unsupported owned state contract: " + path.relative_to(sidecar).as_posix()
        )
    record = KnowledgeRecordStore._decode_payload(
        _read_regular(path, 64 * 1024 * 1024), models[namespace]
    )
    if isinstance(record, CapturedMutations):
        # Its formal model validator checks each body and recomputes the complete
        # WorktreeMutationCapture digest; it has no validate_integrity method.
        CapturedMutations.model_validate(record.to_wire())
    else:
        validate = getattr(record, "validate_integrity", None)
        if not callable(validate):
            raise ValueError("state record lacks sealed integrity")
        validate()
    wire = record.to_wire()
    validate_declared_scopes(wire, expected)
    # Reject duplicate owner claims even if a legitimate Task ID also appears.
    task_id = wire.get("task_id")
    if task_id is not None and task_id not in expected.task_ids:
        raise ValueError("state Task differs")
    keys: set[str] = set()
    if isinstance(record, DeliveryPreflightReceipt):
        keys.add(record.receipt_sha256)
    elif isinstance(record, DeliveryPreflightCheckpoint):
        keys.add(record.work_item_id + ":" + record.receipt_sha256)
    elif isinstance(record, ContextCapacityReceipt):
        keys.add(record.receipt_sha256)
    elif isinstance(record, VerifierPreparationIntent):
        keys.add(f"{record.work_item_id}:{record.checkpoint_sequence}:{record.dispatch_sequence}")
    elif isinstance(record, VerifierPreparationCheckpoint):
        keys.add(record.checkpoint_sha256)
    elif isinstance(record, CapturedMutations):
        keys.add(record.capture_sha256)
    elif isinstance(record, StoppedFailureBudgetSettlement):
        keys.add(record.settlement_sha256)
    elif isinstance(record, EngineeringAdmission):
        keys.add(record.plan_sha256)
    elif isinstance(record, DeliveryResolution):
        keys.add(record.work_item_id + ":" + record.expected_disposition_sha256)
    elif isinstance(record, DeliveryWaitHandling):
        from ai_software_engineer.domain.delivery_resolution import (
            HandleDeliveryWait,
            ResolveDeliveryWait,
        )

        proof = record.investigation
        command = HandleDeliveryWait(
            work_item_id=proof.work_item_id,
            expected_disposition_sha256=proof.disposition_sha256,
            expected_task_intent_sha256=proof.task_intent_sha256,
            expected_source_revision=proof.source_revision,
            expected_checkpoint_sequence=proof.checkpoint_sequence,
        )
        if namespace == "wait-handlings":
            keys.add(record.record_key)
        else:
            keys.add(digest(command.to_wire()))
            if record.resolution is not None:
                resolution = record.resolution
                resolved = ResolveDeliveryWait.model_validate(
                    {
                        **command.to_wire(),
                        "resolution_kind": resolution.resolution_kind,
                        "proof_sha256": resolution.proof_sha256,
                        "submitted_at": resolution.submitted_at,
                    }
                )
                keys.add(digest(resolved.to_wire()))
    elif isinstance(record, DeliveryWaitInvestigation):
        if namespace == "wait-investigations":
            keys.add(record.proof_sha256)
        else:
            from ai_software_engineer.domain.delivery_resolution import (
                DeliveryWaitCollectionFailure,
                InspectDeliveryWait,
                delivery_wait_handling_record_key,
            )

            inspection = InspectDeliveryWait(
                work_item_id=record.work_item_id,
                expected_disposition_sha256=record.disposition_sha256,
                expected_task_intent_sha256=record.task_intent_sha256,
                expected_source_revision=record.source_revision,
                expected_checkpoint_sequence=record.checkpoint_sequence,
            )
            # These are the finite typed producer parameters. A crash may leave
            # the frozen proof before any sibling handling has been published.
            for manual in (False, True):
                for failed in (False, True):
                    for failure in (None, *DeliveryWaitCollectionFailure):
                        if failure is not None and not failed:
                            continue
                        keys.add(
                            delivery_wait_handling_record_key(
                                inspection,
                                record,
                                manual_resolution_allowed=manual,
                                collection_failed=failed,
                                collection_failure=failure,
                            )
                        )
    expected_names = {KnowledgeRecordStore._name(namespace, key) for key in keys}
    if isinstance(record, EngineeringAdmission):
        from ai_software_engineer.recovery.store import FileRecoveryStore

        expected_names = {FileRecoveryStore._name(namespace, key) for key in keys}
    if path.name not in expected_names:
        raise ValueError("state storage namespace/key differs: " + namespace)
    return wire


def _rejected_knowledge_record(path: Path, sidecar: Path) -> DomainModel:
    """Decode only the real shared-directory writer contracts and canonical keys."""
    if path.parent != sidecar / "state/rejected-knowledge":
        raise ValueError("rejected knowledge storage directory differs")
    if path.name.startswith("carry-refusals-"):
        from ai_software_engineer.manager.rejected_knowledge_preparation import (
            RejectedKnowledgeCarryRefusal,
        )

        carry = KnowledgeRecordStore._decode_payload(
            _read_regular(path, 64 * 1024 * 1024), RejectedKnowledgeCarryRefusal
        )
        carry.validate_integrity()
        if path.name != KnowledgeRecordStore._name("carry-refusals", carry.claim.lease.id):
            raise ValueError("rejected knowledge carry storage key differs")
        return carry
    if path.name.startswith("current-drafts-"):
        from ai_software_engineer.manager.rejected_knowledge_draft import (
            RejectedKnowledgeCurrentDraft,
            read_current_draft,
        )

        draft = KnowledgeRecordStore._decode_payload(
            _read_regular(path, 64 * 1024 * 1024), RejectedKnowledgeCurrentDraft
        )
        if (
            path.name != KnowledgeRecordStore._name("current-drafts", draft.record_sha256)
            or read_current_draft(sidecar / "state", draft.record_sha256) != draft
        ):
            raise ValueError("rejected knowledge current draft storage key differs")
        return draft
    raise ValueError("unsupported rejected knowledge state contract")


def rejected_knowledge_files(sidecar: Path, expected: StateDeletionScope) -> tuple[Path, ...]:
    """Select exact owned files, keeping other Tasks in this shared directory."""
    root = sidecar / "state/rejected-knowledge"
    _reject_symlinks(root)
    if not root.exists():
        return ()
    selected = []
    from ai_software_engineer.manager.rejected_knowledge_preparation import (
        RejectedKnowledgeCarryRefusal,
    )

    for path in sorted(root.iterdir()):
        record = _rejected_knowledge_record(path, sidecar)
        task_id = (
            record.claim.work_item.task_id
            if isinstance(record, RejectedKnowledgeCarryRefusal)
            else str(record.to_wire()["task_id"])
        )
        if task_id not in expected.task_ids:
            continue
        verified_state_record(path, sidecar, {}, expected)
        selected.append(path)
    return tuple(selected)


def validate_declared_scopes(wire: WirePayload, expected: StateDeletionScope) -> None:
    """Validate only formal ownership positions, never arbitrary descriptions."""
    records = [wire]
    for record in records:
        _validate_scope(record, expected)
        task_id = record.get("task_id")
        if task_id is not None and task_id not in expected.task_ids:
            raise ValueError("state Task differs")
        task = record.get("task")
        if isinstance(task, dict) and task.get("id") not in expected.task_ids:
            raise ValueError("state Task snapshot differs")
        repository = record.get("repository")
        if repository is not None and repository != expected.repository_root:
            raise ValueError("state Repository path differs")
        scopes = record.get("repository_scopes")
        if scopes is not None and scopes != [expected.repository_root]:
            raise ValueError("state claim Repository differs")
        invocations = record.get("invocations")
        if isinstance(invocations, list):
            records.extend(item for item in invocations if isinstance(item, dict))
        for field in (
            "scope",
            "binding",
            "manifest",
            "progress",
            "publication",
            "start",
            "outcome",
            "capture",
            "capture_stop",
            "assignment",
            "policy",
            "engineering_policy",
            "investigation",
            "resolution",
            "engineering_admission",
            "rejected_output",
            "rejected_workspace_admission",
            "rejected_knowledge",
            "declaration",
            "knowledge_preparation",
            "identity",
            "facts",
            "task",
            "request",
            "new_request",
            "plan",
            "previous_binding",
            "original_start",
            "capture_start",
            "original_claim",
            "claim",
            "work_item",
            "lease",
            "legacy_containment",
            "completed_output",
            "stopped_provider_failure",
            "stopped_failure",
            "native_rule_change",
            "target",
        ):
            nested = record.get(field)
            if isinstance(nested, dict):
                records.append(nested)


def _validate_scope(scope: WirePayload, expected: StateDeletionScope) -> None:
    for field in ("team_id", "project_id", "repository_id", "repository_root"):
        if field in scope and scope[field] != getattr(expected, field):
            raise ValueError("state " + field + " differs")
    repository_ids = scope.get("repository_ids")
    if repository_ids is not None and repository_ids != [expected.repository_id]:
        raise ValueError("state Repository identities differs")
    for field in ("requirement_id", "delivery_id"):
        value = scope.get(field)
        if value is not None and value not in expected.requirement_ids:
            raise ValueError("state Requirement differs")


def task_state_directories(sidecar: Path, expected: StateDeletionScope) -> tuple[Path, ...]:
    from ai_software_engineer.domain.engineering_authority import EngineeringAdmission
    from ai_software_engineer.domain.execution_baseline import ExecutionBaselineBinding
    from ai_software_engineer.domain.execution_native_rules import NativeRuleEpoch
    from ai_software_engineer.manager.baseline_models import (
        BaselineContinueAuthorization,
        BaselineOperationStart,
        BaselineOperatorAuthorization,
        ExecutionBaselinePlan,
    )
    from ai_software_engineer.manager.baseline_production import BaselineQuiescenceProof
    from ai_software_engineer.manager.baseline_store import FileExecutionBaselineStore
    from ai_software_engineer.manager.workspace_admission_contract import (
        WorkspaceAdmissionAdapterContractStore,
    )
    from ai_software_engineer.orchestration.continuation_store import FileContinuationStore

    selected = []
    for task_id in sorted(expected.task_ids):
        continuation = sidecar / "state/continuations" / task_id
        _reject_symlinks(continuation)
        if continuation.exists():
            records = FileContinuationStore(continuation, task_id=task_id)
            validated: dict[str, DomainModel] = {}
            for receipt in records.receipts_for_task(task_id):
                name = (
                    "receipt.json"
                    if receipt.schema_version == "v1"
                    else (f"receipt-{receipt.request.run_id}.json")
                )
                validated[name] = receipt
            for admission in records.admissions_for_task(task_id):
                name = (
                    "admission.json"
                    if admission.schema_version == "v1"
                    else (f"admission-{admission.new_request.run_id}.json")
                )
                validated[name] = admission
            for path in continuation.glob("capture-start-*.json"):
                start = records.capture_start(path.stem.removeprefix("capture-start-"))
                if start.claim.work_item.repository_scopes != (expected.repository_root,):
                    raise ValueError("continuation claim Repository differs")
                validated[path.name] = start
            for path in continuation.glob("capture-stop-*.json"):
                validated[path.name] = records.capture_stop(path.stem.removeprefix("capture-stop-"))
            supported_names = set(validated)
            declarations = WorkspaceAdmissionAdapterContractStore(sidecar / "state", task_id)
            _reject_symlinks(declarations.root)
            if declarations.root.exists():
                testimony = declarations.list_for_task()
                names = {
                    KnowledgeRecordStore._name("adapter-declarations", item.declaration.run_id)
                    for item in testimony
                }
                if {path.name for path in declarations.root.iterdir()} != names:
                    raise ValueError("unsupported workspace admission declaration record")
                for declaration in testimony:
                    validate_declared_scopes(declaration.to_wire(), expected)
                supported_names.add(declarations.root.name)
            if {path.name for path in continuation.iterdir()} != supported_names:
                raise ValueError("unsupported continuation record")
            for record in validated.values():
                validate_declared_scopes(record.to_wire(), expected)
            selected.append(continuation)
        baseline = sidecar / "state/execution-baselines" / task_id
        _reject_symlinks(baseline)
        if baseline.exists():
            store = FileExecutionBaselineStore(baseline, read_only=True)
            models: Mapping[str, type[DomainModel]] = {
                "baseline-plans": ExecutionBaselinePlan,
                "baseline-starts": BaselineOperationStart,
                "baseline-bindings": ExecutionBaselineBinding,
                "baseline-native-rules": NativeRuleEpoch,
                "baseline-quiescence": BaselineQuiescenceProof,
                "baseline-continuations": BaselineContinueAuthorization,
            }
            for path in sorted(baseline.iterdir()):
                if path.name == "execution.lock":
                    _read_regular(path, 256_000)
                    continue
                namespace = next(
                    (name for name in models if path.name.startswith(name + "-")), None
                )
                model: type[DomainModel]
                data = _read_regular(path, 64 * 1024 * 1024)
                if namespace is None and path.name.startswith("baseline-authorities-"):
                    namespace = "baseline-authorities"
                    envelope: WirePayload = TypeAdapter(WirePayload).validate_json(data)
                    body = envelope.get("record")
                    if not isinstance(body, dict):
                        raise ValueError("baseline authority envelope differs")
                    model = (
                        EngineeringAdmission
                        if body.get("kind") == "engineering_admission"
                        else BaselineOperatorAuthorization
                    )
                    record = KnowledgeRecordStore._decode_payload(data, model)
                elif namespace is not None:
                    model = models[namespace]
                    record = KnowledgeRecordStore._decode_payload(data, model)
                else:
                    raise ValueError("unsupported baseline record")
                validate = getattr(record, "validate_integrity", None)
                if callable(validate):
                    validate()
                validate_declared_scopes(record.to_wire(), expected)
                if isinstance(record, ExecutionBaselineBinding):
                    key = f"{record.task_id}:{record.sequence}"
                elif isinstance(record, BaselineContinueAuthorization):
                    key = record.execution_baseline_sha256
                elif isinstance(record, NativeRuleEpoch):
                    key = record.epoch_sha256
                elif isinstance(record, BaselineQuiescenceProof):
                    key = digest(record.to_wire())
                elif isinstance(record, BaselineOperationStart):
                    key = record.plan.plan_sha256
                    if store.plan(key) != record.plan:
                        raise ValueError("baseline start plan differs")
                else:
                    key = str(record.to_wire()["plan_sha256"])
                    if namespace == "baseline-authorities":
                        store.plan(key)
                if path.name != KnowledgeRecordStore._name(namespace, key):
                    raise ValueError("baseline storage key differs")
            # This reader validates every retained predecessor and exact authority.
            store.bindings_for_task(task_id)
            selected.append(baseline)
    return tuple(selected)


def upstream_files(sidecar: Path, native_ids: set[str], repository_id: str) -> tuple[Path, ...]:
    from ai_software_engineer.design.models import DesignCommitCheckpoint, DesignRunRecord
    from ai_software_engineer.design.store import FileDesignRecordStore
    from ai_software_engineer.domain.project_delivery import ProductSpec, ProductSpecApproval
    from ai_software_engineer.manager.delivery_checkpoint import FileProjectDeliveryCheckpointStore
    from ai_software_engineer.planning.models import PlannerCommitCheckpoint, PlannerRunRecord
    from ai_software_engineer.planning.store import FileExecutionPlanStore
    from ai_software_engineer.product.models import (
        ProductDialogueRecord,
        ProductDiscoveryCheckpoint,
        ProductOperationRecord,
        ProjectRequestRevision,
    )
    from ai_software_engineer.product.store import FileProductRecordStore

    selected = []
    requests = set()
    native_root = sidecar / "state/project-deliveries"
    if native_root.exists():
        native = FileProjectDeliveryCheckpointStore(native_root, read_only=True)
        for delivery_id in native_ids:
            for checkpoint in native.list(delivery_id):
                if checkpoint.repository_id != repository_id:
                    raise ValueError("native checkpoint Repository differs")
                if checkpoint.request_id is not None:
                    requests.add(checkpoint.request_id)
    product_root = sidecar / "state/product"
    if product_root.exists():
        products = FileProductRecordStore(product_root, read_only=True)
        for category in ("requests", "dialogue", "specs", "approvals", "checkpoint-history"):
            for request_id in sorted(requests):
                directory = product_root / category / request_id
                _reject_symlinks(directory)
                for path in sorted(directory.glob("*.json")):
                    if category == "requests":
                        record: DomainModel = products.get_request_revision(
                            request_id, int(path.stem)
                        )
                        assert isinstance(record, ProjectRequestRevision)
                        owner = record.request.repository_id
                    elif category == "dialogue":
                        record = products.get_dialogue(request_id, int(path.stem))
                        assert isinstance(record, ProductDialogueRecord)
                        owner = record.repository_id
                    elif category == "specs":
                        record = products.get_product_spec(request_id, int(path.stem))
                        assert isinstance(record, ProductSpec)
                        owner = record.repository_id
                    elif category == "approvals":
                        record = products.get_approval(request_id, path.stem)
                        assert isinstance(record, ProductSpecApproval)
                        owner = record.repository_id
                    else:
                        record = products.get_checkpoint(request_id, int(path.stem))
                        assert isinstance(record, ProductDiscoveryCheckpoint)
                        owner = record.repository_id
                    if owner != repository_id:
                        raise ValueError("upstream Product Repository differs")
                    selected.append(path)
        for path in sorted((product_root / "operations").glob("*.json")):
            operation = products.get_operation(path.stem)
            assert isinstance(operation, ProductOperationRecord)
            if operation.request_id in requests:
                selected.append(path)
    design_root = sidecar / "state/design"
    if design_root.exists():
        designs = FileDesignRecordStore(design_root, read_only=True)
        for category in ("designs", "runs", "checkpoints"):
            for path in sorted((design_root / category).glob("*.json")):
                if category == "designs":
                    record = designs.get_design(path.stem)
                elif category == "runs":
                    run = designs.get_run(path.stem)
                    assert isinstance(run, DesignRunRecord)
                    record = run
                else:
                    commit = designs.get_checkpoint(path.stem)
                    assert isinstance(commit, DesignCommitCheckpoint)
                    record = commit
                wire = record.to_wire()
                if wire.get("request_id") in requests:
                    if wire.get("repository_id") != repository_id:
                        raise ValueError("Design Repository differs")
                    selected.append(path)
    planning_root = sidecar / "state/planning"
    if planning_root.exists():
        plans = FileExecutionPlanStore(planning_root, read_only=True)
        for category in ("execution-plans", "runs", "checkpoints", "decisions"):
            for path in sorted((planning_root / category).glob("*.json")):
                if category == "execution-plans":
                    record = plans.get_execution_plan(path.stem)
                elif category == "runs":
                    planner_run = plans.get_run(path.stem)
                    assert isinstance(planner_run, PlannerRunRecord)
                    record = planner_run
                elif category == "checkpoints":
                    planner_commit = plans.get_checkpoint(path.stem)
                    assert isinstance(planner_commit, PlannerCommitCheckpoint)
                    record = planner_commit
                else:
                    record = plans.get_planning_decision(path.stem)
                wire = record.to_wire()
                if wire.get("request_id") in requests:
                    if wire.get("repository_id") not in (None, repository_id):
                        raise ValueError("Planner Repository differs")
                    selected.append(path)
    return tuple(selected)
