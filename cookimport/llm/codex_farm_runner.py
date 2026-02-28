from __future__ import annotations

import json
import logging
import os
import shlex
import subprocess
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Mapping, Protocol, Sequence

logger = logging.getLogger(__name__)


class CodexFarmRunnerError(RuntimeError):
    """Raised when codex-farm subprocess execution fails."""


class CodexFarmRunner(Protocol):
    def run_pipeline(
        self,
        pipeline_id: str,
        in_dir: Path,
        out_dir: Path,
        env: Mapping[str, str],
        *,
        root_dir: Path | None = None,
        workspace_root: Path | None = None,
        model: str | None = None,
        reasoning_effort: str | None = None,
    ) -> None:
        """Run a codex-farm pipeline over input/output directories."""


def _merge_env(env: Mapping[str, str] | None = None) -> dict[str, str]:
    merged = os.environ.copy()
    if not env:
        return merged
    for key, value in env.items():
        merged[str(key)] = str(value)
    return merged


def _command_prefix(cmd: str) -> list[str]:
    prefix = shlex.split(cmd)
    return prefix or ["codex-farm"]


def _run_codex_farm_command(
    command: list[str],
    *,
    env: Mapping[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            command,
            text=True,
            capture_output=True,
            check=False,
            env=_merge_env(env),
        )
    except FileNotFoundError as exc:
        binary = command[0] if command else "codex-farm"
        raise CodexFarmRunnerError(
            f"codex-farm command not found: {binary!r}. "
            "Install codex-farm or disable llm_recipe_pipeline."
        ) from exc
    except OSError as exc:
        binary = command[0] if command else "codex-farm"
        raise CodexFarmRunnerError(
            f"Failed to execute codex-farm command {binary!r}: {exc}"
        ) from exc


def _parse_json_stdout(
    completed: subprocess.CompletedProcess[str],
    *,
    command_label: str,
) -> Any | None:
    raw_stdout = (completed.stdout or "").strip()
    if not raw_stdout:
        return None
    try:
        return json.loads(raw_stdout)
    except json.JSONDecodeError as exc:
        raise CodexFarmRunnerError(
            f"codex-farm {command_label} returned non-JSON stdout despite --json."
        ) from exc


def _coerce_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _read_json_dict(path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _as_existing_file(path: Path) -> Path:
    if not path.exists() or not path.is_file():
        raise CodexFarmRunnerError(f"Expected file path does not exist: {path}")
    return path


@lru_cache(maxsize=512)
def _resolve_pipeline_output_schema_path(
    *,
    root_dir_str: str,
    pipeline_id: str,
) -> Path:
    root_dir = Path(root_dir_str)
    pipelines_dir = root_dir / "pipelines"
    if not pipelines_dir.exists() or not pipelines_dir.is_dir():
        raise CodexFarmRunnerError(
            f"Invalid codex-farm pipeline root {root_dir}: missing pipelines directory."
        )

    matching_defs: list[tuple[Path, dict[str, Any]]] = []
    for definition_path in sorted(pipelines_dir.rglob("*.json")):
        payload = _read_json_dict(definition_path)
        if payload is None:
            continue
        found_pipeline_id = str(payload.get("pipeline_id") or "").strip()
        if found_pipeline_id != pipeline_id:
            continue
        matching_defs.append((definition_path, payload))

    if not matching_defs:
        raise CodexFarmRunnerError(
            "Unable to resolve codex-farm output schema override: "
            f"pipeline definition for {pipeline_id!r} not found under {pipelines_dir}."
        )
    if len(matching_defs) > 1:
        paths = ", ".join(str(path) for path, _payload in matching_defs)
        raise CodexFarmRunnerError(
            "Unable to resolve codex-farm output schema override: "
            f"pipeline id {pipeline_id!r} is defined multiple times ({paths})."
        )

    definition_path, payload = matching_defs[0]
    raw_schema_path = str(payload.get("output_schema_path") or "").strip()
    if not raw_schema_path:
        raise CodexFarmRunnerError(
            "Unable to resolve codex-farm output schema override: "
            f"{definition_path} is missing output_schema_path."
        )

    schema_path = Path(raw_schema_path).expanduser()
    if not schema_path.is_absolute():
        schema_path = root_dir / schema_path
    return _as_existing_file(schema_path)


def resolve_codex_farm_output_schema_path(
    *,
    root_dir: Path,
    pipeline_id: str,
) -> Path:
    """Resolve a pipeline's output schema path from pack metadata."""

    return _resolve_pipeline_output_schema_path(
        root_dir_str=str(root_dir),
        pipeline_id=str(pipeline_id),
    )


def _normalize_model_row(row: dict[str, Any]) -> dict[str, Any] | None:
    slug = str(row.get("slug") or "").strip()
    if not slug:
        return None
    display_name = str(row.get("display_name") or slug).strip() or slug
    description = str(row.get("description") or "").strip()
    normalized: dict[str, Any] = {
        "slug": slug,
        "display_name": display_name,
        "description": description,
    }
    raw_efforts = row.get("supported_reasoning_efforts")
    if isinstance(raw_efforts, list):
        efforts = [item.strip() for item in raw_efforts if isinstance(item, str) and item.strip()]
        if efforts:
            normalized["supported_reasoning_efforts"] = efforts
    return normalized


def list_codex_farm_models(
    *,
    cmd: str = "codex-farm",
    env: Mapping[str, str] | None = None,
) -> list[dict[str, Any]]:
    """Best-effort model discovery via `codex-farm models list --json`."""

    command = [*_command_prefix(cmd), "models", "list", "--json"]
    try:
        completed = _run_codex_farm_command(command, env=env)
    except CodexFarmRunnerError as exc:
        logger.warning("Unable to list codex-farm models: %s", exc)
        return []

    if completed.returncode != 0:
        stderr = (completed.stderr or "").strip()
        logger.warning(
            "codex-farm models list failed (exit=%s): %s",
            completed.returncode,
            stderr or "no stderr",
        )
        return []

    try:
        payload = _parse_json_stdout(completed, command_label="models list")
    except CodexFarmRunnerError as exc:
        logger.warning("%s", exc)
        return []

    if not isinstance(payload, list):
        return []

    models: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in payload:
        if not isinstance(row, dict):
            continue
        normalized = _normalize_model_row(row)
        if normalized is None:
            continue
        slug = normalized["slug"]
        if slug in seen:
            continue
        models.append(normalized)
        seen.add(slug)
    return models


def list_codex_farm_pipelines(
    *,
    cmd: str = "codex-farm",
    root_dir: Path,
    env: Mapping[str, str] | None = None,
) -> list[dict[str, Any]]:
    """Strict pipeline discovery via `codex-farm pipelines list --root ... --json`."""

    command = [
        *_command_prefix(cmd),
        "pipelines",
        "list",
        "--root",
        str(root_dir),
        "--json",
    ]
    completed = _run_codex_farm_command(command, env=env)
    if completed.returncode != 0:
        stderr = (completed.stderr or "").strip()
        raise CodexFarmRunnerError(
            "codex-farm pipelines list failed for "
            f"{root_dir} (exit={completed.returncode}): {stderr or 'no stderr'}"
        )

    payload = _parse_json_stdout(completed, command_label="pipelines list")
    if not isinstance(payload, list):
        raise CodexFarmRunnerError(
            "codex-farm pipelines list returned unexpected JSON payload."
        )

    rows: list[dict[str, Any]] = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        pipeline_id = str(item.get("pipeline_id") or "").strip()
        if not pipeline_id:
            continue
        rows.append(
            {
                "pipeline_id": pipeline_id,
                "description": str(item.get("description") or "").strip(),
            }
        )
    return rows


def ensure_codex_farm_pipelines_exist(
    *,
    cmd: str,
    root_dir: Path,
    pipeline_ids: Sequence[str],
    env: Mapping[str, str] | None = None,
) -> None:
    """Fail early when configured pipeline ids are missing from a pack root."""

    requested = [str(item).strip() for item in pipeline_ids if str(item).strip()]
    if not requested:
        return
    discovered = list_codex_farm_pipelines(cmd=cmd, root_dir=root_dir, env=env)
    available = {str(row.get("pipeline_id") or "").strip() for row in discovered}
    missing = sorted({item for item in requested if item not in available})
    if not missing:
        return
    raise CodexFarmRunnerError(
        "Configured codex-farm pipeline id(s) not found under "
        f"{root_dir}: {', '.join(missing)}. "
        "Verify pipeline ids with `codex-farm pipelines list --root <pack> --json`."
    )


def _extract_run_id(payload: Any) -> str | None:
    if not isinstance(payload, dict):
        return None
    run_id = str(payload.get("run_id") or "").strip()
    return run_id or None


def _extract_exit_code(payload: Any) -> int | None:
    if not isinstance(payload, dict):
        return None
    return _coerce_int(payload.get("exit_code"))


def _extract_output_schema_path(payload: Any) -> str | None:
    if not isinstance(payload, dict):
        return None
    rendered = str(payload.get("output_schema_path") or "").strip()
    return rendered or None


def _summarize_run_errors_payload(payload: Any) -> str | None:
    if isinstance(payload, dict):
        errors = payload.get("errors")
        if isinstance(errors, list) and errors:
            first = errors[0]
            if isinstance(first, dict):
                for key in ("message", "error", "detail"):
                    text = str(first.get(key) or "").strip()
                    if text:
                        return text
            text = str(first).strip()
            if text:
                return text
        for key in ("message", "error", "detail"):
            text = str(payload.get(key) or "").strip()
            if text:
                return text
    if isinstance(payload, list) and payload:
        first = payload[0]
        if isinstance(first, dict):
            for key in ("message", "error", "detail"):
                text = str(first.get(key) or "").strip()
                if text:
                    return text
        text = str(first).strip()
        if text:
            return text
    return None


def _fetch_run_errors_summary(
    *,
    cmd: str,
    run_id: str,
    env: Mapping[str, str] | None = None,
) -> str | None:
    command = [*_command_prefix(cmd), "run", "errors", "--run-id", run_id, "--json"]
    try:
        completed = _run_codex_farm_command(command, env=env)
    except CodexFarmRunnerError as exc:
        logger.warning("Unable to fetch codex-farm run errors for %s: %s", run_id, exc)
        return None
    if completed.returncode != 0:
        stderr = (completed.stderr or "").strip()
        logger.warning(
            "codex-farm run errors failed for %s (exit=%s): %s",
            run_id,
            completed.returncode,
            stderr or "no stderr",
        )
        return None
    try:
        payload = _parse_json_stdout(completed, command_label="run errors")
    except CodexFarmRunnerError as exc:
        logger.warning("%s", exc)
        return None
    return _summarize_run_errors_payload(payload)


@dataclass(frozen=True)
class SubprocessCodexFarmRunner:
    cmd: str = "codex-farm"

    def run_pipeline(
        self,
        pipeline_id: str,
        in_dir: Path,
        out_dir: Path,
        env: Mapping[str, str],
        *,
        root_dir: Path | None = None,
        workspace_root: Path | None = None,
        model: str | None = None,
        reasoning_effort: str | None = None,
    ) -> None:
        out_dir.mkdir(parents=True, exist_ok=True)
        expected_schema_path: Path | None = None
        command = [
            *_command_prefix(self.cmd),
            "process",
            "--pipeline",
            pipeline_id,
            "--in",
            str(in_dir),
            "--out",
            str(out_dir),
        ]
        if model:
            command.extend(["--model", str(model)])
        if reasoning_effort:
            command.extend(["--reasoning-effort", str(reasoning_effort)])
        if root_dir is not None:
            expected_schema_path = resolve_codex_farm_output_schema_path(
                root_dir=root_dir,
                pipeline_id=pipeline_id,
            )
            command.extend(["--output-schema", str(expected_schema_path)])
        command.append("--json")
        if root_dir is not None:
            command.extend(["--root", str(root_dir)])
        if workspace_root is not None:
            command.extend(["--workspace-root", str(workspace_root)])
        completed = _run_codex_farm_command(command, env=env)

        if completed.stdout.strip():
            logger.info(
                "codex-farm stdout (%s): %s",
                pipeline_id,
                completed.stdout.strip(),
            )
        if completed.stderr.strip():
            logger.warning(
                "codex-farm stderr (%s): %s",
                pipeline_id,
                completed.stderr.strip(),
            )

        process_payload: Any | None
        try:
            process_payload = _parse_json_stdout(completed, command_label="process")
        except CodexFarmRunnerError:
            if completed.returncode == 0:
                # Keep compatibility with older/fake runners that may emit empty/non-JSON stdout.
                process_payload = None
            else:
                raise

        if process_payload is not None and expected_schema_path is not None:
            reported_schema_path = _extract_output_schema_path(process_payload)
            if not reported_schema_path:
                raise CodexFarmRunnerError(
                    "codex-farm process --json response is missing output_schema_path."
                )
            reported_schema = Path(reported_schema_path).expanduser()
            if not reported_schema.is_absolute() and root_dir is not None:
                reported_schema = root_dir / reported_schema
            if reported_schema != expected_schema_path:
                raise CodexFarmRunnerError(
                    "codex-farm process output_schema_path mismatch: "
                    f"expected={expected_schema_path} reported={reported_schema}"
                )

        run_id = _extract_run_id(process_payload)
        payload_exit_code = _extract_exit_code(process_payload)
        failed = completed.returncode != 0 or (payload_exit_code not in {None, 0})
        if failed:
            error_summary: str | None = None
            if run_id:
                error_summary = _fetch_run_errors_summary(cmd=self.cmd, run_id=run_id, env=env)
            details: list[str] = []
            if run_id:
                details.append(f"run_id={run_id}")
            if payload_exit_code is not None:
                details.append(f"process_exit_code={payload_exit_code}")
            details.append(f"subprocess_exit={completed.returncode}")
            details.append(f"out_dir={out_dir}")
            if error_summary:
                details.append(f"first_error={error_summary}")
            raise CodexFarmRunnerError(
                f"codex-farm failed for {pipeline_id} ({', '.join(details)})"
            )
