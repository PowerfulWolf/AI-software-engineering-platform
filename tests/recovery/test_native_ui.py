"""Platform GUI driver checks. These are not business candidate acceptance."""

import json
import os
import select
import shutil
import signal
import socket
import subprocess
import time
from pathlib import Path
from unittest.mock import Mock

import pytest

from ai_software_engineer.manager.native_ui import (
    NativeUiOutput,
    NativeUiScenario,
    NativeUiStep,
    NativeUiUnavailable,
    driver_source,
    native_ui_capability,
    native_ui_profile,
    probe_native_ui_session,
    run_native_ui,
)
from ai_software_engineer.manager.verification_environment import discover_swift_sandbox_capability


def scenario() -> NativeUiScenario:
    return NativeUiScenario(
        product="ASEUIProbe",
        mock_argument="--mock-fixture",
        window_title="ASE isolated UI probe",
        steps=(NativeUiStep(name="initial"),),
    )


def test_native_ui_is_a_bounded_mock_sequence() -> None:
    for invalid in ("/bin/sh", "../escape", "App;evil"):
        with pytest.raises(ValueError):
            NativeUiScenario.model_validate({**scenario().to_wire(), "product": invalid})
    for invalid in ("--real", "--mock-a --other", "--mock-a\n"):
        with pytest.raises(ValueError):
            NativeUiScenario.model_validate({**scenario().to_wire(), "mock_argument": invalid})
    with pytest.raises(ValueError):
        NativeUiStep(name="ambiguous press", action="press")
    with pytest.raises(ValueError):
        NativeUiStep.model_validate({"name": "no menus", "action": "press", "role": "AXMenuItem"})
    with pytest.raises(ValueError):
        NativeUiOutput(pid=123, action="snapshot", nodes=())
    with pytest.raises(ValueError):
        NativeUiOutput.model_validate(
            {
                "pid": 123,
                "action": "snapshot",
                "nodes": [{"path": "0", "attributes": {"AXRole": "AXApplication"}}],
            }
        )


def test_link_press_requires_one_exact_identifier() -> None:
    step = NativeUiStep(
        name="select_only",
        action="press",
        role="AXLink",
        attribute="AXIdentifier",
        value="fixture-select-only",
    )
    assert step.role == "AXLink"
    for update in ({"attribute": "AXTitle"}, {"attribute": "AXDescription"}, {"index": 1}):
        with pytest.raises(ValueError):
            NativeUiStep.model_validate({**step.to_wire(), **update})


def test_scroll_is_normalized_and_cannot_target_coordinates_or_other_controls() -> None:
    step = NativeUiStep.model_validate(
        {"name": "chart_bottom", "action": "scroll", "scroll_position": 1.0}
    )
    assert step.to_wire()["scroll_position"] == 1.0
    assert "scroll_position" not in NativeUiStep(name="legacy").to_wire()
    for update in (
        {"scroll_position": None},
        {"scroll_position": -0.1},
        {"scroll_position": 1.1},
        {"scroll_position": float("nan")},
        {"capture_window": True},
        {"role": "AXButton", "attribute": "AXTitle", "value": "other"},
        {"index": 1},
        {"action": "snapshot"},
    ):
        with pytest.raises(ValueError):
            NativeUiStep.model_validate({**step.to_wire(), **update})


def test_window_capture_requires_explicit_bounded_snapshot() -> None:
    capture = NativeUiStep(name="pixels", capture_window=True)
    assert capture.capture_window is True
    assert "capture_window" not in NativeUiStep(name="legacy").to_wire()
    with pytest.raises(ValueError):
        NativeUiStep.model_validate(
            {
                "name": "press_and_capture",
                "action": "press",
                "role": "AXButton",
                "attribute": "AXIdentifier",
                "value": "fixture",
                "capture_window": True,
            }
        )
    with pytest.raises(ValueError):
        NativeUiScenario.model_validate({**scenario().to_wire(), "steps": [capture.to_wire()] * 7})


