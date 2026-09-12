"""Short team identities must agree across config, storage and wire contracts."""

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from pydantic import TypeAdapter, ValidationError

from ai_software_engineer.config import ProductionConfig
from ai_software_engineer.team_workspace import TeamId, TeamWorkspace


@pytest.mark.parametrize(
    ("identity", "valid"),
    [
        ("team_ai", True),
        ("team_default", True),
        ("team_" + "a" * 64, True),
        ("team_", False),
        ("team_a", False),
        ("team_AI", False),
        ("team_-ai", False),
        ("team_../ai", False),
        ("team_a/b", False),
        ("team_" + "a" * 65, False),
    ],
)
def test_team_id_boundaries_match_all_wire_schemas(identity: str, valid: bool) -> None:
    adapter = TypeAdapter(TeamId)
    if valid:
        assert adapter.validate_python(identity) == identity
    else:
        with pytest.raises(ValidationError):
            adapter.validate_python(identity)
    root = Path(__file__).parents[2] / "schemas"
    for filename in (
        "production-config.schema.json",
        "team-workspace.schema.json",
        "requirement-checkpoint.schema.json",
    ):
        schema = json.loads((root / filename).read_text(encoding="utf-8"))
        validator = Draft202012Validator(schema["properties"]["team_id"])
        assert validator.is_valid(identity) is valid, filename


def test_team_ai_config_reopens_and_cannot_replace_an_existing_team(tmp_path: Path) -> None:
    config = ProductionConfig.model_validate(
        {
            "platform_root": str(tmp_path / "platform"),
            "team_id": "team_ai",
            "team_name": "AI team",
            "model_routes": [{"provider": "codex", "model": "gpt-5.5", "kind": "codex_cli"}],
        }
    )
    workspace = TeamWorkspace.initialize(
        config.platform_root,
        team_id=config.team_id,
        name=config.team_name,
    )
    reopened = TeamWorkspace.initialize(
        config.platform_root, team_id=config.team_id, name=config.team_name
    )
    assert workspace.root.name == "team"
    assert reopened.manifest == workspace.manifest

    occupied_root = tmp_path / "occupied-platform"
    original = TeamWorkspace.initialize(
        occupied_root,
        team_id="team_default",
        name="Default team",
    )
    original_bytes = (original.root / "team.json").read_bytes()
    with pytest.raises(ValueError, match="identity or location"):
        TeamWorkspace.initialize(
            occupied_root,
            team_id=config.team_id,
            name=config.team_name,
        )
    assert (original.root / "team.json").read_bytes() == original_bytes
