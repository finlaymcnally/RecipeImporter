from __future__ import annotations

import json
import time
from pathlib import Path

from cookimport.config.run_settings import RunSettings
from cookimport.core.progress_messages import parse_stage_progress
from cookimport.core.models import ConversionReport, ConversionResult, RawArtifact, RecipeCandidate
from cookimport.llm import codex_farm_orchestrator as recipe_module
from cookimport.llm.codex_exec_runner import CodexExecLiveSnapshot
from cookimport.llm.codex_exec_runner import CodexExecRunResult
from cookimport.llm.codex_farm_orchestrator import run_codex_farm_recipe_pipeline
from cookimport.llm.codex_exec_runner import FakeCodexExecRunner
from cookimport.llm.editable_task_file import load_task_file


def _build_multi_recipe_conversion_result(source_path: Path) -> ConversionResult:
    return ConversionResult(
        recipes=[
            RecipeCandidate(
                name="Toast",
                identifier="urn:recipe:test:toast",
                recipeIngredient=["1 slice bread"],
                recipeInstructions=["Toast the bread."],
                provenance={"location": {"start_block": 1, "end_block": 3}},
            ),
            RecipeCandidate(
                name="Tea",
                identifier="urn:recipe:test:tea",
                recipeIngredient=["1 cup water", "1 tea bag"],
                recipeInstructions=["Boil the water.", "Steep the tea bag."],
                provenance={"location": {"start_block": 5, "end_block": 8}},
            ),
            RecipeCandidate(
                name="Cereal",
                identifier="urn:recipe:test:cereal",
                recipeIngredient=["1 cup cereal", "1/2 cup milk"],
                recipeInstructions=["Pour cereal into a bowl.", "Add milk."],
                provenance={"location": {"start_block": 10, "end_block": 13}},
            ),
        ],
        nonRecipeBlocks=[],
        rawArtifacts=[
            RawArtifact(
                importer="text",
                sourceHash="hash123",
                locationId="full_text",
                extension="json",
                content={
                    "blocks": [
                        {"index": 0, "text": "Preface"},
                        {"index": 1, "text": "Toast"},
                        {"index": 2, "text": "1 slice bread"},
                        {"index": 3, "text": "Toast the bread."},
                        {"index": 4, "text": "Separator"},
                        {"index": 5, "text": "Tea"},
                        {"index": 6, "text": "1 cup water"},
                        {"index": 7, "text": "1 tea bag"},
                        {"index": 8, "text": "Boil the water. Steep the tea bag."},
                        {"index": 9, "text": "Separator"},
                        {"index": 10, "text": "Cereal"},
                        {"index": 11, "text": "1 cup cereal"},
                        {"index": 12, "text": "1/2 cup milk"},
                        {"index": 13, "text": "Pour cereal into a bowl. Add milk."},
                    ],
                },
                metadata={"artifact_type": "extracted_blocks"},
            )
        ],
        report=ConversionReport(),
        workbook=source_path.stem,
        workbookPath=str(source_path),
    )


def _build_fragmentary_recipe_conversion_result(source_path: Path) -> ConversionResult:
    return ConversionResult(
        recipes=[
            RecipeCandidate(
                name="Toast",
                identifier="urn:recipe:test:toast",
                recipeIngredient=["1 slice bread"],
                recipeInstructions=["Toast the bread."],
                provenance={"location": {"start_block": 1, "end_block": 3}},
            ),
            RecipeCandidate(
                name="The Four Elements of Good Cooking",
                identifier="urn:recipe:test:fragmentary",
                recipeIngredient=[],
                recipeInstructions=[],
                provenance={"location": {"start_block": 5, "end_block": 7}},
            ),
        ],
        nonRecipeBlocks=[],
        rawArtifacts=[
            RawArtifact(
                importer="text",
                sourceHash="hash123",
                locationId="full_text",
                extension="json",
                content={
                    "blocks": [
                        {"index": 0, "text": "Preface"},
                        {"index": 1, "text": "Toast"},
                        {"index": 2, "text": "1 slice bread"},
                        {"index": 3, "text": "Toast the bread."},
                        {"index": 4, "text": "Separator"},
                        {"index": 5, "text": "The Four Elements of Good Cooking"},
                        {"index": 6, "text": "SALT"},
                        {"index": 7, "text": "What is Salt?"},
                    ],
                },
                metadata={"artifact_type": "extracted_blocks"},
            )
        ],
        report=ConversionReport(),
        workbook=source_path.stem,
        workbookPath=str(source_path),
    )


