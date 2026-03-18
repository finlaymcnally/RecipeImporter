from __future__ import annotations

import json
import re
import threading
import time
from pathlib import Path

from cookimport.config.run_settings import RunSettings
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
        prev_text=None,
        next_text=None,
        rule_tags=["recipe_span_fallback"],
    )


def _line_role_builder(label_by_atomic_index: dict[int, str]):
    def _builder(payload):
        rows = payload.get("rows") if isinstance(payload, dict) else []
        phase_key = str(payload.get("phase_key") or "") if isinstance(payload, dict) else ""
        atomic_indices = [
            int(row.get("atomic_index"))
            for row in rows
            if isinstance(row, dict) and row.get("atomic_index") is not None
        ]
        if not atomic_indices:
            prompt_text = payload if isinstance(payload, str) else json.dumps(payload, sort_keys=True)
            atomic_indices = [
                int(value)
                for value in re.findall(r'"atomic_index"\s*:\s*(\d+)', prompt_text)
            ]
        if phase_key == "recipe_region_gate":
            return {
                "rows": [
                    {
                        "atomic_index": atomic_index,
                        "region_status": "recipe",
                    }
                    for atomic_index in atomic_indices
                ]
            }
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

    runtime_root = tmp_path / "line-role-pipeline" / "runtime"
    gate_manifest = json.loads(
        (runtime_root / "recipe_region_gate" / "phase_manifest.json").read_text(
            encoding="utf-8"
        )
    )
    gate_assignments = json.loads(
        (runtime_root / "recipe_region_gate" / "worker_assignments.json").read_text(
            encoding="utf-8"
        )
    )
    gate_proposals = sorted(
        (runtime_root / "recipe_region_gate" / "proposals").glob("*.json")
    )
    structure_manifest = json.loads(
        (runtime_root / "recipe_structure_label" / "phase_manifest.json").read_text(
            encoding="utf-8"
        )
    )
    structure_assignments = json.loads(
        (runtime_root / "recipe_structure_label" / "worker_assignments.json").read_text(
            encoding="utf-8"
        )
    )
    structure_proposals = sorted(
        (runtime_root / "recipe_structure_label" / "proposals").glob("*.json")
    )

    assert gate_manifest["worker_count"] == 1
    assert gate_manifest["shard_count"] == 3
    assert gate_assignments[0]["worker_id"] == "worker-001"
    assert gate_assignments[0]["shard_ids"] == [
        "line-role-recipe-region-gate-0001-a000000-a000000",
        "line-role-recipe-region-gate-0002-a000001-a000001",
        "line-role-recipe-region-gate-0003-a000002-a000002",
    ]
    assert len(gate_proposals) == 3
    assert structure_manifest["worker_count"] == 1
    assert structure_manifest["shard_count"] == 3
    assert structure_assignments[0]["worker_id"] == "worker-001"
    assert structure_assignments[0]["shard_ids"] == [
        "line-role-recipe-structure-label-0001-a000000-a000000",
        "line-role-recipe-structure-label-0002-a000001-a000001",
        "line-role-recipe-structure-label-0003-a000002-a000002",
    ]
    assert len(structure_proposals) == 3


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
            / "recipe_structure_label"
            / "failures.json"
        ).read_text(encoding="utf-8")
    )
    parse_errors = json.loads(
        (
            tmp_path
            / "line-role-pipeline"
            / "prompts"
            / "recipe_structure_label"
            / "parse_errors.json"
        ).read_text(encoding="utf-8")
    )

    assert failures[0]["reason"] == "proposal_validation_failed"
    assert "unowned_atomic_index:999" in failures[0]["validation_errors"]
    assert parse_errors["parse_error_count"] == 1


def test_line_role_phase_workers_emit_runtime_telemetry_summary(
    tmp_path: Path,
) -> None:
    class _TelemetryRunner(FakeCodexExecRunner):
        def run_structured_prompt(self, *args, **kwargs):  # noqa: ANN002, ANN003
            result = super().run_structured_prompt(*args, **kwargs)
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
    assert telemetry_summary["summary"]["tokens_input"] == 100
    assert telemetry_summary["summary"]["tokens_cached_input"] == 10
    assert telemetry_summary["summary"]["tokens_output"] == 14
    assert telemetry_summary["summary"]["tokens_reasoning"] == 4
    assert telemetry_summary["summary"]["tokens_total"] == 128
    assert telemetry_summary["runtime_mode"] == "direct_codex_exec_v1"
    assert telemetry_summary["runtime_artifacts"]["phase_count"] == 2
    assert telemetry_summary["phases"][0]["summary"]["tokens_total"] == 64
    assert telemetry_summary["phases"][1]["summary"]["tokens_total"] == 64
    assert telemetry_summary["phases"][0]["runtime_artifacts"]["worker_count"] == 1
    assert telemetry_summary["phases"][1]["runtime_artifacts"]["worker_count"] == 1


def test_line_role_phase_workers_run_concurrently_when_multiple_workers_assigned(
    tmp_path: Path,
) -> None:
    barrier = threading.Barrier(2)
    lock = threading.Lock()
    state = {"current": 0, "max": 0}

    class _ConcurrentRunner(FakeCodexExecRunner):
        def run_structured_prompt(self, *args, **kwargs):  # noqa: ANN002, ANN003
            with lock:
                state["current"] += 1
                state["max"] = max(state["max"], state["current"])
            barrier.wait(timeout=1.0)
            time.sleep(0.05)
            try:
                return super().run_structured_prompt(*args, **kwargs)
            finally:
                with lock:
                    state["current"] -= 1

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
