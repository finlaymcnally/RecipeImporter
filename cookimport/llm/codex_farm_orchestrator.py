from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from cookimport.config.run_settings import RunSettings
from cookimport.core.models import ConversionResult, RecipeCandidate, RecipeDraftV1

from .codex_farm_contracts import (
    BlockLite,
    Pass1RecipeChunkingInput,
    Pass1RecipeChunkingOutput,
    Pass2SchemaOrgInput,
    Pass2SchemaOrgOutput,
    Pass3FinalDraftInput,
    Pass3FinalDraftOutput,
    load_contract_json,
)
from .codex_farm_ids import bundle_filename, ensure_recipe_id, sanitize_for_filename
from .codex_farm_runner import (
    CodexFarmRunner,
    CodexFarmRunnerError,
    SubprocessCodexFarmRunner,
)

logger = logging.getLogger(__name__)

DEFAULT_PASS1_PIPELINE_ID = "recipe.chunking.v1"
DEFAULT_PASS2_PIPELINE_ID = "recipe.schemaorg.v1"
DEFAULT_PASS3_PIPELINE_ID = "recipe.final.v1"

# Backward-compatible exports used by tests/docs.
PASS1_PIPELINE_ID = DEFAULT_PASS1_PIPELINE_ID
PASS2_PIPELINE_ID = DEFAULT_PASS2_PIPELINE_ID
PASS3_PIPELINE_ID = DEFAULT_PASS3_PIPELINE_ID


def _effort_override_value(value: object | None) -> str | None:
    if value is None:
        return None
    resolved = getattr(value, "value", value)
    cleaned = str(resolved).strip()
    return cleaned or None


@dataclass
class CodexFarmApplyResult:
    updated_conversion_result: ConversionResult
    intermediate_overrides_by_recipe_id: dict[str, dict[str, Any]]
    final_overrides_by_recipe_id: dict[str, dict[str, Any]]
    llm_report: dict[str, Any]
    llm_raw_dir: Path


@dataclass
class _RecipeState:
    recipe: RecipeCandidate
    recipe_id: str
    bundle_name: str
    heuristic_start: int | None
    heuristic_end: int | None
    pass1_status: str = "pending"
    pass2_status: str = "pending"
    pass3_status: str = "pending"
    start_block_index: int | None = None
    end_block_index: int | None = None
    excluded_block_ids: set[str] = field(default_factory=set)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    canonical_text: str = ""
    pass2_output: Pass2SchemaOrgOutput | None = None