def _build_recipe_workspace_output(
    payload: dict[str, object] | None,
    *,
    status_by_recipe_id: dict[str, str] | None = None,
) -> dict[str, object]:
    shard_payload = dict(payload or {})
    statuses = dict(status_by_recipe_id or {})
    recipes = []
    for recipe_payload in shard_payload.get("r") or []:
        recipe_payload = dict(recipe_payload)
        recipe_id = str(recipe_payload["rid"])
        recipe_hint = dict(recipe_payload.get("h") or {})
        repair_status = str(statuses.get(recipe_id) or "repaired")
        canonical_recipe = (
            {
                "t": recipe_hint.get("n"),
                "i": recipe_hint.get("i", []),
                "s": recipe_hint.get("s", []),
                "d": None,
                "y": None,
            }
            if repair_status == "repaired"
            else None
        )
        status_reason = None
        ingredient_count = len(
            [item for item in recipe_hint.get("i", []) if str(item or "").strip()]
        )
        step_count = len([item for item in recipe_hint.get("s", []) if str(item or "").strip()])
        if step_count <= 1:
            mapping_reason = "not_needed_single_step"
        elif ingredient_count <= 1:
            mapping_reason = "not_needed_single_ingredient"
        else:
            mapping_reason = "unclear_alignment"
        warnings: list[str] = []
        if repair_status == "fragmentary":
            status_reason = "recipe evidence exists but the owned text is too incomplete"
            mapping_reason = "not_applicable_fragmentary"
            warnings = ["incomplete_recipe_source"]
        elif repair_status == "not_a_recipe":
            status_reason = "owned text is not a recipe"
            mapping_reason = "not_applicable_not_a_recipe"
        recipes.append(
            {
                "v": "1",
                "rid": recipe_id,
                "st": repair_status,
                "sr": status_reason,
                "cr": canonical_recipe,
                "m": [],
                "mr": mapping_reason,
                "g": [],
                "w": warnings,
            }
        )
    return {
        "v": "1",
        "sid": shard_payload.get("sid"),
        "r": recipes,
    }


def _build_recipe_shard_output(payload: dict[str, object] | None) -> dict[str, object]:
    return _build_recipe_workspace_output(payload)


def _build_legacy_recipe_workspace_output(payload: dict[str, object] | None) -> dict[str, object]:
    shard_payload = dict(payload or {})
    recipe_payload = dict((shard_payload.get("r") or [{}])[0])
    return {
        "sid": shard_payload.get("sid"),
        "results": [
            {
                "recipe_id": recipe_payload.get("rid"),
                "not_a_recipe": False,
                "fragmentary": False,
                "notes": "legacy worker contract",
            }
        ],
    }


class _NoFinalWorkspaceMessageRunner(FakeCodexExecRunner):
    def run_workspace_worker(self, **kwargs) -> CodexExecRunResult:  # noqa: ANN003
        result = super().run_workspace_worker(**kwargs)
        return CodexExecRunResult(
            command=list(result.command),
            subprocess_exit_code=result.subprocess_exit_code,
            output_schema_path=result.output_schema_path,
            prompt_text=result.prompt_text,
            response_text=None,
            turn_failed_message=result.turn_failed_message,
            events=tuple(
                event
                for event in result.events
                if event.get("item", {}).get("type") != "agent_message"
            ),
            usage=dict(result.usage or {}),
            stderr_text=result.stderr_text,
            stdout_text=result.stdout_text,
            source_working_dir=result.source_working_dir,
            execution_working_dir=result.execution_working_dir,
            execution_agents_path=result.execution_agents_path,
            duration_ms=result.duration_ms,
            started_at_utc=result.started_at_utc,
            finished_at_utc=result.finished_at_utc,
            workspace_mode=result.workspace_mode,
            supervision_state=result.supervision_state,
            supervision_reason_code=result.supervision_reason_code,
            supervision_reason_detail=result.supervision_reason_detail,
            supervision_retryable=result.supervision_retryable,
        )


