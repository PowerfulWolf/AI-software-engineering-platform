"""No ambient Docker scope, no unowned deletion, and no credential-bearing records."""

from datetime import UTC, datetime
from unittest.mock import Mock

import pytest

from ai_software_engineer.manager.python_mysql_resources import (
    DockerDescription,
    IsolatedMysqlResource,
    MysqlResourceIntent,
    MysqlResourceUnavailable,
    container_argv,
)
from tests.manager.test_python_verification import capability


def test_resource_intent_binds_exact_plan_role_daemon_and_fixed_container(tmp_path) -> None:
    cap = capability(tmp_path)
    intent = MysqlResourceIntent.create(
        plan_sha256="a" * 64,
        invocation_sha256="b" * 64,
        role="qa",
        capability=cap,
        recorded_at=datetime(2026, 10, 2, tzinfo=UTC),
    )
    intent.validate_integrity()
    argv = container_argv(cap, intent)
    assert "--network" in argv and argv[argv.index("--network") + 1] == "none"
    assert "--pull=never" in argv and "--rm" in argv
    assert cap.mysql_image_id in argv
    assert not any(token in {"-p", "--publish", "-v", "--volume"} for token in argv)
    assert intent.container_name.startswith("ase-verify-")
    assert "MYSQL_ROOT_HOST=localhost" in argv
    assert "MYSQL_ROOT_PASSWORD" not in " ".join(argv)
    assert "1195" in argv and "--kill-after=5" in argv
    assert (intent.expires_at - intent.recorded_at).total_seconds() == 1200


def test_resource_identity_and_deadline_cannot_drift(tmp_path) -> None:
    cap = capability(tmp_path)
    intent = MysqlResourceIntent.create(
        plan_sha256="a" * 64,
        invocation_sha256="b" * 64,
        role="qa",
        capability=cap,
        recorded_at=datetime(2026, 10, 2, tzinfo=UTC),
    )
    with pytest.raises(ValueError):
        intent.model_copy(update={"container_name": "ase-mysql"}).validate_integrity()


def resource_fixture(tmp_path):
    intent = MysqlResourceIntent.create(
        plan_sha256="a" * 64,
        invocation_sha256="b" * 64,
        role="qa",
        capability=capability(tmp_path),
        recorded_at=datetime(2026, 10, 2, tzinfo=UTC),
    )
    records = []
    resource = IsolatedMysqlResource(
        intent, lambda r: records.append(r) or r, clock=lambda: intent.recorded_at
    )
    resource.require_daemon = Mock()
    description = {
        "Id": "c" * 64,
        "Name": "/" + intent.container_name,
        "Image": intent.capability.mysql_image_id,
        "Config": {
            "Image": intent.capability.mysql_image_id,
            "Labels": {"ase.verification.resource": intent.resource_id},
            "Entrypoint": ["/usr/bin/timeout"],
            "Cmd": list(container_argv(intent.capability, intent)[-8:]),
            "Env": ["MYSQL_ALLOW_EMPTY_PASSWORD=1", "MYSQL_ROOT_HOST=localhost"],
        },
        "HostConfig": {
            "NetworkMode": "none",
            "PortBindings": {},
            "Memory": 536870912,
            "NanoCpus": 1000000000,
            "PidsLimit": 128,
            "AutoRemove": True,
            "Binds": None,
            "RestartPolicy": {"Name": "no", "MaximumRetryCount": 0},
        },
        "Mounts": [{"Type": "volume", "Destination": "/var/lib/mysql", "Name": "fixture"}],
    }
    return resource, records, description


@pytest.mark.parametrize("change", ["name", "timeout", "restart", "root_host", "bind", "label"])
def test_unowned_or_weakened_resource_cannot_be_removed(tmp_path, change):
    resource, records, value = resource_fixture(tmp_path)
    if change == "name":
        value["Name"] = "/existing-business-mysql"
    if change == "timeout":
        value["Config"]["Cmd"][0] = "--kill-after=1000"
    if change == "restart":
        value["HostConfig"]["RestartPolicy"]["Name"] = "always"
    if change == "root_host":
        value["Config"]["Env"] = ["MYSQL_ROOT_HOST=%"]
    if change == "bind":
        value["HostConfig"]["Binds"] = ["/host:/container"]
    if change == "label":
        value["Config"]["Labels"] = {}
    resource._intent_published = True
    command = Mock(return_value=("c" * 64 + "\t" + resource.intent.container_name).encode())
    resource.command = command
    resource.inspect = Mock(return_value=DockerDescription.model_validate(value))
    with pytest.raises(MysqlResourceUnavailable):
        resource.close()
    assert not any(call.args[0] == "rm" for call in command.call_args_list)
    assert records[-1].phase == "CLEANUP_FAILED"