def run_codex_farm_recipe_pipeline(
    *,
    conversion_result: ConversionResult,
    run_settings: RunSettings,
    run_root: Path,
    workbook_slug: str,
    runner: CodexFarmRunner | None = None,
    full_blocks: list[dict[str, Any]] | None = None,
) -> CodexFarmApplyResult:
    if run_settings.llm_recipe_pipeline.value == "off":
        return CodexFarmApplyResult(
            updated_conversion_result=conversion_result,
            intermediate_overrides_by_recipe_id={},
            final_overrides_by_recipe_id={},
            llm_report={"enabled": False, "pipeline": "off"},
            llm_raw_dir=run_root / "raw" / "llm" / sanitize_for_filename(workbook_slug),
        )

    llm_raw_dir = run_root / "raw" / "llm" / sanitize_for_filename(workbook_slug)
    pass1_in_dir = llm_raw_dir / "pass1_chunking" / "in"
    pass1_out_dir = llm_raw_dir / "pass1_chunking" / "out"
    pass2_in_dir = llm_raw_dir / "pass2_schemaorg" / "in"
    pass2_out_dir = llm_raw_dir / "pass2_schemaorg" / "out"
    pass3_in_dir = llm_raw_dir / "pass3_final" / "in"
    pass3_out_dir = llm_raw_dir / "pass3_final" / "out"
    for path in (
        pass1_in_dir,
        pass1_out_dir,
        pass2_in_dir,
        pass2_out_dir,
        pass3_in_dir,
        pass3_out_dir,
    ):
        path.mkdir(parents=True, exist_ok=True)

    full_blocks_payload = _prepare_full_blocks(
        full_blocks if full_blocks is not None else _extract_full_blocks(conversion_result)
    )
    if not full_blocks_payload:
        raise CodexFarmRunnerError(
            "Cannot run codex-farm recipe pipeline: no full_text blocks available."
        )
    full_blocks_by_index = {int(block["index"]): block for block in full_blocks_payload}
    max_index = max(full_blocks_by_index)
    total_blocks = max_index + 1

    source_hash = _resolve_source_hash(conversion_result)
    states = _build_states(conversion_result, workbook_slug=workbook_slug)
    pipelines = _resolve_pipeline_ids(run_settings)
    if not states:
        llm_manifest = {
            "enabled": True,
            "pipeline": run_settings.llm_recipe_pipeline.value,
            "pipelines": dict(pipelines),
            "codex_farm_cmd": run_settings.codex_farm_cmd,
            "codex_farm_model": run_settings.codex_farm_model,
            "codex_farm_reasoning_effort": _effort_override_value(
                run_settings.codex_farm_reasoning_effort
            ),
            "codex_farm_root": run_settings.codex_farm_root,
            "codex_farm_workspace_root": run_settings.codex_farm_workspace_root,
            "codex_farm_context_blocks": run_settings.codex_farm_context_blocks,
            "codex_farm_failure_mode": run_settings.codex_farm_failure_mode.value,
            "counts": {
                "recipes_total": 0,
                "pass1_inputs": 0,
                "pass2_inputs": 0,
                "pass3_inputs": 0,
            },
            "timing": {"pass1_seconds": 0.0, "pass2_seconds": 0.0, "pass3_seconds": 0.0},
            "paths": _paths_payload(
                pass1_in_dir=pass1_in_dir,
                pass1_out_dir=pass1_out_dir,
                pass2_in_dir=pass2_in_dir,
                pass2_out_dir=pass2_out_dir,
                pass3_in_dir=pass3_in_dir,
                pass3_out_dir=pass3_out_dir,
                llm_manifest_path=llm_raw_dir / "llm_manifest.json",
            ),
            "recipes": {},
        }
        _write_json(llm_manifest, llm_raw_dir / "llm_manifest.json")
        return CodexFarmApplyResult(
            updated_conversion_result=conversion_result,
            intermediate_overrides_by_recipe_id={},
            final_overrides_by_recipe_id={},
            llm_report={
                "enabled": True,
                "pipeline": run_settings.llm_recipe_pipeline.value,
                "llmRawDir": str(llm_raw_dir),
                "counts": llm_manifest["counts"],
            },
            llm_raw_dir=llm_raw_dir,
        )

    pipeline_root = _resolve_pipeline_root(run_settings)
    workspace_root = _resolve_workspace_root(run_settings)
    env = {"CODEX_FARM_ROOT": str(pipeline_root)}
    codex_runner: CodexFarmRunner = runner or SubprocessCodexFarmRunner(
        cmd=run_settings.codex_farm_cmd
    )
    codex_model = run_settings.codex_farm_model
    codex_reasoning_effort = _effort_override_value(
        run_settings.codex_farm_reasoning_effort
    )

    pass_timing: dict[str, float] = {
        "pass1_seconds": 0.0,
        "pass2_seconds": 0.0,
        "pass3_seconds": 0.0,
    }
    intermediate_overrides: dict[str, dict[str, Any]] = {}
    final_overrides: dict[str, dict[str, Any]] = {}

    # Pass 1
    for state in states:
        pass1_input = Pass1RecipeChunkingInput(
            recipe_id=state.recipe_id,
            workbook_slug=workbook_slug,
            source_hash=source_hash,
            heuristic_start_block_index=state.heuristic_start,
            heuristic_end_block_index=state.heuristic_end,
            blocks_before=_block_lites_for_range(
                full_blocks_by_index,
                start=(state.heuristic_start or 0) - run_settings.codex_farm_context_blocks,
                end=state.heuristic_start or 0,
            ),
            blocks_candidate=_block_lites_for_range(
                full_blocks_by_index,
                start=state.heuristic_start,
                end=state.heuristic_end,
            ),
            blocks_after=_block_lites_for_range(
                full_blocks_by_index,
                start=state.heuristic_end,
                end=(
                    (state.heuristic_end or 0)
                    + run_settings.codex_farm_context_blocks
                ),
            ),
        )
        _write_json(
            pass1_input.model_dump(mode="json", by_alias=True),
            pass1_in_dir / state.bundle_name,
        )

    pass1_started = time.perf_counter()
    codex_runner.run_pipeline(
        pipelines["pass1"],
        pass1_in_dir,
        pass1_out_dir,
        env,
        root_dir=pipeline_root,
        workspace_root=workspace_root,
        model=codex_model,
        reasoning_effort=codex_reasoning_effort,
    )
    pass_timing["pass1_seconds"] = round(time.perf_counter() - pass1_started, 3)
    _consume_pass1_outputs(states, pass1_out_dir, total_blocks=total_blocks)
    _apply_pass1_midpoint_clamps(states, total_blocks=total_blocks)
    _apply_pass1_to_result(conversion_result, states)
    _recompute_non_recipe_blocks(
        conversion_result,
        states=states,
        full_blocks_by_index=full_blocks_by_index,
    )

    # Pass 2
    pass2_states = [state for state in states if state.pass1_status == "ok"]
    for state in pass2_states:
        block_indices = _included_indices_for_state(
            state,
            full_blocks_by_index=full_blocks_by_index,
        )
        included_blocks = [
            full_blocks_by_index[idx] for idx in block_indices if idx in full_blocks_by_index
        ]
        canonical_text = "\n".join(
            str(block.get("text") or "").strip() for block in included_blocks
        ).strip()
        state.canonical_text = canonical_text
        if not canonical_text:
            state.pass2_status = "error"
            state.errors.append("pass2 input empty after pass1 boundary/exclusion application.")
            continue
        pass2_input = Pass2SchemaOrgInput(
            recipe_id=state.recipe_id,
            workbook_slug=workbook_slug,
            source_hash=source_hash,
            canonical_text=canonical_text,
            blocks=[_to_block_lite(block) for block in included_blocks],
        )
        _write_json(
            pass2_input.model_dump(mode="json", by_alias=True),
            pass2_in_dir / state.bundle_name,
        )
    if any(path.suffix == ".json" for path in pass2_in_dir.iterdir()):
        pass2_started = time.perf_counter()
        codex_runner.run_pipeline(
            pipelines["pass2"],
            pass2_in_dir,
            pass2_out_dir,
            env,
            root_dir=pipeline_root,
            workspace_root=workspace_root,
            model=codex_model,
            reasoning_effort=codex_reasoning_effort,
        )
        pass_timing["pass2_seconds"] = round(time.perf_counter() - pass2_started, 3)
    for state in pass2_states:
        if state.pass2_status == "error":
            continue
        out_path = pass2_out_dir / state.bundle_name
        if not out_path.exists():
            state.pass2_status = "error"
            state.errors.append("missing pass2 output bundle.")
            continue
        try:
            output = load_contract_json(out_path, Pass2SchemaOrgOutput)
        except Exception as exc:  # noqa: BLE001
            state.pass2_status = "error"
            state.errors.append(f"invalid pass2 output: {exc}")
            continue
        state.pass2_output = output
        guard_warnings = _validate_pass2_guardrails(
            output=output,
            canonical_text=state.canonical_text,
        )
        state.warnings.extend(list(output.warnings))
        state.warnings.extend(guard_warnings)
        state.pass2_status = "ok"
        intermediate_overrides[state.recipe_id] = dict(output.schemaorg_recipe)

    # Pass 3
    pass3_states = [state for state in states if state.pass2_status == "ok" and state.pass2_output]
    for state in pass3_states:
        assert state.pass2_output is not None
        pass3_input = Pass3FinalDraftInput(
            recipe_id=state.recipe_id,
            workbook_slug=workbook_slug,
            source_hash=source_hash,
            schemaorg_recipe=state.pass2_output.schemaorg_recipe,
            extracted_ingredients=list(state.pass2_output.extracted_ingredients),
            extracted_instructions=list(state.pass2_output.extracted_instructions),
        )
        _write_json(
            pass3_input.model_dump(mode="json", by_alias=True),
            pass3_in_dir / state.bundle_name,
        )
    if any(path.suffix == ".json" for path in pass3_in_dir.iterdir()):
        pass3_started = time.perf_counter()
        codex_runner.run_pipeline(
            pipelines["pass3"],
            pass3_in_dir,
            pass3_out_dir,
            env,
            root_dir=pipeline_root,
            workspace_root=workspace_root,
            model=codex_model,
            reasoning_effort=codex_reasoning_effort,
        )
        pass_timing["pass3_seconds"] = round(time.perf_counter() - pass3_started, 3)
    for state in pass3_states:
        out_path = pass3_out_dir / state.bundle_name
        if not out_path.exists():
            state.pass3_status = "error"
            state.errors.append("missing pass3 output bundle.")
            continue
        try:
            output = load_contract_json(out_path, Pass3FinalDraftOutput)
        except Exception as exc:  # noqa: BLE001
            state.pass3_status = "error"
            state.errors.append(f"invalid pass3 output: {exc}")
            continue
        draft_payload = _normalize_draft_payload(dict(output.draft_v1))
        if _patch_recipe_id(draft_payload, recipe_id=state.recipe_id):
            state.warnings.append("pass3 draft id patched to expected recipe_id.")
        try:
            draft_model = RecipeDraftV1.model_validate(draft_payload)
        except Exception as exc:  # noqa: BLE001
            state.pass3_status = "error"
            state.errors.append(f"pass3 draft_v1 validation failed: {exc}")
            continue
        state.warnings.extend(list(output.warnings))
        state.pass3_status = "ok"
        final_overrides[state.recipe_id] = draft_model.model_dump(
            mode="json",
            by_alias=True,
            exclude_none=True,
        )

    llm_manifest_path = llm_raw_dir / "llm_manifest.json"
    llm_manifest = _build_llm_manifest(
        run_settings=run_settings,
        llm_raw_dir=llm_raw_dir,
        states=states,
        pass_timing=pass_timing,
        pass1_in_dir=pass1_in_dir,
        pass1_out_dir=pass1_out_dir,
        pass2_in_dir=pass2_in_dir,
        pass2_out_dir=pass2_out_dir,
        pass3_in_dir=pass3_in_dir,
        pass3_out_dir=pass3_out_dir,
        llm_manifest_path=llm_manifest_path,
        pipelines=pipelines,
    )
    _write_json(llm_manifest, llm_manifest_path)

    llm_report = {
        "enabled": True,
        "pipeline": run_settings.llm_recipe_pipeline.value,
        "pipelines": dict(pipelines),
        "llmRawDir": str(llm_raw_dir),
        "counts": llm_manifest["counts"],
        "timing": llm_manifest["timing"],
        "failures": llm_manifest["failures"],
    }

    return CodexFarmApplyResult(
        updated_conversion_result=conversion_result,
        intermediate_overrides_by_recipe_id=intermediate_overrides,
        final_overrides_by_recipe_id=final_overrides,
        llm_report=llm_report,
        llm_raw_dir=llm_raw_dir,
    )


