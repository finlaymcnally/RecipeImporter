from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from cookimport.runs.stage_observability import stage_label

from .artifact_paths import _resolve_prediction_run_dir
from .io import _coerce_int, _load_json


def _safe_read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _parse_json_text(raw_text: str) -> Any | None:
    text = str(raw_text or "").strip()
    if not text:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


def _mtime_utc(path: Path | None) -> str | None:
    if path is None or not path.exists() or not path.is_file():
        return None
    try:
        stamp = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
    except OSError:
        return None
    return stamp.strftime("%Y-%m-%dT%H:%M:%SZ")


def _load_run_assets_payload(run_id: str) -> dict[str, Any]:
    if not run_id:
        return {}
    run_assets_dir = Path("var") / "run_assets" / run_id
    if not run_assets_dir.exists() or not run_assets_dir.is_dir():
        return {"run_id": run_id}

    def _safe_load_json_dict(path: Path) -> dict[str, Any] | None:
        if not path.is_file():
            return None
        try:
            return _load_json(path)
        except Exception:
            return None

    return {
        "run_id": run_id,
        "prompt_template_text": _safe_read_text(run_assets_dir / "prompt.template.txt"),
        "output_schema_payload": _safe_load_json_dict(run_assets_dir / "output.schema.json"),
        "effective_pipeline_payload": _safe_load_json_dict(
            run_assets_dir / "effective_pipeline.json"
        ),
        "manifest_payload": _safe_load_json_dict(run_assets_dir / "manifest.json"),
    }


def _render_prompt(template_text: str | None, input_text: str, input_file: Path) -> str:
    template = str(template_text or "")
    if not template.strip():
        return input_text
    rendered = template.replace("{{INPUT_TEXT}}", input_text)
    rendered = rendered.replace("{{ INPUT_TEXT }}", input_text)
    rendered = rendered.replace("{{INPUT_PATH}}", str(input_file))
    rendered = rendered.replace("{{ INPUT_PATH }}", str(input_file))
    return rendered


def _collect_context_blocks(parsed_input: Any) -> list[dict[str, Any]]:
    if not isinstance(parsed_input, dict):
        return []
    rows: list[dict[str, Any]] = []
    for key in ("rows_before", "rows_candidate", "rows_after", "rows"):
        blocks = parsed_input.get(key)
        if not isinstance(blocks, list):
            continue
        for block in blocks:
            if not isinstance(block, dict):
                continue
            rows.append(
                {
                    "source_key": key,
                    "block_id": block.get("block_id"),
                    "index": block.get("index"),
                    "text": block.get("text"),
                }
            )
    evidence_rows = parsed_input.get("evidence_rows")
    if isinstance(evidence_rows, list):
        for fallback_index, row in enumerate(evidence_rows):
            if not isinstance(row, (list, tuple)) or len(row) < 2:
                continue
            index = _coerce_int(row[0])
            if index is None:
                index = fallback_index
            rows.append(
                {
                    "source_key": "evidence_rows",
                    "block_id": None,
                    "index": int(index),
                    "text": str(row[1] or ""),
                }
            )
    return rows


