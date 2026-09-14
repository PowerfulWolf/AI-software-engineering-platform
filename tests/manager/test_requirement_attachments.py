"""Requirement screenshots are immutable, digest-bound sidecar artifacts."""

from collections.abc import Mapping
from pathlib import Path
from typing import NoReturn

import pytest

from ai_software_engineer.agents import StructuredModelClient, StructuredModelResult
from ai_software_engineer.domain import TeamRole
from ai_software_engineer.manager.delivery import ReplyToProduct
from ai_software_engineer.multi_directory.attachments import (
    RequirementAttachmentError,
    RequirementAttachmentStore,
)
from ai_software_engineer.multi_directory.models import (
    JointCheckpoint,
    JointExecutionPlan,
    JointStage,
)
from ai_software_engineer.multi_directory.scope import DirectoryScope, DirectoryUnit
from ai_software_engineer.multi_directory.service import JointDeliveryService
from ai_software_engineer.team_workspace import TeamWorkspace
from tests.e2e.test_joint_delivery import JointModels
from tests.manager.test_joint_contracts import checkpoint

DELIVERY_ID = "delivery_multi_" + "a" * 40


def _store(tmp_path: Path) -> RequirementAttachmentStore:
    requirements = tmp_path / "requirements"
    (requirements / DELIVERY_ID).mkdir(parents=True)
    return RequirementAttachmentStore(requirements, project_id="project_test")


def test_screenshot_round_trip_is_idempotent_and_content_addressed(tmp_path: Path) -> None:
    store = _store(tmp_path)
    content = b"\x89PNG\r\n\x1a\nfixture"

    first = store.put(DELIVERY_ID, filename="checkout.png", content=content)
    replay = store.put(DELIVERY_ID, filename="checkout.png", content=content)

    assert replay == first
    assert first.media_type == "image/png"
    assert first.source_name == "checkout.png"
    assert store.get(DELIVERY_ID, first.id) == first
    assert store.source_path(first).read_bytes() == content
    assert first.source_relative_path.startswith(f"attachments/{first.id}/")


def test_screenshot_rejects_unsupported_content_and_detects_tampering(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    with pytest.raises(RequirementAttachmentError, match="PNG, JPEG and WebP"):
        store.put(DELIVERY_ID, filename="notes.txt", content=b"not-an-image")

    stored = store.put(
        DELIVERY_ID,
        filename="screen.jpg",
        content=b"\xff\xd8\xfffixture",
    )
    store.source_path(stored).write_bytes(b"\xff\xd8\xffchanged")
    with pytest.raises(RequirementAttachmentError, match="digest changed"):
        store.get(DELIVERY_ID, stored.id)


class _ProductBackend(StructuredModelClient):
    def __init__(self) -> None:
        self.models = JointModels()
        self.roles: list[TeamRole] = []
        self.images: tuple[Path, ...] = ()

    def client(self, scope: DirectoryScope, role: TeamRole) -> StructuredModelClient:
        del scope
        self.roles.append(role)
        return self

    def complete(
        self,
        *,
        instructions: str,
        input_payload: Mapping[str, object],
        output_schema: Mapping[str, object],
        timeout_seconds: int,
        input_images: tuple[Path, ...] = (),
    ) -> StructuredModelResult:
        self.images = input_images
        return self.models.complete(
            instructions=instructions,
            input_payload=input_payload,
            output_schema=output_schema,
            timeout_seconds=timeout_seconds,
        )

    def reconcile(self, checkpoint: JointCheckpoint) -> None:
        del checkpoint

    def prepare(self, unit: DirectoryUnit) -> NoReturn:
        del unit
        raise AssertionError("Requirement is already prepared")

    def deliver(self, checkpoint: JointCheckpoint, unit_id: str) -> NoReturn:
        del checkpoint, unit_id
        raise AssertionError("Product approval has not been granted")

    def integrate(self, checkpoint: JointCheckpoint) -> NoReturn:
        del checkpoint
        raise AssertionError("Product approval has not been granted")

    def validate_plan(self, checkpoint: JointCheckpoint, plan: JointExecutionPlan) -> None:
        del checkpoint, plan


def test_product_agent_receives_only_bound_screenshot_paths(tmp_path: Path) -> None:
    base = checkpoint(tmp_path)
    team = TeamWorkspace.initialize(tmp_path / "platform", team_id="team_test", name="Test")
    project = team.project_registry().register(project_id="project_test", name="Test Project")
    backend = _ProductBackend()
    service = JointDeliveryService(backend=backend, team=team, project=project)
    seed = JointCheckpoint.seal(
        {
            **base.to_wire(),
            "team_manifest_sha256": team.manifest.manifest_sha256,
            "project_manifest_sha256": project.manifest.manifest_sha256,
            "sequence": 1,
            "previous_checkpoint_sha256": None,
            "stage": JointStage.READY_FOR_DISCUSSION,
            "preparations": (),
            "dialogue": (),
            "product_spec": None,
            "approval": None,
            "design": None,
            "plan": None,
            "children": (),
            "integration": None,
            "attempts": {},
            "next_action": "Discuss the Requirement.",
        }
    )
    service.journal.append(seed, expected=None)
    screenshot = service.attachments.put(
        seed.delivery_id,
        filename="checkout.png",
        content=b"\x89PNG\r\n\x1a\nfixture",
    )

    result = service.reply(
        ReplyToProduct(
            delivery_id=seed.delivery_id,
            expected_checkpoint_sha256=seed.checkpoint_sha256,
            screenshot_ids=(screenshot.id,),
        )
    )

    assert result.checkpoint.stage is JointStage.WAITING_PRODUCT_APPROVAL
    assert result.checkpoint.dialogue[0].screenshots == (screenshot,)
    assert backend.roles == [TeamRole.PRODUCT]
    assert len(backend.images) == 1
    assert backend.images[0].read_bytes().startswith(b"\x89PNG")
