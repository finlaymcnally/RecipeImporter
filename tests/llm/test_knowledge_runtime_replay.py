from __future__ import annotations

import json
from pathlib import Path

from cookimport.llm.knowledge_runtime_replay import replay_knowledge_runtime
from cookimport.llm.knowledge_runtime_state import (
    KnowledgeArtifactState,
    KnowledgePacketAttemptType,
    KnowledgePacketLedger,
    KnowledgePacketRecord,
    KnowledgePacketState,
    KnowledgePacketTerminalOutcome,
    KnowledgeWorkerOutcomeCategory,
)


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def _write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True))
            handle.write("\n")


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_knowledge_packet_ledger_rollup_counts_packets_followups_and_artifacts() -> None:
    ledger = KnowledgePacketLedger()
    ledger.add(
        KnowledgePacketRecord(
            packet_id="pkt-001",
            parent_shard_id="shard-001",
            state=KnowledgePacketState.MAIN_OUTPUT_WRITTEN,
            latest_attempt_type=KnowledgePacketAttemptType.MAIN_WORKER,
            main_output_present=True,
        )
    )
    ledger.add(
        KnowledgePacketRecord(
            packet_id="pkt-002",
            parent_shard_id="shard-001",
            state=KnowledgePacketState.RETRY_RECOVERED,
            terminal_outcome=KnowledgePacketTerminalOutcome.RETRY_RECOVERED,
            latest_attempt_type=KnowledgePacketAttemptType.WATCHDOG_RETRY,
            watchdog_retry_status="validated",
        )
    )
    ledger.add(
        KnowledgePacketRecord(
            packet_id="pkt-003",
            parent_shard_id="shard-002",
            state=KnowledgePacketState.FOLLOW_UP_STALE,
            latest_attempt_type=KnowledgePacketAttemptType.REPAIR,
            repair_stale=True,
        )
    )

    rollup = ledger.rollup(
        worker_outcome_counts={
            KnowledgeWorkerOutcomeCategory.COMPLETED_OUTPUTS_STABILIZED.value: 1,
            KnowledgeWorkerOutcomeCategory.WATCHDOG_COMMAND_FORBIDDEN.value: 1,
        },
        worker_output_count=2,
        malformed_worker_output_count=1,
        stage_artifact_states={
            "phase_manifest.json": KnowledgeArtifactState.MISSING.value,
            "task_manifest.jsonl": KnowledgeArtifactState.PRESENT.value,
        },
        benchmark_artifact_states={
            "processing_timeseries_prediction.jsonl": KnowledgeArtifactState.PRESENT.value,
            "eval_report.json": KnowledgeArtifactState.MISSING.value,
        },
    )

    assert rollup.packet_total == 3
    assert rollup.packet_state_counts == {
        "follow_up_stale": 1,
        "main_output_written": 1,
        "retry_recovered": 1,
    }
    assert rollup.terminal_outcome_counts == {"retry_recovered": 1}
    assert rollup.follow_up_attempt_counts == {
        "repair": 1,
        "watchdog_retry": 1,
    }
    assert rollup.stale_follow_up_count == 1
    assert rollup.worker_output_count == 2
    assert rollup.malformed_worker_output_count == 1
    assert rollup.missing_stage_artifacts == ("phase_manifest.json",)
    assert rollup.missing_benchmark_artifacts == ("eval_report.json",)


