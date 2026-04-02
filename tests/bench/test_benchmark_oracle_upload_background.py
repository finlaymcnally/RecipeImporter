from __future__ import annotations

import tests.bench.oracle_upload_support as _support

# Reuse shared imports/helpers from the local support module.
globals().update({
    name: value
    for name, value in _support.__dict__.items()
    if not name.startswith("test_")
    and not (name.startswith("__") and name.endswith("__"))
})


def test_start_oracle_benchmark_upload_background_persists_sharded_inputs(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    bundle_dir = _make_bundle(
        tmp_path / "single-book-benchmark" / oracle_upload.BENCHMARK_UPLOAD_BUNDLE_DIR_NAME
    )
    _write_profile_bundle_context(bundle_dir)
    payload_rows = []
    for path in oracle_upload.resolve_oracle_benchmark_review_profile("quality").payload_paths:
        payload_rows.append(
            {
                "path": path,
                "payload": "x" * 120_000,
            }
        )
    _review_file(bundle_dir, "payload.json").write_text(
        json.dumps(
            {
                "schema_version": "upload_bundle.review_payload.v1",
                "review_profile": "quality",
                "row_count": len(payload_rows),
                "rows": payload_rows,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
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
        model="instant",
        review_profile="quality",
        popen=FakePopen,
    )

    assert launch.pid == 4242
    assert launch.bundle_dir == bundle_dir
    assert launch.launch_dir.parent == _runs_dir(bundle_dir)
    assert launch.log_path.is_file()
    assert launch.metadata_path.is_file()
    assert "Prepared Oracle quality review packet" in launch.note
    assert launch.browser_profile_dir == oracle_upload._resolve_oracle_browser_profile_dir(env={})
    log_text = launch.log_path.read_text(encoding="utf-8")
    assert "Prepared Oracle quality review packet" in log_text
    assert "Oracle browser profile:" in log_text
    assert "Oracle command:" in log_text
    metadata = json.loads(launch.metadata_path.read_text(encoding="utf-8"))
    assert metadata["pid"] == 4242
    assert metadata["bundle_dir"] == str(bundle_dir)
    assert metadata["log_path"] == str(launch.log_path)
    assert metadata["review_profile"] == "quality"
    assert metadata["review_profile_display_name"] == "Quality"
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
    assert len(file_args) >= 3
    assert "overview.md" in {path.name for path in file_args}
    assert "payload.json" not in {path.name for path in file_args}
    assert any(path.name.startswith("payload.part") for path in file_args)
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


def test_start_oracle_benchmark_upload_background_stages_profile_packet(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    bundle_dir = _make_bundle(
        tmp_path / "single-book-benchmark" / oracle_upload.BENCHMARK_UPLOAD_BUNDLE_DIR_NAME
    )
    _write_profile_bundle_context(bundle_dir)
    _write_profile_payload_rows(bundle_dir)
    target = oracle_upload.resolve_oracle_benchmark_bundle(bundle_dir)

    captured: dict[str, object] = {}

    monkeypatch.setattr(oracle_upload, "_detect_oracle_version", lambda: "0.8.6-test")

    class FakePopen:
        def __init__(self, command: list[str], **kwargs: object) -> None:
            captured["command"] = command
            log_handle = kwargs["stdout"]
            assert log_handle is not None
            log_handle.write(
                "Session running in background. Reattach via: oracle session token-lane-123\n"
            )
            log_handle.flush()
            self.pid = 5252

    launch = oracle_upload.start_oracle_benchmark_upload_background(
        target=target,
        mode="browser",
        model="instant",
        review_profile="token",
        popen=FakePopen,
    )

    assert launch.pid == 5252
    assert launch.review_profile == "token"
    assert launch.model == INSTANT_LANE
    assert "Prepared Oracle token review packet" in launch.note
    command = captured["command"]
    assert isinstance(command, list)
    assert command[command.index("--model") + 1] == INSTANT_MODEL
    file_args = [
        Path(command[index + 1])
        for index, arg in enumerate(command)
        if arg == "--file"
    ]
    assert len(file_args) == 3
    payload_path = next(path for path in file_args if path.name == "payload.json")
    payload_text = payload_path.read_text(encoding="utf-8")
    assert "codex-exec/prompt_budget_summary.json" in payload_text
    assert "starter_pack_v1/02_call_inventory.jsonl" in payload_text
    prompt = command[command.index("-p") + 1]
    assert "`token` lane packet" in prompt
    assert "--browser-keep-browser" not in command


def test_start_oracle_benchmark_upload_background_marks_running_when_process_alive_but_no_session_hint(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    bundle_dir = _make_bundle(
        tmp_path / "single-book-benchmark" / oracle_upload.BENCHMARK_UPLOAD_BUNDLE_DIR_NAME
    )
    target = oracle_upload.resolve_oracle_benchmark_bundle(bundle_dir)
    monkeypatch.setattr(oracle_upload, "_detect_oracle_version", lambda: "0.8.6-test")
    captured: dict[str, object] = {}

    class FakePopen:
        def __init__(self, command: list[str], **kwargs: object) -> None:
            captured["command"] = command
            log_handle = kwargs["stdout"]
            assert log_handle is not None
            log_handle.write(
                "🧿 oracle 0.8.6 — Background magic with foreground receipts.\n"
                f"Launching browser mode ({INSTANT_MODEL}) with ~123 tokens.\n"
            )
            log_handle.flush()
            self.pid = 4243

        def poll(self) -> None:
            return None

    launch = oracle_upload.start_oracle_benchmark_upload_background(
        target=target,
        mode="browser",
        model="instant",
        popen=FakePopen,
    )

    assert "--browser-keep-browser" not in captured["command"]
    assert launch.status == "running"
    assert launch.status_reason == "Oracle process is still running; awaiting session hint or answer."
    assert launch.session_id == ""
    assert launch.reattach_command == ""
    metadata = json.loads(launch.metadata_path.read_text(encoding="utf-8"))
    assert metadata["status"] == "running"
    assert metadata["status_reason"] == "Oracle process is still running; awaiting session hint or answer."


def test_start_oracle_benchmark_upload_background_recovers_session_from_oracle_store_when_log_is_quiet(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    bundle_dir = _make_bundle(
        tmp_path / "single-book-benchmark" / oracle_upload.BENCHMARK_UPLOAD_BUNDLE_DIR_NAME
    )
    target = oracle_upload.resolve_oracle_benchmark_bundle(bundle_dir)
    monkeypatch.setattr(oracle_upload, "_detect_oracle_version", lambda: "0.8.6-test")
    monkeypatch.setattr(
        oracle_upload,
        "_find_matching_oracle_session_snapshot",
        lambda **_kwargs: oracle_upload.OracleSessionSnapshot(
            session_id="you-are-reviewing-a-benchmark-269",
            status="running",
            prompt="prompt",
            created_at="2026-03-19T02:47:52.108Z",
            conversation_url="https://chatgpt.com/c/69bb6568-072c-832f-80b7-8588419c1e27",
            conversation_id="69bb6568-072c-832f-80b7-8588419c1e27",
        ),
    )

    class FakePopen:
        def __init__(self, command: list[str], **kwargs: object) -> None:
            log_handle = kwargs["stdout"]
            assert log_handle is not None
            log_handle.write(
                "🧿 oracle 0.8.6 — Background magic with foreground receipts.\n"
                f"Launching browser mode ({INSTANT_MODEL}) with ~123 tokens.\n"
            )
            log_handle.flush()
            self.pid = 4244

        def poll(self) -> None:
            return None

    launch = oracle_upload.start_oracle_benchmark_upload_background(
        target=target,
        mode="browser",
        model="instant",
        popen=FakePopen,
    )

    assert "--browser-keep-browser" not in launch.command
    assert launch.status == "running"
    assert launch.status_reason == "Oracle session is running; session store metadata is available."
    assert launch.session_id == "you-are-reviewing-a-benchmark-269"
    assert launch.reattach_command == "oracle session you-are-reviewing-a-benchmark-269"
    assert launch.conversation_url == "https://chatgpt.com/c/69bb6568-072c-832f-80b7-8588419c1e27"
    assert launch.conversation_id == "69bb6568-072c-832f-80b7-8588419c1e27"
    metadata = json.loads(launch.metadata_path.read_text(encoding="utf-8"))
    assert metadata["session_id"] == "you-are-reviewing-a-benchmark-269"
    assert metadata["reattach_command"] == "oracle session you-are-reviewing-a-benchmark-269"
    assert metadata["conversation_url"] == "https://chatgpt.com/c/69bb6568-072c-832f-80b7-8588419c1e27"


def test_print_background_oracle_upload_summary_points_to_log_without_full_command(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    bundle_dir = _make_bundle(
        tmp_path / "single-book-benchmark" / oracle_upload.BENCHMARK_UPLOAD_BUNDLE_DIR_NAME
    )
    target = oracle_upload.resolve_oracle_benchmark_bundle(bundle_dir)
    runs_dir = _runs_dir(bundle_dir)
    launch = oracle_upload.OracleBackgroundUploadLaunch(
        mode="browser",
        model=INSTANT_LANE,
        command=["oracle", "--engine", "browser", "--model", INSTANT_MODEL],
        bundle_dir=bundle_dir,
        launch_dir=runs_dir / "2026-03-17_17.05.00",
        log_path=runs_dir / "2026-03-17_17.05.00" / oracle_upload.ORACLE_UPLOAD_LOG_FILE_NAME,
        metadata_path=runs_dir / "2026-03-17_17.05.00" / oracle_upload.ORACLE_UPLOAD_METADATA_FILE_NAME,
        pid=4242,
        note="Prepared Oracle quality review packet with 12 payload rows (25000 bytes).",
        review_profile="quality",
        review_profile_display_name="Quality",
        browser_profile_dir=Path("/tmp/oracle-profile"),
        oracle_version="0.8.6-test",
        status="running",
        status_reason="Oracle session launched and awaiting completion.",
        session_id="test-session-123",
        reattach_command="oracle session test-session-123",
        conversation_url="https://chatgpt.com/c/test-session-123",
        conversation_id="test-session-123",
    )

    messages: list[str] = []
    monkeypatch.setattr(
        cli.typer,
        "secho",
        lambda message, **_kwargs: messages.append(str(message)),
    )
    monkeypatch.setattr(cli_support.typer, "echo", lambda message="", **_kwargs: messages.append(str(message)))

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
    assert any("Oracle version: 0.8.6-test" in message for message in messages)
    assert any("Oracle status: running" in message for message in messages)
    assert any("Reattach: oracle session test-session-123" in message for message in messages)
    assert any("Conversation: https://chatgpt.com/c/test-session-123" in message for message in messages)
    assert any("When Oracle finishes, open that log file to read the response." in message for message in messages)
    assert any("Prepared Oracle quality review packet" in message for message in messages)
    assert not any(message.startswith("Oracle command:") for message in messages)
    assert not any(message.startswith("Oracle launch metadata:") for message in messages)


def test_print_background_oracle_upload_summary_shows_profile_and_note(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    bundle_dir = _make_bundle(
        tmp_path / "single-book-benchmark" / oracle_upload.BENCHMARK_UPLOAD_BUNDLE_DIR_NAME
    )
    target = oracle_upload.resolve_oracle_benchmark_bundle(bundle_dir)
    runs_dir = _runs_dir(bundle_dir)
    launch = oracle_upload.OracleBackgroundUploadLaunch(
        mode="browser",
        model=INSTANT_LANE,
        command=["oracle", "--engine", "browser", "--model", INSTANT_MODEL],
        bundle_dir=bundle_dir,
        launch_dir=runs_dir / "2026-03-21_16.17.50",
        log_path=runs_dir / "2026-03-21_16.17.50" / oracle_upload.ORACLE_UPLOAD_LOG_FILE_NAME,
        metadata_path=runs_dir / "2026-03-21_16.17.50" / oracle_upload.ORACLE_UPLOAD_METADATA_FILE_NAME,
        pid=80663,
        note="Prepared Oracle token review packet with 10 payload rows (18000 bytes).",
        review_profile="token",
        review_profile_display_name="Token",
        browser_profile_dir=Path("/tmp/oracle-profile"),
        oracle_version="0.8.6-test",
        status="running",
        status_reason="Oracle process is still running; awaiting session hint or answer.",
        session_id="you-are-reviewing-a-benchmark-317",
        reattach_command="oracle session you-are-reviewing-a-benchmark-317",
        conversation_url="https://chatgpt.com/c/69befd54-c000-8326-9e9a-7f3e8146eecb",
        conversation_id="69befd54-c000-8326-9e9a-7f3e8146eecb",
    )

    messages: list[str] = []
    monkeypatch.setattr(
        cli.typer,
        "secho",
        lambda message, **_kwargs: messages.append(str(message)),
    )
    monkeypatch.setattr(cli_support.typer, "echo", lambda message="", **_kwargs: messages.append(str(message)))

    cli._print_background_oracle_upload_summary(
        target=target,
        launch=launch,
    )

    assert any(
        "Oracle review profile: Token"
        in message
        for message in messages
    )
    assert any("Prepared Oracle token review packet" in message for message in messages)


def test_start_background_oracle_followup_worker_does_not_forward_launch_default_model_when_override_blank(
    tmp_path: Path,
) -> None:
    bundle_dir = _make_bundle(
        tmp_path / "single-book-benchmark" / oracle_upload.BENCHMARK_UPLOAD_BUNDLE_DIR_NAME
    )
    target = oracle_upload.resolve_oracle_benchmark_bundle(bundle_dir)
    launch_dir = _runs_dir(bundle_dir) / "2026-03-21_11.27.35"
    launch_dir.mkdir(parents=True, exist_ok=True)
    launch = oracle_upload.OracleBackgroundUploadLaunch(
        mode="browser",
        model=INSTANT_LANE,
        command=["oracle", "--engine", "browser", "--model", INSTANT_MODEL],
        bundle_dir=bundle_dir,
        launch_dir=launch_dir,
        log_path=launch_dir / oracle_upload.ORACLE_UPLOAD_LOG_FILE_NAME,
        metadata_path=launch_dir / oracle_upload.ORACLE_UPLOAD_METADATA_FILE_NAME,
        pid=4242,
    )
    captured: dict[str, object] = {}

    class FakePopen:
        def __init__(self, command: list[str], **kwargs: object) -> None:
            captured["command"] = command
            captured["kwargs"] = kwargs
            self.pid = 4243

    updated_launch = cli._start_background_oracle_followup_worker(
        target=target,
        launch=launch,
        model=None,
        popen=FakePopen,
    )

    command = captured["command"]
    assert isinstance(command, list)
    assert "--model" not in command
    status_payload = json.loads(
        (launch_dir / cli.ORACLE_AUTO_FOLLOWUP_STATUS_NAME).read_text(encoding="utf-8")
    )
    assert status_payload["model"] == INSTANT_LANE
    assert updated_launch.auto_followup_worker_pid == 4243


@pytest.mark.heavy_side_effects
def test_start_benchmark_bundle_oracle_upload_background_reports_followup_launch_failure_separately(
    allow_heavy_test_side_effects: None,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("COOKIMPORT_ALLOW_HEAVY_TEST_SIDE_EFFECTS", "1")
    monkeypatch.delenv("COOKIMPORT_DISABLE_HEAVY_TEST_SIDE_EFFECTS", raising=False)
    bundle_dir = _make_bundle(
        tmp_path / "single-book-benchmark" / oracle_upload.BENCHMARK_UPLOAD_BUNDLE_DIR_NAME
    )
    target = oracle_upload.resolve_oracle_benchmark_bundle(bundle_dir)
    runs_dir = _runs_dir(bundle_dir)
    launch = oracle_upload.OracleBackgroundUploadLaunch(
        mode="browser",
        model=INSTANT_LANE,
        command=["oracle", "--engine", "browser", "--model", INSTANT_MODEL],
        bundle_dir=bundle_dir,
        launch_dir=runs_dir / "2026-03-21_11.27.35",
        log_path=runs_dir / "2026-03-21_11.27.35" / oracle_upload.ORACLE_UPLOAD_LOG_FILE_NAME,
        metadata_path=runs_dir / "2026-03-21_11.27.35" / oracle_upload.ORACLE_UPLOAD_METADATA_FILE_NAME,
        pid=4242,
        status="running",
        status_reason="Oracle session is running; session store metadata is available.",
        session_id="you-are-reviewing-a-benchmark-313",
        reattach_command="oracle session you-are-reviewing-a-benchmark-313",
    )
    messages: list[str] = []

    runtime = sys.modules["cookimport.cli_support.bench"]
    oracle_support = sys.modules["cookimport.cli_support.bench_oracle"]
    for module in (cli, cli_support, runtime, oracle_support):
        monkeypatch.setattr(module, "resolve_oracle_benchmark_bundle", lambda _path: target)
        monkeypatch.setattr(
            module,
            "start_oracle_benchmark_upload_background",
            lambda **_kwargs: launch,
        )
        monkeypatch.setattr(
            module,
            "_start_background_oracle_followup_worker",
            lambda **_kwargs: (_ for _ in ()).throw(
                RuntimeError("expected str, bytes or os.PathLike object, not NoneType")
            ),
        )
    monkeypatch.setattr(cli.typer, "secho", lambda message, **_kwargs: messages.append(str(message)))

    cli._start_benchmark_bundle_oracle_upload_background(
        bundle_dir=bundle_dir,
        scope="single_book",
        model=None,
    )

    assert any("Oracle auto-follow-up worker not started" in message for message in messages)
    assert not any("Oracle benchmark upload not started" in message for message in messages)


def test_oracle_upload_log_audit_accepts_grounded_single_profile_answer(tmp_path: Path) -> None:
    bundle_dir = _make_bundle(
        tmp_path / "2026-03-18_19.42.18" / "single-profile-benchmark" / oracle_upload.BENCHMARK_UPLOAD_BUNDLE_DIR_NAME,
        run_count=3,
        pair_count=0,
        changed_lines_total=0,
    )
    target = oracle_upload.resolve_oracle_benchmark_bundle(bundle_dir)

    audit = oracle_upload.audit_oracle_upload_log(
        target=target,
        log_text="\n".join(
            [
                f"oracle ({INSTANT_MODEL})",
                "Reattach via: oracle session grounded-123",
                "Answer:",
                f"Top regressions\n- Benchmark root: {target.source_root}",
                "- run_count = 3",
                "- pair_count = 0",
                "Likely cause buckets\n- none",
                "Immediate next checks\n- none",
            ]
        ),
    )

    assert audit.status == "succeeded"
    assert audit.status_reason == "Answer block present and grounded in the local bundle."
    assert audit.session_id == "grounded-123"
    assert audit.reattach_command == "oracle session grounded-123"


def test_oracle_upload_log_audit_rejects_wrong_bundle_identity(tmp_path: Path) -> None:
    bundle_dir = _make_bundle(
        tmp_path / "2026-03-18_21.10.12" / "single-book-benchmark" / "dinnerfor2cutdown" / oracle_upload.BENCHMARK_UPLOAD_BUNDLE_DIR_NAME,
        run_count=2,
        pair_count=1,
        changed_lines_total=202,
    )
    target = oracle_upload.resolve_oracle_benchmark_bundle(bundle_dir)

    audit = oracle_upload.audit_oracle_upload_log(
        target=target,
        log_text="\n".join(
            [
                f"oracle ({INSTANT_MODEL})",
                "Answer:",
                "Top regressions",
                "- I could not verify the requested 2026-03-18_21.10.12/single-book-benchmark root.",
                "- The attached packet appears to be 2026-03-18_19.42.18/single-profile-benchmark with pair_count = 0.",
                "Likely cause buckets",
                "- stale bundle identity",
                "Immediate next checks",
                "- verify bundle root",
            ]
        ),
    )

    assert audit.status == "invalid_grounding"
    assert "Expected benchmark root" in audit.status_reason


def test_oracle_upload_log_audit_rejects_same_book_different_timestamp_root(
    tmp_path: Path,
) -> None:
    bundle_dir = _make_bundle(
        tmp_path / "2026-03-21_16.10.40" / "single-book-benchmark" / "saltfatacidheatcutdown" / oracle_upload.BENCHMARK_UPLOAD_BUNDLE_DIR_NAME,
        run_count=2,
        pair_count=1,
        changed_lines_total=42,
    )
    target = oracle_upload.resolve_oracle_benchmark_bundle(bundle_dir)

    audit = oracle_upload.audit_oracle_upload_log(
        target=target,
        log_text="\n".join(
            [
                f"oracle ({INSTANT_MODEL})",
                "Answer:",
                "Top regressions",
                (
                    "I could not confirm the requested "
                    "2026-03-21_16.10.40/single-book-benchmark/saltfatacidheatcutdown root. "
                    "The attached packet appears to be "
                    "2026-03-21_14.53.27/single-book-benchmark/saltfatacidheatcutdown."
                ),
                "Likely cause buckets",
                "- bundle identity mismatch",
                "Immediate next checks",
                "- verify exact root",
            ]
        ),
    )

    assert audit.status == "invalid_grounding"
    assert "Expected benchmark root" in audit.status_reason


def test_oracle_upload_log_audit_marks_disconnect_as_reattachable_when_session_id_known(
    tmp_path: Path,
) -> None:
    bundle_dir = _make_bundle(
        tmp_path / "2026-03-18_21.17.59" / "single-book-benchmark" / "saltfatacidheatcutdown" / oracle_upload.BENCHMARK_UPLOAD_BUNDLE_DIR_NAME
    )
    target = oracle_upload.resolve_oracle_benchmark_bundle(bundle_dir)

    audit = oracle_upload.audit_oracle_upload_log(
        target=target,
        log_text="\n".join(
            [
                f"oracle ({INSTANT_MODEL})",
                "Reattach via: oracle session disconnected-123",
                "ERROR: Chrome window closed before oracle finished. Please keep it open until completion.",
                "Chrome disconnected before completion; keeping session running for reattach.",
            ]
        ),
    )

    assert audit.status == "reattachable"
    assert audit.status_reason == "Oracle reported a recoverable browser/session interruption."
    assert audit.session_id == "disconnected-123"
    assert audit.reattach_command == "oracle session disconnected-123"


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
        review_profile: str,
    ) -> oracle_upload.OracleUploadResult:
        captured["target"] = target
        captured["mode"] = mode
        captured["model"] = model
        captured["review_profile"] = review_profile
        return oracle_upload.OracleUploadResult(
            success=True,
            mode=mode,
            command=["npx", "-y", "@steipete/oracle", "--dry-run"],
            bundle_dir=target.bundle_dir,
            returncode=0,
            stdout="files-report ok\n",
            stderr="",
            review_profile=review_profile,
            review_profile_display_name=review_profile.title(),
        )

    monkeypatch.setattr(bench_cli, "run_oracle_benchmark_upload", fake_run_oracle_benchmark_upload)

    result = runner.invoke(
        cli.app,
        [
            "bench",
            "oracle-upload",
            str(sample_single_profile_root),
            "--mode",
            "dry-run",
            "--profile",
            "quality",
        ],
    )

    assert result.exit_code == 0
    assert captured["mode"] == "dry-run"
    assert captured["review_profile"] == "quality"
    target = captured["target"]
    assert isinstance(target, oracle_upload.OracleBenchmarkBundleTarget)
    assert target.bundle_dir == (
        sample_single_profile_root / oracle_upload.BENCHMARK_UPLOAD_BUNDLE_DIR_NAME
    )
    assert str(target.bundle_dir) in result.output
    assert "Oracle review profile: Quality" in result.output
    assert "Oracle mode: dry-run" in result.output


def test_bench_oracle_upload_command_defaults_to_all_profiles(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    sample_single_profile_root = tmp_path / "single-profile-benchmark"
    _make_bundle(sample_single_profile_root / oracle_upload.BENCHMARK_UPLOAD_BUNDLE_DIR_NAME)
    captured_profiles: list[str] = []

    def fake_run_oracle_benchmark_upload(
        *,
        target: oracle_upload.OracleBenchmarkBundleTarget,
        mode: str,
        model: str,
        review_profile: str,
    ) -> oracle_upload.OracleUploadResult:
        captured_profiles.append(review_profile)
        return oracle_upload.OracleUploadResult(
            success=True,
            mode=mode,
            command=["oracle", "--dry-run"],
            bundle_dir=target.bundle_dir,
            returncode=0,
            stdout="ok\n",
            stderr="",
            review_profile=review_profile,
            review_profile_display_name=review_profile.title(),
        )

    monkeypatch.setattr(bench_cli, "run_oracle_benchmark_upload", fake_run_oracle_benchmark_upload)

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
    assert captured_profiles == ["quality", "token"]


@pytest.mark.heavy_side_effects
def test_maybe_upload_benchmark_bundle_to_oracle_is_best_effort(
    allow_heavy_test_side_effects: None,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    bundle_dir = _make_bundle(
        tmp_path / "single-book-benchmark" / oracle_upload.BENCHMARK_UPLOAD_BUNDLE_DIR_NAME
    )
    target = oracle_upload.resolve_oracle_benchmark_bundle(bundle_dir)
    messages: list[str] = []

    runtime = sys.modules["cookimport.cli_support.bench"]
    for module in (cli, cli_support, runtime, bench_oracle_support, bench_cli):
        if hasattr(module, "resolve_oracle_benchmark_bundle"):
            monkeypatch.setattr(module, "resolve_oracle_benchmark_bundle", lambda _path: target)
        if hasattr(module, "run_oracle_benchmark_upload"):
            monkeypatch.setattr(
                module,
                "run_oracle_benchmark_upload",
                lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("oracle broke")),
            )
    monkeypatch.setattr(cli.typer, "secho", lambda message, **_kwargs: messages.append(str(message)))

    cli._maybe_upload_benchmark_bundle_to_oracle(
        bundle_dir=bundle_dir,
        scope="single_book",
    )

    assert any("Oracle quality upload skipped" in message for message in messages)
    assert any("Oracle token upload skipped" in message for message in messages)