def test_pixels_cannot_be_missing_unapproved_or_attached_to_failed_steps() -> None:
    from ai_software_engineer.manager.native_ui import NativeUiCapture, NativeUiNode, NativeUiResult
    from tests.domain.test_visual_evidence import png_evidence

    output = NativeUiOutput(
        pid=123,
        action="snapshot",
        nodes=(NativeUiNode(path="0", attributes={"AXRole": "AXWindow"}),),
        capture=NativeUiCapture(window_id=42, image=png_evidence()),
    )
    step = NativeUiStep(name="initial", capture_window=True)
    result = NativeUiResult(step=step, output=output)
    assert NativeUiResult.model_validate(result.to_wire()) == result
    for changed_step, changed_output in (
        (NativeUiStep(name="unapproved"), output),
        (step, output.model_copy(update={"capture": None})),
        (step, output.model_copy(update={"error": "SESSION_LOCKED"})),
    ):
        with pytest.raises(ValueError, match="approved successful snapshot"):
            NativeUiResult(step=changed_step, output=changed_output)
    legacy = NativeUiResult(
        step=NativeUiStep(name="legacy"), output=output.model_copy(update={"capture": None})
    )
    assert "capture" not in legacy.output.to_wire()
    assert "capture_window" not in legacy.step.to_wire()


def test_ui_proposal_cannot_reuse_or_combine_other_approvals() -> None:
    from ai_software_engineer.manager.delivery import ResumeProjectDelivery
    from ai_software_engineer.web_console.models import ContinueDeliveryIntent

    data = {
        "project_id": "project_alpha",
        "delivery_id": "delivery_alpha",
        "expected_checkpoint_sha256": "a" * 64,
        "native_ui_scenario": scenario().to_wire(),
    }
    assert ContinueDeliveryIntent.model_validate(data).native_ui_scenario == scenario()
    for field in ("approved_plan_sha256", "approved_scope_sha256", "approved_repair_sha256"):
        with pytest.raises(ValueError):
            ContinueDeliveryIntent.model_validate({**data, field: "b" * 64})
        with pytest.raises(ValueError):
            ResumeProjectDelivery.model_validate(
                {
                    "delivery_id": "delivery_alpha",
                    "native_ui_scenario": scenario().to_wire(),
                    "approval_reference": "wrong-combined-grant",
                    field: "b" * 64,
                }
            )


def test_native_ui_profile_cannot_launch_outside_private_scratch(tmp_path: Path) -> None:
    private = tmp_path / "private"
    private.mkdir()
    outside = tmp_path / "outside"
    outside.touch()
    with pytest.raises(ValueError):
        native_ui_profile(native_ui_capability(scenario()), outside, private)


