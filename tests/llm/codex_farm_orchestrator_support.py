from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Mapping

import pytest

from cookimport.cli_worker import execute_source_job
from cookimport.config.run_settings import RunSettings
from cookimport.core.models import (
    ConversionReport,
    ConversionResult,
    MappingConfig,
    RawArtifact,
    RecipeCandidate,
)
from cookimport.core.timing import TimingStats
from cookimport.llm import codex_farm_orchestrator as recipe_module
from cookimport.llm import codex_exec_runner as exec_runner_module
from cookimport.llm.codex_farm_orchestrator import (
    SINGLE_CORRECTION_RECIPE_PIPELINE_ID,
    SINGLE_CORRECTION_STAGE_PIPELINE_ID,
    _preflight_recipe_shard,
    build_codex_farm_recipe_execution_plan,
    run_codex_farm_recipe_pipeline,
)
from cookimport.llm.codex_exec_runner import (
    CodexExecLiveSnapshot,
    CodexExecRunResult,
    FakeCodexExecRunner,
)
from cookimport.llm.phase_worker_runtime import ShardManifestEntryV1
from cookimport.staging.draft_v1 import authoritative_recipe_semantics_to_draft_v1
from cookimport.staging.job_planning import JobSpec


def _write_workspace_task_file_result(
    runner: FakeCodexExecRunner,
    *,
    working_dir: Path,
    execution_working_dir: Path,
    payload: Mapping[str, object] | None = None,
) -> bool:
    task_file_path = execution_working_dir / "task.json"
    if not task_file_path.exists():
        return False
    task_file_payload = exec_runner_module.load_task_file(task_file_path)
    edited_task_file = (
        dict(payload)
        if isinstance(payload, Mapping)
        else runner._build_workspace_task_file_result(task_file_payload=task_file_payload)
    )
    exec_runner_module.write_task_file(path=task_file_path, payload=edited_task_file)
    exec_runner_module._sync_direct_exec_workspace_paths(  # noqa: SLF001
        source_working_dir=working_dir,
        execution_working_dir=execution_working_dir,
        relative_paths=("task.json",),
    )
    return True


def _blank_recipe_task_file_answers(
    *,
    task_file_payload: Mapping[str, object],
) -> dict[str, object]:
    edited = dict(task_file_payload)
    edited_units: list[dict[str, object]] = []
    for unit in task_file_payload.get("units") or []:
        if not isinstance(unit, dict):
            continue
        unit_payload = dict(unit)
        unit_payload["answer"] = {}
        edited_units.append(unit_payload)
    edited["units"] = edited_units
    return edited


def _build_conversion_result(source_path: Path) -> ConversionResult:
    return ConversionResult(
        recipes=[
            RecipeCandidate(
                name="Toast",
                identifier="urn:recipe:test:toast",
                recipeIngredient=["1 slice bread", "1 tablespoon butter"],
                recipeInstructions=[
                    "Toast the bread until golden.",
                    "Spread with butter and serve hot.",
                ],
                provenance={"location": {"start_block": 1, "end_block": 5}},
            )
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
                        {"index": 3, "text": "1 tablespoon butter"},
                        {"index": 4, "text": "Toast the bread until golden."},
                        {"index": 5, "text": "Spread with butter and serve hot."},
                    ],
                    "block_count": 6,
                },
                metadata={"artifact_type": "extracted_blocks"},
            )
        ],
        report=ConversionReport(),
        workbook=source_path.stem,
        workbookPath=str(source_path),
    )


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
                    "block_count": 14,
                },
                metadata={"artifact_type": "extracted_blocks"},
            )
        ],
        report=ConversionReport(),
        workbook=source_path.stem,
        workbookPath=str(source_path),
    )


def _build_run_settings(
    pack_root: Path,
    *,
    llm_recipe_pipeline: str,
    **overrides: object,
) -> RunSettings:
    for name in ("pipelines", "prompts", "schemas"):
        (pack_root / name).mkdir(parents=True, exist_ok=True)
    payload: dict[str, object] = {
        "llm_recipe_pipeline": llm_recipe_pipeline,
        "codex_farm_cmd": "codex-farm",
        "codex_farm_root": str(pack_root),
        "codex_farm_context_blocks": 3,
        "codex_farm_failure_mode": "fail",
        "codex_farm_recipe_mode": "extract",
    }
    payload.update(overrides)
    return RunSettings.model_validate(payload)


