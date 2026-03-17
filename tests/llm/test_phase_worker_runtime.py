from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from cookimport.llm.codex_farm_runner import SubprocessCodexFarmRunner
from cookimport.llm.fake_codex_farm_runner import FakeCodexFarmRunner
from cookimport.llm.phase_worker_runtime import (
    ShardManifestEntryV1,
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
    assert manifest.assignment_strategy == "round_robin_v1"
    assert reports[0].shard_ids == ("shard-001", "shard-002")
    assert reports[0].runtime_mode_audit == {
        "mode": "structured_loop_agentic_v1",
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
    assert "--workers" in process_command
    assert process_command[process_command.index("--workers") + 1] == "1"
    assert process_env["CODEX_HOME"] == str(default_home)
    assert process_env["CODEX_FARM_CODEX_HOME_RECIPE"] == str(default_home)
    assert process_env["EXTRA_ENV"] == "1"

    assert manifest.worker_count == 1
    assert reports[0].runtime_mode_audit == {
        "codex_farm_process_workers": 1,
        "mode": "structured_loop_agentic_v1",
        "output_schema_enforced": True,
        "reason_codes": [],
        "single_process_worker_enforced": True,
        "status": "ok",
        "tool_affordances_requested": False,
    }
