"""Production Team Host configuration contracts."""

from __future__ import annotations

import json
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