def _paths_payload(
    *,
    pass1_in_dir: Path,
    pass1_out_dir: Path,
    pass2_in_dir: Path,
    pass2_out_dir: Path,
    pass3_in_dir: Path,
    pass3_out_dir: Path,
    llm_manifest_path: Path,
) -> dict[str, str]:
    return {
        "pass1_in": str(pass1_in_dir),
        "pass1_out": str(pass1_out_dir),
        "pass2_in": str(pass2_in_dir),
        "pass2_out": str(pass2_out_dir),
        "pass3_in": str(pass3_in_dir),
        "pass3_out": str(pass3_out_dir),
        "llm_manifest": str(llm_manifest_path),
    }


def _build_llm_manifest(
    *,
    run_settings: RunSettings,
    llm_raw_dir: Path,
    states: list[_RecipeState],
    pass_timing: dict[str, float],
    pass1_in_dir: Path,
    pass1_out_dir: Path,
    pass2_in_dir: Path,
    pass2_out_dir: Path,
    pass3_in_dir: Path,
    pass3_out_dir: Path,
    llm_manifest_path: Path,
    pipelines: dict[str, str],
) -> dict[str, Any]:
    recipe_rows: dict[str, dict[str, Any]] = {}
    failures: list[dict[str, Any]] = []
    for state in states:
        row = {
            "pass1": state.pass1_status,
            "pass2": state.pass2_status,
            "pass3": state.pass3_status,
            "warnings": list(state.warnings),
            "errors": list(state.errors),
        }
        recipe_rows[state.recipe_id] = row
        if state.errors:
            failures.append({"recipe_id": state.recipe_id, "errors": list(state.errors)})
    counts = {
        "recipes_total": len(states),
        "pass1_inputs": len(list(pass1_in_dir.glob("*.json"))),
        "pass1_ok": sum(1 for state in states if state.pass1_status == "ok"),
        "pass1_dropped": sum(1 for state in states if state.pass1_status == "dropped"),
        "pass1_errors": sum(1 for state in states if state.pass1_status == "error"),
        "pass2_inputs": len(list(pass2_in_dir.glob("*.json"))),
        "pass2_ok": sum(1 for state in states if state.pass2_status == "ok"),
        "pass2_errors": sum(1 for state in states if state.pass2_status == "error"),
        "pass3_inputs": len(list(pass3_in_dir.glob("*.json"))),
        "pass3_ok": sum(1 for state in states if state.pass3_status == "ok"),
        "pass3_errors": sum(1 for state in states if state.pass3_status == "error"),
    }
    return {
        "enabled": True,
        "pipeline": run_settings.llm_recipe_pipeline.value,
        "codex_farm_cmd": run_settings.codex_farm_cmd,
        "codex_farm_model": run_settings.codex_farm_model,
        "codex_farm_reasoning_effort": _effort_override_value(
            run_settings.codex_farm_reasoning_effort
        ),
        "codex_farm_root": run_settings.codex_farm_root,
        "codex_farm_workspace_root": run_settings.codex_farm_workspace_root,
        "codex_farm_context_blocks": run_settings.codex_farm_context_blocks,
        "codex_farm_failure_mode": run_settings.codex_farm_failure_mode.value,
        "pipelines": dict(pipelines),
        "counts": counts,
        "timing": pass_timing,
        "paths": _paths_payload(
            pass1_in_dir=pass1_in_dir,
            pass1_out_dir=pass1_out_dir,
            pass2_in_dir=pass2_in_dir,
            pass2_out_dir=pass2_out_dir,
            pass3_in_dir=pass3_in_dir,
            pass3_out_dir=pass3_out_dir,
            llm_manifest_path=llm_manifest_path,
        ),
        "failures": failures,
        "recipes": recipe_rows,
        "llm_raw_dir": str(llm_raw_dir),
    }


