"""Closed native verifier journals and legacy Manager ownership."""

import hashlib
from pathlib import Path

from ai_software_engineer.domain.engineering_authority import EngineeringScope
from ai_software_engineer.knowledge.models import digest
from ai_software_engineer.knowledge.store import KnowledgeRecordStore
from ai_software_engineer.manager.native_verification_store import (
    NativeRoleVerificationBinding,
    NativeRoleVerificationStore,
)
from ai_software_engineer.manager.verifier_preparation import (
    VerifierPreparationIntent,
    observe_verifier_preparation,
)
from ai_software_engineer.safe_files import _read_regular, _reject_symlinks
from ai_software_engineer.work_queue.invocation import DeliveryInvocationStart


def native_stores(
    sidecar: Path, tasks: set[str], scope: EngineeringScope, *, read_only: bool = True
) -> tuple[NativeRoleVerificationStore, ...]:
    requests = {}
    invocations = sidecar / "state/invocations"
    if invocations.exists():
        for start in KnowledgeRecordStore(invocations, read_only=True).list(
            "invocation-starts", DeliveryInvocationStart
        ):
            start.validate_integrity()
            requests[start.request.run_id] = start.request
    preparations = sidecar / "state/delivery-preflight"
    if preparations.exists():
        for intent in KnowledgeRecordStore(preparations, read_only=True).list(
            "verifier-preparation-intents", VerifierPreparationIntent
        ):
            intent.validate_integrity()
            if (
                intent.request.run_id in requests
                and requests[intent.request.run_id] != intent.request
            ):
                raise ValueError("native verifier request identity differs")
            requests[intent.request.run_id] = intent.request
    selected = []
    for task_id in sorted(tasks):
        root = sidecar / "native-role-verification" / hashlib.sha256(task_id.encode()).hexdigest()
        _reject_symlinks(root)
        if not root.exists():
            continue
        for directory in sorted(root.iterdir()):
            _reject_symlinks(directory)
            binding = NativeRoleVerificationBinding.model_validate_json(
                _read_regular(directory / "binding.json", 8_000_000)
            )
            binding.validate_integrity()
            plan = binding.plan
            if (
                plan.task_id != task_id
                or plan.scope != scope
                or directory.name != hashlib.sha256(plan.run_id.encode()).hexdigest()
            ):
                raise ValueError("native verifier directory owner differs")
            request = requests.get(plan.run_id)
            if request is None:
                raise ValueError("native verifier has no original typed request")
            observed = observe_verifier_preparation(
                repository_workspace_root=sidecar, request=request, lease_id=plan.claim.lease_id
            )
            if observed.native_execution_state == "UNCERTAIN":
                raise ValueError("native verification execution stop cannot be verified")
            store = NativeRoleVerificationStore(root, binding, read_only=read_only)
            if store.root != directory:
                raise ValueError("native verifier Run index differs")
            selected.append(store)
    return tuple(selected)


def legacy_manager_files(
    root: Path, identities: set[str], team_id: str, project_id: str
) -> tuple[Path, ...]:
    from ai_software_engineer.manager.model_execution import ManagerContext, ManagerRunRecord

    if not root.exists():
        return ()
    records = KnowledgeRecordStore(root, read_only=True)
    starts = records.list("manager-start", ManagerRunRecord)
    finals = records.list("manager-final", ManagerRunRecord)
    for namespace, values in (("manager-start", starts), ("manager-final", finals)):
        for run in values:
            if records.get(namespace, run.run_id, ManagerRunRecord) != run:
                raise ValueError("Manager Run index differs")
    owned = [run for run in starts if run.scope.requirement_id in identities]
    selected = []
    foreign_contexts = {
        run.context_manifest_id
        for run in (*starts, *finals)
        if run.scope.requirement_id not in identities
    }
    for episode in {run.scope.episode_id for run in owned}:
        history = sorted(
            (run for run in owned if run.scope.episode_id == episode),
            key=lambda value: value.sequence,
        )
        for sequence, run in enumerate(history, 1):
            if (
                sequence != run.sequence
                or run.state != "STARTED"
                or (run.scope.team_id, run.scope.project_id) != (team_id, project_id)
            ):
                raise ValueError("Manager Run owner/history differs")
            final = records.find("manager-final", run.run_id, ManagerRunRecord)
            if final is not None:
                mutable = {"state", "result", "provider", "model", "error_code"}
                if final.state == "STARTED" or final.model_dump(exclude=mutable) != run.model_dump(
                    exclude=mutable
                ):
                    raise ValueError("Manager final differs from start")
                selected.append(root / records._name("manager-final", run.run_id))
            selected.append(root / records._name("manager-start", run.run_id))
            if run.context_manifest_id in foreign_contexts:
                continue
            sha = run.context_manifest_id.removeprefix("ctx_manager_")
            context = records.get("manager-context", sha, ManagerContext)
            if (
                run.context_manifest_id != "ctx_manager_" + context.input_sha256
                or digest(
                    {
                        "payload": context.payload,
                        "instructions": context.instructions,
                        "schema": context.output_schema,
                    }
                )
                != context.input_sha256
            ):
                raise ValueError("Manager Context identity differs")
            selected.append(root / records._name("manager-context", sha))
    return tuple(sorted(set(selected)))
