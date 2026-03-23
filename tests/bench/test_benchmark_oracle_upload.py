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
    _write_profile_bundle_context(bundle_dir)
    _write_profile_payload_rows(bundle_dir)
    return bundle_dir


def _write_browser_safe_row_locator_index(bundle_dir: Path) -> None:
    index_path = bundle_dir / "upload_bundle_index.json"
    payload = json.loads(index_path.read_text(encoding="utf-8"))
    payload["navigation"] = {
        "row_locators": {
            "root_files": {
                "comparison_summary_json": {
                    "path": "codex_vs_vanilla_comparison.json",
                    "payload_row": 2,
                },
                "triage_packet_jsonl": {
                    "path": "_upload_bundle_derived/root/01_recipe_triage.packet.jsonl",
                    "payload_row": 5,
                },
            },
            "starter_pack": {
                "casebook_md": {
                    "path": "_upload_bundle_derived/starter_pack_v1/07_casebook.md",
                    "payload_row": 7,
                },
            },
            "per_run_summaries": [
                {
                    "run_id": "codexfarm",
                    "summary": {
                        "path": "codexfarm/need_to_know_summary.json",
                        "payload_row": 9,
                    },
                }
            ],
        }
    }
    index_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _write_profile_bundle_context(bundle_dir: Path) -> None:
    index_path = bundle_dir / "upload_bundle_index.json"
    payload = json.loads(index_path.read_text(encoding="utf-8"))
    payload["topline"]["active_recipe_span_breakout"] = {
        "outside_share_of_scored_lines": 0.839018,
    }
    payload["analysis"] = {
        "top_confusion_deltas": [
            {
                "gold_label": "KNOWLEDGE",
                "pred_label": "OTHER",
            }
        ],
        "structure_label_report": {
            "boundary": {
                "codex_exact_ratio_avg": 1.0,
            },
            "slices": {
                "structure_core": {
                    "codex_f1_avg": 0.777012,
                },
                "nonrecipe_core": {
                    "codex_f1_avg": 0.578081,
                },
            },
        },
        "call_inventory_runtime": {
            "summary": {
                "total_tokens": 33699633,
                "nonrecipe_knowledge_review_token_share": 0.8535,
            }
        },
    }
    index_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    comparison_path = bundle_dir.parent / "codex_vs_vanilla_comparison.json"
    comparison_path.write_text(
        json.dumps(
            {
                "metrics": {
                    "codexfarm": {
                        "strict_accuracy": 0.64734,
                        "macro_f1_excluding_other": 0.777327,
                    }
                }
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    prompt_budget_path = bundle_dir.parent / "codexfarm" / "prompt_budget_summary.json"
    prompt_budget_path.parent.mkdir(parents=True, exist_ok=True)
    prompt_budget_path.write_text(
        json.dumps(
            {
                "by_stage": {
                    "knowledge": {
                        "tokens_total": 28762251,
                        "wrapper_overhead_tokens": 14637956,
                    },
                    "line_role": {
                        "tokens_total": 2952847,
                    },
                    "recipe_correction": {
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


def _write_profile_payload_rows(bundle_dir: Path) -> None:
    selected_paths = set()
    for profile in oracle_upload.ORACLE_BENCHMARK_REVIEW_PROFILES:
        selected_paths.update(profile.payload_paths)
    rows = []
    for path in sorted(selected_paths):
        rows.append(
            json.dumps(
                {
                    "path": path,
                    "payload": f"payload for {path}",
                }
            )
            + "\n"
        )
    rows.append(
        json.dumps(
            {
                "path": "heavy/unselected.json",
                "payload": "x" * 20000,
            }
        )
        + "\n"
    )
    (bundle_dir / "upload_bundle_payload.jsonl").write_text("".join(rows), encoding="utf-8")


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
    (bundle_dir / "upload_bundle_overview.md").write_text("overview\n", encoding="utf-8")

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
    assert "Start with `oracle_quality_focus.md`" in prompt
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
    assert "Start with `oracle_token_focus.md`" in prompt
    assert "sharpest token-spend reductions" in prompt
    assert "`Top spend sinks`" in prompt
    assert "`Requested follow-up data`" in prompt


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
    monkeypatch.setenv("ORACLE_TEST_MODEL", "gpt-5.3-instant-test")
    monkeypatch.setenv("ORACLE_GENUINE_MODEL", "gpt-5.4-pro-real")
    monkeypatch.setenv(oracle_upload.ORACLE_TEST_HELPER_ENV, "1")

    assert oracle_upload.resolve_oracle_benchmark_model() == "gpt-5.3-instant-test"
    assert (
        oracle_upload.resolve_oracle_benchmark_model("gpt-explicit-override")
        == "gpt-explicit-override"
    )


def test_oracle_browser_upload_defaults_to_explicit_pro_selection() -> None:
    assert oracle_upload.ORACLE_BROWSER_MODEL_STRATEGY == "select"
    assert oracle_upload.ORACLE_DEFAULT_MODEL == "gpt-5-pro"


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
                    "oracle (gpt-5.2)",
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
    assert command[command.index("--model") + 1] == "gpt-5.2-pro"
    assert command.count("--file") == 4
    assert any(arg.endswith("oracle_quality_focus.md") for arg in command)
    assert any(arg.endswith("upload_bundle_overview.md") for arg in command)
    assert any(arg.endswith("upload_bundle_index.json") for arg in command)
    assert any(arg.endswith("upload_bundle_payload.jsonl") for arg in command)
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
    monkeypatch.setenv("ORACLE_TEST_MODEL", "gpt-5.3-instant-test")
    monkeypatch.setenv("ORACLE_GENUINE_MODEL", "gpt-5.4-pro-real")
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
                    "oracle (gpt-5.3)",
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
    assert "gpt-5.3-instant-test" in command
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
    captured: dict[str, object] = {}

    def fake_runner(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        captured["command"] = command
        return subprocess.CompletedProcess(
            command,
            0,
            stdout="\n".join(
                [
                    "oracle (gpt-5.2)",
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
    assert command.count("--file") == 4
    assert any(arg.endswith("oracle_quality_focus.md") for arg in command)
    assert any(arg.endswith("upload_bundle_payload.jsonl") for arg in command)


def test_run_oracle_benchmark_upload_dry_run_falls_back_to_local_preview_for_large_bundle(
    tmp_path: Path,
) -> None:
    bundle_dir = _make_bundle(
        tmp_path / "single-profile-benchmark" / oracle_upload.BENCHMARK_UPLOAD_BUNDLE_DIR_NAME
    )
    oversized_rows = []
    for path in oracle_upload.resolve_oracle_benchmark_review_profile("quality").payload_paths:
        oversized_rows.append(
            json.dumps(
                {
                    "path": path,
                    "payload": "x" * 120_000,
                }
            )
            + "\n"
        )
    (bundle_dir / "upload_bundle_payload.jsonl").write_text("".join(oversized_rows), encoding="utf-8")
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
            json.dumps(
                {
                    "path": path,
                    "payload": "x" * 120_000,
                }
            )
            + "\n"
        )
    (bundle_dir / "upload_bundle_payload.jsonl").write_text("".join(rows), encoding="utf-8")
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
        assert "upload_bundle_payload.part001.jsonl" in prompt
        return subprocess.CompletedProcess(
            command,
            0,
            stdout="\n".join(
                [
                    "oracle (gpt-5.2)",
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
    assert "oracle_quality_focus.md" in file_names
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
        payload_path = next(path for path in file_args if path.name == "upload_bundle_payload.jsonl")
        payload_rows = payload_path.read_text(encoding="utf-8").splitlines()
        assert len(payload_rows) == len(
            oracle_upload.resolve_oracle_benchmark_review_profile("quality").payload_paths
        )
        assert "heavy/unselected.json" not in payload_path.read_text(encoding="utf-8")
        assert any(path.name == "oracle_quality_focus.md" for path in file_args)
        assert payload_path.stat().st_size <= oracle_upload.ORACLE_INLINE_FILE_SIZE_LIMIT_BYTES
        prompt = command[command.index("-p") + 1]
        assert "oracle_quality_focus.md" in prompt
        assert "`quality` review subset" in prompt
        return subprocess.CompletedProcess(
            command,
            0,
            stdout="\n".join(
                [
                    "oracle (gpt-5.2)",
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
        review_profile="quality",
        runner=fake_runner,
    )

    assert result.success is True
    assert result.review_profile == "quality"
    assert "Prepared Oracle quality review packet" in result.stdout
    command = captured["command"]
    assert isinstance(command, list)
    assert command[command.index("--model") + 1] == "gpt-5.2-pro"
    file_args = captured["file_args"]
    assert isinstance(file_args, list)
    assert len(file_args) == 4
    assert {
        "oracle_quality_focus.md",
        "upload_bundle_overview.md",
        "upload_bundle_index.json",
        "upload_bundle_payload.jsonl",
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
        payload_path = next(path for path in file_args if path.name == "upload_bundle_payload.jsonl")
        payload_text = payload_path.read_text(encoding="utf-8")
        assert 'codexfarm/prompt_budget_summary.json' in payload_text
        assert 'starter_pack_v1/02_call_inventory.jsonl' in payload_text
        assert 'codexfarm/eval_report.json' not in payload_text
        prompt = command[command.index("-p") + 1]
        assert "oracle_token_focus.md" in prompt
        assert "`token` review subset" in prompt
        return subprocess.CompletedProcess(
            command,
            0,
            stdout="oracle (gpt-5.2)\nAnswer:\nTop spend sinks\n- none\nLikely waste buckets\n- none\nLowest-risk cuts\n- none\nRequested follow-up data\nNone\n",
            stderr="",
        )

    result = oracle_upload.run_oracle_benchmark_upload(
        target=target,
        mode="browser",
        review_profile="token",
        runner=fake_runner,
    )

    assert result.success is True
    assert result.review_profile == "token"
    assert result.review_profile_display_name == "Token"
    command = captured["command"]
    assert isinstance(command, list)
    assert command[command.index("--model") + 1] == "gpt-5.2-pro"


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
                    "oracle (gpt-5.4)",
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
        runner=fake_runner,
    )

    assert result.success is True
    assert result.status == "succeeded"
    assert result.session_id == "you-are-reviewing-a-benchmark-999"
    assert result.reattach_command == "oracle session you-are-reviewing-a-benchmark-999"
    assert result.conversation_url == "https://chatgpt.com/c/test-benchmark-999"
    runs_dir = bundle_dir / oracle_upload.ORACLE_UPLOAD_RUNS_DIR_NAME
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
        lambda: {
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
    runs_dir = bundle_dir / oracle_upload.ORACLE_UPLOAD_RUNS_DIR_NAME
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
            json.dumps(
                {
                    "path": path,
                    "payload": "x" * 120_000,
                }
            )
            + "\n"
        )
    (bundle_dir / "upload_bundle_payload.jsonl").write_text("".join(payload_rows), encoding="utf-8")
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
        review_profile="quality",
        popen=FakePopen,
    )

    assert launch.pid == 4242
    assert launch.bundle_dir == bundle_dir
    assert launch.launch_dir.parent == bundle_dir / oracle_upload.ORACLE_UPLOAD_RUNS_DIR_NAME
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
    assert len(file_args) > 3
    assert "oracle_quality_focus.md" in {path.name for path in file_args}
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
        review_profile="token",
        popen=FakePopen,
    )

    assert launch.pid == 5252
    assert launch.review_profile == "token"
    assert launch.model == "gpt-5.2-pro"
    assert "Prepared Oracle token review packet" in launch.note
    command = captured["command"]
    assert isinstance(command, list)
    assert command[command.index("--model") + 1] == "gpt-5.2-pro"
    file_args = [
        Path(command[index + 1])
        for index, arg in enumerate(command)
        if arg == "--file"
    ]
    assert len(file_args) == 4
    payload_path = next(path for path in file_args if path.name == "upload_bundle_payload.jsonl")
    payload_text = payload_path.read_text(encoding="utf-8")
    assert "codexfarm/prompt_budget_summary.json" in payload_text
    assert "starter_pack_v1/02_call_inventory.jsonl" in payload_text
    prompt = command[command.index("-p") + 1]
    assert "oracle_token_focus.md" in prompt
    assert "`token` review subset" in prompt
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
                "Launching browser mode (gpt-5.2) with ~123 tokens.\n"
            )
            log_handle.flush()
            self.pid = 4243

        def poll(self) -> None:
            return None

    launch = oracle_upload.start_oracle_benchmark_upload_background(
        target=target,
        mode="browser",
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
                "Launching browser mode (gpt-5.2) with ~123 tokens.\n"
            )
            log_handle.flush()
            self.pid = 4244

        def poll(self) -> None:
            return None

    launch = oracle_upload.start_oracle_benchmark_upload_background(
        target=target,
        mode="browser",
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
    launch = oracle_upload.OracleBackgroundUploadLaunch(
        mode="browser",
        model="gpt-5.2",
        command=["oracle", "--engine", "browser", "--model", "gpt-5.2"],
        bundle_dir=bundle_dir,
        launch_dir=bundle_dir / oracle_upload.ORACLE_UPLOAD_RUNS_DIR_NAME / "2026-03-17_17.05.00",
        log_path=bundle_dir / oracle_upload.ORACLE_UPLOAD_RUNS_DIR_NAME / "2026-03-17_17.05.00" / oracle_upload.ORACLE_UPLOAD_LOG_FILE_NAME,
        metadata_path=bundle_dir / oracle_upload.ORACLE_UPLOAD_RUNS_DIR_NAME / "2026-03-17_17.05.00" / oracle_upload.ORACLE_UPLOAD_METADATA_FILE_NAME,
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
    launch = oracle_upload.OracleBackgroundUploadLaunch(
        mode="browser",
        model="gpt-5.4",
        command=["oracle", "--engine", "browser", "--model", "gpt-5.4"],
        bundle_dir=bundle_dir,
        launch_dir=bundle_dir / oracle_upload.ORACLE_UPLOAD_RUNS_DIR_NAME / "2026-03-21_16.17.50",
        log_path=bundle_dir
        / oracle_upload.ORACLE_UPLOAD_RUNS_DIR_NAME
        / "2026-03-21_16.17.50"
        / oracle_upload.ORACLE_UPLOAD_LOG_FILE_NAME,
        metadata_path=bundle_dir
        / oracle_upload.ORACLE_UPLOAD_RUNS_DIR_NAME
        / "2026-03-21_16.17.50"
        / oracle_upload.ORACLE_UPLOAD_METADATA_FILE_NAME,
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
    monkeypatch.setattr(cli.typer, "echo", lambda message="", **_kwargs: messages.append(str(message)))

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
    launch_dir = bundle_dir / oracle_upload.ORACLE_UPLOAD_RUNS_DIR_NAME / "2026-03-21_11.27.35"
    launch_dir.mkdir(parents=True, exist_ok=True)
    launch = oracle_upload.OracleBackgroundUploadLaunch(
        mode="browser",
        model="gpt-5.4",
        command=["oracle", "--engine", "browser", "--model", "gpt-5.4"],
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
    assert status_payload["model"] == "gpt-5.4"
    assert updated_launch.auto_followup_worker_pid == 4243


def test_start_benchmark_bundle_oracle_upload_background_reports_followup_launch_failure_separately(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    bundle_dir = _make_bundle(
        tmp_path / "single-book-benchmark" / oracle_upload.BENCHMARK_UPLOAD_BUNDLE_DIR_NAME
    )
    target = oracle_upload.resolve_oracle_benchmark_bundle(bundle_dir)
    launch = oracle_upload.OracleBackgroundUploadLaunch(
        mode="browser",
        model="gpt-5.4",
        command=["oracle", "--engine", "browser", "--model", "gpt-5.4"],
        bundle_dir=bundle_dir,
        launch_dir=bundle_dir / oracle_upload.ORACLE_UPLOAD_RUNS_DIR_NAME / "2026-03-21_11.27.35",
        log_path=bundle_dir
        / oracle_upload.ORACLE_UPLOAD_RUNS_DIR_NAME
        / "2026-03-21_11.27.35"
        / oracle_upload.ORACLE_UPLOAD_LOG_FILE_NAME,
        metadata_path=bundle_dir
        / oracle_upload.ORACLE_UPLOAD_RUNS_DIR_NAME
        / "2026-03-21_11.27.35"
        / oracle_upload.ORACLE_UPLOAD_METADATA_FILE_NAME,
        pid=4242,
        status="running",
        status_reason="Oracle session is running; session store metadata is available.",
        session_id="you-are-reviewing-a-benchmark-313",
        reattach_command="oracle session you-are-reviewing-a-benchmark-313",
    )
    messages: list[str] = []
    summary_calls: list[
        tuple[oracle_upload.OracleBenchmarkBundleTarget, oracle_upload.OracleBackgroundUploadLaunch]
    ] = []

    monkeypatch.setattr(cli, "resolve_oracle_benchmark_bundle", lambda _path: target)
    monkeypatch.setattr(cli, "start_oracle_benchmark_upload_background", lambda **_kwargs: launch)
    monkeypatch.setattr(
        cli,
        "_start_background_oracle_followup_worker",
        lambda **_kwargs: (_ for _ in ()).throw(
            RuntimeError("expected str, bytes or os.PathLike object, not NoneType")
        ),
    )
    monkeypatch.setattr(
        cli,
        "_print_background_oracle_upload_summary",
        lambda *, target, launch: summary_calls.append((target, launch)),
    )
    monkeypatch.setattr(cli.typer, "secho", lambda message, **_kwargs: messages.append(str(message)))

    cli._start_benchmark_bundle_oracle_upload_background(
        bundle_dir=bundle_dir,
        scope="single_book",
        model=None,
    )

    assert summary_calls == [(target, launch), (target, launch)]
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
                "oracle (gpt-5.2)",
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
                "oracle (gpt-5.2)",
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
                "oracle (gpt-5.4)",
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
                "oracle (gpt-5.2)",
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

    monkeypatch.setattr(cli, "run_oracle_benchmark_upload", fake_run_oracle_benchmark_upload)

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
    assert captured_profiles == ["quality", "token"]


def test_maybe_upload_benchmark_bundle_to_oracle_is_best_effort(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    bundle_dir = _make_bundle(
        tmp_path / "single-book-benchmark" / oracle_upload.BENCHMARK_UPLOAD_BUNDLE_DIR_NAME
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
        scope="single_book",
    )