def _build_valid_recipe_task_output(task_payload: dict[str, object]) -> dict[str, object]:
    recipe_row = task_payload["r"][0]
    return {
        "v": "1",
        "sid": task_payload["sid"],
        "r": [
            {
                "v": "1",
                "rid": recipe_row["rid"],
                "st": "repaired",
                "sr": None,
                "cr": {
                    "t": recipe_row["h"]["n"],
                    "i": recipe_row["h"]["i"],
                    "s": recipe_row["h"]["s"],
                    "d": None,
                    "y": None,
                },
                "m": [],
                "mr": "unclear_alignment",
                "g": [],
                "w": [],
            }
        ],
    }


class _ValidRecipeWorkspaceRunner(FakeCodexExecRunner):
    def run_taskfile_worker(self, **kwargs) -> CodexExecRunResult:  # noqa: ANN003
        working_dir = Path(kwargs["working_dir"])
        process_env = exec_runner_module._merge_env(kwargs["env"])
        prepared = exec_runner_module.prepare_direct_exec_workspace(
            source_working_dir=working_dir,
            env=process_env,
            task_label=kwargs.get("workspace_task_label"),
            mode="taskfile",
        )
        execution_working_dir = prepared.execution_working_dir
        execution_prompt_text = exec_runner_module.rewrite_direct_exec_prompt_paths(
            prompt_text=kwargs["prompt_text"],
            source_working_dir=working_dir,
            execution_working_dir=execution_working_dir,
        )
        self.calls.append(
            {
                "mode": "taskfile",
                "prompt_text": execution_prompt_text,
                "input_payload": None,
                "working_dir": str(working_dir),
                "execution_working_dir": str(execution_working_dir),
                "output_schema_path": None,
                "model": kwargs.get("model"),
                "reasoning_effort": kwargs.get("reasoning_effort"),
                "timeout_seconds": kwargs.get("timeout_seconds"),
                "workspace_task_label": kwargs.get("workspace_task_label"),
            }
        )

        if not _write_workspace_task_file_result(
            self,
            working_dir=working_dir,
            execution_working_dir=execution_working_dir,
        ):
            out_dir = execution_working_dir / "out"
            out_dir.mkdir(parents=True, exist_ok=True)
            for task_row in exec_runner_module._read_workspace_manifest_rows(  # noqa: SLF001
                execution_working_dir=execution_working_dir
            ):
                if not isinstance(task_row, dict):
                    continue
                task_id = str(task_row.get("task_id") or task_row.get("shard_id") or "").strip()
                if not task_id:
                    continue
                input_path = execution_working_dir / "in" / f"{task_id}.json"
                if not input_path.exists():
                    continue
                input_payload = json.loads(input_path.read_text(encoding="utf-8"))
                output_payload = self.output_builder(input_payload)
                (out_dir / f"{task_id}.json").write_text(
                    json.dumps(output_payload, indent=2, sort_keys=True),
                    encoding="utf-8",
                )

        exec_runner_module._sync_direct_exec_workspace_paths(  # noqa: SLF001
            source_working_dir=working_dir,
            execution_working_dir=execution_working_dir,
            relative_paths=("in", "out", "scratch", "work", "repair"),
        )
        response_text = (
            str(self.workspace_final_message_text)
            if self.workspace_final_message_text is not None
            else json.dumps({"status": "worker_completed"}, indent=2, sort_keys=True)
        )
        usage = {
            "input_tokens": max(1, len(execution_prompt_text) // 4),
            "cached_input_tokens": 0,
            "output_tokens": max(1, len(response_text) // 4),
            "reasoning_tokens": 0,
        }
        events = (
            {"type": "thread.started"},
            {
                "type": "item.completed",
                "item": {"type": "agent_message", "text": response_text},
            },
            {"type": "turn.completed", "usage": usage},
        )
        return CodexExecRunResult(
            command=["codex", "exec"],
            subprocess_exit_code=0,
            output_schema_path=None,
            prompt_text=execution_prompt_text,
            response_text=response_text,
            turn_failed_message=None,
            events=events,
            usage=usage,
            stdout_text="\n".join(json.dumps(event) for event in events) + "\n",
            source_working_dir=str(working_dir),
            execution_working_dir=str(execution_working_dir),
            execution_agents_path=str(prepared.agents_path),
            duration_ms=1,
            started_at_utc="2026-01-01T00:00:00Z",
            finished_at_utc="2026-01-01T00:00:00Z",
            workspace_mode="taskfile",
            supervision_state="completed",
        )
