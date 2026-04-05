from __future__ import annotations

from pathlib import Path
from typing import Any

from .io import _load_json


def _first_existing_file(candidate_paths: list[Path]) -> Path | None:
    seen: set[Path] = set()
    for candidate in candidate_paths:
        resolved = candidate.resolve(strict=False)
        if resolved in seen:
            continue
        seen.add(resolved)
        if candidate.is_file():
            return candidate
    return None


def _manifest_artifact_path(
    *,
    run_dir: Path,
    run_manifest: dict[str, Any],
    artifact_keys: tuple[str, ...],
) -> Path | None:
    artifacts = run_manifest.get("artifacts")
    if not isinstance(artifacts, dict):
        return None
    for key in artifact_keys:
        artifact_raw = artifacts.get(key)
        if not isinstance(artifact_raw, str) or not artifact_raw.strip():
            continue
        candidate = Path(artifact_raw.strip())
        candidate = candidate if candidate.is_absolute() else run_dir / candidate
        if candidate.is_file():
            return candidate
    return None


def _load_stage_observability_payload(
    *,
    run_dir: Path,
    run_manifest: dict[str, Any],
) -> dict[str, Any]:
    report_path = _manifest_artifact_path(
        run_dir=run_dir,
        run_manifest=run_manifest,
        artifact_keys=("stage_observability_json",),
    )
    if report_path is None:
        return {}
    try:
        payload = _load_json(report_path)
    except Exception:  # noqa: BLE001
        return {}
    return payload if isinstance(payload, dict) else {}


def _resolve_stage_observability_manifest_paths(
    *,
    run_dir: Path,
    run_manifest: dict[str, Any],
    stage_key: str,
) -> list[Path]:
    payload = _load_stage_observability_payload(run_dir=run_dir, run_manifest=run_manifest)
    stages = payload.get("stages")
    if not isinstance(stages, list):
        return []
    rows: list[Path] = []
    for stage in stages:
        if not isinstance(stage, dict):
            continue
        if str(stage.get("stage_key") or "").strip() != stage_key:
            continue
        workbooks = stage.get("workbooks")
        if not isinstance(workbooks, list):
            continue
        for workbook in workbooks:
            if not isinstance(workbook, dict):
                continue
            manifest_raw = str(workbook.get("manifest_path") or "").strip()
            if not manifest_raw:
                continue
            manifest_path = Path(manifest_raw)
            rows.append(manifest_path if manifest_path.is_absolute() else run_dir / manifest_path)
    return rows


def _iter_prompt_category_manifest_paths(prompts_dir: Path) -> list[Path]:
    manifest_path = prompts_dir / "prompt_category_logs_manifest.txt"
    if not manifest_path.is_file():
        return []
    rows: list[Path] = []
    for raw_line in manifest_path.read_text(encoding="utf-8").splitlines():
        text = raw_line.strip()
        if not text:
            continue
        candidate = Path(text)
        if not candidate.is_absolute():
            candidate = (prompts_dir / candidate).resolve()
        rows.append(candidate)
    return rows


def _resolve_prompt_log_path(
    *,
    run_dir: Path,
    run_manifest: dict[str, Any],
    prompt_log_manifest_artifact_key: str,
    prompt_log_file_name: str,
    prompt_request_response_log_name: str,
) -> Path | None:
    candidate_paths: list[Path] = []

    artifacts = run_manifest.get("artifacts")
    if isinstance(artifacts, dict):
        manifest_path_raw = artifacts.get(prompt_log_manifest_artifact_key)
        if isinstance(manifest_path_raw, str) and manifest_path_raw.strip():
            manifest_path = Path(manifest_path_raw.strip())
            candidate_paths.append(
                manifest_path if manifest_path.is_absolute() else run_dir / manifest_path
            )

    candidate_paths.extend(
        [
            run_dir / prompt_log_file_name,
            run_dir / "codex-exec" / prompt_request_response_log_name,
            run_dir / "codex-exec" / prompt_log_file_name,
            run_dir / prompt_request_response_log_name,
        ]
    )
    return _first_existing_file(candidate_paths)


def _resolve_full_prompt_log_path(
    *,
    run_dir: Path,
    run_manifest: dict[str, Any],
    full_prompt_log_manifest_artifact_keys: tuple[str, ...],
    full_prompt_log_file_name: str,
) -> Path | None:
    candidate_paths: list[Path] = []

    artifacts = run_manifest.get("artifacts")
    if isinstance(artifacts, dict):
        for key in full_prompt_log_manifest_artifact_keys:
            manifest_path_raw = artifacts.get(key)
            if isinstance(manifest_path_raw, str) and manifest_path_raw.strip():
                manifest_path = Path(manifest_path_raw.strip())
                candidate_paths.append(
                    manifest_path if manifest_path.is_absolute() else run_dir / manifest_path
                )

    candidate_paths.extend(
        [
            run_dir / "prompts" / full_prompt_log_file_name,
            run_dir / full_prompt_log_file_name,
            run_dir / "codex-exec" / full_prompt_log_file_name,
        ]
    )
    return _first_existing_file(candidate_paths)