@pytest.mark.parametrize(
    "status", ["READY", "SESSION_LOCKED", "SESSION_UNAVAILABLE", "unknown", "compile_failed"]
)
def test_manager_session_probe_is_candidate_free_bounded_and_private(
    monkeypatch: pytest.MonkeyPatch, status: str
) -> None:
    from ai_software_engineer.manager import native_ui as module
    from tests.recovery.test_verification_environment import capability

    monkeypatch.setenv("ASE_TEST_PRIVATE_TOKEN", "must_not_inherit")
    monkeypatch.setattr(module, "discover_swift_sandbox_capability", lambda _: capability())
    roots: list[Path] = []

    def execute(
        argv: tuple[str, ...] | list[str],
        *,
        cwd: Path,
        env: dict[str, str],
        capture_output: bool,
        timeout: int,
        check: bool,
        text: bool = False,
    ) -> subprocess.CompletedProcess[str]:
        assert "ASE_TEST_PRIVATE_TOKEN" not in env
        assert capture_output and not check and timeout <= 60
        if "swiftc" in argv:
            assert str(driver_source()) in argv
            assert "network={enabled=false}" in " ".join(argv)
            assert "--disable-sandbox" not in argv
            assert cwd == driver_source().parent.resolve()
            driver = Path(argv[-1])
            roots.append(driver.parent)
            assert driver.parent.stat().st_mode & 0o777 == 0o700
            driver.touch()
            return subprocess.CompletedProcess(argv, int(status == "compile_failed"), "", "")
        assert argv == [str(roots[0] / "ASEAXDriver"), "--session-check"]
        assert cwd == roots[0] and text
        return subprocess.CompletedProcess(argv, 0, json.dumps({"status": status}), "")

    monkeypatch.setattr("ai_software_engineer.manager.native_ui.run_owned_subprocess", execute)
    launch = Mock(side_effect=AssertionError("session probe cannot launch a candidate"))
    monkeypatch.setattr("ai_software_engineer.manager.native_ui.subprocess.Popen", launch)
    result = probe_native_ui_session(capability())
    if status in {"READY", "SESSION_LOCKED", "SESSION_UNAVAILABLE"}:
        assert result is not None and result.status == status
    else:
        assert result is None
    launch.assert_not_called()
    assert roots and all(not root.exists() for root in roots)
    monkeypatch.setattr(module, "discover_swift_sandbox_capability", lambda _: None)
    assert probe_native_ui_session(capability()) is None
    assert probe_native_ui_session(None) is None


@pytest.mark.parametrize("status", ["SESSION_LOCKED", "SESSION_UNAVAILABLE", "unknown"])
def test_session_preflight_blocks_before_candidate_launch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, status: str
) -> None:
    from tests.recovery.test_verification_environment import capability

    private = tmp_path.resolve()
    binary = private / "build/debug/ASEUIProbe"
    binary.parent.mkdir(parents=True)
    binary.touch()
    (private / "ASEAXDriver").touch()
    run = Mock(
        side_effect=[
            subprocess.CompletedProcess([], 0, b"", b""),
            subprocess.CompletedProcess([], 0, json.dumps({"status": status}), ""),
        ]
    )
    launch = Mock(side_effect=AssertionError("candidate must not launch without usable desktop"))
    monkeypatch.setattr("ai_software_engineer.manager.native_ui.run_owned_subprocess", run)
    monkeypatch.setattr("ai_software_engineer.manager.native_ui.subprocess.Popen", launch)
    with pytest.raises(NativeUiUnavailable, match=r"SESSION_|invalid session"):
        run_native_ui(native_ui_capability(scenario()), capability(), Path.cwd(), private, {})
    launch.assert_not_called()
    assert run.call_args.args[0] == [str(private / "ASEAXDriver"), "--session-check"]


def test_exited_mock_preserves_exact_launch_diagnostics_without_retry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tests.recovery.test_verification_environment import capability

    private = tmp_path.resolve()
    binary = private / "build/debug/ASEUIProbe"
    binary.parent.mkdir(parents=True)
    binary.touch()
    (private / "ASEAXDriver").touch()
    run = Mock(
        side_effect=[
            subprocess.CompletedProcess([], 0, b"", b""),
            subprocess.CompletedProcess([], 0, '{"status":"READY"}', ""),
        ]
    )
    process = Mock(pid=123)
    process.poll.return_value = 3
    launch = Mock(return_value=process)
    monkeypatch.setattr("ai_software_engineer.manager.native_ui.run_owned_subprocess", run)
    monkeypatch.setattr("ai_software_engineer.manager.native_ui.subprocess.Popen", launch)
    monkeypatch.setattr("ai_software_engineer.manager.native_ui.finish_owned_process", Mock())
    monkeypatch.setattr("ai_software_engineer.manager.native_ui.time.sleep", lambda _: None)
    results = run_native_ui(native_ui_capability(scenario()), capability(), Path.cwd(), private, {})
    assert len(results) == 1
    output = results[0].output
    assert output.error == "PROCESS_EXITED" and output.pid == 123
    assert output.diagnostics is not None
    assert output.diagnostics.launch_argv == (str(binary), "--mock-fixture")
    assert output.diagnostics.process_returncode == 3
    assert output.diagnostics.process_running is False
    assert run.call_count == 2  # compile + session; no AX call or candidate replay
    launch.assert_called_once()