def _write_json(payload: Any, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True),
        encoding="utf-8",
    )


def _resolve_pipeline_root(run_settings: RunSettings) -> Path:
    if run_settings.codex_farm_root:
        root = Path(run_settings.codex_farm_root).expanduser()
    else:
        root = Path(__file__).resolve().parents[2] / "llm_pipelines"
    required = ("pipelines", "prompts", "schemas")
    missing = [name for name in required if not (root / name).exists()]
    if missing:
        raise CodexFarmRunnerError(
            "Invalid codex-farm pipeline root "
            f"{root}: missing {', '.join(missing)}."
        )
    return root


def _resolve_workspace_root(run_settings: RunSettings) -> Path | None:
    value = run_settings.codex_farm_workspace_root
    if not value:
        return None
    root = Path(value).expanduser()
    if not root.exists() or not root.is_dir():
        raise CodexFarmRunnerError(
            "Invalid codex-farm workspace root "
            f"{root}: path does not exist or is not a directory."
        )
    return root


def _resolve_pipeline_ids(run_settings: RunSettings) -> dict[str, str]:
    return {
        "pass1": _non_empty(
            run_settings.codex_farm_pipeline_pass1,
            fallback=DEFAULT_PASS1_PIPELINE_ID,
        ),
        "pass2": _non_empty(
            run_settings.codex_farm_pipeline_pass2,
            fallback=DEFAULT_PASS2_PIPELINE_ID,
        ),
        "pass3": _non_empty(
            run_settings.codex_farm_pipeline_pass3,
            fallback=DEFAULT_PASS3_PIPELINE_ID,
        ),
    }