def _resolve_prompt_type_samples_path(
    *,
    run_dir: Path,
    run_manifest: dict[str, Any],
    prompt_type_samples_manifest_artifact_keys: tuple[str, ...],
    prompt_type_samples_file_name: str,
) -> Path | None:
    candidate_paths: list[Path] = []

    artifacts = run_manifest.get("artifacts")
    if isinstance(artifacts, dict):
        for key in prompt_type_samples_manifest_artifact_keys:
            manifest_path_raw = artifacts.get(key)
            if isinstance(manifest_path_raw, str) and manifest_path_raw.strip():
                manifest_path = Path(manifest_path_raw.strip())
                candidate_paths.append(
                    manifest_path if manifest_path.is_absolute() else run_dir / manifest_path
                )

    candidate_paths.extend(
        [
            run_dir / "prompts" / prompt_type_samples_file_name,
            run_dir / "codex-exec" / "prompts" / prompt_type_samples_file_name,
        ]
    )
    return _first_existing_file(candidate_paths)


def _resolve_knowledge_prompt_path(
    *,
    run_dir: Path,
    knowledge_prompt_file_name: str,
) -> Path | None:
    candidate_paths: list[Path] = [
        run_dir / "prompts" / knowledge_prompt_file_name,
        run_dir / "codex-exec" / "prompts" / knowledge_prompt_file_name,
    ]
    for prompts_dir in (
        run_dir / "prompts",
        run_dir / "codex-exec" / "prompts",
    ):
        if not prompts_dir.is_dir():
            continue
        for candidate in _iter_prompt_category_manifest_paths(prompts_dir):
            name = candidate.name.lower()
            if name.startswith("prompt_nonrecipe_finalize") and name.endswith(".txt"):
                candidate_paths.append(candidate)
        candidate_paths.extend(sorted(prompts_dir.glob("prompt_nonrecipe_finalize*.txt")))
    return _first_existing_file(candidate_paths)


def _resolve_prediction_run_dir(run_dir: Path, run_manifest: dict[str, Any]) -> Path | None:
    artifacts = run_manifest.get("artifacts")
    if isinstance(artifacts, dict):
        pred_run_raw = artifacts.get("artifact_root_dir")
        if isinstance(pred_run_raw, str) and pred_run_raw.strip():
            pred_candidate = Path(pred_run_raw.strip())
            pred_path = pred_candidate if pred_candidate.is_absolute() else run_dir / pred_candidate
            if pred_path.exists() and pred_path.is_dir():
                return pred_path
    return None


def _resolve_processed_output_run_dir(run_dir: Path, run_manifest: dict[str, Any]) -> Path | None:
    artifacts = run_manifest.get("artifacts")
    if not isinstance(artifacts, dict):
        return None
    for key in ("processed_output_run_dir", "stage_run_dir"):
        artifact_raw = artifacts.get(key)
        if not isinstance(artifact_raw, str) or not artifact_raw.strip():
            continue
        candidate = Path(artifact_raw.strip())
        candidate = candidate if candidate.is_absolute() else run_dir / candidate
        if candidate.exists() and candidate.is_dir():
            return candidate
    return None


def _resolve_extracted_archive_path(
    *,
    run_dir: Path,
    run_manifest: dict[str, Any],
    pred_run_dir: Path | None = None,
) -> Path | None:
    candidate_paths: list[Path] = []
    artifacts = run_manifest.get("artifacts")
    if isinstance(artifacts, dict):
        for key in ("evaluation_extracted_archive_json", "extracted_archive_json"):
            artifact_raw = artifacts.get(key)
            if not isinstance(artifact_raw, str) or not artifact_raw.strip():
                continue
            candidate = Path(artifact_raw.strip())
            candidate_paths.append(candidate if candidate.is_absolute() else run_dir / candidate)
    if pred_run_dir is not None:
        candidate_paths.extend(
            [
                pred_run_dir / "extracted_archive.json",
                pred_run_dir / "line-role-pipeline" / "extracted_archive.json",
            ]
        )
    candidate_paths.extend(
        [
            run_dir
            / ".prediction-record-replay"
            / "pipelined"
            / "extracted_archive.from_records.json",
            run_dir / "line-role-pipeline" / "extracted_archive.json",
        ]
    )
    return _first_existing_file(candidate_paths)


