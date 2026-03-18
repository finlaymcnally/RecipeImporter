from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from cookimport.core.progress_messages import parse_stage_progress
from cookimport.llm.codex_farm_runner import (
    CODEX_FARM_RUNTIME_MODE_CLASSIC_TASK_FARM_V1,
    SubprocessCodexFarmRunner,
)
from cookimport.llm.fake_codex_farm_runner import FakeCodexFarmRunner
from cookimport.llm.phase_worker_runtime import (
    ShardManifestEntryV1,
    resolve_phase_worker_count,
    run_phase_workers_v1,
)


def test_phase_worker_runtime_writes_manifests_assignments_and_failures(
    tmp_path: Path,
) -> None:
    runner = FakeCodexFarmRunner(
        output_builders={
            "recipe.correction.compact.v1": lambda payload: {
                "shard_id": payload["shard_id"],
                "accepted": payload["shard_id"] != "shard-002",
            }
        }
    )
    shards = [
        ShardManifestEntryV1(
            shard_id="shard-001",
            owned_ids=("recipe-001",),
            evidence_refs=("block-1",),
            input_payload={"shard_id": "shard-001", "recipes": ["recipe-001"]},
        ),
        ShardManifestEntryV1(
            shard_id="shard-002",
            owned_ids=("recipe-002",),
            evidence_refs=("block-2",),
            input_payload={"shard_id": "shard-002", "recipes": ["recipe-002"]},
        ),
    ]

    def _validator(shard: ShardManifestEntryV1, payload: dict[str, object]):
        accepted = bool(payload.get("accepted"))
        metadata = {"owned_ids": list(shard.owned_ids)}
        if accepted:
            return True, (), metadata
        return False, ("synthetic_rejection",), metadata

    manifest, reports = run_phase_workers_v1(
        phase_key="recipe",
        pipeline_id="recipe.correction.compact.v1",
        run_root=tmp_path / "runtime",
        shards=shards,
        runner=runner,
        worker_count=1,
        proposal_validator=_validator,
        settings={"llm_recipe_pipeline": "codex-recipe-shard-v1"},
        runtime_metadata={"normalized_from": "codex-recipe-shard-v1"},
    )

    assert manifest.worker_count == 1
    assert manifest.shard_count == 2
    assert manifest.runtime_mode == CODEX_FARM_RUNTIME_MODE_CLASSIC_TASK_FARM_V1
    assert manifest.assignment_strategy == "round_robin_v1"
    assert reports[0].shard_ids == ("shard-001", "shard-002")
    assert reports[0].runtime_mode_audit == {
        "mode": CODEX_FARM_RUNTIME_MODE_CLASSIC_TASK_FARM_V1,
        "status": "ok",
    }
    assert reports[0].failure_count == 1
    assert reports[0].proposal_count == 1

    run_root = Path(manifest.run_root)
    phase_manifest = json.loads((run_root / "phase_manifest.json").read_text(encoding="utf-8"))
    assignments = json.loads((run_root / "worker_assignments.json").read_text(encoding="utf-8"))
    promotion_report = json.loads((run_root / "promotion_report.json").read_text(encoding="utf-8"))
    telemetry = json.loads((run_root / "telemetry.json").read_text(encoding="utf-8"))
    failures = json.loads((run_root / "failures.json").read_text(encoding="utf-8"))
    shard_one_proposal = json.loads(
        (run_root / "proposals" / "shard-001.json").read_text(encoding="utf-8")
    )
    shard_two_proposal = json.loads(
        (run_root / "proposals" / "shard-002.json").read_text(encoding="utf-8")
    )

    assert phase_manifest["artifact_paths"]["shard_manifest"] == "shard_manifest.jsonl"
    assert phase_manifest["runtime_mode"] == CODEX_FARM_RUNTIME_MODE_CLASSIC_TASK_FARM_V1
    assert phase_manifest["max_turns_per_shard"] == 1
    assert assignments == [
        {
            "shard_ids": ["shard-001", "shard-002"],
            "worker_id": "worker-001",
            "workspace_root": str(run_root / "workers" / "worker-001"),
        }
    ]
    assert promotion_report["validated_shards"] == 1
    assert promotion_report["invalid_shards"] == 1
    assert promotion_report["missing_output_shards"] == 0
    assert telemetry["runtime_mode"] == CODEX_FARM_RUNTIME_MODE_CLASSIC_TASK_FARM_V1
    assert telemetry["fresh_agent_count"] == 1
    assert telemetry["shard_count"] == 2
    assert failures == [
        {
            "reason": "proposal_validation_failed",
            "shard_id": "shard-002",
            "validation_errors": ["synthetic_rejection"],
            "worker_id": "worker-001",
        }
    ]
    assert shard_one_proposal["validation_errors"] == []
    assert shard_two_proposal["validation_errors"] == ["synthetic_rejection"]


