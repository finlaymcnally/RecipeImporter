from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

import cookimport.cli as cli
from cookimport.bench import oracle_upload


runner = CliRunner()


def _make_bundle(
    bundle_dir: Path,
    *,
    run_count: int = 1,
    pair_count: int = 0,
    changed_lines_total: int = 0,
) -> Path:
    bundle_dir.mkdir(parents=True, exist_ok=True)
    source_root = bundle_dir.parent
    (bundle_dir / "upload_bundle_overview.md").write_text(
        "\n".join(
            [
                "# Upload Bundle Overview",
                "",
                f"- benchmark root: `{source_root}`",
                f"- run_count = {run_count}",
                f"- pair_count = {pair_count}",
                f"- changed_lines_total = {changed_lines_total}",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    (bundle_dir / "upload_bundle_index.json").write_text(
        json.dumps(
            {
                "topline": {
                    "run_count": run_count,
                    "pair_count": pair_count,
                    "changed_lines_total": changed_lines_total,
                },
                "self_check": {
                    "run_count_verified": True,
                    "pair_count_verified": True,
                    "changed_lines_verified": True,
                    "topline_consistent": True,
                },
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    (bundle_dir / "upload_bundle_payload.jsonl").write_text(
        '{"path":"row","payload":"benchmark payload"}\n',
        encoding="utf-8",
    )
    return bundle_dir


def test_resolve_oracle_benchmark_bundle_accepts_bundle_dir_and_parent(tmp_path: Path) -> None:
    session_root = tmp_path / "single-profile-benchmark"
    bundle_dir = _make_bundle(session_root / oracle_upload.BENCHMARK_UPLOAD_BUNDLE_DIR_NAME)

    from_bundle = oracle_upload.resolve_oracle_benchmark_bundle(bundle_dir)
    assert from_bundle.source_root == session_root
    assert from_bundle.bundle_dir == bundle_dir
    assert from_bundle.scope == "single_profile_group"

    from_parent = oracle_upload.resolve_oracle_benchmark_bundle(session_root)
    assert from_parent.source_root == session_root
    assert from_parent.bundle_dir == bundle_dir
    assert from_parent.scope == "single_profile_group"


def test_resolve_oracle_benchmark_bundle_rejects_missing_files(tmp_path: Path) -> None:
    session_root = tmp_path / "single-offline-benchmark"
    bundle_dir = session_root / oracle_upload.BENCHMARK_UPLOAD_BUNDLE_DIR_NAME
    bundle_dir.mkdir(parents=True, exist_ok=True)
    (bundle_dir / "upload_bundle_overview.md").write_text("overview\n", encoding="utf-8")

    with pytest.raises(ValueError, match="missing"):
        oracle_upload.resolve_oracle_benchmark_bundle(session_root)


def test_resolve_oracle_browser_profile_dir_prefers_most_recent_populated_profile(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    current_profile = tmp_path / "current" / "browser-profile"
    legacy_profile = tmp_path / "legacy" / "browser-profile"
    (current_profile / "Default").mkdir(parents=True, exist_ok=True)
    (legacy_profile / "Default").mkdir(parents=True, exist_ok=True)
    current_cookie = current_profile / "Default" / "Cookies"
    legacy_cookie = legacy_profile / "Default" / "Cookies"
    current_cookie.write_text("current", encoding="utf-8")
    legacy_cookie.write_text("legacy", encoding="utf-8")
    current_mtime = 1_700_000_000
    legacy_mtime = current_mtime + 100
    os.utime(current_cookie, (current_mtime, current_mtime))
    os.utime(legacy_cookie, (legacy_mtime, legacy_mtime))

    monkeypatch.setattr(oracle_upload, "ORACLE_BROWSER_PROFILE_DIR", str(current_profile))
    monkeypatch.setattr(oracle_upload, "ORACLE_LEGACY_BROWSER_PROFILE_DIR", str(legacy_profile))

    resolved = oracle_upload._resolve_oracle_browser_profile_dir(env={})

    assert resolved == legacy_profile


def test_run_oracle_benchmark_upload_assembles_browser_command(tmp_path: Path) -> None:
    bundle_dir = _make_bundle(
        tmp_path / "single-offline-benchmark" / oracle_upload.BENCHMARK_UPLOAD_BUNDLE_DIR_NAME
    )
    target = oracle_upload.resolve_oracle_benchmark_bundle(bundle_dir)

    captured: dict[str, object] = {}

    def fake_runner(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        captured["command"] = command
        captured["kwargs"] = kwargs
        return subprocess.CompletedProcess(
            command,
            0,
            stdout="browser ok\n",
            stderr="",
        )

    result = oracle_upload.run_oracle_benchmark_upload(
        target=target,
        mode="browser",
        runner=fake_runner,
    )

    assert result.success is True
    assert result.mode == "browser"
    assert result.bundle_dir == bundle_dir
    command = captured["command"]
    assert isinstance(command, list)
    assert command[:10] == [
        oracle_upload.ORACLE_BROWSER_CMD,
        "--engine",
        "browser",
        "--browser-manual-login",
        "--browser-chrome-path",
        oracle_upload.ORACLE_BROWSER_CHROME_PATH,
        "--browser-model-strategy",
        oracle_upload.ORACLE_BROWSER_MODEL_STRATEGY,
        "--browser-input-timeout",
        "90s",
    ]
    assert command[10:24] == [
        "--browser-reuse-wait",
        oracle_upload.ORACLE_BROWSER_REUSE_WAIT,
        "--browser-profile-lock-timeout",
        oracle_upload.ORACLE_BROWSER_PROFILE_LOCK_TIMEOUT,
        "--browser-auto-reattach-delay",
        oracle_upload.ORACLE_BROWSER_AUTO_REATTACH_DELAY,
        "--browser-auto-reattach-interval",
        oracle_upload.ORACLE_BROWSER_AUTO_REATTACH_INTERVAL,
        "--browser-auto-reattach-timeout",
        oracle_upload.ORACLE_BROWSER_AUTO_REATTACH_TIMEOUT,
        "--browser-attachments",
        "always",
        "--browser-bundle-files",
        "--model",
    ]
    assert oracle_upload.ORACLE_DEFAULT_MODEL in command
    assert command.count("--file") == 3
    for file_argument in oracle_upload._oracle_file_arguments(
        [bundle_dir / file_name for file_name in oracle_upload.BENCHMARK_UPLOAD_BUNDLE_FILE_NAMES]
    ):
        assert file_argument in command
    assert "-p" in command
    kwargs = captured["kwargs"]
    assert kwargs["check"] is False
    assert kwargs["capture_output"] is True
    assert kwargs["text"] is True
    env = kwargs["env"]
    assert isinstance(env, dict)
    resolved_profile = oracle_upload._resolve_oracle_browser_profile_dir(env={})
    assert env["ORACLE_HOME_DIR"] == str(resolved_profile.parent)
    assert env["ORACLE_BROWSER_PROFILE_DIR"] == str(resolved_profile)
    assert env["ORACLE_BROWSER_REMOTE_DEBUG_HOST"] == oracle_upload.ORACLE_BROWSER_REMOTE_DEBUG_HOST


def test_run_oracle_benchmark_upload_adds_chatgpt_target_url_when_configured(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    bundle_dir = _make_bundle(
        tmp_path / "single-offline-benchmark" / oracle_upload.BENCHMARK_UPLOAD_BUNDLE_DIR_NAME
    )
    target = oracle_upload.resolve_oracle_benchmark_bundle(bundle_dir)
    monkeypatch.setenv(
        "COOKIMPORT_ORACLE_CHATGPT_URL",
        "https://chatgpt.com/g/g-123/project",
    )
    captured: dict[str, object] = {}

    def fake_runner(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        captured["command"] = command
        return subprocess.CompletedProcess(command, 0, stdout="browser ok\n", stderr="")

    result = oracle_upload.run_oracle_benchmark_upload(
        target=target,
        mode="browser",
        runner=fake_runner,
    )

    assert result.success is True
    command = captured["command"]
    assert isinstance(command, list)
    assert "--chatgpt-url" in command
    assert "https://chatgpt.com/g/g-123/project" in command


def test_run_oracle_benchmark_upload_assembles_dry_run_command(tmp_path: Path) -> None:
    bundle_dir = _make_bundle(
        tmp_path / "single-profile-benchmark" / oracle_upload.BENCHMARK_UPLOAD_BUNDLE_DIR_NAME
    )
    target = oracle_upload.resolve_oracle_benchmark_bundle(bundle_dir.parent)

    captured: dict[str, object] = {}

    def fake_runner(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        captured["command"] = command
        captured["kwargs"] = kwargs
        return subprocess.CompletedProcess(
            command,
            0,
            stdout="dry run ok\n",
            stderr="",
        )

    result = oracle_upload.run_oracle_benchmark_upload(
        target=target,
        mode="dry-run",
        runner=fake_runner,
    )

    assert result.success is True
    assert result.mode == "dry-run"
    command = captured["command"]
    assert isinstance(command, list)
    assert command[:6] == list(oracle_upload.ORACLE_DRY_RUN_BASE_COMMAND)
    assert "--model" in command
    assert oracle_upload.ORACLE_DEFAULT_MODEL in command
    assert command.count("--file") == 3
    for file_argument in oracle_upload._oracle_file_arguments(
        [bundle_dir / file_name for file_name in oracle_upload.BENCHMARK_UPLOAD_BUNDLE_FILE_NAMES]
    ):
        assert file_argument in command


def test_run_oracle_benchmark_upload_dry_run_falls_back_to_local_preview_for_large_bundle(
    tmp_path: Path,
) -> None:
    bundle_dir = _make_bundle(
        tmp_path / "single-profile-benchmark" / oracle_upload.BENCHMARK_UPLOAD_BUNDLE_DIR_NAME
    )
    (bundle_dir / "upload_bundle_payload.jsonl").write_text(
        "x" * (oracle_upload.ORACLE_INLINE_FILE_SIZE_LIMIT_BYTES + 1),
        encoding="utf-8",
    )
    target = oracle_upload.resolve_oracle_benchmark_bundle(bundle_dir)

    result = oracle_upload.run_oracle_benchmark_upload(
        target=target,
        mode="dry-run",
    )

    assert result.success is True
    assert result.mode == "dry-run"
    assert result.returncode == 0
    assert "Local dry-run preview only" in result.stdout
    assert "upload_bundle_payload.jsonl" in result.stdout
    assert result.command[:10] == [
        oracle_upload.ORACLE_BROWSER_CMD,
        "--engine",
        "browser",
        "--browser-manual-login",
        "--browser-chrome-path",
        oracle_upload.ORACLE_BROWSER_CHROME_PATH,
        "--browser-model-strategy",
        oracle_upload.ORACLE_BROWSER_MODEL_STRATEGY,
        "--browser-input-timeout",
        "90s",
    ]
    assert result.command[10:24] == [
        "--browser-reuse-wait",
        oracle_upload.ORACLE_BROWSER_REUSE_WAIT,
        "--browser-profile-lock-timeout",
        oracle_upload.ORACLE_BROWSER_PROFILE_LOCK_TIMEOUT,
        "--browser-auto-reattach-delay",
        oracle_upload.ORACLE_BROWSER_AUTO_REATTACH_DELAY,
        "--browser-auto-reattach-interval",
        oracle_upload.ORACLE_BROWSER_AUTO_REATTACH_INTERVAL,
        "--browser-auto-reattach-timeout",
        oracle_upload.ORACLE_BROWSER_AUTO_REATTACH_TIMEOUT,
        "--browser-attachments",
        "always",
        "--browser-bundle-files",
        "--model",
    ]


def test_run_oracle_benchmark_upload_browser_shards_oversized_payload(
    tmp_path: Path,
) -> None:
    bundle_dir = _make_bundle(
        tmp_path / "single-offline-benchmark" / oracle_upload.BENCHMARK_UPLOAD_BUNDLE_DIR_NAME
    )
    payload_rows = []
    while len("".join(payload_rows).encode("utf-8")) <= (
        oracle_upload.ORACLE_INLINE_FILE_SIZE_LIMIT_BYTES + 50_000
    ):
        payload_rows.append('{"path":"row","payload":"' + ("x" * 2000) + '"}\n')
    (bundle_dir / "upload_bundle_payload.jsonl").write_text(
        "".join(payload_rows),
        encoding="utf-8",
    )
    target = oracle_upload.resolve_oracle_benchmark_bundle(bundle_dir)

    captured: dict[str, object] = {}

    def fake_runner(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        captured["command"] = command
        captured["kwargs"] = kwargs
        file_args = [
            Path(command[index + 1])
            for index, arg in enumerate(command)
            if arg == "--file"
        ]
        captured["file_args"] = file_args
        for path in file_args:
            assert path.is_file()
            assert path.stat().st_size <= oracle_upload.ORACLE_INLINE_FILE_SIZE_LIMIT_BYTES
        prompt = command[command.index("-p") + 1]
        assert "split into ordered shards" in prompt
        assert "upload_bundle_payload.part001.jsonl" in prompt
        return subprocess.CompletedProcess(
            command,
            0,
            stdout="browser ok\n",
            stderr="",
        )

    result = oracle_upload.run_oracle_benchmark_upload(
        target=target,
        mode="browser",
        runner=fake_runner,
    )

    assert result.success is True
    assert "Prepared sharded Oracle browser upload" in result.stdout
    command = captured["command"]
    assert isinstance(command, list)
    file_args = captured["file_args"]
    assert isinstance(file_args, list)
    file_names = sorted(path.name for path in file_args)
    assert "upload_bundle_overview.md" in file_names
    assert "upload_bundle_index.json" in file_names
    assert "upload_bundle_payload.jsonl" not in file_names
    assert any(name.startswith("upload_bundle_payload.part") for name in file_names)
    assert len(file_args) > 3
    kwargs = captured["kwargs"]
    assert kwargs["check"] is False
    assert kwargs["capture_output"] is True
    assert kwargs["text"] is True
    env = kwargs["env"]
    assert isinstance(env, dict)
    resolved_profile = oracle_upload._resolve_oracle_browser_profile_dir(env={})
    assert env["ORACLE_HOME_DIR"] == str(resolved_profile.parent)
    assert env["ORACLE_BROWSER_PROFILE_DIR"] == str(resolved_profile)
    assert env["ORACLE_BROWSER_REMOTE_DEBUG_HOST"] == oracle_upload.ORACLE_BROWSER_REMOTE_DEBUG_HOST


def test_start_oracle_benchmark_upload_background_persists_sharded_inputs(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    bundle_dir = _make_bundle(
        tmp_path / "single-offline-benchmark" / oracle_upload.BENCHMARK_UPLOAD_BUNDLE_DIR_NAME
    )
    payload_rows = []
    while len("".join(payload_rows).encode("utf-8")) <= (
        oracle_upload.ORACLE_INLINE_FILE_SIZE_LIMIT_BYTES + 50_000
    ):
        payload_rows.append('{"path":"row","payload":"' + ("x" * 2000) + '"}\n')
    (bundle_dir / "upload_bundle_payload.jsonl").write_text(
        "".join(payload_rows),
        encoding="utf-8",
    )
    target = oracle_upload.resolve_oracle_benchmark_bundle(bundle_dir)

    captured: dict[str, object] = {}

    monkeypatch.setattr(oracle_upload, "_detect_oracle_version", lambda: "0.8.6-test")

    class FakePopen:
        def __init__(self, command: list[str], **kwargs: object) -> None:
            captured["command"] = command
            captured["kwargs"] = kwargs
            log_handle = kwargs["stdout"]
            assert log_handle is not None
            log_handle.write(
                "Session running in background. Reattach via: oracle session test-session-123\n"
            )
            log_handle.flush()
            self.pid = 4242

    launch = oracle_upload.start_oracle_benchmark_upload_background(
        target=target,
        mode="browser",
        popen=FakePopen,
    )

    assert launch.pid == 4242
    assert launch.bundle_dir == bundle_dir
    assert launch.launch_dir.parent == bundle_dir / oracle_upload.ORACLE_UPLOAD_RUNS_DIR_NAME
    assert launch.log_path.is_file()
    assert launch.metadata_path.is_file()
    assert "Prepared sharded Oracle browser upload" in launch.note
    assert launch.browser_profile_dir == oracle_upload._resolve_oracle_browser_profile_dir(env={})
    log_text = launch.log_path.read_text(encoding="utf-8")
    assert "Prepared sharded Oracle browser upload" in log_text
    assert "Oracle browser profile:" in log_text
    assert "Oracle command:" in log_text
    metadata = json.loads(launch.metadata_path.read_text(encoding="utf-8"))
    assert metadata["pid"] == 4242
    assert metadata["bundle_dir"] == str(bundle_dir)
    assert metadata["log_path"] == str(launch.log_path)
    assert metadata["mode"] == "browser"
    assert metadata["browser_profile_dir"] == str(launch.browser_profile_dir)
    assert metadata["oracle_version"] == "0.8.6-test"
    assert metadata["session_id"] == "test-session-123"
    assert metadata["reattach_command"] == "oracle session test-session-123"
    assert metadata["status"] == "running"
    assert metadata["status_reason"] == "Oracle session launched and awaiting completion."
    assert launch.oracle_version == "0.8.6-test"
    assert launch.session_id == "test-session-123"
    assert launch.reattach_command == "oracle session test-session-123"
    assert launch.status == "running"
    assert launch.status_reason == "Oracle session launched and awaiting completion."
    command = captured["command"]
    assert isinstance(command, list)
    file_args = [
        Path(command[index + 1])
        for index, arg in enumerate(command)
        if arg == "--file"
    ]
    assert len(file_args) > 3
    assert "upload_bundle_payload.jsonl" not in {path.name for path in file_args}
    assert any(path.name.startswith("upload_bundle_payload.part") for path in file_args)
    for path in file_args:
        assert path.is_file()
        assert path.stat().st_size <= oracle_upload.ORACLE_INLINE_FILE_SIZE_LIMIT_BYTES
    kwargs = captured["kwargs"]
    assert kwargs["stdin"] == subprocess.DEVNULL
    assert kwargs["stderr"] == subprocess.STDOUT
    assert kwargs["text"] is True
    assert kwargs["cwd"] == str(Path.cwd())
    assert kwargs["start_new_session"] is True
    env = kwargs["env"]
    assert isinstance(env, dict)
    resolved_profile = oracle_upload._resolve_oracle_browser_profile_dir(env={})
    assert env["ORACLE_HOME_DIR"] == str(resolved_profile.parent)
    assert env["ORACLE_BROWSER_PROFILE_DIR"] == str(resolved_profile)
    assert env["ORACLE_BROWSER_REMOTE_DEBUG_HOST"] == oracle_upload.ORACLE_BROWSER_REMOTE_DEBUG_HOST


def test_print_background_oracle_upload_summary_points_to_log_without_full_command(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    bundle_dir = _make_bundle(
        tmp_path / "single-offline-benchmark" / oracle_upload.BENCHMARK_UPLOAD_BUNDLE_DIR_NAME
    )
    target = oracle_upload.resolve_oracle_benchmark_bundle(bundle_dir)
    launch = oracle_upload.OracleBackgroundUploadLaunch(
        mode="browser",
        model="gpt-5.2",
        command=["oracle", "--engine", "browser", "--model", "gpt-5.2"],
        bundle_dir=bundle_dir,
        launch_dir=bundle_dir / oracle_upload.ORACLE_UPLOAD_RUNS_DIR_NAME / "2026-03-17_17.05.00",
        log_path=bundle_dir / oracle_upload.ORACLE_UPLOAD_RUNS_DIR_NAME / "2026-03-17_17.05.00" / oracle_upload.ORACLE_UPLOAD_LOG_FILE_NAME,
        metadata_path=bundle_dir / oracle_upload.ORACLE_UPLOAD_RUNS_DIR_NAME / "2026-03-17_17.05.00" / oracle_upload.ORACLE_UPLOAD_METADATA_FILE_NAME,
        pid=4242,
        note="Prepared sharded Oracle browser upload for oversized bundle files: upload_bundle_payload.jsonl (37675212 bytes).",
        browser_profile_dir=Path("/tmp/oracle-profile"),
    )

    messages: list[str] = []
    monkeypatch.setattr(
        cli.typer,
        "secho",
        lambda message, **_kwargs: messages.append(str(message)),
    )
    monkeypatch.setattr(cli.typer, "echo", lambda message="", **_kwargs: messages.append(str(message)))

    cli._print_background_oracle_upload_summary(
        target=target,
        launch=launch,
    )

    assert any("Oracle response/log:" in message for message in messages)
    assert any(
        "Oracle browser launcher: auto (visible with display, xvfb otherwise)"
        in message
        for message in messages
    )
    assert any("Oracle browser profile: /tmp/oracle-profile" in message for message in messages)
    assert any("When Oracle finishes, open that log file to read the response." in message for message in messages)
    assert any("oversized bundle files were sharded for upload" in message for message in messages)
    assert not any(message.startswith("Oracle command:") for message in messages)
    assert not any(message.startswith("Oracle launch metadata:") for message in messages)


def test_bench_oracle_upload_command_resolves_existing_single_profile_root(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    sample_single_profile_root = tmp_path / "single-profile-benchmark"
    _make_bundle(sample_single_profile_root / oracle_upload.BENCHMARK_UPLOAD_BUNDLE_DIR_NAME)
    captured: dict[str, object] = {}

    def fake_run_oracle_benchmark_upload(
        *,
        target: oracle_upload.OracleBenchmarkBundleTarget,
        mode: str,
        model: str,
    ) -> oracle_upload.OracleUploadResult:
        captured["target"] = target
        captured["mode"] = mode
        captured["model"] = model
        return oracle_upload.OracleUploadResult(
            success=True,
            mode=mode,
            command=["npx", "-y", "@steipete/oracle", "--dry-run"],
            bundle_dir=target.bundle_dir,
            returncode=0,
            stdout="files-report ok\n",
            stderr="",
        )

    monkeypatch.setattr(cli, "run_oracle_benchmark_upload", fake_run_oracle_benchmark_upload)

    result = runner.invoke(
        cli.app,
        [
            "bench",
            "oracle-upload",
            str(sample_single_profile_root),
            "--mode",
            "dry-run",
        ],
    )

    assert result.exit_code == 0
    assert captured["mode"] == "dry-run"
    target = captured["target"]
    assert isinstance(target, oracle_upload.OracleBenchmarkBundleTarget)
    assert target.bundle_dir == (
        sample_single_profile_root / oracle_upload.BENCHMARK_UPLOAD_BUNDLE_DIR_NAME
    )
    assert str(target.bundle_dir) in result.output
    assert "Oracle mode: dry-run" in result.output


def test_maybe_upload_benchmark_bundle_to_oracle_is_best_effort(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    bundle_dir = _make_bundle(
        tmp_path / "single-offline-benchmark" / oracle_upload.BENCHMARK_UPLOAD_BUNDLE_DIR_NAME
    )
    target = oracle_upload.resolve_oracle_benchmark_bundle(bundle_dir)

    monkeypatch.setattr(cli, "resolve_oracle_benchmark_bundle", lambda _path: target)
    monkeypatch.setattr(
        cli,
        "run_oracle_benchmark_upload",
        lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("oracle broke")),
    )

    cli._maybe_upload_benchmark_bundle_to_oracle(
        bundle_dir=bundle_dir,
        scope="single_offline",
    )