def _run_multi_recipe_phase_fixture(tmp_path: Path) -> dict[str, object]:
    source = tmp_path / "book.txt"
    source.write_text("source", encoding="utf-8")
    settings = RunSettings.model_validate(
        {
            "llm_recipe_pipeline": "codex-recipe-shard-v1",
            "codex_farm_cmd": "codex-farm",
            "codex_farm_root": str(tmp_path / "pack"),
            "recipe_prompt_target_count": 2,
            "recipe_worker_count": 1,
        }
    )
    for name in ("pipelines", "prompts", "schemas"):
        (tmp_path / "pack" / name).mkdir(parents=True, exist_ok=True)

    runner = FakeCodexExecRunner(output_builder=_build_recipe_shard_output)

    apply_result = run_codex_farm_recipe_pipeline(
        conversion_result=_build_multi_recipe_conversion_result(source),
        run_settings=settings,
        run_root=tmp_path / "run",
        workbook_slug="book",
        runner=runner,
    )

    runtime_dir = apply_result.llm_raw_dir / "recipe_phase_runtime"
    manifest = json.loads(
        (apply_result.llm_raw_dir / "recipe_manifest.json").read_text(encoding="utf-8")
    )
    phase_manifest = json.loads((runtime_dir / "phase_manifest.json").read_text(encoding="utf-8"))
    worker_assignments = json.loads(
        (runtime_dir / "worker_assignments.json").read_text(encoding="utf-8")
    )
    shard_manifest = [
        json.loads(line)
        for line in (runtime_dir / "shard_manifest.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    task_manifest = [
        json.loads(line)
        for line in (runtime_dir / "task_manifest.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    worker_root = runtime_dir / "workers" / "worker-001"
    worker_manifest = json.loads(
        (worker_root / "worker_manifest.json").read_text(encoding="utf-8")
    )
    worker_status = json.loads((worker_root / "status.json").read_text(encoding="utf-8"))
    proposal = json.loads(
        (
            runtime_dir / "proposals" / "recipe-shard-0000-r0000-r0001.json"
        ).read_text(encoding="utf-8")
    )
    return {
        "apply_result": apply_result,
        "runtime_dir": runtime_dir,
        "manifest": manifest,
        "phase_manifest": phase_manifest,
        "worker_assignments": worker_assignments,
        "shard_manifest": shard_manifest,
        "task_manifest": task_manifest,
        "runner": runner,
        "worker_root": worker_root,
        "worker_manifest": worker_manifest,
        "worker_status": worker_status,
        "proposal": proposal,
    }


def test_recipe_phase_runtime_groups_multi_recipe_shards_and_promotes_outputs(
    tmp_path: Path,
) -> None:
    fixture = _run_multi_recipe_phase_fixture(tmp_path)
    apply_result = fixture["apply_result"]
    manifest = fixture["manifest"]
    phase_manifest = fixture["phase_manifest"]
    worker_assignments = fixture["worker_assignments"]
    shard_manifest = fixture["shard_manifest"]
    task_manifest = fixture["task_manifest"]
    runner = fixture["runner"]

    assert manifest["counts"]["recipe_shards_total"] == 2
    assert manifest["counts"]["recipe_workers_total"] == 1
    assert manifest["counts"]["recipe_correction_ok"] == 3
    assert manifest["counts"]["recipe_build_final_ok"] == 3
    assert manifest["process_runs"]["recipe_correction"]["runtime_mode"] == "direct_codex_exec_v1"

    assert phase_manifest["worker_count"] == 1
    assert phase_manifest["shard_count"] == 2
    assert phase_manifest["runtime_mode"] == "direct_codex_exec_v1"
    assert worker_assignments[0]["worker_id"] == "worker-001"
    assert len(worker_assignments[0]["shard_ids"]) == 2
    assert len(shard_manifest) == 2
    assert [row["task_id"] for row in task_manifest] == [
        "recipe-shard-0000-r0000-r0001.task-001",
        "recipe-shard-0000-r0000-r0001.task-002",
        "recipe-shard-0001-r0002-r0002",
    ]
    assert [row["parent_shard_id"] for row in task_manifest] == [
        "recipe-shard-0000-r0000-r0001",
        "recipe-shard-0000-r0000-r0001",
        "recipe-shard-0001-r0002-r0002",
    ]
    assert shard_manifest[0]["owned_ids"] == [
        "urn:recipe:test:toast",
        "urn:recipe:test:tea",
    ]
    assert shard_manifest[1]["owned_ids"] == ["urn:recipe:test:cereal"]

    phase_input_dir = apply_result.llm_raw_dir / "recipe_phase_runtime" / "inputs"
    assert len(list(phase_input_dir.glob("*.json"))) == 2
    assert not (apply_result.llm_raw_dir / "recipe_correction").exists()
    assert len(apply_result.authoritative_recipe_payloads_by_recipe_id) == 3
    assert len(runner.calls) == 1
    assert runner.calls[0]["mode"] == "workspace_worker"


def test_recipe_phase_runtime_writes_worker_prompt_and_manifest_contract(
    tmp_path: Path,
) -> None:
    fixture = _run_multi_recipe_phase_fixture(tmp_path)
    worker_root = fixture["worker_root"]
    worker_manifest = fixture["worker_manifest"]

    worker_prompt = (worker_root / "prompt.txt").read_text(encoding="utf-8")
    assert "Open `task.json`, read the whole file once" in worker_prompt
    assert "edit only `/units/*/answer`" in worker_prompt
    assert "`task.json` already contains the full job for this worker." in worker_prompt
    assert "If you briefly reread part of the file or make a small local false start" in worker_prompt
    assert "Do not invent helper ledgers, queue files, or alternate output files." in worker_prompt
    assert "The repo will validate the edited task file and expand accepted answers into final artifacts." in worker_prompt
    assert "assigned_tasks.json" not in worker_prompt
    assert "CURRENT_TASK.md" not in worker_prompt
    assert "CURRENT_TASK_FEEDBACK.md" not in worker_prompt
    assert worker_manifest["entry_files"] == ["task.json"]
    assert worker_manifest["single_file_worker_runtime"] is True
    assert worker_manifest["assigned_tasks_file"] is None
    assert worker_manifest["assigned_shards_file"] is None
    assert worker_manifest["current_packet_file"] is None
    assert worker_manifest["current_hint_file"] is None
    assert worker_manifest["current_result_path_file"] is None
    assert worker_manifest["packet_lease_status_file"] is None
    assert worker_manifest["output_contract_file"] is None
    assert worker_manifest["examples_dir"] is None
    assert worker_manifest["tools_dir"] is None
    assert worker_manifest["hints_dir"] is None
    assert worker_manifest["input_dir"] is None
    assert worker_manifest["output_dir"] is None
    assert worker_manifest["task_file"] == "task.json"
    assert worker_manifest["mirrored_example_files"] == []
    assert worker_manifest["mirrored_tool_files"] == []
    assert (worker_root / "_repo_control" / "original_task.json").exists()

def test_recipe_phase_runtime_uses_fixed_assignment_task_manifest(
    tmp_path: Path,
) -> None:
    fixture = _run_multi_recipe_phase_fixture(tmp_path)
    worker_root = fixture["worker_root"]
    task_file = load_task_file(worker_root / "task.json")
    assert task_file["stage_key"] == "recipe_refine"
    assert task_file["mode"] == "initial"
    assert task_file["editable_json_pointers"] == [
        "/units/0/answer",
        "/units/1/answer",
        "/units/2/answer",
    ]
    assert [unit["owned_id"] for unit in task_file["units"]] == [
        "urn:recipe:test:toast",
        "urn:recipe:test:tea",
        "urn:recipe:test:cereal",
    ]
    assert not (worker_root / "CURRENT_TASK.md").exists()
    assert not (worker_root / "CURRENT_TASK_FEEDBACK.md").exists()
    assert not (worker_root / "assigned_tasks.json").exists()
    assert not (worker_root / "SHARD_PACKET.md").exists()
    assert not (worker_root / "scratch").exists()
    assert not (worker_root / "current_packet.json").exists()


def test_recipe_phase_runtime_writes_packet_outputs_and_session_telemetry(
    tmp_path: Path,
) -> None:
    fixture = _run_multi_recipe_phase_fixture(tmp_path)
    worker_root = fixture["worker_root"]
    worker_status = fixture["worker_status"]
    phase_manifest = fixture["phase_manifest"]
    proposal = fixture["proposal"]

    assert not any((worker_root / "hints").glob("*.md"))
    assert (worker_root / "out" / "recipe-shard-0000-r0000-r0001.task-001.json").exists()
    assert (worker_root / "out" / "recipe-shard-0000-r0000-r0001.task-002.json").exists()
    assert (worker_root / "out" / "recipe-shard-0001-r0002-r0002.json").exists()
    assert (worker_root / "events.jsonl").exists()
    assert (worker_root / "usage.json").exists()
    assert worker_status["runtime_mode_audit"]["output_schema_enforced"] is False
    assert worker_status["runtime_mode_audit"]["tool_affordances_requested"] is True
    assert worker_status["telemetry"]["summary"]["workspace_worker_session_count"] == 1
    assert (
        worker_status["telemetry"]["summary"]["worker_session_guardrails"][
            "planned_happy_path_worker_cap"
        ]
        == 1
    )
    assert (
        worker_status["telemetry"]["summary"]["task_file_guardrails"]["assignment_count"]
        == 1
    )
    assert (
        phase_manifest["runtime_metadata"]["worker_session_guardrails"][
            "actual_happy_path_worker_sessions"
        ]
        == 1
    )
    assert proposal["validation_metadata"]["task_aggregation"]["task_count"] == 2


def test_recipe_phase_runtime_short_circuits_fragmentary_scaffolds_before_worker_queue(
    tmp_path: Path,
) -> None:
    source = tmp_path / "book.txt"
    source.write_text("source", encoding="utf-8")
    settings = RunSettings.model_validate(
        {
            "llm_recipe_pipeline": "codex-recipe-shard-v1",
            "codex_farm_cmd": "codex-farm",
            "codex_farm_root": str(tmp_path / "pack"),
            "recipe_prompt_target_count": 2,
            "recipe_worker_count": 1,
        }
    )
    for name in ("pipelines", "prompts", "schemas"):
        (tmp_path / "pack" / name).mkdir(parents=True, exist_ok=True)

    runner = FakeCodexExecRunner(output_builder=_build_recipe_shard_output)

    apply_result = run_codex_farm_recipe_pipeline(
        conversion_result=_build_fragmentary_recipe_conversion_result(source),
        run_settings=settings,
        run_root=tmp_path / "run",
        workbook_slug="book",
        runner=runner,
    )

    runtime_dir = apply_result.llm_raw_dir / "recipe_phase_runtime"
    worker_root = runtime_dir / "workers" / "worker-001"
    worker_prompt = (worker_root / "prompt.txt").read_text(encoding="utf-8")
    promotion_report = json.loads((runtime_dir / "promotion_report.json").read_text(encoding="utf-8"))
    recipe_manifest = json.loads(
        (apply_result.llm_raw_dir / "recipe_manifest.json").read_text(encoding="utf-8")
    )
    fragmentary_proposal = json.loads(
        (
            runtime_dir / "proposals" / "recipe-shard-0001-r0001-r0001.json"
        ).read_text(encoding="utf-8")
    )

    assert "recipe-shard-0001-r0001-r0001" not in worker_prompt
    assert (worker_root / "task.json").exists()
    task_file = load_task_file(worker_root / "task.json")
    assert [unit["owned_id"] for unit in task_file["units"]] == [
        "urn:recipe:test:toast"
    ]
    assert (worker_root / "out" / "recipe-shard-0000-r0000-r0000.json").exists()
    assert (worker_root / "out" / "recipe-shard-0001-r0001-r0001.json").exists()
    assert fragmentary_proposal["payload"]["r"][0]["rid"] == "urn:recipe:test:fragmentary"
    assert fragmentary_proposal["payload"]["r"][0]["st"] == "fragmentary"
    assert fragmentary_proposal["validation_metadata"]["task_aggregation"]["accepted_task_count"] == 1
    assert fragmentary_proposal["validation_metadata"]["task_status_by_task_id"][
        "recipe-shard-0001-r0001-r0001"
    ]["llm_dispatch_reason"] == "deterministic_terminal_scaffold"
    assert promotion_report["handled_locally_skip_llm"]["count"] == 1
    assert promotion_report["handled_locally_skip_llm"]["status_counts"] == {
        "fragmentary": 1,
        "not_a_recipe": 0,
    }
    assert promotion_report["handled_locally_skip_llm"]["recipes"] == [
        {
            "recipe_id": "urn:recipe:test:fragmentary",
            "task_status": "handled_locally_skip_llm",
            "llm_dispatch": "handled_locally_skip_llm",
            "llm_dispatch_reason": "deterministic_terminal_scaffold",
            "repair_status": "fragmentary",
            "shard_id": "recipe-shard-0001-r0001-r0001",
            "status_reason": "insufficient_source_detail",
            "task_id": "recipe-shard-0001-r0001-r0001",
            "worker_id": "worker-001",
        }
    ]
    assert (
        promotion_report["recipe_results"]["urn:recipe:test:fragmentary"]["llm_dispatch"]
        == "handled_locally_skip_llm"
    )
    assert (
        recipe_manifest["counts"]["recipe_correction_handled_locally_skip_llm"] == 1
    )
    assert len(runner.calls) == 1
    assert runner.calls[0]["mode"] == "workspace_worker"


def test_recipe_phase_runtime_defaults_workers_to_shard_count_when_unspecified(
    tmp_path: Path,
) -> None:
    source = tmp_path / "book.txt"
    source.write_text("source", encoding="utf-8")
    settings = RunSettings.model_validate(
        {
            "llm_recipe_pipeline": "codex-recipe-shard-v1",
            "codex_farm_cmd": "codex-farm",
            "codex_farm_root": str(tmp_path / "pack"),
        }
    )
    for name in ("pipelines", "prompts", "schemas"):
        (tmp_path / "pack" / name).mkdir(parents=True, exist_ok=True)

    runner = FakeCodexExecRunner(output_builder=_build_recipe_shard_output)

    apply_result = run_codex_farm_recipe_pipeline(
        conversion_result=_build_multi_recipe_conversion_result(source),
        run_settings=settings,
        run_root=tmp_path / "run",
        workbook_slug="book",
        runner=runner,
    )

    phase_manifest = json.loads(
        (
            apply_result.llm_raw_dir / "recipe_phase_runtime" / "phase_manifest.json"
        ).read_text(encoding="utf-8")
    )

    assert phase_manifest["shard_count"] == 3
    assert phase_manifest["worker_count"] == 3


def test_recipe_phase_runtime_forwards_structured_progress(
    tmp_path: Path,
    monkeypatch,
) -> None:
    class _SlowFakeCodexExecRunner(FakeCodexExecRunner):
        def run_workspace_worker(self, *args, **kwargs):
            result = super().run_workspace_worker(*args, **kwargs)
            time.sleep(0.25)
            return result

    codex_home = str(tmp_path / "codex-home")
    monkeypatch.setenv("COOKIMPORT_CODEX_FARM_CODEX_HOME", codex_home)
    monkeypatch.setenv("CODEX_FARM_CODEX_HOME_RECIPE", codex_home)
    monkeypatch.setenv("CODEX_HOME", codex_home)
    source = tmp_path / "book.txt"
    source.write_text("source", encoding="utf-8")
    settings = RunSettings.model_validate(
        {
            "llm_recipe_pipeline": "codex-recipe-shard-v1",
            "codex_farm_cmd": "codex-farm",
            "codex_farm_root": str(tmp_path / "pack"),
            "recipe_prompt_target_count": 2,
            "recipe_worker_count": 2,
        }
    )
    for name in ("pipelines", "prompts", "schemas"):
        (tmp_path / "pack" / name).mkdir(parents=True, exist_ok=True)

    progress_messages: list[str] = []
    runner = _SlowFakeCodexExecRunner(output_builder=_build_recipe_shard_output)

    run_codex_farm_recipe_pipeline(
        conversion_result=_build_multi_recipe_conversion_result(source),
        run_settings=settings,
        run_root=tmp_path / "run",
        workbook_slug="book",
        runner=runner,
        progress_callback=progress_messages.append,
    )

    payloads = [
        payload
        for message in progress_messages
        for payload in [parse_stage_progress(message)]
        if payload is not None
    ]
    assert payloads
    assert payloads[0]["stage_label"] == "recipe pipeline"
    assert payloads[0]["work_unit_label"] == "recipe task"
    assert payloads[0]["task_total"] == 3
    assert payloads[0]["task_current"] == 0
    assert int(payloads[0]["worker_total"] or 0) >= 1
    assert int(payloads[0]["worker_running"] or 0) >= 1
    assert any(
        str(line) == "completed shards: 0/2"
        for line in (payloads[0].get("detail_lines") or [])
    )
    assert any(
        str(task).startswith("recipe-shard-0000-r0000-r0001.task-001")
        for task in (payloads[0].get("active_tasks") or [])
    )
    assert payloads[-1]["task_current"] == payloads[-1]["task_total"]
    assert any(payload.get("worker_completed") == 2 for payload in payloads)
    assert any(payload.get("followup_label") == "shard finalization" for payload in payloads)
    assert any(payload.get("followup_total") == 2 for payload in payloads)
    assert any(
        (payload.get("artifact_counts") or {}).get("repair_attempted") is not None
        for payload in payloads
    )


def test_recipe_phase_runtime_uses_configured_codex_home_for_sterile_exec_workspace(
    tmp_path: Path,
    monkeypatch,
) -> None:
    codex_home = tmp_path / "codex-home"
    monkeypatch.setenv("COOKIMPORT_CODEX_FARM_CODEX_HOME", str(codex_home))
    monkeypatch.setenv("CODEX_FARM_CODEX_HOME_RECIPE", str(codex_home))
    monkeypatch.setenv("CODEX_HOME", str(codex_home))

    source = tmp_path / "book.txt"
    source.write_text("source", encoding="utf-8")
    settings = RunSettings.model_validate(
        {
            "llm_recipe_pipeline": "codex-recipe-shard-v1",
            "codex_farm_cmd": "codex-farm",
            "codex_farm_root": str(tmp_path / "pack"),
            "recipe_prompt_target_count": 2,
            "recipe_worker_count": 1,
        }
    )
    for name in ("pipelines", "prompts", "schemas"):
        (tmp_path / "pack" / name).mkdir(parents=True, exist_ok=True)

    runner = FakeCodexExecRunner(output_builder=_build_recipe_shard_output)
    apply_result = run_codex_farm_recipe_pipeline(
        conversion_result=_build_multi_recipe_conversion_result(source),
        run_settings=settings,
        run_root=tmp_path / "run",
        workbook_slug="book",
        runner=runner,
    )

    assert len(runner.calls) == 1
    expected_prefix = str(codex_home / "recipeimport-direct-exec-workspaces")
    assert str(runner.calls[0]["execution_working_dir"]).startswith(expected_prefix)
    assert not (apply_result.llm_raw_dir / "recipe_phase_runtime" / ".codex-recipe").exists()


def test_recipe_prompt_target_count_balances_multi_recipe_shards(
    tmp_path: Path,
) -> None:
    source = tmp_path / "book.txt"
    source.write_text("source", encoding="utf-8")
    settings = RunSettings.model_validate(
        {
            "llm_recipe_pipeline": "codex-recipe-shard-v1",
            "codex_farm_cmd": "codex-farm",
            "codex_farm_root": str(tmp_path / "pack"),
            "recipe_prompt_target_count": 2,
        }
    )
    for name in ("pipelines", "prompts", "schemas"):
        (tmp_path / "pack" / name).mkdir(parents=True, exist_ok=True)

    apply_result = run_codex_farm_recipe_pipeline(
        conversion_result=_build_multi_recipe_conversion_result(source),
        run_settings=settings,
        run_root=tmp_path / "run",
        workbook_slug="book",
        runner=FakeCodexExecRunner(output_builder=_build_recipe_shard_output),
    )

    runtime_dir = apply_result.llm_raw_dir / "recipe_phase_runtime"
    phase_manifest = json.loads((runtime_dir / "phase_manifest.json").read_text(encoding="utf-8"))
    worker_assignments = json.loads(
        (runtime_dir / "worker_assignments.json").read_text(encoding="utf-8")
    )
    shard_manifest = [
        json.loads(line)
        for line in (runtime_dir / "shard_manifest.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]

    assert phase_manifest["shard_count"] == 2
    assert phase_manifest["worker_count"] == 2
    assert worker_assignments == [
        {
            "worker_id": "worker-001",
            "shard_ids": ["recipe-shard-0000-r0000-r0001"],
            "workspace_root": str(runtime_dir / "workers" / "worker-001"),
        },
        {
            "worker_id": "worker-002",
            "shard_ids": ["recipe-shard-0001-r0002-r0002"],
            "workspace_root": str(runtime_dir / "workers" / "worker-002"),
        },
    ]
    assert [len(shard["owned_ids"]) for shard in shard_manifest] == [2, 1]


def test_recipe_prompt_target_count_is_a_hard_cap(
    tmp_path: Path,
) -> None:
    source = tmp_path / "book.txt"
    source.write_text("source", encoding="utf-8")
    settings = RunSettings.model_validate(
        {
            "llm_recipe_pipeline": "codex-recipe-shard-v1",
            "codex_farm_cmd": "codex-farm",
            "codex_farm_root": str(tmp_path / "pack"),
            "recipe_prompt_target_count": 1,
        }
    )
    for name in ("pipelines", "prompts", "schemas"):
        (tmp_path / "pack" / name).mkdir(parents=True, exist_ok=True)

    apply_result = run_codex_farm_recipe_pipeline(
        conversion_result=_build_multi_recipe_conversion_result(source),
        run_settings=settings,
        run_root=tmp_path / "run",
        workbook_slug="book",
        runner=FakeCodexExecRunner(output_builder=_build_recipe_shard_output),
    )

    runtime_dir = apply_result.llm_raw_dir / "recipe_phase_runtime"
    phase_manifest = json.loads((runtime_dir / "phase_manifest.json").read_text(encoding="utf-8"))
    worker_assignments = json.loads(
        (runtime_dir / "worker_assignments.json").read_text(encoding="utf-8")
    )
    shard_manifest = [
        json.loads(line)
        for line in (runtime_dir / "shard_manifest.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]

    assert phase_manifest["shard_count"] == 1
    assert phase_manifest["worker_count"] == 1
    assert [assignment["shard_ids"] for assignment in worker_assignments] == [
        ["recipe-shard-0000-r0000-r0002"]
    ]
    assert [shard["owned_ids"] for shard in shard_manifest] == [
        [
            "urn:recipe:test:toast",
            "urn:recipe:test:tea",
            "urn:recipe:test:cereal",
        ]
    ]


def test_recipe_workspace_worker_with_valid_files_and_prose_final_message_stays_valid(
    tmp_path: Path,
) -> None:
    source = tmp_path / "book.txt"
    source.write_text("source", encoding="utf-8")
    settings = RunSettings.model_validate(
        {
            "llm_recipe_pipeline": "codex-recipe-shard-v1",
            "codex_farm_cmd": "codex-farm",
            "codex_farm_root": str(tmp_path / "pack"),
            "recipe_worker_count": 1,
        }
    )
    for name in ("pipelines", "prompts", "schemas"):
        (tmp_path / "pack" / name).mkdir(parents=True, exist_ok=True)

    runner = FakeCodexExecRunner(
        output_builder=_build_recipe_shard_output,
        workspace_final_message_text="Finished all assigned task files. Outputs are in out/.",
    )

    apply_result = run_codex_farm_recipe_pipeline(
        conversion_result=_build_multi_recipe_conversion_result(source),
        run_settings=settings,
        run_root=tmp_path / "run",
        workbook_slug="book",
        runner=runner,
    )

    telemetry = json.loads(
        (
            apply_result.llm_raw_dir / "recipe_phase_runtime" / "telemetry.json"
        ).read_text(encoding="utf-8")
    )
    rows = [
        row
        for row in telemetry["rows"]
        if row.get("worker_session_primary_row")
    ]

    assert rows
    assert rows[0]["prompt_input_mode"] == "workspace_worker"
    assert rows[0]["repair_task_count"] == 0
    assert rows[0]["final_agent_message_state"] == "informational"
    assert "informational only" in str(rows[0]["final_agent_message_reason"])
    assert telemetry["summary"]["structured_followup_call_count"] == 0
    assert telemetry["summary"]["workspace_worker_session_count"] == 1


def test_recipe_workspace_worker_with_valid_files_and_no_final_message_stays_valid(
    tmp_path: Path,
) -> None:
    source = tmp_path / "book.txt"
    source.write_text("source", encoding="utf-8")
    settings = RunSettings.model_validate(
        {
            "llm_recipe_pipeline": "codex-recipe-shard-v1",
            "codex_farm_cmd": "codex-farm",
            "codex_farm_root": str(tmp_path / "pack"),
            "recipe_worker_count": 1,
        }
    )
    for name in ("pipelines", "prompts", "schemas"):
        (tmp_path / "pack" / name).mkdir(parents=True, exist_ok=True)

    runner = _NoFinalWorkspaceMessageRunner(
        output_builder=_build_recipe_shard_output,
    )

    apply_result = run_codex_farm_recipe_pipeline(
        conversion_result=_build_multi_recipe_conversion_result(source),
        run_settings=settings,
        run_root=tmp_path / "run",
        workbook_slug="book",
        runner=runner,
    )

    telemetry = json.loads(
        (
            apply_result.llm_raw_dir / "recipe_phase_runtime" / "telemetry.json"
        ).read_text(encoding="utf-8")
    )
    rows = [
        row
        for row in telemetry["rows"]
        if row.get("worker_session_primary_row")
    ]

    assert rows
    assert rows[0]["prompt_input_mode"] == "workspace_worker"
    assert rows[0]["repair_task_count"] == 0
    assert rows[0]["final_agent_message_state"] == "absent"
    assert rows[0]["final_agent_message_reason"] is None
    assert telemetry["summary"]["structured_followup_call_count"] == 0
    assert telemetry["summary"]["workspace_worker_session_count"] == 1


def test_recipe_workspace_validation_rejects_legacy_results_shape() -> None:
    shard = recipe_module.ShardManifestEntryV1(  # noqa: SLF001
        shard_id="recipe-shard-0000-r0000-r0000.task-001",
        owned_ids=("urn:recipe:test:toast",),
        input_payload={
            "v": "1",
            "sid": "recipe-shard-0000-r0000-r0000.task-001",
            "r": [
                {
                    "rid": "urn:recipe:test:toast",
                    "h": {"n": "Toast", "i": ["1 slice bread"], "s": ["Toast the bread."]},
                }
            ],
        },
    )

    payload, validation_errors, validation_metadata, proposal_status = recipe_module._evaluate_recipe_response(  # noqa: SLF001
        shard=shard,
        response_text=json.dumps(_build_legacy_recipe_workspace_output(shard.input_payload)),
    )

    assert payload is None
    assert proposal_status == "invalid"
    assert validation_metadata["contract"] == "recipe.correction.compact.v1"
    assert any("legacy key `results`" in error for error in validation_errors)
    assert any("use `r`" in error for error in validation_errors)


def test_recipe_workspace_promotion_preserves_fragmentary_and_not_a_recipe_outputs(
    tmp_path: Path,
) -> None:
    source = tmp_path / "book.txt"
    source.write_text("source", encoding="utf-8")
    settings = RunSettings.model_validate(
        {
            "llm_recipe_pipeline": "codex-recipe-shard-v1",
            "codex_farm_cmd": "codex-farm",
            "codex_farm_root": str(tmp_path / "pack"),
            "recipe_worker_count": 1,
        }
    )
    for name in ("pipelines", "prompts", "schemas"):
        (tmp_path / "pack" / name).mkdir(parents=True, exist_ok=True)

    runner = FakeCodexExecRunner(
        output_builder=lambda payload: _build_recipe_workspace_output(
            payload,
            status_by_recipe_id={
                "urn:recipe:test:tea": "fragmentary",
                "urn:recipe:test:cereal": "not_a_recipe",
            },
        )
    )

    apply_result = run_codex_farm_recipe_pipeline(
        conversion_result=_build_multi_recipe_conversion_result(source),
        run_settings=settings,
        run_root=tmp_path / "run",
        workbook_slug="book",
        runner=runner,
    )

    manifest = json.loads(
        (apply_result.llm_raw_dir / "recipe_manifest.json").read_text(encoding="utf-8")
    )
    tea_proposal = json.loads(
        (
            apply_result.llm_raw_dir
            / "recipe_phase_runtime"
            / "proposals"
            / "recipe-shard-0001-r0001-r0001.json"
        ).read_text(encoding="utf-8")
    )
    cereal_proposal = json.loads(
        (
            apply_result.llm_raw_dir
            / "recipe_phase_runtime"
            / "proposals"
            / "recipe-shard-0002-r0002-r0002.json"
        ).read_text(encoding="utf-8")
    )

    assert sorted(apply_result.authoritative_recipe_payloads_by_recipe_id) == [
        "urn:recipe:test:toast"
    ]
    assert manifest["recipes"]["urn:recipe:test:tea"]["correction_output_status"] == "fragmentary"
    assert manifest["recipes"]["urn:recipe:test:cereal"]["correction_output_status"] == "not_a_recipe"
    assert tea_proposal["payload"]["r"][0]["rid"] == "urn:recipe:test:tea"
    assert tea_proposal["payload"]["r"][0]["st"] == "fragmentary"
    assert cereal_proposal["payload"]["r"][0]["rid"] == "urn:recipe:test:cereal"
    assert cereal_proposal["payload"]["r"][0]["st"] == "not_a_recipe"


def test_recipe_workspace_watchdog_allows_shell_work_until_command_loop(
    tmp_path: Path,
) -> None:
    callback = recipe_module._build_recipe_watchdog_callback(  # noqa: SLF001
        live_status_path=tmp_path / "live_status.json",
        watchdog_policy="workspace_worker_v1",
        stage_label="workspace worker stage",
        allow_workspace_commands=True,
    )
    decision = callback(
        CodexExecLiveSnapshot(
            elapsed_seconds=0.5,
            last_event_seconds_ago=0.0,
            event_count=14,
            command_execution_count=7,
            reasoning_item_count=0,
            last_command="/bin/bash -lc cat in/recipe-shard-0000-r0000-r0001.json",
            last_command_repeat_count=2,
            has_final_agent_message=False,
            timeout_seconds=30,
        )
    )

    assert decision is None
    live_status = json.loads((tmp_path / "live_status.json").read_text(encoding="utf-8"))
    assert live_status["last_command_policy"] == "tolerated_workspace_shell_command"
    assert live_status["last_command_policy_allowed"] is True
    assert live_status["last_command_boundary_violation_detected"] is False