def test_phase_worker_runtime_routes_through_runner_workspace_and_codex_home(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    pack_root = tmp_path / "pack"
    schema_path = pack_root / "schemas" / "recipe.correction.v1.output.schema.json"
    pipeline_path = pack_root / "pipelines" / "recipe.correction.compact.v1.json"
    schema_path.parent.mkdir(parents=True, exist_ok=True)
    pipeline_path.parent.mkdir(parents=True, exist_ok=True)
    schema_path.write_text(
        json.dumps(
            {
                "$schema": "https://json-schema.org/draft/2020-12/schema",
                "type": "object",
                "additionalProperties": False,
                "required": [],
                "properties": {},
            }
        ),
        encoding="utf-8",
    )
    pipeline_path.write_text(
        json.dumps(
            {
                "pipeline_id": "recipe.correction.compact.v1",
                "prompt_template_path": "prompts/recipe.correction.compact.v1.prompt.md",
                "output_schema_path": "schemas/recipe.correction.v1.output.schema.json",
            }
        ),
        encoding="utf-8",
    )

    default_home = tmp_path / ".codex-recipe"
    default_home.mkdir(parents=True, exist_ok=True)
    monkeypatch.delenv("COOKIMPORT_CODEX_FARM_CODEX_HOME", raising=False)
    monkeypatch.delenv("CODEX_FARM_CODEX_HOME_RECIPE", raising=False)
    monkeypatch.setattr("cookimport.llm.codex_farm_runner.Path.home", lambda: tmp_path)

    captured: dict[str, object] = {}

    def _fake_run(command, **kwargs):  # noqa: ANN001
        argv = list(command)
        if argv[1:3] == ["process", "--pipeline"]:
            in_dir = Path(argv[argv.index("--in") + 1])
            out_dir = Path(argv[argv.index("--out") + 1])
            out_dir.mkdir(parents=True, exist_ok=True)
            captured["process_command"] = argv
            captured["process_env"] = dict(kwargs.get("env") or {})
            for in_path in sorted(in_dir.glob("*.json")):
                payload = json.loads(in_path.read_text(encoding="utf-8"))
                (out_dir / in_path.name).write_text(
                    json.dumps(
                        {
                            "shard_id": payload.get("shard_id"),
                            "accepted": True,
                        }
                    ),
                    encoding="utf-8",
                )
            return SimpleNamespace(
                returncode=0,
                stdout=json.dumps(
                    {
                        "run_id": "run-phase-runtime",
                        "status": "completed",
                        "exit_code": 0,
                        "output_schema_path": str(schema_path),
                        "telemetry_report": {"schema_version": 2},
                    }
                ),
                stderr="",
            )
        if argv[1:3] == ["run", "autotune"]:
            return SimpleNamespace(
                returncode=0,
                stdout=json.dumps(
                    {
                        "schema_version": 1,
                        "run_id": "run-phase-runtime",
                        "pipeline_id": "recipe.correction.compact.v1",
                        "flag_overrides": [],
                        "command_preview": "",
                    }
                ),
                stderr="",
            )
        raise AssertionError(f"Unexpected command: {argv}")

    monkeypatch.setattr("cookimport.llm.codex_farm_runner.subprocess.run", _fake_run)

    manifest, reports = run_phase_workers_v1(
        phase_key="recipe",
        pipeline_id="recipe.correction.compact.v1",
        run_root=tmp_path / "runtime",
        shards=[
            ShardManifestEntryV1(
                shard_id="shard-001",
                owned_ids=("recipe-001",),
                input_payload={"shard_id": "shard-001"},
            ),
            ShardManifestEntryV1(
                shard_id="shard-002",
                owned_ids=("recipe-002",),
                input_payload={"shard_id": "shard-002"},
            ),
        ],
        runner=SubprocessCodexFarmRunner(cmd="codex-farm"),
        worker_count=1,
        root_dir=pack_root,
        env={"EXTRA_ENV": "1"},
    )

    process_command = captured["process_command"]
    process_env = captured["process_env"]
    assert isinstance(process_command, list)
    assert isinstance(process_env, dict)
    assert "--workspace-root" in process_command
    assert str(tmp_path / "runtime" / "workers" / "worker-001") in process_command
    assert "--runtime-mode" in process_command
    assert (
        process_command[process_command.index("--runtime-mode") + 1]
        == CODEX_FARM_RUNTIME_MODE_CLASSIC_TASK_FARM_V1
    )
    assert "--workers" in process_command
    assert process_command[process_command.index("--workers") + 1] == "1"
    assert process_env["CODEX_HOME"] == str(default_home)
    assert process_env["CODEX_FARM_CODEX_HOME_RECIPE"] == str(default_home)
    assert process_env["EXTRA_ENV"] == "1"

    assert manifest.worker_count == 1
    assert manifest.runtime_mode == CODEX_FARM_RUNTIME_MODE_CLASSIC_TASK_FARM_V1
    assert reports[0].runtime_mode_audit == {
        "codex_farm_process_workers": 1,
        "mode": CODEX_FARM_RUNTIME_MODE_CLASSIC_TASK_FARM_V1,
        "output_schema_enforced": True,
        "reason_codes": [],
        "single_process_worker_enforced": True,
        "status": "ok",
        "tool_affordances_requested": False,
    }


def test_resolve_phase_worker_count_defaults_to_shard_count_capped_at_20() -> None:
    assert resolve_phase_worker_count(requested_worker_count=None, shard_count=0) == 0
    assert resolve_phase_worker_count(requested_worker_count=None, shard_count=5) == 5
    assert resolve_phase_worker_count(requested_worker_count=None, shard_count=25) == 20


def test_resolve_phase_worker_count_honors_explicit_override() -> None:
    assert resolve_phase_worker_count(requested_worker_count=7, shard_count=5) == 5
    assert resolve_phase_worker_count(requested_worker_count=3, shard_count=5) == 3


def test_phase_worker_runtime_executes_multiple_worker_assignments_concurrently(
    tmp_path: Path,
) -> None:
    barrier = threading.Barrier(2)
    lock = threading.Lock()
    state = {"current": 0, "max": 0}

    class _ConcurrentRunner:
        def run_pipeline(
            self,
            pipeline_id: str,
            in_dir: Path,
            out_dir: Path,
            env: dict[str, str],
            *,
            root_dir: Path | None = None,
            workspace_root: Path | None = None,
            model: str | None = None,
            reasoning_effort: str | None = None,
            runtime_mode: str | None = None,
            process_worker_count: int | None = None,
        ):
            del env, root_dir, workspace_root, model, reasoning_effort, runtime_mode, process_worker_count
            assert pipeline_id == "recipe.correction.compact.v1"
            out_dir.mkdir(parents=True, exist_ok=True)
            with lock:
                state["current"] += 1
                state["max"] = max(state["max"], state["current"])
            barrier.wait(timeout=1.0)
            time.sleep(0.05)
            for in_path in sorted(in_dir.glob("*.json")):
                payload = json.loads(in_path.read_text(encoding="utf-8"))
                (out_dir / in_path.name).write_text(
                    json.dumps(
                        {
                            "shard_id": payload.get("shard_id"),
                            "accepted": True,
                        }
                    ),
                    encoding="utf-8",
                )
            with lock:
                state["current"] -= 1
            return {
                "pipeline_id": pipeline_id,
                "runtime_mode_audit": {"mode": "test", "status": "ok"},
            }

    def _validator(shard: ShardManifestEntryV1, payload: dict[str, object]):
        accepted = bool(payload.get("accepted"))
        if accepted:
            return True, (), {}
        return False, ("synthetic_rejection",), {}

    manifest, reports = run_phase_workers_v1(
        phase_key="recipe",
        pipeline_id="recipe.correction.compact.v1",
        run_root=tmp_path / "runtime",
        shards=[
            ShardManifestEntryV1(
                shard_id="shard-001",
                owned_ids=("recipe-001",),
                input_payload={"shard_id": "shard-001"},
            ),
            ShardManifestEntryV1(
                shard_id="shard-002",
                owned_ids=("recipe-002",),
                input_payload={"shard_id": "shard-002"},
            ),
        ],
        runner=_ConcurrentRunner(),
        worker_count=2,
        proposal_validator=_validator,
    )

    assert manifest.worker_count == 2
    assert len(reports) == 2
    assert state["max"] >= 2


def test_phase_worker_runtime_emits_structured_progress_snapshots(tmp_path: Path) -> None:
    progress_messages: list[str] = []

    runner = FakeCodexFarmRunner(
        output_builders={
            "recipe.correction.compact.v1": lambda payload: {
                "shard_id": payload["shard_id"],
                "accepted": True,
            }
        }
    )

    def _validator(shard: ShardManifestEntryV1, payload: dict[str, object]):
        if bool(payload.get("accepted")):
            return True, (), {"owned_ids": list(shard.owned_ids)}
        return False, ("synthetic_rejection",), {}

    manifest, reports = run_phase_workers_v1(
        phase_key="recipe_llm_correct_and_link",
        pipeline_id="recipe.correction.compact.v1",
        run_root=tmp_path / "runtime",
        shards=[
            ShardManifestEntryV1(
                shard_id="shard-001",
                owned_ids=("recipe-001",),
                input_payload={"shard_id": "shard-001"},
            ),
            ShardManifestEntryV1(
                shard_id="shard-002",
                owned_ids=("recipe-002",),
                input_payload={"shard_id": "shard-002"},
            ),
        ],
        runner=runner,
        worker_count=2,
        proposal_validator=_validator,
        progress_callback=progress_messages.append,
        progress_message_prefix="Running codex-farm recipe pipeline...",
        progress_stage_label="recipe pipeline",
    )

    assert manifest.worker_count == 2
    assert len(reports) == 2
    payloads = [
        payload
        for message in progress_messages
        for payload in [parse_stage_progress(message)]
        if payload is not None
    ]
    assert payloads
    assert payloads[0]["stage_label"] == "recipe pipeline"
    assert payloads[0]["task_current"] == 0
    assert payloads[0]["task_total"] == 2
    assert payloads[0]["worker_total"] == 2
    assert any(
        "configured workers: 2" in (payload.get("detail_lines") or [])
        for payload in payloads
    )
    assert payloads[-1]["task_current"] == 2
    assert payloads[-1]["running_workers"] == 0