@pytest.mark.parametrize("container_state", ["running", "created"])
def test_lost_create_response_is_recovered_by_exact_name_before_removal(tmp_path, container_state):
    resource, records, value = resource_fixture(tmp_path)
    value["State"] = {"Status": container_state, "Running": container_state == "running"}
    resource._intent_published = True
    resource.command = Mock(
        side_effect=[("c" * 64 + "\t" + resource.intent.container_name).encode(), b""]
    )
    resource.inspect = Mock(return_value=DockerDescription.model_validate(value))
    resource.close()
    assert [r.phase for r in records] == ["CREATED", "CLEANED"]
    assert resource.command.call_args.args == ("rm", "-f", "c" * 64)
    assert resource.require_daemon.called
    assert not any(
        call.args[0] in {"run", "start", "exec"} for call in resource.command.call_args_list
    )


@pytest.mark.parametrize("daemon_failed", [False, True])
def test_expired_absent_resource_requires_successful_exact_query(tmp_path, daemon_failed):
    resource, records, _ = resource_fixture(tmp_path)
    resource._intent_published = True
    resource.container_id = "c" * 64
    resource.command = Mock(
        return_value=b"", side_effect=MysqlResourceUnavailable("failed") if daemon_failed else None
    )
    if daemon_failed:
        with pytest.raises(MysqlResourceUnavailable):
            resource.close()
        assert records[-1].phase == "CLEANUP_FAILED"
    else:
        resource.close()
        assert records[-1].phase == "CLEANED"
    assert not any(call.args[0] == "rm" for call in resource.command.call_args_list)


def test_create_never_precedes_published_intent_and_failed_observation_is_cleaned(tmp_path):
    resource, records, value = resource_fixture(tmp_path)

    def publish(record):
        records.append(record)
        if record.phase == "CREATED":
            raise ValueError("durable write failed")
        return record

    resource._publish = publish
    resource.inspect = Mock(return_value=DockerDescription.model_validate(value))

    def command(*argv, **kwargs):
        if argv[0] == "run":
            assert records[0].phase == "INTENT"
            return ("c" * 64).encode()
        if argv[0] == "ps":
            return ("c" * 64 + "\t" + resource.intent.container_name).encode()
        return b""

    resource.command = Mock(side_effect=command)
    with pytest.raises(ValueError, match="durable"):
        resource.start(lambda: None)
    resource.close()
    assert records[-1].phase == "CLEANED"


def test_resource_wire_preserves_partial_failure_but_rejects_hash_without_identity(tmp_path):
    import json
    from pathlib import Path

    from jsonschema import Draft202012Validator
    from jsonschema.exceptions import ValidationError as SchemaValidationError

    from ai_software_engineer.recovery.python_mysql_records import MysqlResourceRecord

    resource, _, _ = resource_fixture(tmp_path)
    try:
        record = MysqlResourceRecord.create(
            phase="CLEANUP_FAILED",
            intent=resource.intent,
            container_id="c" * 64,
            recorded_at=resource.intent.recorded_at,
        )
        schema = json.loads(
            (Path(__file__).parents[2] / "schemas/candidate-verification.schema.json").read_text()
        )
        validator = Draft202012Validator(schema)
        validator.validate(record.to_wire())
        invalid = {**record.to_wire(), "configuration_sha256": "d" * 64}
        invalid.pop("container_id")
        with pytest.raises(ValueError):
            MysqlResourceRecord.model_validate(invalid)
        with pytest.raises(SchemaValidationError):
            validator.validate(invalid)
    finally:
        resource._docker_config.cleanup()
