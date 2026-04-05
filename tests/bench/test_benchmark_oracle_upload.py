from __future__ import annotations

import tests.bench.oracle_upload_support as _support

# Reuse shared imports/helpers from the local support module.
globals().update({
    name: value
    for name, value in _support.__dict__.items()
    if not name.startswith("test_")
    and not (name.startswith("__") and name.endswith("__"))
})


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
    session_root = tmp_path / "single-book-benchmark"
    bundle_dir = session_root / oracle_upload.BENCHMARK_UPLOAD_BUNDLE_DIR_NAME
    bundle_dir.mkdir(parents=True, exist_ok=True)
    _review_dir(bundle_dir).mkdir(parents=True, exist_ok=True)
    _review_file(bundle_dir, "overview.md").write_text("overview\n", encoding="utf-8")

    with pytest.raises(ValueError, match="missing"):
        oracle_upload.resolve_oracle_benchmark_bundle(session_root)


def test_resolve_oracle_benchmark_bundle_rejects_legacy_top_level_bundle_files(
    tmp_path: Path,
) -> None:
    session_root = tmp_path / "single-book-benchmark"
    bundle_dir = session_root / oracle_upload.BENCHMARK_UPLOAD_BUNDLE_DIR_NAME
    bundle_dir.mkdir(parents=True, exist_ok=True)
    (bundle_dir / "upload_bundle_overview.md").write_text("overview\n", encoding="utf-8")
    (bundle_dir / "upload_bundle_index.json").write_text("{}", encoding="utf-8")
    (bundle_dir / "upload_bundle_payload.jsonl").write_text("{}\n", encoding="utf-8")

    with pytest.raises(ValueError, match="missing"):
        oracle_upload.resolve_oracle_benchmark_bundle(session_root)


def test_build_oracle_benchmark_prompt_describes_synthetic_attachment_transport(
    tmp_path: Path,
) -> None:
    bundle_dir = _make_bundle(
        tmp_path / "single-book-benchmark" / oracle_upload.BENCHMARK_UPLOAD_BUNDLE_DIR_NAME
    )
    target = oracle_upload.resolve_oracle_benchmark_bundle(bundle_dir)

    prompt = oracle_upload.build_oracle_benchmark_prompt(target=target)

    assert "You are the quality lane" in prompt
    assert "logical contents come from an existing `upload_bundle_v1` benchmark package" in prompt
    assert "synthetic text attachment such as `attachments-bundle.txt`" in prompt
    assert "Start with `overview.md`" in prompt
    assert "path from the current benchmark quality toward `>95%`" in prompt
    assert "Only write `None` in `Requested follow-up data`" in prompt
    assert "Useful local follow-up tools include `cf-debug structure-report`" in prompt
    assert "`Top blockers to 95%`" in prompt
    assert "`Requested follow-up data`" in prompt
    assert "`ask_id: <short_slug>`" in prompt
    assert "`outputs: <comma-separated outputs such as case_export, line_role_audit" in prompt


def test_build_oracle_benchmark_prompt_supports_token_lane(
    tmp_path: Path,
) -> None:
    bundle_dir = _make_bundle(
        tmp_path / "single-book-benchmark" / oracle_upload.BENCHMARK_UPLOAD_BUNDLE_DIR_NAME
    )
    target = oracle_upload.resolve_oracle_benchmark_bundle(bundle_dir)

    prompt = oracle_upload.build_oracle_benchmark_prompt(
        target=target,
        review_profile="token",
    )

    assert "You are the token lane" in prompt
    assert "Start with `overview.md`" in prompt
    assert "sharpest token-spend reductions" in prompt
    assert "`Top spend sinks`" in prompt
    assert "`Requested follow-up data`" in prompt


