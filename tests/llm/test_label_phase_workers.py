from __future__ import annotations

import json
import re
import threading
import time
from pathlib import Path

import pytest

from cookimport.config.run_settings import RunSettings
from cookimport.core.progress_messages import parse_stage_progress
from cookimport.llm.codex_exec_runner import FakeCodexExecRunner
import cookimport.parsing.canonical_line_roles as canonical_line_roles_module
from cookimport.parsing.canonical_line_roles import label_atomic_lines
from cookimport.parsing.recipe_block_atomizer import AtomicLineCandidate


def _settings(**kwargs) -> RunSettings:
    return RunSettings(line_role_pipeline="codex-line-role-route-v2", **kwargs)


@pytest.fixture(autouse=True)
def _set_codex_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    codex_home = tmp_path / "codex-home"
    codex_home.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv(
        "COOKIMPORT_CODEX_FARM_CODEX_HOME",
        str(codex_home),
    )


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
        if (
            isinstance(payload, dict)
            and payload.get("stage_key") == "line_role"
            and payload.get("atomic_index") is not None
        ):
            atomic_index = int(payload["atomic_index"])
            return {
                "label": label_by_atomic_index.get(atomic_index, "RECIPE_NOTES"),
            }
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
                    "label": label_by_atomic_index.get(atomic_index, "RECIPE_NOTES"),
                }
                for atomic_index in atomic_indices
            ]
        }

    return _builder