def test_replay_knowledge_runtime_classifies_synthetic_artifacts(tmp_path: Path) -> None:
    knowledge_root = tmp_path / "knowledge"
    benchmark_root = tmp_path / "benchmark"
    _write_jsonl(
        knowledge_root / "task_manifest.jsonl",
        [
            {
                "task_id": "book.ks0000.nr.task-001",
                "parent_shard_id": "book.ks0000.nr",
                "owned_ids": ["chunk-001"],
            },
            {
                "task_id": "book.ks0000.nr.task-002",
                "parent_shard_id": "book.ks0000.nr",
                "owned_ids": ["chunk-002"],
            },
            {
                "task_id": "book.ks0001.nr.task-001",
                "parent_shard_id": "book.ks0001.nr",
                "owned_ids": ["chunk-101"],
            },
            {
                "task_id": "book.ks0001.nr.task-002",
                "parent_shard_id": "book.ks0001.nr",
                "owned_ids": ["chunk-102"],
            },
            {
                "task_id": "book.ks0002.nr.task-001",
                "parent_shard_id": "book.ks0002.nr",
                "owned_ids": ["chunk-201"],
            },
        ],
    )
    _write_jsonl(
        knowledge_root / "shard_manifest.jsonl",
        [
            {"shard_id": "book.ks0000.nr"},
            {"shard_id": "book.ks0001.nr"},
            {"shard_id": "book.ks0002.nr"},
        ],
    )
    _write_json(
        knowledge_root / "worker_assignments.json",
        [
            {"worker_id": "worker-001", "shard_ids": ["book.ks0000.nr"]},
            {"worker_id": "worker-002", "shard_ids": ["book.ks0001.nr"]},
            {"worker_id": "worker-003", "shard_ids": ["book.ks0002.nr"]},
        ],
    )

    _write_json(
        knowledge_root / "workers" / "worker-001" / "live_status.json",
        {"state": "completed", "reason_code": "workspace_outputs_stabilized"},
    )
    _write_json(
        knowledge_root / "workers" / "worker-001" / "assigned_tasks.json",
        [
            {"task_id": "book.ks0000.nr.task-001"},
            {"task_id": "book.ks0000.nr.task-002"},
        ],
    )
    _write_json(
        knowledge_root / "workers" / "worker-001" / "out" / "book.ks0000.nr.task-001.json",
        {"v": "2", "bid": "book.ks0000.nr.task-001", "r": []},
    )
    malformed_path = (
        knowledge_root / "workers" / "worker-001" / "out" / "book.ks0000.nr.task-002.json"
    )
    malformed_path.parent.mkdir(parents=True, exist_ok=True)
    malformed_path.write_text('{"v":"2","bid":"book.ks0000.nr.task-002"}EOF', encoding="utf-8")
    _write_json(
        knowledge_root
        / "workers"
        / "worker-001"
        / "shards"
        / "book.ks0000.nr.task-002"
        / "repair_status.json",
        {"status": "failed"},
    )

    _write_json(
        knowledge_root / "workers" / "worker-002" / "live_status.json",
        {
            "state": "watchdog_killed",
            "reason_code": "watchdog_command_execution_forbidden",
        },
    )
    _write_json(
        knowledge_root / "workers" / "worker-002" / "assigned_tasks.json",
        [
            {"task_id": "book.ks0001.nr.task-001"},
            {"task_id": "book.ks0001.nr.task-002"},
        ],
    )
    _write_json(
        knowledge_root
        / "workers"
        / "worker-002"
        / "shards"
        / "book.ks0001.nr.task-001"
        / "watchdog_retry"
        / "status.json",
        {"status": "validated"},
    )
    _write_json(
        knowledge_root
        / "workers"
        / "worker-002"
        / "shards"
        / "book.ks0001.nr.task-002"
        / "watchdog_retry"
        / "live_status.json",
        {"state": "running"},
    )

    _write_json(
        knowledge_root / "workers" / "worker-003" / "live_status.json",
        {
            "state": "completed",
            "reason_code": "process_exited_without_watchdog_intervention",
        },
    )
    _write_json(
        knowledge_root / "workers" / "worker-003" / "assigned_tasks.json",
        [{"task_id": "book.ks0002.nr.task-001"}],
    )
    _write_json(
        knowledge_root
        / "workers"
        / "worker-003"
        / "shards"
        / "book.ks0002.nr.task-001"
        / "repair_live_status.json",
        {"state": "running"},
    )

    _write_json(benchmark_root / "processing_timeseries_prediction.jsonl", {"ok": True})

    summary = replay_knowledge_runtime(
        knowledge_root=knowledge_root,
        benchmark_root=benchmark_root,
    )

    assert summary.shard_total == 3
    assert summary.rollup.packet_total == 5
    assert summary.rollup.worker_output_count == 2
    assert summary.rollup.malformed_worker_output_count == 1
    assert summary.rollup.worker_outcome_counts == {
        "completed_outputs_stabilized": 1,
        "completed_process_exit": 1,
        "watchdog_command_forbidden": 1,
    }
    assert summary.rollup.follow_up_attempt_counts == {
        "repair": 2,
        "watchdog_retry": 2,
    }
    assert summary.rollup.stale_follow_up_count == 2
    assert summary.rollup.packet_state_counts == {
        "follow_up_stale": 2,
        "main_output_written": 1,
        "repair_failed": 1,
        "retry_recovered": 1,
    }
    assert summary.rollup.terminal_outcome_counts == {
        "repair_failed": 1,
        "retry_recovered": 1,
    }
    assert summary.rollup.stage_artifact_states["phase_manifest.json"] == "missing"
    assert summary.rollup.stage_artifact_states["task_manifest.jsonl"] == "present"
    assert summary.rollup.benchmark_artifact_states == {
        "eval_report.json": "missing",
        "processing_timeseries_evaluation.jsonl": "missing",
        "processing_timeseries_prediction.jsonl": "present",
        "prompt_budget_summary.json": "missing",
    }