def test_missing_approved_pixels_is_a_typed_environment_block(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tests.recovery.test_verification_environment import capability

    private = tmp_path.resolve()
    binary = private / "build/debug/ASEUIProbe"
    binary.parent.mkdir(parents=True)
    binary.touch()
    (private / "ASEAXDriver").touch()
    run = Mock(
        side_effect=[
            subprocess.CompletedProcess([], 0, b"", b""),
            subprocess.CompletedProcess([], 0, '{"status":"READY"}', ""),
            subprocess.CompletedProcess(
                [],
                0,
                json.dumps(
                    {
                        "pid": 123,
                        "action": "snapshot",
                        "nodes": [{"path": "0", "attributes": {"AXRole": "AXWindow"}}],
                    }
                ),
                "",
            ),
        ]
    )
    process = Mock(pid=123)
    process.poll.side_effect = [None, None, 0]
    launch = Mock(return_value=process)
    monkeypatch.setattr("ai_software_engineer.manager.native_ui.run_owned_subprocess", run)
    monkeypatch.setattr("ai_software_engineer.manager.native_ui.subprocess.Popen", launch)
    monkeypatch.setattr("ai_software_engineer.manager.native_ui.finish_owned_process", Mock())
    monkeypatch.setattr("ai_software_engineer.manager.native_ui.time.sleep", lambda _: None)
    capture = scenario().model_copy(
        update={"steps": (NativeUiStep(name="initial", capture_window=True),)}
    )
    with pytest.raises(NativeUiUnavailable, match="approved snapshot"):
        run_native_ui(native_ui_capability(capture), capability(), Path.cwd(), private, {})
    assert run.call_count == 3
    launch.assert_called_once()


@pytest.mark.skipif(os.environ.get("ASE_RUN_NATIVE_UI_TESTS") != "1", reason="explicit GUI test")
def test_real_native_ui_reads_and_presses_only_fixture_window(tmp_path: Path) -> None:
    private = (tmp_path / "private").resolve()
    private.mkdir()
    binary, driver = private / "ASEUIProbe", private / "ASEAXDriver"
    fixture = Path(__file__).parents[1] / "fixtures/macos_ui_probe.swift"
    for source, output in ((fixture, binary), (driver_source(), driver)):
        result = subprocess.run(
            ["/usr/bin/xcrun", "swiftc", str(source), "-o", str(output)],
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        assert result.returncode == 0, result.stderr
    capability = native_ui_capability(scenario())
    protected = tmp_path / "private-host-fixture"
    protected.write_text("unchanged")
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        isolated = subprocess.run(
            [
                "/usr/bin/sandbox-exec",
                "-p",
                native_ui_profile(capability, binary, private),
                str(binary),
                "--isolation-probe",
                str(protected),
                str(private / "scratch-check"),
                str(listener.getsockname()[1]),
            ],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
            env={"PATH": "/usr/bin:/bin", "TMPDIR": str(private)},
        )
        assert isolated.returncode == 0, isolated.stderr
        for expected in (
            "READ_DENIED=true",
            "WRITE_DENIED=true",
            "SCRATCH_WRITE=true",
            "NETWORK_DENIED=true",
            "OTHER_EXEC_DENIED=true",
        ):
            assert expected in isolated.stdout
    assert protected.read_text() == "unchanged"
    # Exercise the real production executor, including its sandboxed trusted-driver compiler.
    built = private / "build" / "debug"
    built.mkdir(parents=True)
    shutil.copyfile(binary, built / "ASEUIProbe")
    (built / "ASEUIProbe").chmod(0o700)
    for directory in ("clang", "tmp"):
        (private / directory).mkdir()
    execution_scenario = scenario().model_copy(
        update={
            "steps": (
                NativeUiStep(name="initial"),
                NativeUiStep(
                    name="toggle",
                    action="press",
                    role="AXCheckBox",
                    attribute="AXIdentifier",
                    value="ase-fixture-toggle",
                ),
            )
        }
    )
    build_capability = discover_swift_sandbox_capability(os.environ["ASE_TEST_CODEX_EXECUTABLE"])
    assert build_capability is not None
    production_results = run_native_ui(
        native_ui_capability(execution_scenario),
        build_capability,
        Path.cwd().resolve(),
        private,
        {
            "PATH": "/usr/bin:/bin",
            "LANG": "C",
            "DEVELOPER_DIR": build_capability.developer_directory,
            "TMPDIR": str(private / "tmp"),
            "CLANG_MODULE_CACHE_PATH": str(private / "clang"),
        },
    )
    assert len(production_results) == 2
    assert all(result.output.error is None for result in production_results)
    for ui_result in production_results:
        diagnostic = ui_result.output.diagnostics
        assert diagnostic is not None
        assert diagnostic.session_status == "READY" and diagnostic.ax_trusted is True
        assert diagnostic.native_window_count is not None and diagnostic.native_window_count >= 1
        assert diagnostic.ax_status == 0 and diagnostic.ax_window_count == 1
        assert diagnostic.process_running is True
        assert diagnostic.launch_argv == (str(built / "ASEUIProbe"), "--mock-fixture")
    assert (
        next(
            n
            for n in production_results[1].output.nodes
            if n.attributes.get("AXIdentifier") == "ase-fixture-toggle"
        ).attributes["AXValue"]
        == "1"
    )
    with subprocess.Popen(
        [
            "/usr/bin/sandbox-exec",
            "-p",
            native_ui_profile(capability, binary, private),
            str(binary),
        ],
        env={"PATH": "/usr/bin:/bin", "LANG": "C", "TMPDIR": str(private)},
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
    ) as process:
        try:
            assert process.stdout is not None
            assert select.select([process.stdout], [], [], 10)[0], "fixture startup timeout"
            started = process.stdout.readline().strip()
            if not started:
                _, error = process.communicate(timeout=5)
                pytest.fail(f"fixture launch failed: {error}")
            assert started == f"ASE_UI_PID={process.pid}"
            time.sleep(2)

            def invoke(
                step: NativeUiStep, title: str = scenario().window_title
            ) -> subprocess.CompletedProcess[str]:
                return subprocess.run(
                    [str(driver)],
                    input=json.dumps(
                        {"pid": process.pid, "window_title": title, "step": step.to_wire()}
                    ),
                    capture_output=True,
                    text=True,
                    timeout=15,
                    check=False,
                    env={"PATH": "/usr/bin:/bin", "LANG": "C"},
                )

            snapshot = invoke(NativeUiStep(name="initial"))
            assert snapshot.returncode == 0, snapshot.stdout + snapshot.stderr
            initial = json.loads(snapshot.stdout)
            assert all(n["attributes"].get("AXRole") != "AXMenuBar" for n in initial["nodes"])
            toggle = next(
                n
                for n in initial["nodes"]
                if n["attributes"].get("AXIdentifier") == "ase-fixture-toggle"
            )
            assert toggle["attributes"]["AXValue"] == "0"
            pressed = invoke(
                NativeUiStep(
                    name="toggle",
                    action="press",
                    role="AXCheckBox",
                    attribute="AXIdentifier",
                    value="ase-fixture-toggle",
                )
            )
            assert pressed.returncode == 0, pressed.stdout
            changed = json.loads(pressed.stdout)
            toggle = next(
                n
                for n in changed["nodes"]
                if n["attributes"].get("AXIdentifier") == "ase-fixture-toggle"
            )
            assert toggle["attributes"]["AXValue"] == "1"
            assert invoke(NativeUiStep(name="wrong"), "Unapproved window").returncode == 1
        finally:
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGTERM)
            process.communicate(timeout=10)


@pytest.mark.skipif(os.environ.get("ASE_RUN_NATIVE_UI_TESTS") != "1", reason="explicit GUI test")
@pytest.mark.parametrize("ambiguous_scroll", [False, True])
def test_real_swiftui_launch_exposes_its_primary_window(
    tmp_path: Path, ambiguous_scroll: bool
) -> None:
    private = (tmp_path / "private").resolve()
    binary = private / "build/debug/ASEUIProbe"
    binary.parent.mkdir(parents=True)
    for directory in ("clang", "tmp"):
        (private / directory).mkdir()
    fixture = Path(__file__).parents[1] / "fixtures/macos_swiftui_probe.swift"
    compiled = subprocess.run(
        ["/usr/bin/xcrun", "swiftc", "-parse-as-library", str(fixture), "-o", str(binary)],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert compiled.returncode == 0, compiled.stderr
    capability = discover_swift_sandbox_capability(os.environ["ASE_TEST_CODEX_EXECUTABLE"])
    assert capability is not None
    results = run_native_ui(
        native_ui_capability(
            scenario().model_copy(
                update={
                    "mock_argument": "--mock-two-scrolls" if ambiguous_scroll else "--mock-fixture",
                    "steps": (
                        NativeUiStep(name="initial", capture_window=True),
                        NativeUiStep(
                            name="select_only",
                            action="press",
                            role="AXLink",
                            attribute="AXIdentifier",
                            value="ase-swiftui-link",
                        ),
                        NativeUiStep(name="after_link", capture_window=True),
                        NativeUiStep(name="scroll_bottom", action="scroll", scroll_position=1.0),
                        NativeUiStep(name="at_bottom", capture_window=True),
                        NativeUiStep(name="scroll_top", action="scroll", scroll_position=0.0),
                        NativeUiStep(name="at_top", capture_window=True),
                    ),
                }
            )
        ),
        capability,
        Path.cwd().resolve(),
        private,
        {
            "PATH": "/usr/bin:/bin",
            "LANG": "C",
            "DEVELOPER_DIR": capability.developer_directory,
            "TMPDIR": str(private / "tmp"),
            "CLANG_MODULE_CACHE_PATH": str(private / "clang"),
        },
    )
    assert results[0].output.error is None, results[0].output.to_wire()
    assert any(
        n.attributes.get("AXIdentifier") == "ase-swiftui-banner" for n in results[0].output.nodes
    )
    assert all(r.output.error is None for r in results[:3])
    assert any(
        n.attributes.get("AXRole") == "AXLink"
        and n.attributes.get("AXIdentifier") == "ase-swiftui-link"
        for n in results[0].output.nodes
    )
    assert any("Link presses: 0" in n.attributes.values() for n in results[0].output.nodes)
    assert any("Link presses: 1" in n.attributes.values() for n in results[2].output.nodes)
    before, after = results[0].output.capture, results[2].output.capture
    assert before is not None and after is not None
    assert before.window_id == after.window_id
    assert before.image.sha256 != after.image.sha256
    assert before.image.width > 100 and before.image.height > 100
    if ambiguous_scroll:
        assert len(results) == 4 and results[-1].output.error == "SCROLL_UNAVAILABLE"
        bars = [n for n in results[-1].output.nodes if n.attributes.get("AXRole") == "AXScrollBar"]
        assert len(bars) == 2 and all(n.attributes["AXValue"] == "0" for n in bars)
        return
    assert len(results) == 7 and all(r.output.error is None for r in results)
    for index, expected in ((0, "0"), (4, "1"), (6, "0")):
        bars = [
            n for n in results[index].output.nodes if n.attributes.get("AXRole") == "AXScrollBar"
        ]
        assert len(bars) == 1 and bars[0].attributes["AXValue"] == expected
    bottom = results[4].output.capture
    assert bottom is not None and bottom.image.sha256 != after.image.sha256
    assert bottom.window_id == after.window_id