def _resolve_knowledge_manifest_path(
    *,
    run_dir: Path,
    run_manifest: dict[str, Any],
    knowledge_manifest_file_name: str,
) -> Path | None:
    candidate_paths: list[Path] = []
    manifest_artifact_path = _manifest_artifact_path(
        run_dir=run_dir,
        run_manifest=run_manifest,
        artifact_keys=("knowledge_manifest_json",),
    )
    if manifest_artifact_path is not None:
        candidate_paths.append(manifest_artifact_path)

    pred_run_dir = _resolve_prediction_run_dir(run_dir, run_manifest)
    if pred_run_dir is not None:
        pred_manifest_path = pred_run_dir / "manifest.json"
        pred_manifest: dict[str, Any] = {}
        if pred_manifest_path.is_file():
            try:
                pred_manifest = _load_json(pred_manifest_path)
            except Exception:  # noqa: BLE001
                pred_manifest = {}
        llm_payload = pred_manifest.get("llm_codex_farm") if isinstance(pred_manifest, dict) else {}
        llm_payload = llm_payload if isinstance(llm_payload, dict) else {}
        knowledge_payload = llm_payload.get("knowledge")
        knowledge_payload = knowledge_payload if isinstance(knowledge_payload, dict) else {}
        knowledge_paths = (
            knowledge_payload.get("paths")
            if isinstance(knowledge_payload.get("paths"), dict)
            else {}
        )
        manifest_path_raw = (
            knowledge_paths.get("manifest_path")
            or knowledge_payload.get("manifest_path")
            or ""
        )
        if isinstance(manifest_path_raw, str) and manifest_path_raw.strip():
            manifest_path = Path(manifest_path_raw.strip())
            candidate_paths.append(
                manifest_path if manifest_path.is_absolute() else pred_run_dir / manifest_path
            )

    processed_output_dir = _resolve_processed_output_run_dir(run_dir, run_manifest)
    if processed_output_dir is not None:
        candidate_paths.extend(
            _resolve_stage_observability_manifest_paths(
                run_dir=processed_output_dir,
                run_manifest=_load_json(processed_output_dir / "run_manifest.json")
                if (processed_output_dir / "run_manifest.json").is_file()
                else {
                    "artifacts": {"stage_observability_json": "stage_observability.json"},
                },
                stage_key="nonrecipe_finalize",
            )
        )
    candidate_paths.extend(
        _resolve_stage_observability_manifest_paths(
            run_dir=run_dir,
            run_manifest=run_manifest,
            stage_key="nonrecipe_finalize",
        )
    )

    return _first_existing_file(candidate_paths)


def _resolve_recipe_manifest_path(
    *,
    run_dir: Path,
    run_manifest: dict[str, Any],
) -> Path | None:
    candidate_paths: list[Path] = []
    manifest_artifact_path = _manifest_artifact_path(
        run_dir=run_dir,
        run_manifest=run_manifest,
        artifact_keys=("recipe_manifest_json",),
    )
    if manifest_artifact_path is not None:
        candidate_paths.append(manifest_artifact_path)

    candidate_paths.extend(
        _resolve_stage_observability_manifest_paths(
            run_dir=run_dir,
            run_manifest=run_manifest,
            stage_key="recipe_refine",
        )
    )
    candidate_paths.extend(
        _resolve_stage_observability_manifest_paths(
            run_dir=run_dir,
            run_manifest=run_manifest,
            stage_key="recipe_build_final",
        )
    )

    processed_output_dir = _resolve_processed_output_run_dir(run_dir, run_manifest)
    if processed_output_dir is not None:
        processed_manifest = (
            _load_json(processed_output_dir / "run_manifest.json")
            if (processed_output_dir / "run_manifest.json").is_file()
            else {"artifacts": {"stage_observability_json": "stage_observability.json"}}
        )
        candidate_paths.extend(
            _resolve_stage_observability_manifest_paths(
                run_dir=processed_output_dir,
                run_manifest=processed_manifest if isinstance(processed_manifest, dict) else {},
                stage_key="recipe_refine",
            )
        )
        candidate_paths.extend(
            _resolve_stage_observability_manifest_paths(
                run_dir=processed_output_dir,
                run_manifest=processed_manifest if isinstance(processed_manifest, dict) else {},
                stage_key="recipe_build_final",
            )
        )

    pred_run_dir = _resolve_prediction_run_dir(run_dir, run_manifest)
    if pred_run_dir is not None:
        pred_manifest = (
            _load_json(pred_run_dir / "run_manifest.json")
            if (pred_run_dir / "run_manifest.json").is_file()
            else {"artifacts": {"stage_observability_json": "stage_observability.json"}}
        )
        candidate_paths.extend(
            _resolve_stage_observability_manifest_paths(
                run_dir=pred_run_dir,
                run_manifest=pred_manifest if isinstance(pred_manifest, dict) else {},
                stage_key="recipe_refine",
            )
        )
        candidate_paths.extend(
            _resolve_stage_observability_manifest_paths(
                run_dir=pred_run_dir,
                run_manifest=pred_manifest if isinstance(pred_manifest, dict) else {},
                stage_key="recipe_build_final",
            )
        )

    return _first_existing_file(candidate_paths)
