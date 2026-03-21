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


def test_replay_knowledge_runtime_matches_saved_march20_saltfat_artifacts() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    knowledge_root = (
        repo_root
        / "data/output/2026-03-20_21.44.20/single-book-benchmark/saltfatacidheatcutdown/codexfarm/2026-03-20_21.44.56/raw/llm/saltfatacidheatcutdown/knowledge"
    )
    benchmark_root = (
        repo_root
        / "data/golden/benchmark-vs-golden/2026-03-20_21.44.20/single-book-benchmark/saltfatacidheatcutdown/codexfarm"
    )

    summary = replay_knowledge_runtime(
        knowledge_root=knowledge_root,
        benchmark_root=benchmark_root,
    )

    assert summary.shard_total == 10
    assert summary.rollup.packet_total == 485
    assert summary.rollup.worker_output_count == 339
    assert summary.rollup.malformed_worker_output_count == 50
    assert summary.rollup.worker_outcome_counts == {
        "completed_outputs_stabilized": 4,
        "completed_process_exit": 2,
        "watchdog_command_forbidden": 4,
    }
    assert summary.rollup.follow_up_attempt_counts == {
        "repair": 122,
        "watchdog_retry": 77,
    }
    assert summary.rollup.stale_follow_up_count == 9
    assert summary.rollup.stage_artifact_states == {
        "failures.json": "missing",
        "phase_manifest.json": "missing",
        "promotion_report.json": "missing",
        "proposals/*": "missing",
        "shard_manifest.jsonl": "present",
        "task_manifest.jsonl": "present",
        "telemetry.json": "missing",
        "worker_assignments.json": "present",
    }
    assert summary.rollup.benchmark_artifact_states == {
        "eval_report.json": "missing",
        "processing_timeseries_evaluation.jsonl": "missing",
        "processing_timeseries_prediction.jsonl": "present",
        "prompt_budget_summary.json": "missing",
    }