def test_line_role_phase_workers_write_runtime_artifacts_and_reuse_workers(
    tmp_path: Path,
) -> None:
    runner = FakeCodexExecRunner(
        output_builder=_line_role_builder(
            {0: "RECIPE_NOTES", 1: "RECIPE_NOTES", 2: "RECIPE_NOTES"}
        )
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
    assert runner.calls[0]["mode"] == "taskfile"

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
    assert compact_input["v"] == 2
    assert compact_input["rows"][0][0] == 0
    assert compact_input["rows"][0][1] == "Ambiguous line 0"
    assert debug_input["phase_key"] == "line_role"
    assert debug_input["rows"][0]["atomic_index"] == 0
    assert debug_input["rows"][0]["current_line"] == "Ambiguous line 0"
    assert "rule_tags" in debug_input["rows"][0]


def test_line_role_phase_workers_reject_invalid_task_file_answer_after_one_repair_and_fail_closed(
    tmp_path: Path,
) -> None:
    def _invalid_task_file_builder(payload):
        edited = dict(payload or {})
        units = list(edited.get("units") or [])
        if units and isinstance(units[0], dict):
            first_unit = dict(units[0])
            first_unit["answer"] = {"label": "NOT_A_LABEL", "exclusion_reason": None}
            units[0] = first_unit
        edited["units"] = units
        return edited

    runner = FakeCodexExecRunner(
        output_builder=_invalid_task_file_builder
    )

    with pytest.raises(
        canonical_line_roles_module.LineRoleRepairFailureError,
        match="failed closed",
    ):
        label_atomic_lines(
            [_candidate(0)],
            _settings(line_role_worker_count=1),
            artifact_root=tmp_path,
            codex_batch_size=1,
            codex_runner=runner,
            live_llm_allowed=True,
        )

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
    task_status_path = (
        tmp_path
        / "line-role-pipeline"
        / "runtime"
        / "line_role"
        / "task_status.jsonl"
    )
    task_status_rows = (
        [
            json.loads(line)
            for line in task_status_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        if task_status_path.exists()
        else []
    )

    assert [row["reason"] for row in failures] == ["proposal_validation_failed"]
    assert [row["reason_code"] for row in failures] == ["same_session_repair_failed"]
    assert failures[0]["validation_errors"] == ["invalid_label:0:NOT_A_LABEL"]
    assert parse_errors["parse_error_count"] == 1
    assert proposal["validation_errors"] == ["invalid_label:0:NOT_A_LABEL"]
    assert proposal["payload"] is None
    assert proposal["repair_attempted"] is True
    assert proposal["repair_status"] == "failed"
    assert proposal["validation_metadata"]["row_resolution"]["unresolved_atomic_indices"] == [0]
    shard_status_rows = [
        json.loads(line)
        for line in (
            tmp_path
            / "line-role-pipeline"
            / "runtime"
            / "line_role"
            / "shard_status.jsonl"
        ).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert not task_status_rows
    assert [row["state"] for row in shard_status_rows] == ["repair_failed"]


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

        def run_packet_worker(self, *args, **kwargs):  # noqa: ANN002, ANN003
            result = super().run_packet_worker(*args, **kwargs)
            return self._with_usage(result)

        def run_taskfile_worker(self, *args, **kwargs):  # noqa: ANN002, ANN003
            result = super().run_taskfile_worker(*args, **kwargs)
            return self._with_usage(result)

    predictions = label_atomic_lines(
        [_candidate(0)],
        _settings(line_role_worker_count=1),
        artifact_root=tmp_path,
        codex_batch_size=1,
        codex_runner=_TelemetryRunner(
            output_builder=_line_role_builder({0: "RECIPE_NOTES"})
        ),
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

        def run_packet_worker(self, *args, **kwargs):  # noqa: ANN002, ANN003
            return self._run_with_overlap(super().run_packet_worker, *args, **kwargs)

        def run_taskfile_worker(self, *args, **kwargs):  # noqa: ANN002, ANN003
            return self._run_with_overlap(super().run_taskfile_worker, *args, **kwargs)

    predictions = label_atomic_lines(
        [_candidate(0), _candidate(1)],
        _settings(line_role_worker_count=2, line_role_prompt_target_count=None),
        artifact_root=tmp_path,
        codex_batch_size=1,
        codex_runner=_ConcurrentRunner(
            output_builder=_line_role_builder(
                {0: "RECIPE_NOTES", 1: "RECIPE_NOTES"}
            )
        ),
        live_llm_allowed=True,
    )

    assert [row.atomic_index for row in predictions] == [0, 1]
    assert state["max"] >= 2


def test_line_role_prompt_target_count_is_a_direct_shard_override(
    tmp_path: Path,
) -> None:
    runner = FakeCodexExecRunner(
        output_builder=_line_role_builder(
            {index: "RECIPE_NOTES" for index in range(5)}
        )
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


def test_line_role_prompt_target_count_is_a_hard_cap(
    tmp_path: Path,
) -> None:
    runner = FakeCodexExecRunner(
        output_builder=_line_role_builder(
            {index: "RECIPE_NOTES" for index in range(5)}
        )
    )

    label_atomic_lines(
        [_candidate(index) for index in range(5)],
        _settings(line_role_prompt_target_count=1, line_role_worker_count=1),
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
    telemetry = json.loads(
        (
            tmp_path
            / "line-role-pipeline"
            / "runtime"
            / "line_role"
            / "telemetry.json"
        ).read_text(encoding="utf-8")
    )
    worker_assignments = json.loads(
        (
            tmp_path
            / "line-role-pipeline"
            / "runtime"
            / "line_role"
            / "worker_assignments.json"
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

    assert phase_manifest["shard_count"] == 1
    assert phase_manifest["worker_count"] == 1
    assert (
        phase_manifest["runtime_metadata"]["worker_session_guardrails"][
            "actual_happy_path_worker_sessions"
        ]
        == 1
    )
    assert (
        telemetry["summary"]["task_file_guardrails"]["assignment_count"] == 1
    )
    assert [assignment["shard_ids"] for assignment in worker_assignments] == [
        ["line-role-canonical-0001-a000000-a000004"]
    ]
    assert [len(shard["owned_ids"]) for shard in shard_manifest] == [5]


def test_line_role_fails_closed_before_worker_launch_when_survivability_is_unsafe(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = FakeCodexExecRunner(
        output_builder=lambda _payload: pytest.fail("worker should not start for unsafe shard plans")
    )
    unsafe_report = lambda **_kwargs: {
        "stage_label": "Canonical Line Role",
        "requested_shard_count": 1,
        "minimum_safe_shard_count": 2,
        "binding_limit": "session_peak",
        "survivability_verdict": "unsafe",
        "worst_shard": {"shard_id": "line-role-canonical-0001-a000000-a000004"},
    }
    monkeypatch.setattr(
        canonical_line_roles_module,
        "_build_line_role_shard_survivability_report",
        unsafe_report,
    )
    monkeypatch.setattr(
        "cookimport.parsing.canonical_line_roles.runtime._build_line_role_shard_survivability_report",
        unsafe_report,
    )
    monkeypatch.setitem(
        label_atomic_lines.__globals__,
        "_build_line_role_shard_survivability_report",
        unsafe_report,
    )

    with pytest.raises(RuntimeError, match="minimum safe count is 2"):
        label_atomic_lines(
            [_candidate(index) for index in range(5)],
            _settings(line_role_prompt_target_count=1, line_role_worker_count=1),
            artifact_root=tmp_path,
            codex_batch_size=1,
            codex_runner=runner,
            live_llm_allowed=True,
        )

    assert runner.calls == []


def test_line_role_phase_workers_report_task_packet_progress(
    tmp_path: Path,
) -> None:
    class _SlowRunner(FakeCodexExecRunner):
        def run_taskfile_worker(self, *args, **kwargs):  # noqa: ANN002, ANN003
            result = super().run_taskfile_worker(*args, **kwargs)
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
                {
                    0: "RECIPE_NOTES",
                    1: "RECIPE_NOTES",
                    2: "RECIPE_NOTES",
                    3: "RECIPE_NOTES",
                }
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
    assert payloads[-1]["work_unit_label"] == "shard"
    assert payloads[-1]["task_current"] == payloads[-1]["task_total"] == 2
    assert any(int(payload.get("worker_total") or 0) == 2 for payload in payloads)
    assert any(payload.get("followup_label") == "shard finalization" for payload in payloads)
