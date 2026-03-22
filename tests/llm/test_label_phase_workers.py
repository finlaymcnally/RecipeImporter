from __future__ import annotations

import json
import re
import threading
import time
from pathlib import Path

from cookimport.config.run_settings import RunSettings
from cookimport.core.progress_messages import parse_stage_progress
from cookimport.llm.codex_exec_runner import FakeCodexExecRunner
from cookimport.parsing.canonical_line_roles import label_atomic_lines
from cookimport.parsing.recipe_block_atomizer import AtomicLineCandidate


def _settings(**kwargs) -> RunSettings:
    return RunSettings(line_role_pipeline="codex-line-role-shard-v1", **kwargs)


def _candidate(atomic_index: int, *, text: str | None = None) -> AtomicLineCandidate:
    return AtomicLineCandidate(
        recipe_id="recipe:0",
        block_id=f"block:{atomic_index}",
        block_index=atomic_index,
        atomic_index=atomic_index,
        text=text or f"Ambiguous line {atomic_index}",
        within_recipe_span=True,
        rule_tags=["recipe_span_fallback"],
    )


def _line_role_builder(label_by_atomic_index: dict[int, str]):
    def _builder(payload):
        rows = payload.get("rows") if isinstance(payload, dict) else []
        atomic_indices: list[int] = []
        for row in rows:
            value = None
            if isinstance(row, dict):
                value = row.get("atomic_index")
            elif isinstance(row, list | tuple) and row:
                value = row[0]
            if value is not None:
                atomic_indices.append(int(value))
        if not atomic_indices:
            prompt_text = payload if isinstance(payload, str) else json.dumps(payload, sort_keys=True)
            atomic_indices = [
                int(value)
                for value in re.findall(r'"atomic_index"\s*:\s*(\d+)', prompt_text)
            ]
        return {
            "rows": [
                {
                    "atomic_index": atomic_index,
                    "label": label_by_atomic_index.get(atomic_index, "OTHER"),
                }
                for atomic_index in atomic_indices
            ]
        }

    return _builder


def test_line_role_phase_workers_write_runtime_artifacts_and_reuse_workers(
    tmp_path: Path,
) -> None:
    runner = FakeCodexExecRunner(
        output_builder=_line_role_builder({0: "OTHER", 1: "OTHER", 2: "OTHER"})
    )

    predictions = label_atomic_lines(
        [_candidate(0), _candidate(1), _candidate(2)],
        _settings(line_role_worker_count=1, line_role_prompt_target_count=None),
        artifact_root=tmp_path,
        codex_batch_size=1,
        codex_runner=runner,
        live_llm_allowed=True,
    )

    assert [row.atomic_index for row in predictions] == [0, 1, 2]
    assert all(row.decided_by == "codex" for row in predictions)
    assert len(runner.calls) == 1
    assert runner.calls[0]["mode"] == "workspace_worker"

    runtime_root = tmp_path / "line-role-pipeline" / "runtime"
    phase_manifest = json.loads(
        (runtime_root / "line_role" / "phase_manifest.json").read_text(
            encoding="utf-8"
        )
    )
    phase_assignments = json.loads(
        (runtime_root / "line_role" / "worker_assignments.json").read_text(
            encoding="utf-8"
        )
    )
    phase_proposals = sorted(
        (runtime_root / "line_role" / "proposals").glob("*.json")
    )

    assert phase_manifest["worker_count"] == 1
    assert phase_manifest["shard_count"] == 3
    assert phase_assignments[0]["worker_id"] == "worker-001"
    assert phase_assignments[0]["shard_ids"] == [
        "line-role-canonical-0001-a000000-a000000",
        "line-role-canonical-0002-a000001-a000001",
        "line-role-canonical-0003-a000002-a000002",
    ]
    assert len(phase_proposals) == 3
    assert (
        runtime_root
        / "line_role"
        / "workers"
        / "worker-001"
        / "out"
        / "line-role-canonical-0001-a000000-a000000.json"
    ).exists()
    compact_input = json.loads(
        (
            runtime_root
            / "line_role"
            / "workers"
            / "worker-001"
            / "in"
            / "line-role-canonical-0001-a000000-a000000.json"
        ).read_text(encoding="utf-8")
    )
    debug_input = json.loads(
        (
            runtime_root
            / "line_role"
            / "workers"
            / "worker-001"
            / "debug"
            / "line-role-canonical-0001-a000000-a000000.json"
        ).read_text(encoding="utf-8")
    )
    assert compact_input["v"] == 1
    assert compact_input["rows"][0][0] == 0
    assert compact_input["rows"][0][2] == "Ambiguous line 0"
    assert debug_input["phase_key"] == "line_role"
    assert debug_input["rows"][0]["atomic_index"] == 0
    assert debug_input["rows"][0]["current_line"] == "Ambiguous line 0"
    assert "rule_tags" in debug_input["rows"][0]