def _non_empty(value: Any, *, fallback: str) -> str:
    rendered = str(value).strip() if value is not None else ""
    return rendered or fallback


def _resolve_source_hash(result: ConversionResult) -> str:
    for artifact in result.raw_artifacts:
        if artifact.source_hash:
            return str(artifact.source_hash)
    for recipe in result.recipes:
        provenance = recipe.provenance if isinstance(recipe.provenance, dict) else {}
        source_hash = provenance.get("file_hash") or provenance.get("fileHash")
        if source_hash:
            return str(source_hash)
    return "unknown"


def _coerce_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _recipe_location(recipe: RecipeCandidate) -> dict[str, Any]:
    provenance = recipe.provenance if isinstance(recipe.provenance, dict) else {}
    location = provenance.get("location")
    if not isinstance(location, dict):
        location = {}
        provenance["location"] = location
        recipe.provenance = provenance
    return location


def _build_states(
    result: ConversionResult,
    *,
    workbook_slug: str,
) -> list[_RecipeState]:
    states: list[_RecipeState] = []
    for index, recipe in enumerate(result.recipes):
        provenance = recipe.provenance if isinstance(recipe.provenance, dict) else {}
        recipe_id = ensure_recipe_id(
            recipe.identifier or provenance.get("@id") or provenance.get("id"),
            workbook_slug=workbook_slug,
            recipe_index=index,
        )
        recipe.identifier = recipe_id
        if not isinstance(recipe.provenance, dict):
            recipe.provenance = {}
        recipe.provenance["@id"] = recipe_id
        if "id" in recipe.provenance:
            recipe.provenance["id"] = recipe_id
        location = _recipe_location(recipe)
        start_raw = (
            location.get("start_block")
            if "start_block" in location
            else location.get("startBlock")
        )
        end_raw = (
            location.get("end_block")
            if "end_block" in location
            else location.get("endBlock")
        )
        heuristic_start = _coerce_int(start_raw)
        heuristic_end = _coerce_int(end_raw)
        states.append(
            _RecipeState(
                recipe=recipe,
                recipe_id=recipe_id,
                bundle_name=bundle_filename(recipe_id, recipe_index=index),
                heuristic_start=heuristic_start,
                heuristic_end=heuristic_end,
            )
        )
    return states