def _reconstruct_full_prompt_log(
    *,
    run_dir: Path,
    run_manifest: dict[str, Any],
    output_path: Path,
    llm_stage_map: dict[str, dict[str, Any]],
) -> int:
    pred_run_dir = _resolve_prediction_run_dir(run_dir, run_manifest)
    if pred_run_dir is None:
        return 0
    raw_llm_dir = pred_run_dir / "raw" / "llm"
    if not raw_llm_dir.exists() or not raw_llm_dir.is_dir():
        return 0

    pred_manifest_path = pred_run_dir / "manifest.json"
    pred_manifest = _load_json(pred_manifest_path) if pred_manifest_path.is_file() else {}
    llm_payload = pred_manifest.get("llm_codex_farm") if isinstance(pred_manifest, dict) else {}
    process_runs = llm_payload.get("process_runs") if isinstance(llm_payload, dict) else {}
    knowledge_payload = llm_payload.get("knowledge") if isinstance(llm_payload, dict) else {}
    knowledge_payload = knowledge_payload if isinstance(knowledge_payload, dict) else {}
    source_payload = (
        run_manifest.get("source") if isinstance(run_manifest.get("source"), dict) else {}
    )
    source_file = source_payload.get("path") if isinstance(source_payload, dict) else None
    source_file = str(source_file).strip() if isinstance(source_file, str) else None

    rows_written = 0
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as handle:
        run_dirs = sorted(path for path in raw_llm_dir.iterdir() if path.is_dir())
        for llm_run_dir in run_dirs:
            for stage_key, stage_meta in sorted(
                llm_stage_map.items(),
                key=lambda item: (
                    int(item[1].get("sort_order") or 999),
                    str(item[0]),
                ),
            ):
                stage_dir = str(stage_meta.get("artifact_stem") or "").strip()
                if not stage_dir:
                    continue
                stage_in_dir = llm_run_dir / stage_dir / "in"
                stage_out_dir = llm_run_dir / stage_dir / "out"
                input_files = (
                    sorted(path for path in stage_in_dir.iterdir() if path.is_file())
                    if stage_in_dir.exists()
                    else []
                )
                output_files = (
                    sorted(path for path in stage_out_dir.iterdir() if path.is_file())
                    if stage_out_dir.exists()
                    else []
                )
                if not input_files and not output_files:
                    continue
                input_by_name = {path.name: path for path in input_files}
                output_by_name = {path.name: path for path in output_files}
                if stage_key == "nonrecipe_finalize":
                    pass_process_payload = (
                        knowledge_payload.get("process_run")
                        if isinstance(knowledge_payload.get("process_run"), dict)
                        else None
                    )
                elif stage_key == "recipe_refine":
                    pass_process_payload = (
                        process_runs.get("recipe_correction")
                        if isinstance(process_runs, dict)
                        else None
                    )
                else:
                    pass_process_payload = None
                pass_run_id = None
                if isinstance(pass_process_payload, dict):
                    pass_run_id = str(pass_process_payload.get("run_id") or "").strip() or None
                run_assets = _load_run_assets_payload(pass_run_id or "")
                prompt_template_text = (
                    run_assets.get("prompt_template_text")
                    if isinstance(run_assets, dict)
                    else None
                )
                output_schema_payload = (
                    run_assets.get("output_schema_payload")
                    if isinstance(run_assets, dict)
                    else None
                )
                effective_pipeline_payload = (
                    run_assets.get("effective_pipeline_payload")
                    if isinstance(run_assets, dict)
                    else None
                )
                model_value = None
                if isinstance(effective_pipeline_payload, dict):
                    model_raw = effective_pipeline_payload.get("codex_model")
                    if isinstance(model_raw, str) and model_raw.strip():
                        model_value = model_raw.strip()

                for file_name in sorted(set(input_by_name) | set(output_by_name)):
                    input_file = input_by_name.get(file_name)
                    output_file = output_by_name.get(file_name)
                    input_text = _safe_read_text(input_file) if input_file is not None else ""
                    output_text = _safe_read_text(output_file) if output_file is not None else ""
                    parsed_input = _parse_json_text(input_text)
                    parsed_output = _parse_json_text(output_text)
                    timestamp_utc = _mtime_utc(output_file) or _mtime_utc(input_file)
                    call_id = (
                        input_file.stem
                        if input_file is not None
                        else (output_file.stem if output_file is not None else Path(file_name).stem)
                    )
                    recipe_id = None
                    if isinstance(parsed_input, dict):
                        recipe_id = str(parsed_input.get("recipe_id") or "").strip() or None
                    if recipe_id is None and isinstance(parsed_output, dict):
                        recipe_id = str(parsed_output.get("recipe_id") or "").strip() or None
                    if recipe_id is None and stage_key == "nonrecipe_finalize":
                        chunk_id = None
                        if isinstance(parsed_input, dict):
                            chunk_id = str(parsed_input.get("chunk_id") or "").strip() or None
                        if chunk_id is None and isinstance(parsed_output, dict):
                            chunk_id = str(parsed_output.get("chunk_id") or "").strip() or None
                        recipe_id = chunk_id
                    rendered_prompt = _render_prompt(
                        prompt_template_text,
                        input_text,
                        input_file or (stage_in_dir / file_name),
                    )
                    request_messages = [{"role": "user", "content": rendered_prompt}]
                    response_format = (
                        {
                            "type": "json_schema",
                            "json_schema": output_schema_payload,
                        }
                        if isinstance(output_schema_payload, dict)
                        else None
                    )
                    row = {
                        "run_id": str(run_manifest.get("run_id") or run_dir.name),
                        "stage_key": stage_key,
                        "stage_label": stage_label(stage_key),
                        "stage_artifact_stem": stage_dir,
                        "call_id": call_id,
                        "timestamp_utc": timestamp_utc,
                        "recipe_id": recipe_id,
                        "source_file": source_file,
                        "pipeline_id": stage_meta.get("pipeline_id"),
                        "process_run_id": pass_run_id,
                        "model": model_value,
                        "request_messages": request_messages,
                        "system_prompt": None,
                        "developer_prompt": None,
                        "user_prompt": rendered_prompt,
                        "rendered_prompt_text": rendered_prompt,
                        "rendered_messages": request_messages,
                        "prompt_templates": {
                            "prompt_template_text": prompt_template_text,
                        },
                        "template_vars": {
                            "INPUT_PATH": str(input_file) if input_file is not None else None,
                            "INPUT_TEXT": input_text,
                        },
                        "inserted_context_blocks": _collect_context_blocks(parsed_input),
                        "request": {
                            "messages": request_messages,
                            "tools": [],
                            "response_format": response_format,
                            "model": model_value,
                            "temperature": None,
                            "top_p": None,
                            "max_output_tokens": None,
                            "seed": None,
                            "pipeline_id": stage_meta.get("pipeline_id"),
                        },
                        "raw_response": {
                            "output_text": output_text,
                            "output_file": str(output_file) if output_file is not None else None,
                        },
                        "parsed_response": parsed_output,
                        "request_input_payload": parsed_input,
                        "request_input_file": str(input_file) if input_file is not None else None,
                    }
                    handle.write(json.dumps(row, ensure_ascii=False))
                    handle.write("\n")
                    rows_written += 1

    if rows_written <= 0:
        output_path.unlink(missing_ok=True)
    return rows_written