def test_line_role_phase_workers_reject_unowned_rows_and_fall_back(
    tmp_path: Path,
) -> None:
    runner = FakeCodexExecRunner(
        output_builder=lambda _payload: {
            "rows": [{"atomic_index": 999, "label": "OTHER"}]
        }
    )

    predictions = label_atomic_lines(
        [_candidate(0)],
        _settings(line_role_worker_count=1),
        artifact_root=tmp_path,
        codex_batch_size=1,
        codex_runner=runner,
        live_llm_allowed=True,
    )

    assert predictions[0].label == "OTHER"
    assert predictions[0].decided_by == "fallback"
    assert "deterministic_unavailable" in predictions[0].reason_tags

    failures = json.loads(
        (
            tmp_path
            / "line-role-pipeline"
            / "runtime"
            / "line_role"
            / "failures.json"
        ).read_text(encoding="utf-8")
    )
    parse_errors = json.loads(
        (
            tmp_path
            / "line-role-pipeline"
            / "prompts"
            / "line_role"
            / "parse_errors.json"
        ).read_text(encoding="utf-8")
    )
    proposal = json.loads(
        (
            tmp_path
            / "line-role-pipeline"
            / "runtime"
            / "line_role"
            / "proposals"
            / "line-role-canonical-0001-a000000-a000000.json"
        ).read_text(encoding="utf-8")
    )
    task_status_rows = [
        json.loads(line)
        for line in (
            tmp_path
            / "line-role-pipeline"
            / "runtime"
            / "line_role"
            / "task_status.jsonl"
        ).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]

    assert failures == []
    assert parse_errors["parse_error_count"] == 0
    assert proposal["validation_errors"] == []
    assert proposal["validation_metadata"]["task_aggregation"]["fallback_task_count"] == 1
    assert (
        proposal["validation_metadata"]["task_aggregation"]["task_validation_errors_by_task_id"][
            "line-role-canonical-0001-a000000-a000000"
        ]
        == ["unowned_atomic_index:999", "missing_owned_atomic_indices:0"]
    )
    assert [row["state"] for row in task_status_rows] == ["repair_failed"]


def test_line_role_phase_workers_emit_runtime_telemetry_summary(
    tmp_path: Path,
) -> None:
    class _TelemetryRunner(FakeCodexExecRunner):
        @staticmethod
        def _with_usage(result):  # noqa: ANN001
            return result.__class__(
                command=result.command,
                subprocess_exit_code=result.subprocess_exit_code,
                output_schema_path=result.output_schema_path,
                prompt_text=result.prompt_text,
                response_text=result.response_text,
                turn_failed_message=result.turn_failed_message,
                events=result.events,
                usage={
                    "input_tokens": 50,
                    "cached_input_tokens": 5,
                    "output_tokens": 7,
                    "reasoning_tokens": 2,
                },
                stderr_text=result.stderr_text,
                stdout_text=result.stdout_text,
            )

        def run_structured_prompt(self, *args, **kwargs):  # noqa: ANN002, ANN003
            result = super().run_structured_prompt(*args, **kwargs)
            return self._with_usage(result)

        def run_workspace_worker(self, *args, **kwargs):  # noqa: ANN002, ANN003
            result = super().run_workspace_worker(*args, **kwargs)
            return self._with_usage(result)

    predictions = label_atomic_lines(
        [_candidate(0)],
        _settings(line_role_worker_count=1),
        artifact_root=tmp_path,
        codex_batch_size=1,
        codex_runner=_TelemetryRunner(output_builder=_line_role_builder({0: "OTHER"})),
        live_llm_allowed=True,
    )

    assert predictions[0].decided_by == "codex"
    telemetry_summary = json.loads(
        (
            tmp_path / "line-role-pipeline" / "telemetry_summary.json"
        ).read_text(encoding="utf-8")
    )
    assert telemetry_summary["summary"]["tokens_input"] == 50
    assert telemetry_summary["summary"]["tokens_cached_input"] == 5
    assert telemetry_summary["summary"]["tokens_output"] == 7
    assert telemetry_summary["summary"]["tokens_reasoning"] == 2
    assert telemetry_summary["summary"]["tokens_total"] == 64
    assert telemetry_summary["runtime_mode"] == "direct_codex_exec_v1"
    assert telemetry_summary["runtime_artifacts"]["phase_count"] == 1
    assert telemetry_summary["phases"][0]["summary"]["tokens_total"] == 64
    assert telemetry_summary["phases"][0]["runtime_artifacts"]["worker_count"] == 1