def _extract_full_blocks(result: ConversionResult) -> list[dict[str, Any]]:
    by_index: dict[int, dict[str, Any]] = {}
    artifacts = sorted(
        result.raw_artifacts,
        key=lambda item: 0 if str(item.location_id) == "full_text" else 1,
    )
    for artifact in artifacts:
        content = artifact.content
        if not isinstance(content, dict):
            continue
        blocks = content.get("blocks")
        if not isinstance(blocks, list):
            continue
        for raw_block in blocks:
            if not isinstance(raw_block, dict):
                continue
            index = _coerce_int(raw_block.get("index"))
            if index is None:
                continue
            if index in by_index:
                continue
            by_index[index] = dict(raw_block)
    return [by_index[index] for index in sorted(by_index)]


def _prepare_full_blocks(blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    prepared: list[dict[str, Any]] = []
    for block in blocks:
        if not isinstance(block, dict):
            continue
        index = _coerce_int(block.get("index"))
        if index is None:
            continue
        payload = dict(block)
        payload["index"] = index
        block_id = payload.get("block_id") or payload.get("id")
        if not isinstance(block_id, str) or not block_id.strip():
            block_id = f"b{index}"
        payload["block_id"] = block_id.strip()
        prepared.append(payload)
    prepared.sort(key=lambda item: int(item["index"]))
    return prepared


def _to_block_lite(block: dict[str, Any]) -> BlockLite:
    features = block.get("features")
    if not isinstance(features, dict):
        features = {}
    page = _coerce_int(block.get("page"))
    spine_index = _coerce_int(block.get("spine_index"))
    if spine_index is None:
        spine_index = _coerce_int(features.get("spine_index"))
    heading_level = _coerce_int(block.get("heading_level"))
    if heading_level is None:
        heading_level = _coerce_int(features.get("heading_level"))
    return BlockLite(
        index=int(block["index"]),
        block_id=str(block.get("block_id") or f"b{int(block['index'])}"),
        text=str(block.get("text") or ""),
        page=page,
        spine_index=spine_index,
        heading_level=heading_level,
    )


def _block_lites_for_range(
    blocks_by_index: dict[int, dict[str, Any]],
    *,
    start: int | None,
    end: int | None,
) -> list[BlockLite]:
    start_value = _coerce_int(start)
    end_value = _coerce_int(end)
    if start_value is None or end_value is None:
        return []
    lo = min(start_value, end_value)
    hi = max(start_value, end_value)
    result: list[BlockLite] = []
    for idx in range(lo, hi):
        block = blocks_by_index.get(idx)
        if block is None:
            continue
        result.append(_to_block_lite(block))
    return result


def _consume_pass1_outputs(
    states: list[_RecipeState],
    pass1_out_dir: Path,
    *,
    total_blocks: int,
) -> None:
    for state in states:
        out_path = pass1_out_dir / state.bundle_name
        if not out_path.exists():
            state.pass1_status = "error"
            state.errors.append("missing pass1 output bundle.")
            continue
        try:
            output = load_contract_json(out_path, Pass1RecipeChunkingOutput)
        except Exception as exc:  # noqa: BLE001
            state.pass1_status = "error"
            state.errors.append(f"invalid pass1 output: {exc}")
            continue
        if not output.is_recipe:
            state.pass1_status = "dropped"
            state.start_block_index = None
            state.end_block_index = None
            continue
        start = _coerce_int(output.start_block_index)
        end = _coerce_int(output.end_block_index)
        if start is None or end is None:
            state.pass1_status = "error"
            state.errors.append("pass1 returned null start/end for accepted recipe.")
            continue
        start = max(0, min(start, max(total_blocks - 1, 0)))
        end = max(start + 1, min(end, total_blocks))
        state.start_block_index = start
        state.end_block_index = end
        state.excluded_block_ids = {
            str(block_id)
            for block_id in output.excluded_block_ids
            if isinstance(block_id, str) and block_id.strip()
        }
        if isinstance(output.title, str) and output.title.strip():
            state.recipe.name = output.title.strip()
        state.pass1_status = "ok"


def _apply_pass1_midpoint_clamps(states: list[_RecipeState], *, total_blocks: int) -> None:
    active = [state for state in states if state.pass1_status == "ok"]
    if not active:
        return
    active.sort(key=lambda state: state.heuristic_start if state.heuristic_start is not None else 0)
    heuristic_points = [
        state.heuristic_start
        if state.heuristic_start is not None
        else (state.start_block_index or 0)
        for state in active
    ]

    previous_end = 0
    for index, state in enumerate(active):
        start = state.start_block_index or 0
        end = state.end_block_index or (start + 1)
        left_bound = (
            0
            if index == 0
            else (heuristic_points[index - 1] + heuristic_points[index]) // 2
        )
        right_bound = (
            total_blocks
            if index == (len(active) - 1)
            else max(
                left_bound + 1,
                (heuristic_points[index] + heuristic_points[index + 1] + 1) // 2,
            )
        )
        adjusted_start = max(start, left_bound, previous_end)
        adjusted_end = min(end, right_bound)
        if adjusted_end <= adjusted_start:
            adjusted_end = min(total_blocks, adjusted_start + 1)
        if adjusted_start != start or adjusted_end != end:
            state.warnings.append(
                "pass1 boundaries clamped to prevent overlap/cross-midpoint drift."
            )
        state.start_block_index = adjusted_start
        state.end_block_index = adjusted_end
        previous_end = adjusted_end


def _apply_pass1_to_result(result: ConversionResult, states: list[_RecipeState]) -> None:
    kept_states = [state for state in states if state.pass1_status != "dropped"]
    kept_states.sort(key=_state_sort_key)
    for state in kept_states:
        if state.pass1_status != "ok":
            continue
        location = _recipe_location(state.recipe)
        location["start_block"] = state.start_block_index
        location["end_block"] = state.end_block_index
        if "startBlock" in location:
            location["startBlock"] = state.start_block_index
        if "endBlock" in location:
            location["endBlock"] = state.end_block_index
    result.recipes = [state.recipe for state in kept_states]


def _state_sort_key(state: _RecipeState) -> tuple[int, int]:
    if state.start_block_index is not None:
        return (0, state.start_block_index)
    if state.heuristic_start is not None:
        return (1, state.heuristic_start)
    return (2, 0)


def _recompute_non_recipe_blocks(
    result: ConversionResult,
    *,
    states: list[_RecipeState],
    full_blocks_by_index: dict[int, dict[str, Any]],
) -> None:
    if not full_blocks_by_index:
        return
    max_index = max(full_blocks_by_index)
    mask = [False] * (max_index + 1)
    block_id_to_index = {
        str(block.get("block_id")): int(block["index"])
        for block in full_blocks_by_index.values()
        if isinstance(block.get("block_id"), str)
    }

    for state in states:
        if state.pass1_status == "dropped":
            continue
        start = state.start_block_index
        end = state.end_block_index
        if start is None or end is None:
            start = state.heuristic_start
            end = state.heuristic_end
        if start is None or end is None:
            continue
        lo = max(0, min(int(start), max_index))
        hi = max(lo + 1, min(int(end), max_index + 1))
        for idx in range(lo, hi):
            mask[idx] = True
        for block_id in state.excluded_block_ids:
            block_index = block_id_to_index.get(block_id)
            if block_index is None:
                continue
            if 0 <= block_index < len(mask):
                mask[block_index] = False

    non_recipe_blocks: list[dict[str, Any]] = []
    for idx in range(len(mask)):
        block = full_blocks_by_index.get(idx)
        if block is None:
            continue
        if mask[idx]:
            continue
        non_recipe_blocks.append(dict(block))
    result.non_recipe_blocks = non_recipe_blocks


def _included_indices_for_state(
    state: _RecipeState,
    *,
    full_blocks_by_index: dict[int, dict[str, Any]],
) -> list[int]:
    start = state.start_block_index
    end = state.end_block_index
    if start is None or end is None:
        return []
    indices: list[int] = []
    for idx in range(int(start), int(end)):
        block = full_blocks_by_index.get(idx, {})
        block_id = str(block.get("block_id") or f"b{idx}")
        if block_id in state.excluded_block_ids:
            continue
        indices.append(idx)
    return indices


def _normalize_for_match(value: str) -> str:
    return " ".join(value.casefold().split())


def _validate_pass2_guardrails(
    *,
    output: Pass2SchemaOrgOutput,
    canonical_text: str,
) -> list[str]:
    warnings: list[str] = []
    canonical = _normalize_for_match(canonical_text)
    for index, ingredient in enumerate(output.extracted_ingredients):
        target = _normalize_for_match(str(ingredient))
        if target and target not in canonical:
            warnings.append(
                f"pass2 ingredient[{index}] not found in canonical_text: {ingredient!r}"
            )
    for index, instruction in enumerate(output.extracted_instructions):
        target = _normalize_for_match(str(instruction))
        if target and target not in canonical:
            warnings.append(
                f"pass2 instruction[{index}] not found in canonical_text: {instruction!r}"
            )
    return warnings


def _normalize_draft_payload(payload: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(payload)
    source = normalized.get("source")
    if isinstance(source, str):
        source = source.strip() or None
    else:
        source = None if source is None else str(source)
    normalized["source"] = source

    recipe_payload = normalized.get("recipe")
    if not isinstance(recipe_payload, dict):
        recipe_payload = {}
    title = recipe_payload.get("title")
    if not isinstance(title, str) or not title.strip():
        recipe_payload["title"] = "Untitled Recipe"
    normalized["recipe"] = recipe_payload

    steps_payload = normalized.get("steps")
    normalized_steps: list[dict[str, Any]] = []
    if isinstance(steps_payload, list):
        for step in steps_payload:
            if not isinstance(step, dict):
                continue
            instruction = step.get("instruction")
            if not isinstance(instruction, str) or not instruction.strip():
                instruction = "See original recipe for details."
            ingredient_lines = step.get("ingredient_lines")
            if not isinstance(ingredient_lines, list):
                ingredient_lines = []
            normalized_steps.append(
                {
                    **step,
                    "instruction": instruction.strip(),
                    "ingredient_lines": ingredient_lines,
                }
            )
    if not normalized_steps:
        normalized_steps = [
            {
                "instruction": "See original recipe for details.",
                "ingredient_lines": [],
            }
        ]
    normalized["steps"] = normalized_steps
    return normalized


def _patch_recipe_id(payload: dict[str, Any], *, recipe_id: str) -> bool:
    patched = False
    existing = payload.get("id")
    if isinstance(existing, str) and existing.strip() and existing.strip() != recipe_id:
        payload["id"] = recipe_id
        patched = True

    recipe_payload = payload.get("recipe")
    if isinstance(recipe_payload, dict):
        recipe_id_value = recipe_payload.get("id")
        if (
            isinstance(recipe_id_value, str)
            and recipe_id_value.strip()
            and recipe_id_value.strip() != recipe_id
        ):
            recipe_payload["id"] = recipe_id
            patched = True
    return patched
