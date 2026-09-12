"""Context projection does not repeat exhaustive language detection inventories."""

import json
from pathlib import Path

from ai_software_engineer.context import FileContextBuilder
from ai_software_engineer.context.profile import repository_profile_context
from ai_software_engineer.repository_profile import RepositoryProfile
from tests.domain.factories import make_agent, make_task


def test_marker_heavy_profile_is_compact_without_losing_rules(tmp_path: Path) -> None:
    for i in range(1500):
        (tmp_path / f"long_module_name_to_reproduce_context_overflow_{i:04d}.py").touch()
    (tmp_path / "AGENTS.md").write_text("Follow project rules.")
    (tmp_path / "pyproject.toml").write_text('[project]\nname="example"\nversion="0.1"\n')
    profile = RepositoryProfile.discover(tmp_path)
    original = profile.to_wire()
    source = repository_profile_context(profile)
    payload = json.loads(source.content or "")
    assert payload["kind"] == "repository_profile_context"
    assert payload["profile_sha256"] == profile.profile_sha256
    assert payload["native_rules"] == original["native_rules"]
    assert payload["build_systems"] == original["build_systems"]
    assert payload["languages"][0]["marker_count"] == len(profile.languages[0].markers)
    assert payload["languages"][0]["marker_count"] >= 1500
    assert len(payload["languages"][0]["marker_samples"]) == 3
    assert profile.to_wire() == original
    assert source == repository_profile_context(profile)
    assert source.required
    assert source.uri.endswith(profile.profile_sha256)
    agent = make_agent()
    task = make_task().model_copy(update={"repository": str(tmp_path)})
    bundle = FileContextBuilder(tmp_path, agent.permissions, sources=(source,)).build(
        task, agent.role, attempt=1
    )
    assert bundle.budget.used_input_tokens < 4000
    assert all(not section.truncated for section in bundle.sections)