def test_line_role_phase_workers_run_concurrently_when_multiple_workers_assigned(
    tmp_path: Path,
) -> None:
    barrier = threading.Barrier(2)
    lock = threading.Lock()
    state = {"current": 0, "max": 0}

    class _ConcurrentRunner(FakeCodexExecRunner):
        def _run_with_overlap(self, fn, *args, **kwargs):  # noqa: ANN002, ANN003
            with lock:
                state["current"] += 1
                state["max"] = max(state["max"], state["current"])
            barrier.wait(timeout=1.0)
            time.sleep(0.05)
            try:
                return fn(*args, **kwargs)
            finally:
                with lock:
                    state["current"] -= 1

        def run_structured_prompt(self, *args, **kwargs):  # noqa: ANN002, ANN003
            return self._run_with_overlap(super().run_structured_prompt, *args, **kwargs)

        def run_workspace_worker(self, *args, **kwargs):  # noqa: ANN002, ANN003
            return self._run_with_overlap(super().run_workspace_worker, *args, **kwargs)

    predictions = label_atomic_lines(
        [_candidate(0), _candidate(1)],
        _settings(line_role_worker_count=2, line_role_prompt_target_count=None),
        artifact_root=tmp_path,
        codex_batch_size=1,
        codex_runner=_ConcurrentRunner(
            output_builder=_line_role_builder({0: "OTHER", 1: "OTHER"})
        ),
        live_llm_allowed=True,
    )

    assert [row.atomic_index for row in predictions] == [0, 1]
    assert state["max"] >= 2


def test_line_role_prompt_target_count_is_a_direct_shard_override(
    tmp_path: Path,
) -> None:
    runner = FakeCodexExecRunner(
        output_builder=_line_role_builder({index: "OTHER" for index in range(5)})
    )

    label_atomic_lines(
        [_candidate(index) for index in range(5)],
        _settings(line_role_prompt_target_count=2, line_role_worker_count=1),
        artifact_root=tmp_path,
        codex_batch_size=1,
        codex_runner=runner,
        live_llm_allowed=True,
    )

    phase_manifest = json.loads(
        (
            tmp_path
            / "line-role-pipeline"
            / "runtime"
            / "line_role"
            / "phase_manifest.json"
        ).read_text(encoding="utf-8")
    )
    shard_manifest = [
        json.loads(line)
        for line in (
            tmp_path
            / "line-role-pipeline"
            / "runtime"
            / "line_role"
            / "shard_manifest.jsonl"
        ).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]

    assert phase_manifest["shard_count"] == 2
    assert [len(shard["owned_ids"]) for shard in shard_manifest] == [3, 2]


def test_line_role_phase_workers_report_task_packet_progress(
    tmp_path: Path,
) -> None:
    class _SlowRunner(FakeCodexExecRunner):
        def run_workspace_worker(self, *args, **kwargs):  # noqa: ANN002, ANN003
            result = super().run_workspace_worker(*args, **kwargs)
            time.sleep(0.2)
            return result

    progress_messages: list[str] = []
    label_atomic_lines(
        [_candidate(0), _candidate(1), _candidate(2), _candidate(3)],
        _settings(line_role_worker_count=2, line_role_prompt_target_count=2),
        artifact_root=tmp_path,
        codex_batch_size=1,
        codex_runner=_SlowRunner(
            output_builder=_line_role_builder(
                {0: "OTHER", 1: "OTHER", 2: "OTHER", 3: "OTHER"}
            )
        ),
        live_llm_allowed=True,
        progress_callback=progress_messages.append,
    )

    payloads = [
        payload
        for message in progress_messages
        for payload in [parse_stage_progress(message)]
        if payload is not None and payload.get("stage_label") == "canonical line-role pipeline"
    ]

    assert payloads
    assert payloads[-1]["work_unit_label"] == "task packet"
    assert payloads[-1]["task_current"] == payloads[-1]["task_total"] == 2
    assert any(int(payload.get("worker_total") or 0) == 2 for payload in payloads)
    assert any(payload.get("followup_label") == "shard finalization" for payload in payloads)
