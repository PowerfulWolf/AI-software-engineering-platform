"""Production Team Host configuration contracts."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from pydantic import ValidationError

from ai_software_engineer.config import ProductionConfig, ProductionConfigError
from ai_software_engineer.domain import TeamRole


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


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1:8317/v1",
        "http://localhost:8317/v1",
        "http://[::1]:8317/v1",
    ],
)
def test_local_codex_proxy_round_trip_and_schema(tmp_path: Path, url: str) -> None:
    payload = {**_payload(tmp_path), "codex_cli_proxy_base_url": url}
    schema = json.loads(
        (Path(__file__).parents[2] / "schemas" / "production-config.schema.json").read_text()
    )

    config = ProductionConfig.model_validate(payload)

    assert config.codex_cli_proxy_base_url == url
    assert ProductionConfig.model_validate(config.to_wire()) == config
    Draft202012Validator(schema).validate(config.to_wire())


def test_codex_connection_mode_is_per_route_and_legacy_mode_is_preserved(tmp_path: Path) -> None:
    payload = _payload(tmp_path)
    routes = payload["model_routes"]
    assert isinstance(routes, list)
    routes[0]["connection_mode"] = "direct"
    routes.append({**routes[0], "connection_mode": "proxy"})
    payload["codex_cli_proxy_base_url"] = "http://127.0.0.1:8317/v1"
    config = ProductionConfig.model_validate(payload)
    schema = json.loads(
        (Path(__file__).parents[2] / "schemas" / "production-config.schema.json").read_text()
    )
    Draft202012Validator(schema).validate(config.to_wire())
    assert [config.effective_connection_mode(route) for route in config.enabled_routes()] == [
        "direct",
        "proxy",
    ]
    assert ProductionConfig.model_validate(config.to_wire()) == config
    legacy = ProductionConfig.model_validate(
        {**_payload(tmp_path), "codex_cli_proxy_base_url": payload["codex_cli_proxy_base_url"]}
    )
    assert legacy.effective_connection_mode(legacy.enabled_routes()[0]) == "proxy"


def test_codex_connection_mode_rejects_missing_proxy_and_ambiguous_legacy_reference(
    tmp_path: Path,
) -> None:
    payload = _payload(tmp_path)
    routes = payload["model_routes"]
    assert isinstance(routes, list)
    routes[0]["connection_mode"] = "proxy"
    with pytest.raises(ValidationError, match="proxy URL"):
        ProductionConfig.model_validate(payload)
    payload["codex_cli_proxy_base_url"] = "http://127.0.0.1:8317/v1"
    routes.append({**routes[0], "connection_mode": "direct"})
    payload["agent_model_routes"] = [
        {"role": role.value, "routes": [{"provider": "codex", "model": "gpt-5.5"}]}
        for role in TeamRole
    ]
    with pytest.raises(ValidationError, match="ambiguous"):
        ProductionConfig.model_validate(payload)


def test_responses_route_rejects_codex_connection_mode(tmp_path: Path) -> None:
    payload = _payload(tmp_path)
    routes = payload["model_routes"]
    assert isinstance(routes, list)
    routes[1]["connection_mode"] = "direct"
    with pytest.raises(ValidationError):
        ProductionConfig.model_validate(payload)
    schema = json.loads(
        (Path(__file__).parents[2] / "schemas" / "production-config.schema.json").read_text()
    )
    assert list(Draft202012Validator(schema).iter_errors(payload))


@pytest.mark.parametrize(
    "url",
    [
        "http://example.com/v1",
        "http://127.0.0.2:8317/v1",
        "https://127.0.0.1:8317/v1",
        "http://user:password@127.0.0.1:8317/v1",
        "http://127.0.0.1:8317/v1?token=secret",
        "http://127.0.0.1:8317/v1#fragment",
        "http://127.0.0.1:0/v1",
        "http://127.0.0.1:99999/v1",
        'http://127.0.0.1:8317/v1"injected',
        "http://127.0.0.1:8317/v1\nother=value",
        "not-a-url",
    ],
)
def test_local_codex_proxy_rejects_unsafe_url(tmp_path: Path, url: str) -> None:
    with pytest.raises(ValidationError):
        ProductionConfig.model_validate({**_payload(tmp_path), "codex_cli_proxy_base_url": url})


def test_local_codex_proxy_key_reference_is_secret_free_and_requires_url(
    tmp_path: Path,
) -> None:
    payload = {
        **_payload(tmp_path),
        "codex_cli_proxy_base_url": "http://127.0.0.1:8317/v1",
        "codex_cli_proxy_api_key_env": "ASE_CODEX_PROXY_API_KEY",
    }
    schema = json.loads(
        (Path(__file__).parents[2] / "schemas" / "production-config.schema.json").read_text()
    )
    config = ProductionConfig.model_validate(payload)

    assert config.codex_cli_proxy_api_key_env == "ASE_CODEX_PROXY_API_KEY"
    assert "proxy-secret" not in config.model_dump_json()
    Draft202012Validator(schema).validate(config.to_wire())
    for invalid in (
        {**payload, "codex_cli_proxy_base_url": None},
        {**payload, "codex_cli_proxy_api_key_env": "invalid-name"},
    ):
        with pytest.raises(ValidationError):
            ProductionConfig.model_validate(invalid)
        assert list(Draft202012Validator(schema).iter_errors(invalid))


def test_design_retry_policy_defaults_and_custom_limits(tmp_path: Path) -> None:
    config = ProductionConfig.model_validate(_payload(tmp_path))
    assert config.design_retry_policy.max_design_attempts == 3
    assert config.design_retry_policy.max_transient_failures == 5
    payload = {
        **_payload(tmp_path),
        "design_retry_policy": {
            "max_design_attempts": 8,
            "max_transient_failures": 20,
        },
    }
    custom = ProductionConfig.model_validate(payload)
    assert custom.design_retry_policy.max_design_attempts == 8
    assert ProductionConfig.model_validate(custom.to_wire()) == custom


@pytest.mark.parametrize("key", ["max_design_attempts", "max_transient_failures"])
@pytest.mark.parametrize("value", [0, -1, 101, True, "5", 1.5])
def test_design_retry_policy_rejects_invalid_limits(
    tmp_path: Path, key: str, value: object
) -> None:
    with pytest.raises(ValidationError):
        ProductionConfig.model_validate({**_payload(tmp_path), "design_retry_policy": {key: value}})


def test_environment_selects_config_path(tmp_path: Path) -> None:
    path = tmp_path / "config.json"
    path.write_text(json.dumps(_payload(tmp_path)), encoding="utf-8")

    config = ProductionConfig.from_environment({"ASE_CONFIG": str(path)})

    assert config.platform_root == str((tmp_path / "platform").resolve())


def test_first_run_defaults_are_visible_without_writing_configuration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "home"
    monkeypatch.setattr("ai_software_engineer.config.production.Path.home", lambda: home)

    config = ProductionConfig.default()

    assert config.platform_root == str(home / ".ase")
    assert config.team_id == "team_ai"
    assert config.team_name == "AI Team"
    assert config.console_port == 8765
    assert [(route.provider, route.enabled) for route in config.model_routes] == [
        ("codex", True),
        ("deepseek", False),
        ("qwen", False),
    ]
    assert not home.exists()


def test_first_run_routes_match_the_committed_operator_example(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "ai_software_engineer.config.production.Path.home", lambda: tmp_path / "home"
    )

    defaults = ProductionConfig.default()
    example = ProductionConfig.from_file(
        Path(__file__).parents[2] / "config" / "production.example.json"
    )

    assert example.model_routes == defaults.model_routes
    assert example.database == defaults.database
    assert example.team_id == defaults.team_id
    assert example.team_name == defaults.team_name
    assert example.console_port == defaults.console_port
    assert example.live_model_execution == defaults.live_model_execution


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


def test_same_provider_model_supports_multiple_reasoning_efforts(tmp_path: Path) -> None:
    payload = _payload(tmp_path)
    routes = payload["model_routes"]
    assert isinstance(routes, list)
    routes.append({**routes[0], "reasoning_effort": "high"})

    config = ProductionConfig.model_validate(payload)

    assert [route.reasoning_effort for route in config.enabled_routes()] == [
        "medium",
        "high",
    ]


def test_duplicate_provider_model_reasoning_route_is_rejected(tmp_path: Path) -> None:
    payload = _payload(tmp_path)
    routes = payload["model_routes"]
    assert isinstance(routes, list)
    routes.append(dict(routes[0]))

    with pytest.raises(ValidationError, match="provider/model/reasoning/type routes"):
        ProductionConfig.model_validate(payload)


def test_same_model_reasoning_can_use_distinct_route_types(tmp_path: Path) -> None:
    payload = _payload(tmp_path)
    routes = payload["model_routes"]
    assert isinstance(routes, list)
    routes.append(
        {
            "provider": "codex",
            "model": "gpt-5.5",
            "kind": "responses",
            "reasoning_effort": "medium",
            "endpoint": "https://example.invalid/responses",
            "api_key_env": "CODEX_RESPONSES_API_KEY",
        }
    )

    config = ProductionConfig.model_validate(payload)

    assert [route.kind.value for route in config.enabled_routes()] == ["codex_cli", "responses"]
    assert config.model_routes[0].accepts_image_input()
    assert not config.model_routes[-1].accepts_image_input()
    assert (
        not config.model_routes[0].model_copy(update={"image_input": False}).accepts_image_input()
    )


def test_agent_reference_requires_type_when_same_model_has_two_types(tmp_path: Path) -> None:
    payload = _payload(tmp_path)
    routes = payload["model_routes"]
    assert isinstance(routes, list)
    routes.append(
        {
            "provider": "codex",
            "model": "gpt-5.5",
            "kind": "responses",
            "reasoning_effort": "medium",
            "endpoint": "https://example.invalid/responses",
            "api_key_env": "CODEX_RESPONSES_API_KEY",
        }
    )
    roles = ("manager", "product", "designer", "planner", "coder", "qa", "reviewer")
    payload["agent_model_routes"] = [
        {
            "role": role,
            "routes": [{"provider": "codex", "model": "gpt-5.5", "reasoning_effort": "medium"}],
        }
        for role in roles
    ]
    with pytest.raises(ValidationError, match="ambiguous"):
        ProductionConfig.model_validate(payload)

    for policy in payload["agent_model_routes"]:
        policy["routes"][0]["route_kind"] = "responses"
    config = ProductionConfig.model_validate(payload)
    assert all(config.routes_for(role)[0].kind.value == "responses" for role in TeamRole)
    schema = json.loads(
        (Path(__file__).parents[2] / "schemas/production-config.schema.json").read_text()
    )
    assert list(Draft202012Validator(schema).iter_errors(config.to_wire())) == []


def test_each_agent_can_have_an_independent_primary_and_fallback_order(
    tmp_path: Path,
) -> None:
    payload = _payload(tmp_path)
    routes = payload["model_routes"]
    assert isinstance(routes, list)
    second = routes[1]
    assert isinstance(second, dict)
    second["enabled"] = True
    roles = ["manager", "product", "designer", "planner", "coder", "qa", "reviewer"]
    payload["agent_model_routes"] = [
        {
            "role": role,
            "routes": (
                [
                    {"provider": "qwen", "model": "qwen3.8-max"},
                    {"provider": "codex", "model": "gpt-5.5"},
                ]
                if role == "product"
                else [
                    {"provider": "codex", "model": "gpt-5.5"},
                    {"provider": "qwen", "model": "qwen3.8-max"},
                ]
            ),
        }
        for role in roles
    ]

    config = ProductionConfig.model_validate(payload)

    assert [route.model for route in config.routes_for(TeamRole.PRODUCT)] == [
        "qwen3.8-max",
        "gpt-5.5",
    ]
    assert [route.model for route in config.routes_for(TeamRole.CODER)] == [
        "gpt-5.5",
        "qwen3.8-max",
    ]


def test_each_agent_can_select_a_distinct_reasoning_effort_for_the_same_model(
    tmp_path: Path,
) -> None:
    payload = _payload(tmp_path)
    routes = payload["model_routes"]
    assert isinstance(routes, list)
    routes.append({**routes[0], "reasoning_effort": "high"})
    roles = ["manager", "product", "designer", "planner", "coder", "qa", "reviewer"]
    payload["agent_model_routes"] = [
        {
            "role": role,
            "routes": [
                {
                    "provider": "codex",
                    "model": "gpt-5.5",
                    "reasoning_effort": "high" if role == "coder" else "medium",
                }
            ],
        }
        for role in roles
    ]

    config = ProductionConfig.model_validate(payload)

    assert config.routes_for(TeamRole.CODER)[0].reasoning_effort == "high"
    assert config.routes_for(TeamRole.QA)[0].reasoning_effort == "medium"
    assert len(config.routes_for(TeamRole.CODER)) == 1
    assert len(config.routes_for(TeamRole.QA)) == 1


def test_legacy_agent_route_without_reasoning_requires_an_unambiguous_model(
    tmp_path: Path,
) -> None:
    payload = _payload(tmp_path)
    routes = payload["model_routes"]
    assert isinstance(routes, list)
    routes.append({**routes[0], "reasoning_effort": "high"})
    payload["agent_model_routes"] = [
        {
            "role": role,
            "routes": [{"provider": "codex", "model": "gpt-5.5"}],
        }
        for role in ("manager", "product", "designer", "planner", "coder", "qa", "reviewer")
    ]

    with pytest.raises(ValidationError, match="ambiguous without reasoning_effort"):
        ProductionConfig.model_validate(payload)


def test_agent_model_routes_require_all_roles_and_enabled_catalog_entries(
    tmp_path: Path,
) -> None:
    payload = _payload(tmp_path)
    payload["agent_model_routes"] = [
        {
            "role": "product",
            "routes": [{"provider": "codex", "model": "gpt-5.5"}],
        }
    ]
    with pytest.raises(ValidationError, match="cover every Team role"):
        ProductionConfig.model_validate(payload)

    payload["agent_model_routes"] = [
        {
            "role": role,
            "routes": [{"provider": "qwen", "model": "qwen3.8-max"}],
        }
        for role in ("manager", "product", "designer", "planner", "coder", "qa", "reviewer")
    ]
    with pytest.raises(ValidationError, match="reference enabled model routes"):
        ProductionConfig.model_validate(payload)


@pytest.mark.parametrize("console_port", [0, 65536, True])
def test_console_port_is_bounded_and_strict(tmp_path: Path, console_port: object) -> None:
    payload = _payload(tmp_path)
    payload["console_port"] = console_port

    with pytest.raises(ValidationError):
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
