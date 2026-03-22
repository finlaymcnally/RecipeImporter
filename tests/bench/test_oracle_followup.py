from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from cookimport.bench.oracle_followup import (
    ORACLE_AUTO_FOLLOWUP_STATUS_NAME,
    extract_requested_followup_section,
    parse_requested_followup_text,
    run_oracle_benchmark_followup_background_worker,
    run_oracle_benchmark_followup,
)
from cookimport.bench.oracle_followup import OracleFollowupWorkspace
from cookimport.bench.oracle_upload import (
    OracleUploadResult,
    resolve_oracle_benchmark_bundle,
)


REPO_ROOT = Path(__file__).resolve().parents[2]
SAMPLE_BUNDLE = (
    REPO_ROOT
    / "data/golden/benchmark-vs-golden/2026-03-21_11.17.08/single-book-benchmark/saltfatacidheatcutdown/upload_bundle_v1"
)


def _copy_sample_bundle_root(destination_root: Path) -> Path:
    shutil.copytree(SAMPLE_BUNDLE.parent, destination_root)
    copied_bundle_dir = destination_root / "upload_bundle_v1"
    shutil.rmtree(copied_bundle_dir / ".oracle_upload_runs", ignore_errors=True)
    return copied_bundle_dir


def test_parse_requested_followup_text_reads_structured_asks() -> None:
    answer_text = """
Top regressions
...

Likely cause buckets
...

Immediate next checks
...

Requested follow-up data
Ask 1
ask_id: ask_001_line_role
question: Show the line-role evidence for the worst negative cases.
outputs: case_export, line_role_audit, prompt_link_audit
stage_filters: line_role
include_case_ids: regression_c6, regression_c9
include_line_ranges: saltfatacidheatcutdown:120:145
hypothesis: The issue is in line-role repair.
smallest_useful_packet: Two bad cases plus one exact range is enough.
"""

    section = extract_requested_followup_section(answer_text)
    assert section is not None
    parsed = parse_requested_followup_text(section)

    assert parsed.none_requested is False
    assert len(parsed.asks) == 1
    ask = parsed.asks[0]
    assert ask.ask_id == "ask_001_line_role"
    assert ask.outputs == ["case_export", "line_role_audit", "prompt_link_audit"]
    assert ask.stage_filters == ["line_role"]
    assert ask.include_case_ids == ["regression_c6", "regression_c9"]
    assert ask.include_line_ranges == ["saltfatacidheatcutdown:120:145"]
    assert ask.hypothesis == "The issue is in line-role repair."


