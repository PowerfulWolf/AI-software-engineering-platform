"""Published knowledge wire contracts must track their runtime validation models."""

import json
from pathlib import Path

import pytest

from ai_software_engineer.domain.model import DomainModel
from ai_software_engineer.knowledge.administration import KnowledgeHumanActionEvent
from ai_software_engineer.knowledge.agents import KnowledgeConsultation, KnowledgeModelCall
from ai_software_engineer.knowledge.delivery import DeliveryWorkflowAdmission, DeliveryWorkflowProof
from ai_software_engineer.knowledge.evaluation import KnowledgeEvaluationReport
from ai_software_engineer.knowledge.gaps import KnowledgeGap, KnowledgeResolution, KnowledgeResume
from ai_software_engineer.knowledge.models import (
    KnowledgeEvidence,
    KnowledgeReadRequest,
    KnowledgeRunManifest,
    KnowledgeSearchRequest,
    KnowledgeSnapshot,
)
from ai_software_engineer.knowledge.stages import StageWorkflowProof
from ai_software_engineer.knowledge.workflow import WorkflowSkillEvidence

MODELS: dict[str, type[DomainModel]] = {
    "knowledge-consultation": KnowledgeConsultation,
    "knowledge-model-call": KnowledgeModelCall,
    "knowledge-delivery-proof": DeliveryWorkflowProof,
    "knowledge-delivery-admission": DeliveryWorkflowAdmission,
    "knowledge-resume": KnowledgeResume,
    "knowledge-stage-workflow": StageWorkflowProof,
    "knowledge-evaluation": KnowledgeEvaluationReport,
    "knowledge-evidence": KnowledgeEvidence,
    "knowledge-gap": KnowledgeGap,
    "knowledge-human-action": KnowledgeHumanActionEvent,
    "knowledge-read": KnowledgeReadRequest,
    "knowledge-resolution": KnowledgeResolution,
    "knowledge-run-manifest": KnowledgeRunManifest,
    "knowledge-search": KnowledgeSearchRequest,
    "knowledge-snapshot": KnowledgeSnapshot,
    "agent-skill-workflow": WorkflowSkillEvidence,
}


@pytest.mark.parametrize("name", MODELS)
def test_published_knowledge_schemas_match_runtime_models(name: str) -> None:
    path = Path(__file__).parents[2] / "schemas" / f"{name}.schema.json"
    schema = json.loads(path.read_text())
    assert schema.pop("$schema") == "https://json-schema.org/draft/2020-12/schema"
    assert schema.pop("$id") == f"https://ai-software-engineer.local/schemas/{name}.schema.json"
    assert schema == MODELS[name].model_json_schema()
