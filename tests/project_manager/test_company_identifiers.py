"""Short company identities must agree across config, storage and wire contracts."""

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from pydantic import TypeAdapter, ValidationError

from ai_software_engineer.company_workspace import CompanyId, CompanyWorkspace
from ai_software_engineer.config import ProductionConfig


@pytest.mark.parametrize(
    ("identity", "valid"),
    [
        ("company_ai", True),
        ("company_default", True),
        ("company_" + "a" * 64, True),
        ("company_", False),
        ("company_a", False),
        ("company_AI", False),
        ("company_-ai", False),
        ("company_../ai", False),
        ("company_a/b", False),
        ("company_" + "a" * 65, False),
    ],
)
def test_company_id_boundaries_match_all_wire_schemas(identity: str, valid: bool) -> None:
    adapter = TypeAdapter(CompanyId)
    if valid:
        assert adapter.validate_python(identity) == identity
    else:
        with pytest.raises(ValidationError):
            adapter.validate_python(identity)
    root = Path(__file__).parents[2] / "schemas"
    for filename in (
        "production-config.schema.json",
        "company-workspace.schema.json",
        "requirement-project-checkpoint.schema.json",
    ):
        schema = json.loads((root / filename).read_text(encoding="utf-8"))
        validator = Draft202012Validator(schema["properties"]["company_id"])
        assert validator.is_valid(identity) is valid, filename


def test_company_ai_config_initializes_and_reopens_without_renaming(tmp_path: Path) -> None:
    config = ProductionConfig.model_validate(
        {
            "platform_root": str(tmp_path / "platform"),
            "company_id": "company_ai",
            "company_name": "AI company",
            "model_routes": [{"provider": "codex", "model": "gpt-5.5", "kind": "codex_cli"}],
        }
    )
    original = CompanyWorkspace.initialize(
        config.platform_root, company_id="company_default", name="Default company"
    )
    original_bytes = (original.root / "company.json").read_bytes()
    workspace = CompanyWorkspace.initialize(
        config.platform_root, company_id=config.company_id, name=config.company_name
    )
    reopened = CompanyWorkspace.initialize(
        config.platform_root, company_id=config.company_id, name=config.company_name
    )
    assert workspace.root.name == "company_ai"
    assert reopened.manifest == workspace.manifest
    assert (original.root / "company.json").read_bytes() == original_bytes
    repo = tmp_path / "repo"
    repo.mkdir()
    assert (
        workspace.project_registry().register(repo).project_id
        != original.project_registry().register(repo).project_id
    )