def test_run_oracle_benchmark_followup_dry_run_prepares_packet_and_command(tmp_path: Path) -> None:
    copied_root = tmp_path / "single-book-benchmark" / "saltfatacidheatcutdown"
    bundle_dir = _copy_sample_bundle_root(copied_root)
    launch_dir = bundle_dir / ".oracle_upload_runs" / "2026-03-19_15.20.00"
    launch_dir.mkdir(parents=True, exist_ok=True)
    (launch_dir / "oracle_upload.json").write_text(
        json.dumps(
            {
                "session_id": "you-are-reviewing-a-benchmark-301",
                "conversation_url": "https://chatgpt.com/c/followup-source-301",
                "conversation_id": "followup-source-301",
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    (launch_dir / "oracle_upload.log").write_text(
        "\n".join(
            [
                "Oracle command: oracle ...",
                "Answer:",
                "Top regressions",
                "The main regression is line-role collapse.",
                "",
                "Likely cause buckets",
                "Line-role repair dominates.",
                "",
                "Immediate next checks",
                "Inspect the worst cases.",
                "",
                "Requested follow-up data",
                "Ask 1",
                "ask_id: ask_001_line_role",
                "question: Show the line-role evidence for the worst negative cases.",
                "outputs: case_export, line_role_audit",
                "stage_filters: line_role",
                "hypothesis: The issue is in line-role repair.",
                "smallest_useful_packet: One bad case is enough.",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    target = resolve_oracle_benchmark_bundle(bundle_dir)
    result, workspace = run_oracle_benchmark_followup(
        target=target,
        from_run="latest",
        dry_run=True,
    )

    assert result.success is True
    assert result.status == "dry_run"
    assert result.session_id == "you-are-reviewing-a-benchmark-301"
    assert result.command[:3] == [
        "/home/mcnal/.local/bin/oracle",
        "continue-session",
        "you-are-reviewing-a-benchmark-301",
    ]
    assert "--browser-keep-browser" not in result.command
    assert workspace.handoff_path.is_file()
    assert workspace.request_json_path.is_file()
    assert workspace.prompt_path.is_file()
    assert (workspace.followup_packet_dir / "index.json").is_file()
    assert "continue-session you-are-reviewing-a-benchmark-301" in result.stdout

    request_payload = json.loads(workspace.request_json_path.read_text(encoding="utf-8"))
    assert request_payload["schema_version"] == "cf.followup_request.v1"
    assert request_payload["asks"][0]["ask_id"] == "ask_001_line_role"


def test_run_oracle_benchmark_followup_uses_request_file_when_source_run_is_older(tmp_path: Path) -> None:
    copied_root = tmp_path / "single-book-benchmark" / "saltfatacidheatcutdown"
    bundle_dir = _copy_sample_bundle_root(copied_root)
    launch_dir = bundle_dir / ".oracle_upload_runs" / "2026-03-19_15.30.00"
    launch_dir.mkdir(parents=True, exist_ok=True)
    (launch_dir / "oracle_upload.json").write_text(
        json.dumps(
            {
                "session_id": "you-are-reviewing-a-benchmark-302",
                "conversation_url": "https://chatgpt.com/c/followup-source-302",
                "conversation_id": "followup-source-302",
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    (launch_dir / "oracle_upload.log").write_text(
        "Answer:\nTop regressions\nNo structured follow-up block here.\n",
        encoding="utf-8",
    )
    request_file = tmp_path / "manual_followup_request.json"
    request_file.write_text(
        json.dumps(
            {
                "schema_version": "cf.followup_request.v1",
                "bundle_dir": str(bundle_dir),
                "bundle_sha256": "",
                "request_id": "manual_request_01",
                "request_summary": "Manual follow-up request.",
                "requester_context": {
                    "already_has_upload_bundle_v1": True,
                    "prefer_new_local_artifacts_over_bundle_repeats": True,
                    "duplicate_bundle_payloads_only_when_needed_for_context": True,
                },
                "default_stage_filters": ["line_role"],
                "asks": [
                    {
                        "ask_id": "ask_manual_001",
                        "question": "Show one compact line-role packet.",
                        "outputs": ["case_export"],
                        "selectors": {
                            "top_neg": 1,
                            "top_pos": 0,
                            "outside_span": 0,
                            "stage_filters": ["line_role"],
                            "include_case_ids": [],
                            "include_recipe_ids": [],
                            "include_line_ranges": [],
                            "include_knowledge_source_keys": [],
                            "include_knowledge_output_subdirs": [],
                        },
                    }
                ],
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    target = resolve_oracle_benchmark_bundle(bundle_dir)
    result, workspace = run_oracle_benchmark_followup(
        target=target,
        from_run="latest",
        dry_run=True,
        request_file=request_file,
    )

    assert result.success is True
    assert workspace.request_json_path.is_file()
    request_payload = json.loads(workspace.request_json_path.read_text(encoding="utf-8"))
    assert request_payload["request_id"] == "manual_request_01"


def test_auto_followup_worker_waits_for_completed_turn1_and_launches_turn2(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    copied_root = tmp_path / "single-book-benchmark" / "saltfatacidheatcutdown"
    bundle_dir = _copy_sample_bundle_root(copied_root)
    source_run = "2026-03-19_17.13.29"
    launch_dir = bundle_dir / ".oracle_upload_runs" / source_run
    launch_dir.mkdir(parents=True, exist_ok=True)
    (launch_dir / "oracle_upload.json").write_text(
        json.dumps(
            {
                "session_id": "you-are-reviewing-a-benchmark-390",
                "conversation_url": "https://chatgpt.com/c/source-390",
                "conversation_id": "source-390",
                "status": "running",
                "status_reason": "Initial launch state.",
                "pid": 0,
                "prompt": "Benchmark turn 1 prompt.",
                "launch_started_at_utc": "2026-03-19T21:13:29+00:00",
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    (launch_dir / "oracle_upload.log").write_text(
        "\n".join(
            [
                "Oracle command: oracle ...",
                "Answer:",
                "Top regressions",
                "The main regression is line-role collapse.",
                "",
                "Likely cause buckets",
                "Line-role repair dominates.",
                "",
                "Immediate next checks",
                "Inspect the worst cases.",
                "",
                "Requested follow-up data",
                "Ask 1",
                "ask_id: ask_001_line_role",
                "question: Show the line-role evidence for the worst negative cases.",
                "outputs: case_export, line_role_audit",
                "stage_filters: line_role",
                "hypothesis: The issue is in line-role repair.",
                "smallest_useful_packet: One bad case is enough.",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    target = resolve_oracle_benchmark_bundle(bundle_dir)
    captured: dict[str, object] = {}

    def fake_run_followup(**kwargs):
        captured.update(kwargs)
        workspace = OracleFollowupWorkspace(
            launch_dir=bundle_dir / ".oracle_upload_runs" / "2026-03-19_17.35.00",
            metadata_path=bundle_dir / ".oracle_upload_runs" / "2026-03-19_17.35.00" / "oracle_upload.json",
            status_path=bundle_dir / ".oracle_upload_runs" / "2026-03-19_17.35.00" / "oracle_upload_status.json",
            log_path=bundle_dir / ".oracle_upload_runs" / "2026-03-19_17.35.00" / "oracle_upload.log",
            request_markdown_path=bundle_dir / ".oracle_upload_runs" / "2026-03-19_17.35.00" / "oracle_followup_request.md",
            request_json_path=bundle_dir / ".oracle_upload_runs" / "2026-03-19_17.35.00" / "oracle_followup_request.json",
            handoff_path=bundle_dir / ".oracle_upload_runs" / "2026-03-19_17.35.00" / "codex_followup_handoff.md",
            prompt_path=bundle_dir / ".oracle_upload_runs" / "2026-03-19_17.35.00" / "turn2_prompt.md",
            followup_packet_dir=bundle_dir / ".oracle_upload_runs" / "2026-03-19_17.35.00" / "followup_data1",
        )
        return (
            OracleUploadResult(
                success=True,
                mode="browser",
                command=["oracle", "continue-session"],
                bundle_dir=bundle_dir,
                returncode=0,
                stdout="Answer:\nUpdated assessment\n...",
                stderr="",
                status="succeeded",
                status_reason="Follow-up answer captured from Oracle.",
                session_id="you-are-reviewing-a-benchmark-390-turn-2",
                reattach_command="oracle session you-are-reviewing-a-benchmark-390-turn-2",
                conversation_url="https://chatgpt.com/c/source-390",
            ),
            workspace,
        )

    monkeypatch.setattr(
        "cookimport.bench.oracle_followup.run_oracle_benchmark_followup",
        fake_run_followup,
    )

    result = run_oracle_benchmark_followup_background_worker(
        target=target,
        from_run=source_run,
        model="gpt-5.3",
        poll_interval_seconds=0.01,
        timeout_seconds=1.0,
    )

    assert captured["from_run"] == source_run
    assert captured["model"] == "gpt-5.3"
    assert result["status"] == "succeeded"
    assert result["followup_session_id"] == "you-are-reviewing-a-benchmark-390-turn-2"
    status_payload = json.loads((launch_dir / ORACLE_AUTO_FOLLOWUP_STATUS_NAME).read_text(encoding="utf-8"))
    assert status_payload["status"] == "succeeded"
    source_status = json.loads((launch_dir / "oracle_upload_status.json").read_text(encoding="utf-8"))
    assert source_status["status"] == "succeeded"


def test_auto_followup_worker_marks_missing_requested_section_explicitly(tmp_path: Path) -> None:
    copied_root = tmp_path / "single-book-benchmark" / "saltfatacidheatcutdown"
    bundle_dir = _copy_sample_bundle_root(copied_root)
    source_run = "2026-03-19_17.13.29"
    launch_dir = bundle_dir / ".oracle_upload_runs" / source_run
    launch_dir.mkdir(parents=True, exist_ok=True)
    (launch_dir / "oracle_upload.json").write_text(
        json.dumps(
            {
                "session_id": "you-are-reviewing-a-benchmark-391",
                "conversation_url": "https://chatgpt.com/c/source-391",
                "conversation_id": "source-391",
                "status": "running",
                "status_reason": "Initial launch state.",
                "pid": 0,
                "prompt": "Benchmark turn 1 prompt.",
                "launch_started_at_utc": "2026-03-19T21:13:29+00:00",
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    (launch_dir / "oracle_upload.log").write_text(
        "Answer:\nTwo-sentence answer without structured follow-up.\n",
        encoding="utf-8",
    )

    target = resolve_oracle_benchmark_bundle(bundle_dir)
    result = run_oracle_benchmark_followup_background_worker(
        target=target,
        from_run=source_run,
        model="gpt-5.3",
        poll_interval_seconds=0.01,
        timeout_seconds=1.0,
    )

    assert result["status"] == "failed"
    assert "Requested follow-up data" in result["status_reason"]
    source_status = json.loads((launch_dir / "oracle_upload_status.json").read_text(encoding="utf-8"))
    assert source_status["status"] == "succeeded"


def _run_followup_timeout_recovery_fixture(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> dict[str, object]:
    copied_root = tmp_path / "single-book-benchmark" / "saltfatacidheatcutdown"
    bundle_dir = _copy_sample_bundle_root(copied_root)
    source_run = "2026-03-19_21.18.04"
    launch_dir = bundle_dir / ".oracle_upload_runs" / source_run
    launch_dir.mkdir(parents=True, exist_ok=True)
    browser_profile_dir = tmp_path / "oracle-home" / "browser-profile"
    sessions_dir = browser_profile_dir.parent / "sessions" / "you-are-reviewing-a-benchmark-392"
    sessions_dir.mkdir(parents=True, exist_ok=True)
    (launch_dir / "oracle_upload.json").write_text(
        json.dumps(
            {
                "bundle_dir": str(bundle_dir),
                "session_id": "you-are-reviewing-a-benchmark-392",
                "conversation_url": "https://chatgpt.com/c/source-392",
                "conversation_id": "source-392",
                "status": "running",
                "status_reason": "Initial launch state.",
                "pid": 0,
                "prompt": "Benchmark turn 1 prompt.",
                "launch_started_at_utc": "2026-03-19T21:18:04+00:00",
                "browser_profile_dir": str(browser_profile_dir),
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    (launch_dir / "oracle_upload.log").write_text(
        "\n".join(
            [
                "Oracle command: oracle ...",
                "Session running in background.",
                "Reattach later with: oracle session you-are-reviewing-a-benchmark-392",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    (sessions_dir / "meta.json").write_text(
        json.dumps(
            {
                "id": "you-are-reviewing-a-benchmark-392",
                "status": "running",
                "browser": {
                    "conversationUrl": "https://chatgpt.com/c/source-392",
                    "conversationId": "source-392",
                    "runtime": {
                        "tabUrl": "https://chatgpt.com/c/source-392",
                        "conversationId": "source-392",
                        "controllerPid": 1234,
                    },
                },
                "response": {
                    "status": "running",
                    "incompleteReason": "assistant-timeout",
                },
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    target = resolve_oracle_benchmark_bundle(bundle_dir)
    runner_calls: list[list[str]] = []
    captured: dict[str, object] = {}

    def fake_runner(command, **kwargs):
        runner_calls.append([str(part) for part in command])
        assert command[:3] == [
            "/home/mcnal/.local/bin/oracle",
            "session",
            "you-are-reviewing-a-benchmark-392",
        ]
        (sessions_dir / "meta.json").write_text(
            json.dumps(
                {
                    "id": "you-are-reviewing-a-benchmark-392",
                    "status": "completed",
                    "browser": {
                        "conversationUrl": "https://chatgpt.com/c/source-392",
                        "conversationId": "source-392",
                        "runtime": {
                            "tabUrl": "https://chatgpt.com/c/source-392",
                            "conversationId": "source-392",
                        },
                    },
                    "response": {
                        "status": "completed",
                    },
                },
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        return subprocess.CompletedProcess(
            command,
            0,
            stdout="\n".join(
                [
                    "Reattach succeeded; session marked completed.",
                    "Answer:",
                    "Top regressions",
                    "Recovered answer after timeout.",
                    "",
                    "Likely cause buckets",
                    "Line-role repair dominates.",
                    "",
                    "Immediate next checks",
                    "Inspect the worst cases.",
                    "",
                    "Requested follow-up data",
                    "Ask 1",
                    "ask_id: ask_001_line_role",
                    "question: Show the line-role evidence for the worst negative cases.",
                    "outputs: case_export, line_role_audit",
                    "stage_filters: line_role",
                    "hypothesis: The issue is in line-role repair.",
                    "smallest_useful_packet: One bad case is enough.",
                ]
            )
            + "\n",
            stderr="",
        )

    def fake_run_followup(**kwargs):
        captured.update(kwargs)
        workspace = OracleFollowupWorkspace(
            launch_dir=bundle_dir / ".oracle_upload_runs" / "2026-03-19_21.30.00",
            metadata_path=bundle_dir / ".oracle_upload_runs" / "2026-03-19_21.30.00" / "oracle_upload.json",
            status_path=bundle_dir / ".oracle_upload_runs" / "2026-03-19_21.30.00" / "oracle_upload_status.json",
            log_path=bundle_dir / ".oracle_upload_runs" / "2026-03-19_21.30.00" / "oracle_upload.log",
            request_markdown_path=bundle_dir / ".oracle_upload_runs" / "2026-03-19_21.30.00" / "oracle_followup_request.md",
            request_json_path=bundle_dir / ".oracle_upload_runs" / "2026-03-19_21.30.00" / "oracle_followup_request.json",
            handoff_path=bundle_dir / ".oracle_upload_runs" / "2026-03-19_21.30.00" / "codex_followup_handoff.md",
            prompt_path=bundle_dir / ".oracle_upload_runs" / "2026-03-19_21.30.00" / "turn2_prompt.md",
            followup_packet_dir=bundle_dir / ".oracle_upload_runs" / "2026-03-19_21.30.00" / "followup_data1",
        )
        return (
            OracleUploadResult(
                success=True,
                mode="browser",
                command=["oracle", "continue-session"],
                bundle_dir=bundle_dir,
                returncode=0,
                stdout="Answer:\nUpdated assessment\n...",
                stderr="",
                status="succeeded",
                status_reason="Follow-up answer captured from Oracle.",
                session_id="you-are-reviewing-a-benchmark-392-turn-2",
                reattach_command="oracle session you-are-reviewing-a-benchmark-392-turn-2",
                conversation_url="https://chatgpt.com/c/source-392",
            ),
            workspace,
        )

    monkeypatch.setattr(
        "cookimport.bench.oracle_followup.run_oracle_benchmark_followup",
        fake_run_followup,
    )

    result = run_oracle_benchmark_followup_background_worker(
        target=target,
        from_run=source_run,
        model="gpt-5.3",
        runner=fake_runner,
        poll_interval_seconds=0.01,
        timeout_seconds=1.0,
    )
    return {
        "result": result,
        "runner_calls": runner_calls,
        "captured": captured,
        "launch_dir": launch_dir,
        "source_run": source_run,
    }


def test_auto_followup_worker_recovers_assistant_timeout_turn1_before_launching_turn2(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _run_followup_timeout_recovery_fixture(tmp_path, monkeypatch)
    result = fixture["result"]
    runner_calls = fixture["runner_calls"]
    captured = fixture["captured"]
    source_run = fixture["source_run"]

    assert runner_calls
    assert captured["from_run"] == source_run
    assert result["status"] == "succeeded"
    assert result["followup_session_id"] == "you-are-reviewing-a-benchmark-392-turn-2"


def test_auto_followup_worker_appends_recovered_turn1_answer_before_turn2(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _run_followup_timeout_recovery_fixture(tmp_path, monkeypatch)
    launch_dir = fixture["launch_dir"]
    log_text = (launch_dir / "oracle_upload.log").read_text(encoding="utf-8")
    assert "Recovered answer after timeout." in log_text


def test_auto_followup_worker_allows_invalid_grounding_turn1_when_followup_was_requested(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    copied_root = (
        tmp_path / "2026-03-21_16.10.40" / "single-book-benchmark" / "saltfatacidheatcutdown"
    )
    bundle_dir = _copy_sample_bundle_root(copied_root)
    source_run = "2026-03-21_16.17.50"
    launch_dir = bundle_dir / ".oracle_upload_runs" / source_run
    launch_dir.mkdir(parents=True, exist_ok=True)
    (launch_dir / "oracle_upload.json").write_text(
        json.dumps(
            {
                "session_id": "you-are-reviewing-a-benchmark-317",
                "conversation_url": "https://chatgpt.com/c/source-317",
                "conversation_id": "source-317",
                "status": "running",
                "status_reason": "Initial launch state.",
                "pid": 0,
                "prompt": "Benchmark turn 1 prompt.",
                "launch_started_at_utc": "2026-03-21T20:17:50+00:00",
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    (launch_dir / "oracle_upload.log").write_text(
        "\n".join(
            [
                "Oracle command: oracle ...",
                "Answer:",
                "Top regressions",
                (
                    "I could not confirm the requested "
                    "2026-03-21_16.10.40/single-book-benchmark/saltfatacidheatcutdown root. "
                    "The accessible packet resolves to 2026-03-21_14.53.27/single-book-benchmark/saltfatacidheatcutdown."
                ),
                "",
                "Likely cause buckets",
                "Bundle identity mismatch.",
                "",
                "Immediate next checks",
                "Verify exact root identity.",
                "",
                "Requested follow-up data",
                "Ask 1",
                "ask_id: exact_root_identity",
                "question: Confirm the exact attached bundle root.",
                "outputs: structure_report",
                "stage_filters:",
                "hypothesis: The browser-safe attachment came from a neighboring run.",
                "smallest_useful_packet: A structure packet is enough.",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    target = resolve_oracle_benchmark_bundle(bundle_dir)
    captured: dict[str, object] = {}

    def fake_run_followup(**kwargs):
        captured.update(kwargs)
        workspace = OracleFollowupWorkspace(
            launch_dir=bundle_dir / ".oracle_upload_runs" / "2026-03-21_17.10.00",
            metadata_path=bundle_dir / ".oracle_upload_runs" / "2026-03-21_17.10.00" / "oracle_upload.json",
            status_path=bundle_dir / ".oracle_upload_runs" / "2026-03-21_17.10.00" / "oracle_upload_status.json",
            log_path=bundle_dir / ".oracle_upload_runs" / "2026-03-21_17.10.00" / "oracle_upload.log",
            request_markdown_path=bundle_dir / ".oracle_upload_runs" / "2026-03-21_17.10.00" / "oracle_followup_request.md",
            request_json_path=bundle_dir / ".oracle_upload_runs" / "2026-03-21_17.10.00" / "oracle_followup_request.json",
            handoff_path=bundle_dir / ".oracle_upload_runs" / "2026-03-21_17.10.00" / "codex_followup_handoff.md",
            prompt_path=bundle_dir / ".oracle_upload_runs" / "2026-03-21_17.10.00" / "turn2_prompt.md",
            followup_packet_dir=bundle_dir / ".oracle_upload_runs" / "2026-03-21_17.10.00" / "followup_data1",
        )
        return (
            OracleUploadResult(
                success=True,
                mode="browser",
                command=["oracle", "continue-session"],
                bundle_dir=bundle_dir,
                returncode=0,
                stdout="Answer:\nUpdated assessment\n...",
                stderr="",
                status="succeeded",
                status_reason="Follow-up answer captured from Oracle.",
                session_id="you-are-reviewing-a-benchmark-317-turn-2",
                reattach_command="oracle session you-are-reviewing-a-benchmark-317-turn-2",
                conversation_url="https://chatgpt.com/c/source-317",
            ),
            workspace,
        )

    monkeypatch.setattr(
        "cookimport.bench.oracle_followup.run_oracle_benchmark_followup",
        fake_run_followup,
    )

    result = run_oracle_benchmark_followup_background_worker(
        target=target,
        from_run=source_run,
        model="gpt-5.4",
        poll_interval_seconds=0.01,
        timeout_seconds=1.0,
    )

    assert captured["from_run"] == source_run
    assert result["status"] == "succeeded"
    assert result["followup_session_id"] == "you-are-reviewing-a-benchmark-317-turn-2"
    source_status = json.loads((launch_dir / "oracle_upload_status.json").read_text(encoding="utf-8"))
    assert source_status["status"] == "invalid_grounding"