def test_build_token_lane_brief_reads_current_stage_names(
    tmp_path: Path,
) -> None:
    bundle_dir = _make_bundle(
        tmp_path / "single-book-benchmark" / oracle_upload.BENCHMARK_UPLOAD_BUNDLE_DIR_NAME
    )
    target = oracle_upload.resolve_oracle_benchmark_bundle(bundle_dir)
    profile = oracle_upload.resolve_oracle_benchmark_review_profile("token")
    prompt_budget_path = bundle_dir.parent / "codex-exec" / "prompt_budget_summary.json"
    prompt_budget_path.write_text(
        json.dumps(
            {
                "by_stage": {
                    "nonrecipe_finalize": {
                        "tokens_total": 28762251,
                        "wrapper_overhead_tokens": 14637956,
                    },
                    "line_role": {
                        "tokens_total": 2952847,
                    },
                    "recipe_refine": {
                        "tokens_total": 1984535,
                    },
                }
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    brief = oracle_upload._build_token_lane_brief(
        target=target,
        profile=profile,
        missing_paths=[],
    )

    assert "- knowledge tokens: `28762251`" in brief
    assert "- knowledge wrapper overhead tokens: `14637956`" in brief
    assert "- line-role tokens: `2952847`" in brief
    assert "- recipe correction tokens: `1984535`" in brief


def test_build_oracle_benchmark_prompt_renders_editable_template_file_tokens(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    bundle_dir = _make_bundle(
        tmp_path / "single-profile-benchmark" / oracle_upload.BENCHMARK_UPLOAD_BUNDLE_DIR_NAME
    )
    target = oracle_upload.resolve_oracle_benchmark_bundle(bundle_dir)
    template_path = tmp_path / "oracle-benchmark-upload.prompt.md"
    template_path.write_text(
        "\n".join(
            [
                "brief={{LANE_BRIEF_FILE}}",
                "scope={{BUNDLE_SCOPE}}",
                "root={{BENCHMARK_ROOT}}",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        oracle_upload,
        "ORACLE_BENCHMARK_PROMPT_TEMPLATE_PATH",
        template_path,
    )

    prompt = oracle_upload.build_oracle_benchmark_prompt(target=target)

    assert prompt == (
        f"brief=oracle_quality_focus.md\nscope={target.scope}\nroot={target.source_root}"
    )


def test_build_oracle_benchmark_prompt_marks_test_helpers_clearly(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    bundle_dir = _make_bundle(
        tmp_path / "single-book-benchmark" / oracle_upload.BENCHMARK_UPLOAD_BUNDLE_DIR_NAME
    )
    target = oracle_upload.resolve_oracle_benchmark_bundle(bundle_dir)
    monkeypatch.setenv(oracle_upload.ORACLE_TEST_HELPER_ENV, "1")
    monkeypatch.setenv(
        oracle_upload.ORACLE_TEST_HELPER_LABEL_ENV,
        "pytest labelstudio benchmark helper",
    )

    prompt = oracle_upload.build_oracle_benchmark_prompt(target=target)

    assert prompt.startswith("TEST HELPER ONLY.")
    assert "pytest labelstudio benchmark helper" in prompt
    assert "not a real operator benchmark run" in prompt
    assert "disposable test data" in prompt


def test_resolve_oracle_benchmark_model_uses_test_lane_for_helper_mode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ORACLE_INSTANT_MODEL", INSTANT_MODEL)
    monkeypatch.setenv(oracle_upload.ORACLE_TEST_HELPER_ENV, "1")

    assert oracle_upload.resolve_oracle_benchmark_model() == INSTANT_LANE
    assert (
        oracle_upload.resolve_oracle_benchmark_model("instant")
        == INSTANT_LANE
    )
    assert (
        oracle_upload.resolve_oracle_benchmark_model("instant-explicit-override")
        == "instant-explicit-override"
    )


def test_oracle_browser_upload_accepts_explicit_instant_selection() -> None:
    assert oracle_upload.ORACLE_BROWSER_MODEL_STRATEGY == "select"
    assert oracle_upload.resolve_oracle_benchmark_model("instant") == INSTANT_LANE


def test_oracle_model_helpers_keep_instant_selector_and_raw_overrides_distinct(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ORACLE_INSTANT_MODEL", INSTANT_MODEL)

    assert (
        oracle_upload.normalize_oracle_model_selector("test")
        == INSTANT_LANE
    )
    assert oracle_upload.normalize_oracle_browser_model("instant") == INSTANT_MODEL
    assert oracle_upload.normalize_oracle_browser_model("instant-browser-raw") == "instant-browser-raw"


def test_resolve_oracle_browser_profile_dir_uses_current_profile_only(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    current_profile = tmp_path / "current" / "browser-profile"
    (current_profile / "Default").mkdir(parents=True, exist_ok=True)
    current_cookie = current_profile / "Default" / "Cookies"
    current_cookie.write_text("current", encoding="utf-8")
    current_mtime = 1_700_000_000
    os.utime(current_cookie, (current_mtime, current_mtime))

    monkeypatch.setattr(oracle_upload, "ORACLE_BROWSER_PROFILE_DIR", str(current_profile))

    resolved = oracle_upload._resolve_oracle_browser_profile_dir(env={})

    assert resolved == current_profile


def test_run_oracle_benchmark_upload_assembles_browser_command(tmp_path: Path) -> None:
    bundle_dir = _make_bundle(
        tmp_path / "single-book-benchmark" / oracle_upload.BENCHMARK_UPLOAD_BUNDLE_DIR_NAME
    )
    target = oracle_upload.resolve_oracle_benchmark_bundle(bundle_dir)
    captured: dict[str, object] = {}

    def fake_runner(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        captured["command"] = command
        captured["kwargs"] = kwargs
        return subprocess.CompletedProcess(
            command,
            0,
            stdout="\n".join(
                [
                    f"oracle ({INSTANT_MODEL})",
                    "Answer:",
                    f"Top regressions\n- Benchmark root: {target.source_root}",
                    "- run_count = 1",
                    "- pair_count = 0",
                    "Likely cause buckets\n- none",
                    "Immediate next checks\n- none",
                ]
            ),
            stderr="",
        )

    result = oracle_upload.run_oracle_benchmark_upload(
        target=target,
        mode="browser",
        model="instant",
        runner=fake_runner,
    )

    assert result.success is True
    assert result.mode == "browser"
    assert result.bundle_dir == bundle_dir
    command = captured["command"]
    assert isinstance(command, list)
    assert command[:9] == [
        oracle_upload.ORACLE_BROWSER_CMD,
        "--engine",
        "browser",
        "--browser-model-strategy",
        oracle_upload.ORACLE_BROWSER_MODEL_STRATEGY,
        "--browser-input-timeout",
        "90s",
        "--browser-reuse-wait",
        oracle_upload.ORACLE_BROWSER_REUSE_WAIT,
    ]
    assert command[9:21] == [
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
    assert command[command.index("--model") + 1] == INSTANT_MODEL
    assert command.count("--file") == 3
    assert any(arg.endswith("/overview.md") or arg.endswith("overview.md") for arg in command)
    assert any(arg.endswith("/index.json") or arg.endswith("index.json") for arg in command)
    assert any(arg.endswith("/payload.json") or arg.endswith("payload.json") for arg in command)
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


def test_run_oracle_benchmark_upload_helper_mode_uses_test_model(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    bundle_dir = _make_bundle(
        tmp_path / "single-book-benchmark" / oracle_upload.BENCHMARK_UPLOAD_BUNDLE_DIR_NAME
    )
    target = oracle_upload.resolve_oracle_benchmark_bundle(bundle_dir)
    monkeypatch.setenv("ORACLE_INSTANT_MODEL", INSTANT_MODEL)
    monkeypatch.setenv(oracle_upload.ORACLE_TEST_HELPER_ENV, "1")
    monkeypatch.setenv(oracle_upload.ORACLE_TEST_HELPER_LABEL_ENV, "pytest helper")

    captured: dict[str, object] = {}

    def fake_runner(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        captured["command"] = command
        return subprocess.CompletedProcess(
            command,
            0,
            stdout="\n".join(
                [
                    f"oracle ({INSTANT_MODEL})",
                    "Answer:",
                    "Top regressions\n- helper",
                    "Likely cause buckets\n- helper",
                    "Immediate next checks\n- helper",
                    "Requested follow-up data\nNone",
                ]
            ),
            stderr="",
        )

    result = oracle_upload.run_oracle_benchmark_upload(
        target=target,
        mode="browser",
        model=None,
        runner=fake_runner,
    )

    assert result.success is True
    command = captured["command"]
    assert isinstance(command, list)
    assert INSTANT_MODEL in command
    prompt = command[command.index("-p") + 1]
    assert prompt.startswith("TEST HELPER ONLY.")
    assert "pytest helper" in prompt


def test_run_oracle_benchmark_upload_adds_chatgpt_target_url_when_configured(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    bundle_dir = _make_bundle(
        tmp_path / "single-book-benchmark" / oracle_upload.BENCHMARK_UPLOAD_BUNDLE_DIR_NAME
    )
    target = oracle_upload.resolve_oracle_benchmark_bundle(bundle_dir)
    monkeypatch.setenv(
        "COOKIMPORT_ORACLE_CHATGPT_URL",
        "https://chatgpt.com/g/g-123/project",
    )
    monkeypatch.setenv("ORACLE_INSTANT_MODEL", INSTANT_MODEL)
    captured: dict[str, object] = {}

    def fake_runner(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        captured["command"] = command
        return subprocess.CompletedProcess(
            command,
            0,
            stdout="\n".join(
                [
                    f"oracle ({INSTANT_MODEL})",
                    "Answer:",
                    f"Top regressions\n- Benchmark root: {target.source_root}",
                    "- run_count = 1",
                    "- pair_count = 0",
                    "Likely cause buckets\n- none",
                    "Immediate next checks\n- none",
                ]
            ),
            stderr="",
        )

    result = oracle_upload.run_oracle_benchmark_upload(
        target=target,
        mode="browser",
        model="instant",
        runner=fake_runner,
    )

    assert result.success is True
    command = captured["command"]
    assert isinstance(command, list)
    assert "--chatgpt-url" in command
    assert "https://chatgpt.com/g/g-123/project" in command


def test_run_oracle_benchmark_upload_defaults_chatgpt_target_url_to_normal_history(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    bundle_dir = _make_bundle(
        tmp_path / "single-book-benchmark" / oracle_upload.BENCHMARK_UPLOAD_BUNDLE_DIR_NAME
    )
    target = oracle_upload.resolve_oracle_benchmark_bundle(bundle_dir)
    monkeypatch.delenv("COOKIMPORT_ORACLE_CHATGPT_URL", raising=False)
    monkeypatch.setenv("ORACLE_INSTANT_MODEL", INSTANT_MODEL)
    captured: dict[str, object] = {}

    def fake_runner(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        captured["command"] = command
        return subprocess.CompletedProcess(
            command,
            0,
            stdout="\n".join(
                [
                    f"oracle ({INSTANT_MODEL})",
                    "Answer:",
                    f"Top regressions\n- Benchmark root: {target.source_root}",
                    "- run_count = 1",
                    "- pair_count = 0",
                    "Likely cause buckets\n- none",
                    "Immediate next checks\n- none",
                ]
            ),
            stderr="",
        )

    result = oracle_upload.run_oracle_benchmark_upload(
        target=target,
        mode="browser",
        model="instant",
        runner=fake_runner,
    )

    assert result.success is True
    command = captured["command"]
    assert isinstance(command, list)
    assert "--chatgpt-url" in command
    assert oracle_upload.ORACLE_DEFAULT_CHATGPT_URL in command
    assert not any("temporary-chat=true" in str(arg) for arg in command)


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
        model="instant",
        runner=fake_runner,
    )

    assert result.success is True
    assert result.mode == "dry-run"
    command = captured["command"]
    assert isinstance(command, list)
    assert command[:6] == list(oracle_upload.ORACLE_DRY_RUN_BASE_COMMAND)
    assert "--model" in command
    assert command[command.index("--model") + 1] == "instant"
    assert command.count("--file") == 3
    assert any(arg.endswith("/payload.json") or arg.endswith("payload.json") for arg in command)


def test_run_oracle_benchmark_upload_dry_run_falls_back_to_local_preview_for_large_bundle(
    tmp_path: Path,
) -> None:
    bundle_dir = _make_bundle(
        tmp_path / "single-profile-benchmark" / oracle_upload.BENCHMARK_UPLOAD_BUNDLE_DIR_NAME
    )
    oversized_rows = []
    for path in oracle_upload.resolve_oracle_benchmark_review_profile("quality").payload_paths:
        oversized_rows.append(
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
                "row_count": len(oversized_rows),
                "rows": oversized_rows,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    target = oracle_upload.resolve_oracle_benchmark_bundle(bundle_dir)

    result = oracle_upload.run_oracle_benchmark_upload(
        target=target,
        mode="dry-run",
        model="instant",
    )

    assert result.success is True
    assert result.mode == "dry-run"
    assert result.returncode == 0
    assert "Local dry-run preview only" in result.stdout
    assert "payload.json" in result.stdout
    assert result.review_profile == "quality"
    assert result.command[:9] == [
        oracle_upload.ORACLE_BROWSER_CMD,
        "--engine",
        "browser",
        "--browser-model-strategy",
        oracle_upload.ORACLE_BROWSER_MODEL_STRATEGY,
        "--browser-input-timeout",
        "90s",
        "--browser-reuse-wait",
        oracle_upload.ORACLE_BROWSER_REUSE_WAIT,
    ]
    assert result.command[9:21] == [
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
        tmp_path / "single-book-benchmark" / oracle_upload.BENCHMARK_UPLOAD_BUNDLE_DIR_NAME
    )
    _write_profile_bundle_context(bundle_dir)
    rows = []
    for path in oracle_upload.resolve_oracle_benchmark_review_profile("quality").payload_paths:
        rows.append(
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
                "row_count": len(rows),
                "rows": rows,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
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
        assert "was split into 2 ordered shards" in prompt
        assert "payload.part001.json" in prompt
        return subprocess.CompletedProcess(
            command,
            0,
            stdout="\n".join(
                [
                    f"oracle ({INSTANT_MODEL})",
                    "Answer:",
                    f"Top regressions\n- Benchmark root: {target.source_root}",
                    "- run_count = 1",
                    "- pair_count = 0",
                    "Likely cause buckets\n- none",
                    "Immediate next checks\n- none",
                ]
            ),
            stderr="",
        )

    result = oracle_upload.run_oracle_benchmark_upload(
        target=target,
        mode="browser",
        model="instant",
        review_profile="quality",
        runner=fake_runner,
    )

    assert result.success is True
    assert "Prepared Oracle quality review packet" in result.stdout
    command = captured["command"]
    assert isinstance(command, list)
    file_args = captured["file_args"]
    assert isinstance(file_args, list)
    file_names = sorted(path.name for path in file_args)
    assert "overview.md" in file_names
    assert "index.json" in file_names
    assert "payload.json" not in file_names
    assert any(name.startswith("payload.part") for name in file_names)
    assert len(file_args) >= 3
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


def test_run_oracle_benchmark_upload_browser_stages_quality_profile_subset(
    tmp_path: Path,
) -> None:
    bundle_dir = _make_bundle(
        tmp_path / "single-book-benchmark" / oracle_upload.BENCHMARK_UPLOAD_BUNDLE_DIR_NAME
    )
    _write_profile_bundle_context(bundle_dir)
    _write_profile_payload_rows(bundle_dir)
    target = oracle_upload.resolve_oracle_benchmark_bundle(bundle_dir)

    captured: dict[str, object] = {}

    def fake_runner(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        captured["command"] = command
        file_args = [
            Path(command[index + 1])
            for index, arg in enumerate(command)
            if arg == "--file"
        ]
        captured["file_args"] = file_args
        payload_path = next(path for path in file_args if path.name == "payload.json")
        payload_payload = json.loads(payload_path.read_text(encoding="utf-8"))
        payload_rows = payload_payload["rows"]
        assert len(payload_rows) == len(
            oracle_upload.resolve_oracle_benchmark_review_profile("quality").payload_paths
        )
        assert "heavy/unselected.json" not in payload_path.read_text(encoding="utf-8")
        assert payload_path.stat().st_size <= oracle_upload.ORACLE_INLINE_FILE_SIZE_LIMIT_BYTES
        prompt = command[command.index("-p") + 1]
        assert "`quality` lane packet" in prompt
        return subprocess.CompletedProcess(
            command,
            0,
            stdout="\n".join(
                [
                    f"oracle ({INSTANT_MODEL})",
                    "Answer:",
                    f"Top regressions\n- Benchmark root: {target.source_root}",
                    "- run_count = 1",
                    "- pair_count = 0",
                    "Likely cause buckets\n- none",
                    "Immediate next checks\n- none",
                ]
            ),
            stderr="",
        )

    result = oracle_upload.run_oracle_benchmark_upload(
        target=target,
        mode="browser",
        model="instant",
        review_profile="quality",
        runner=fake_runner,
    )

    assert result.success is True
    assert result.review_profile == "quality"
    assert "Prepared Oracle quality review packet" in result.stdout
    command = captured["command"]
    assert isinstance(command, list)
    assert command[command.index("--model") + 1] == INSTANT_MODEL
    file_args = captured["file_args"]
    assert isinstance(file_args, list)
    assert len(file_args) == 3
    assert {
        "overview.md",
        "index.json",
        "payload.json",
    } == {path.name for path in file_args}


def test_run_oracle_benchmark_upload_browser_stages_token_profile_subset(
    tmp_path: Path,
) -> None:
    bundle_dir = _make_bundle(
        tmp_path / "single-book-benchmark" / oracle_upload.BENCHMARK_UPLOAD_BUNDLE_DIR_NAME
    )
    _write_profile_bundle_context(bundle_dir)
    _write_profile_payload_rows(bundle_dir)
    target = oracle_upload.resolve_oracle_benchmark_bundle(bundle_dir)

    captured: dict[str, object] = {}

    def fake_runner(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        captured["command"] = command
        file_args = [
            Path(command[index + 1])
            for index, arg in enumerate(command)
            if arg == "--file"
        ]
        payload_path = next(path for path in file_args if path.name == "payload.json")
        payload_text = payload_path.read_text(encoding="utf-8")
        assert 'codex-exec/prompt_budget_summary.json' in payload_text
        assert 'starter_pack_v1/02_call_inventory.jsonl' in payload_text
        assert 'codex-exec/eval_report.json' not in payload_text
        prompt = command[command.index("-p") + 1]
        assert "`token` lane packet" in prompt
        return subprocess.CompletedProcess(
            command,
            0,
            stdout=f"oracle ({INSTANT_MODEL})\nAnswer:\nTop spend sinks\n- none\nLikely waste buckets\n- none\nLowest-risk cuts\n- none\nRequested follow-up data\nNone\n",
            stderr="",
        )

    result = oracle_upload.run_oracle_benchmark_upload(
        target=target,
        mode="browser",
        model="instant",
        review_profile="token",
        runner=fake_runner,
    )

    assert result.success is True
    assert result.review_profile == "token"
    assert result.review_profile_display_name == "Token"
    command = captured["command"]
    assert isinstance(command, list)
    assert command[command.index("--model") + 1] == INSTANT_MODEL


def test_run_oracle_benchmark_upload_browser_persists_launch_artifacts_and_session_metadata(
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
            session_id="you-are-reviewing-a-benchmark-999",
            status="completed",
            prompt="prompt",
            created_at="2026-03-19T16:06:12.548Z",
            conversation_url="https://chatgpt.com/c/test-benchmark-999",
            conversation_id="test-benchmark-999",
        ),
    )

    captured: dict[str, object] = {}

    def fake_runner(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        captured["command"] = command
        captured["kwargs"] = kwargs
        return subprocess.CompletedProcess(
            command,
            0,
            stdout="\n".join(
                [
                    f"oracle ({INSTANT_MODEL})",
                    "Answer:",
                    f"Top regressions\n- Benchmark root: {target.source_root}",
                    "- run_count = 1",
                    "- pair_count = 0",
                    "Likely cause buckets\n- none",
                    "Immediate next checks\n- none",
                    "Conversation URL: https://chatgpt.com/c/test-benchmark-999",
                ]
            ),
            stderr="",
        )

    result = oracle_upload.run_oracle_benchmark_upload(
        target=target,
        mode="browser",
        model="instant",
        runner=fake_runner,
    )

    assert result.success is True
    assert result.status == "succeeded"
    assert result.session_id == "you-are-reviewing-a-benchmark-999"
    assert result.reattach_command == "oracle session you-are-reviewing-a-benchmark-999"
    assert result.conversation_url == "https://chatgpt.com/c/test-benchmark-999"
    runs_dir = _runs_dir(bundle_dir)
    launch_dirs = sorted(path for path in runs_dir.iterdir() if path.is_dir())
    assert len(launch_dirs) == 1
    launch_dir = launch_dirs[0]
    log_path = launch_dir / oracle_upload.ORACLE_UPLOAD_LOG_FILE_NAME
    metadata_path = launch_dir / oracle_upload.ORACLE_UPLOAD_METADATA_FILE_NAME
    status_path = launch_dir / oracle_upload.ORACLE_UPLOAD_STATUS_FILE_NAME
    assert log_path.is_file()
    assert metadata_path.is_file()
    assert status_path.is_file()
    log_text = log_path.read_text(encoding="utf-8")
    assert "Oracle command:" in log_text
    assert "Oracle browser profile:" in log_text
    assert "Conversation URL: https://chatgpt.com/c/test-benchmark-999" in log_text
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    assert metadata["oracle_version"] == "0.8.6-test"
    assert metadata["returncode"] == 0
    assert metadata["mode"] == "browser"
    assert metadata["launch_dir"] == str(launch_dir)
    assert metadata["session_id"] == "you-are-reviewing-a-benchmark-999"
    assert metadata["reattach_command"] == "oracle session you-are-reviewing-a-benchmark-999"
    assert metadata["conversation_url"] == "https://chatgpt.com/c/test-benchmark-999"
    status = json.loads(status_path.read_text(encoding="utf-8"))
    assert status["status"] == "succeeded"
    assert status["conversation_url"] == "https://chatgpt.com/c/test-benchmark-999"


def test_run_oracle_benchmark_upload_browser_duplicate_guard_backfills_conversation_url_from_session_store(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    bundle_dir = _make_bundle(
        tmp_path / "single-book-benchmark" / oracle_upload.BENCHMARK_UPLOAD_BUNDLE_DIR_NAME
    )
    target = oracle_upload.resolve_oracle_benchmark_bundle(bundle_dir)
    monkeypatch.setattr(oracle_upload, "_detect_oracle_version", lambda: "0.8.6-test")

    session_dir = tmp_path / "oracle-home" / "sessions" / "you-are-reviewing-a-benchmark-286"
    session_dir.mkdir(parents=True, exist_ok=True)
    (session_dir / "meta.json").write_text(
        json.dumps(
            {
                "id": "you-are-reviewing-a-benchmark-286",
                "status": "running",
                "createdAt": "2026-03-19T16:39:28.000Z",
                "browser": {
                    "conversationUrl": "https://chatgpt.com/c/from-session-store-286",
                    "conversationId": "from-session-store-286",
                    "runtime": {
                        "tabUrl": "https://chatgpt.com/c/from-session-store-286",
                        "conversationId": "from-session-store-286",
                    },
                },
                "options": {
                    "prompt": "duplicate prompt",
                },
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        oracle_upload,
        "_oracle_browser_env",
        lambda **_kwargs: {
            "ORACLE_HOME_DIR": str(session_dir.parent.parent),
            "ORACLE_BROWSER_PROFILE_DIR": str(session_dir.parent.parent / "browser-profile"),
            "ORACLE_BROWSER_REMOTE_DEBUG_HOST": oracle_upload.ORACLE_BROWSER_REMOTE_DEBUG_HOST,
        },
    )
    monkeypatch.setattr(
        oracle_upload,
        "_find_matching_oracle_session_snapshot",
        lambda **_kwargs: None,
    )

    def fake_runner(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            command,
            1,
            stdout=(
                "🧿 oracle 0.8.6 — duplicate guard.\n"
                'A session with the same prompt is already running (you-are-reviewing-a-benchmark-286). '
                'Reattach with "oracle session you-are-reviewing-a-benchmark-286" or rerun with --force to start another run.\n'
            ),
            stderr="",
        )

    result = oracle_upload.run_oracle_benchmark_upload(
        target=target,
        mode="browser",
        model="instant",
        runner=fake_runner,
    )

    assert result.success is False
    assert result.status == "reattachable"
    assert (
        result.status_reason
        == "Oracle found an already-running matching session; reattach instead of launching a duplicate."
    )
    assert result.session_id == "you-are-reviewing-a-benchmark-286"
    assert result.reattach_command == "oracle session you-are-reviewing-a-benchmark-286"
    assert result.conversation_url == "https://chatgpt.com/c/from-session-store-286"
    runs_dir = _runs_dir(bundle_dir)
    launch_dir = next(path for path in runs_dir.iterdir() if path.is_dir())
    metadata = json.loads((launch_dir / oracle_upload.ORACLE_UPLOAD_METADATA_FILE_NAME).read_text(encoding="utf-8"))
    assert metadata["status"] == "reattachable"
    assert metadata["conversation_url"] == "https://chatgpt.com/c/from-session-store-286"
    status = json.loads((launch_dir / oracle_upload.ORACLE_UPLOAD_STATUS_FILE_NAME).read_text(encoding="utf-8"))
    assert status["status"] == "reattachable"
    assert status["conversation_url"] == "https://chatgpt.com/c/from-session-store-286"


def test_read_oracle_session_snapshot_by_id_synthesizes_chat_url_from_conversation_id(
    tmp_path: Path,
) -> None:
    sessions_dir = tmp_path / "oracle-home" / "sessions"
    session_dir = sessions_dir / "you-are-reviewing-a-benchmark-317"
    session_dir.mkdir(parents=True, exist_ok=True)
    (session_dir / "meta.json").write_text(
        json.dumps(
            {
                "id": "you-are-reviewing-a-benchmark-317",
                "status": "running",
                "createdAt": "2026-03-21T20:17:54.013Z",
                "browser": {
                    "runtime": {
                        "tabUrl": "https://chatgpt.com/",
                        "conversationId": "69befd54-c000-8326-9e9a-7f3e8146eecb",
                    }
                },
                "options": {
                    "prompt": "prompt",
                },
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    snapshot = oracle_upload._read_oracle_session_snapshot_by_id(
        session_id="you-are-reviewing-a-benchmark-317",
        sessions_dir=sessions_dir,
    )

    assert snapshot is not None
    assert (
        snapshot.conversation_url
        == "https://chatgpt.com/c/69befd54-c000-8326-9e9a-7f3e8146eecb"
    )
    assert snapshot.conversation_id == "69befd54-c000-8326-9e9a-7f3e8146eecb"
