"""Production Team Host configuration contracts."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

from ai_software_engineer.config import ProductionConfig, ProductionConfigError


def _payload(tmp_path: Path) -> dict[str, object]:
    return {
        "platform_root": str((tmp_path / "platform").resolve()),
        "database": {"backend": "mysql", "dsn_env": "TEAM_MYSQL_DSN"},
        "model_routes": [
            {
                "provider": "codex",
                "model": "gpt-5.5",
                "kind": "codex_cli",
                "reasoning_effort": "medium",
            },
            {
                "provider": "qwen",
                "model": "qwen3.8-max",
                "kind": "responses",
                "endpoint": "https://example.invalid/responses",
                "api_key_env": "QWEN_API_KEY",
                "enabled": False,
            },
        ],
    }


def test_config_loads_without_storing_secrets(tmp_path: Path) -> None:
    path = tmp_path / "config.json"
    path.write_text(json.dumps(_payload(tmp_path)), encoding="utf-8")

    config = ProductionConfig.from_file(path)

    assert config.enabled_routes()[0].model == "gpt-5.5"
    assert "password" not in json.dumps(config.to_wire()).lower()
    assert "api_key" not in config.to_wire()


def test_environment_selects_config_path(tmp_path: Path) -> None:
    path = tmp_path / "config.json"
    path.write_text(json.dumps(_payload(tmp_path)), encoding="utf-8")

    config = ProductionConfig.from_environment({"ASE_CONFIG": str(path)})

    assert config.platform_root == str((tmp_path / "platform").resolve())


def test_mysql_dsn_resolves_by_name_without_leaking_value(tmp_path: Path) -> None:
    config = ProductionConfig.model_validate(_payload(tmp_path))
    secret = "mysql://user:do-not-leak@example.invalid/database"

    assert config.require_mysql_dsn({"TEAM_MYSQL_DSN": secret}) == secret
    with pytest.raises(ProductionConfigError, match="TEAM_MYSQL_DSN") as captured:
        config.require_mysql_dsn({})
    assert "do-not-leak" not in str(captured.value)


def test_codex_route_rejects_embedded_endpoint_or_key(tmp_path: Path) -> None:
    payload = _payload(tmp_path)
    routes = payload["model_routes"]
    assert isinstance(routes, list)
    first = routes[0]
    assert isinstance(first, dict)
    first["api_key_env"] = "OPENAI_API_KEY"

    with pytest.raises(ValidationError, match="Codex CLI route"):
        ProductionConfig.model_validate(payload)


def test_duplicate_provider_model_route_is_rejected(tmp_path: Path) -> None:
    payload = _payload(tmp_path)
    routes = payload["model_routes"]
    assert isinstance(routes, list)
    routes.append(dict(routes[0]))

    with pytest.raises(ValidationError, match="provider/model routes"):
        ProductionConfig.model_validate(payload)


@pytest.mark.parametrize("system", ["darwin", "linux"])
def test_omitted_platform_root_uses_home_independent_of_cwd_without_creating_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, system: str
) -> None:
    home = tmp_path / "home"
    first_cwd = tmp_path / "first"
    second_cwd = tmp_path / "second"
    first_cwd.mkdir()
    second_cwd.mkdir()
    monkeypatch.setattr("ai_software_engineer.config.production.Path.home", lambda: home)
    monkeypatch.setattr("sys.platform", system)
    payload = _payload(tmp_path)
    payload.pop("platform_root")

    monkeypatch.chdir(first_cwd)
    first = ProductionConfig.model_validate(payload)
    monkeypatch.chdir(second_cwd)
    second = ProductionConfig.model_validate(payload)

    expected = home / ".ase"
    assert first.platform_root == str(expected)
    assert second.platform_root == str(expected)
    assert not expected.exists()


def test_explicit_home_relative_platform_root_is_expanded_without_creation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "home"
    monkeypatch.setattr("ai_software_engineer.config.production.Path.home", lambda: home)
    payload = _payload(tmp_path)
    payload["platform_root"] = "~/custom-ase"

    config = ProductionConfig.model_validate(payload)

    expected = home / "custom-ase"
    assert config.platform_root == str(expected)
    assert not expected.exists()


@pytest.mark.parametrize(
    "platform_root",
    [
        "relative",
        "~//escape",
        "~/../escape",
        "~/custom/../escape",
        "/../escape",
        "/tmp/platform/../escape",
        "bad\x00path",
    ],
)
def test_invalid_explicit_platform_root_rejects_without_default_fallback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, platform_root: str
) -> None:
    home = tmp_path / "home"
    monkeypatch.setattr("ai_software_engineer.config.production.Path.home", lambda: home)
    payload = _payload(tmp_path)
    payload["platform_root"] = platform_root

    with pytest.raises(ValidationError, match="platform_root must be an absolute safe path"):
        ProductionConfig.model_validate(payload)

    assert not (home / ".ase").exists()


def test_omitted_platform_root_rejects_on_unsupported_platform(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("sys.platform", "win32")
    payload = _payload(tmp_path)
    payload.pop("platform_root")

    with pytest.raises(ValueError, match="platform_root must be explicitly configured"):
        ProductionConfig.model_validate(payload)


def test_importing_production_config_does_not_create_default_workspace(tmp_path: Path) -> None:
    home = tmp_path / "home"
    source_root = Path(__file__).parents[2] / "src"
    environment = {
        "HOME": str(home),
        "LANG": os.environ.get("LANG", "C.UTF-8"),
        "PATH": os.environ.get("PATH", ""),
        "PYTHONPATH": str(source_root),
    }

    completed = subprocess.run(
        [sys.executable, "-c", "import ai_software_engineer.config.production"],
        cwd=tmp_path,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )

    assert completed.returncode == 0, completed.stderr
    assert not (home / ".ase").exists()