def test_replay_knowledge_runtime_matches_large_generated_fixture(tmp_path: Path) -> None:
    knowledge_root = tmp_path / "knowledge"
    benchmark_root = tmp_path / "benchmark"
    worker_ids = [
        "worker-001",
        "worker-002",
        "worker-003",
        "worker-004",
        "worker-005",
    ]
    shard_ids = [
        "book.ks0000.nr",
        "book.ks0001.nr",
        "book.ks0002.nr",
        "book.ks0003.nr",
        "book.ks0004.nr",
    ]
    task_rows: list[dict[str, object]] = []
    worker_assignments: list[dict[str, object]] = []
    task_counter = 1
    for worker_index, worker_id in enumerate(worker_ids):
        shard_id = shard_ids[worker_index]
        worker_assignments.append({"worker_id": worker_id, "shard_ids": [shard_id]})
        assigned_tasks: list[dict[str, object]] = []
        task_count = 89 if worker_index < 2 else 88
        for _ in range(task_count):
            task_id = f"{shard_id}.task-{task_counter:03d}"
            task_counter += 1
            task_rows.append(
                {
                    "task_id": task_id,
                    "parent_shard_id": shard_id,
                    "owned_ids": [f"chunk-{task_id}"],
                }
            )
            assigned_tasks.append({"task_id": task_id})
        _write_json(knowledge_root / "workers" / worker_id / "assigned_tasks.json", assigned_tasks)

    _write_jsonl(knowledge_root / "task_manifest.jsonl", task_rows)
    _write_jsonl(
        knowledge_root / "shard_manifest.jsonl",
        [{"shard_id": shard_id} for shard_id in shard_ids],
    )
    _write_json(knowledge_root / "worker_assignments.json", worker_assignments)
    _write_json(knowledge_root / "phase_manifest.json", {"ok": True})
    _write_json(knowledge_root / "promotion_report.json", {"ok": True})
    _write_json(knowledge_root / "telemetry.json", {"ok": True})
    _write_json(knowledge_root / "failures.json", [])
    _write_json(knowledge_root / "proposals" / "book.ks0000.nr.json", {"ok": True})

    for worker_id in worker_ids[:4]:
        _write_json(
            knowledge_root / "workers" / worker_id / "live_status.json",
            {"state": "completed", "reason_code": "workspace_outputs_stabilized"},
        )
    _write_json(
        knowledge_root / "workers" / worker_ids[-1] / "live_status.json",
        {
            "state": "completed",
            "reason_code": "process_exited_without_watchdog_intervention",
        },
    )

    output_task_ids = [row["task_id"] for row in task_rows[:354]]
    repair_failed_task_ids = output_task_ids[-3:]

    for task_id in output_task_ids:
        _write_json(
            knowledge_root / "workers" / _worker_id_for_task(task_id, worker_assignments) / "out" / f"{task_id}.json",
            {"v": "2", "bid": task_id, "r": []},
        )
    for task_id in repair_failed_task_ids:
        _write_json(
            knowledge_root
            / "workers"
            / _worker_id_for_task(task_id, worker_assignments)
            / "shards"
            / task_id
            / "repair_status.json",
            {"status": "failed"},
        )

    _write_text(benchmark_root / "processing_timeseries_prediction.jsonl", '{"ok": true}\n')
    _write_text(benchmark_root / "processing_timeseries_evaluation.jsonl", '{"ok": true}\n')
    _write_json(benchmark_root / "prompt_budget_summary.json", {"ok": True})
    _write_json(benchmark_root / "eval_report.json", {"ok": True})

    summary = replay_knowledge_runtime(
        knowledge_root=knowledge_root,
        benchmark_root=benchmark_root,
    )

    assert summary.shard_total == 5
    assert summary.rollup.packet_total == 442
    assert summary.rollup.worker_output_count == 354
    assert summary.rollup.malformed_worker_output_count == 0
    assert summary.rollup.worker_outcome_counts == {
        "completed_outputs_stabilized": 4,
        "completed_process_exit": 1,
    }
    assert summary.rollup.follow_up_attempt_counts == {
        "repair": 3,
    }
    assert summary.rollup.stale_follow_up_count == 0
    assert summary.rollup.packet_state_counts == {
        "main_output_written": 351,
        "pending": 88,
        "repair_failed": 3,
    }
    assert summary.rollup.terminal_outcome_counts == {
        "repair_failed": 3,
    }
    assert summary.rollup.stage_artifact_states == {
        "failures.json": "present",
        "phase_manifest.json": "present",
        "promotion_report.json": "present",
        "proposals/*": "present",
        "shard_manifest.jsonl": "present",
        "task_manifest.jsonl": "present",
        "telemetry.json": "present",
        "worker_assignments.json": "present",
    }
    assert summary.rollup.benchmark_artifact_states == {
        "eval_report.json": "present",
        "processing_timeseries_evaluation.jsonl": "present",
        "processing_timeseries_prediction.jsonl": "present",
        "prompt_budget_summary.json": "present",
    }


def _worker_id_for_task(
    task_id: object,
    worker_assignments: list[dict[str, object]],
) -> str:
    cleaned_task_id = str(task_id)
    parent_shard_id = cleaned_task_id.rsplit(".task-", 1)[0]
    for row in worker_assignments:
        shard_ids = row.get("shard_ids")
        if isinstance(shard_ids, list) and parent_shard_id in shard_ids:
            return str(row["worker_id"])
    raise AssertionError(f"missing worker assignment for task {cleaned_task_id}")
