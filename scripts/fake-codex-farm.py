#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from cookimport.llm.fake_codex_farm_runner import FakeCodexFarmRunner  # noqa: E402
from cookimport.llm.fake_codex_farm_runner import build_structural_pipeline_output  # noqa: E402
from cookimport.llm.codex_farm_runner import (  # noqa: E402
    resolve_codex_farm_output_schema_path,
)


def _read_any_json(path: Path) -> Any | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload


def _read_json(path: Path) -> dict[str, Any] | None:
    payload = _read_any_json(path)
    return payload if isinstance(payload, dict) else None


def _pipeline_rows(root: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    pipelines_dir = root / "pipelines"
    if not pipelines_dir.exists():
        return rows
    seen: set[str] = set()
    for definition_path in sorted(pipelines_dir.rglob("*.json")):
        payload = _read_json(definition_path)
        if payload is None:
            continue
        pipeline_id = str(payload.get("pipeline_id") or "").strip()
        if not pipeline_id or pipeline_id in seen:
            continue
        seen.add(pipeline_id)
        rows.append(
            {
                "pipeline_id": pipeline_id,
                "description": str(payload.get("description") or "").strip(),
            }
        )
    return rows


def _fake_models() -> list[dict[str, Any]]:
    return [
        {
            "slug": "fake-gpt-5-mini",
            "display_name": "Fake GPT-5 Mini",
            "description": "Zero-token local stand-in for CodexFarm dry runs.",
            "supported_reasoning_efforts": ["minimal", "low", "medium", "high"],
        }
    ]


def _sanitize_slug(value: str) -> str:
    cleaned = re.sub(r"[^a-z0-9]+", "-", value.strip().lower())
    return cleaned.strip("-") or "pipeline"


def _extract_first_json_object(raw: str) -> dict[str, Any] | None:
    decoder = json.JSONDecoder()
    for index, char in enumerate(raw):
        if char != "{":
            continue
        try:
            value, _ = decoder.raw_decode(raw[index:])
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value
    return None


def _extract_task_file_payload(prompt_text: str, *, cd: str | None) -> dict[str, Any] | None:
    candidates: list[Path] = []
    for match in re.finditer(r"([A-Za-z0-9_./:-]+\.json)", prompt_text):
        raw_path = match.group(1).strip()
        path = Path(raw_path)
        if path.is_absolute():
            candidates.append(path)
            continue
        if cd:
            candidates.append((REPO_ROOT / cd / path).resolve())
            candidates.append((Path(cd) / path).resolve())
        candidates.append((REPO_ROOT / path).resolve())
        candidates.append(path.resolve())

    seen: set[Path] = set()
    for candidate in candidates:
        if candidate in seen:
            continue
        seen.add(candidate)
        if not candidate.is_file():
            continue
        payload = _read_json(candidate)
        if payload is not None:
            return payload
    return None


def _resolve_cd_root(cd: str | None) -> Path | None:
    if not cd:
        return None
    candidate = Path(cd)
    if candidate.is_absolute():
        return candidate.resolve()
    return (REPO_ROOT / candidate).resolve()


def _infer_exec_pipeline_id(prompt_text: str, *, output_schema_path: str) -> str:
    if output_schema_path:
        return _pipeline_id_for_exec_schema(output_schema_path)
    prompt_lower = prompt_text.lower()
    if "recipe knowledge" in prompt_lower or "knowledge review" in prompt_lower:
        return "recipe.knowledge.compact.v1"
    if "recipe correction" in prompt_lower or "recipe.correction" in prompt_lower:
        return "recipe.correction.compact.v1"
    return "line-role.canonical.v1"


def _run_workspace_worker_exec(
    *,
    prompt_text: str,
    cd: str | None,
    pipeline_id: str,
) -> bool:
    workspace_root = _resolve_cd_root(cd)
    if workspace_root is None:
        return False
    assigned_path = workspace_root / "assigned_shards.json"
    if not assigned_path.is_file():
        return False
    assigned_payload = _read_any_json(assigned_path)
    if not isinstance(assigned_payload, list):
        return False

    in_dir = workspace_root / "in"
    out_dir = workspace_root / "out"
    out_dir.mkdir(parents=True, exist_ok=True)

    processed_any = False
    for row in assigned_payload:
        if not isinstance(row, dict):
            continue
        shard_id = str(row.get("shard_id") or "").strip()
        if not shard_id:
            continue
        input_payload = _read_json(in_dir / f"{shard_id}.json")
        if input_payload is None:
            continue
        output_payload = build_structural_pipeline_output(pipeline_id, input_payload)
        (out_dir / f"{shard_id}.json").write_text(
            json.dumps(output_payload, sort_keys=True),
            encoding="utf-8",
        )
        processed_any = True

    if not processed_any:
        return False

    response_text = json.dumps(
        {
            "status": "worker_completed",
            "processed_shards": len(
                [
                    row
                    for row in assigned_payload
                    if isinstance(row, dict) and str(row.get("shard_id") or "").strip()
                ]
            ),
        },
        sort_keys=True,
    )
    usage = {
        "input_tokens": max(1, len(prompt_text) // 4),
        "cached_input_tokens": 0,
        "output_tokens": max(1, len(response_text) // 4),
        "reasoning_tokens": 0,
    }
    for event in (
        {"type": "thread.started"},
        {"type": "item.completed", "item": {"type": "agent_message", "text": response_text}},
        {"type": "turn.completed", "usage": usage},
    ):
        sys.stdout.write(json.dumps(event, sort_keys=True))
        sys.stdout.write("\n")
    return True


def _emit_progress(
    *,
    enabled: bool,
    event: dict[str, Any],
) -> None:
    if not enabled:
        return
    sys.stderr.write("__codex_farm_progress__ ")
    sys.stderr.write(json.dumps(event, sort_keys=True))
    sys.stderr.write("\n")
    sys.stderr.flush()


def _run_process(args: argparse.Namespace) -> int:
    in_dir = Path(args.in_dir).resolve()
    out_dir = Path(args.out_dir).resolve()
    root_dir = Path(args.root).resolve() if args.root else None
    workspace_root = Path(args.workspace_root).resolve() if args.workspace_root else None

    file_names = sorted(path.name for path in in_dir.glob("*.json") if path.is_file())
    run_id = f"fake-{_sanitize_slug(args.pipeline)}-{len(file_names):03d}"
    output_schema_path = str(args.output_schema or "").strip()
    if not output_schema_path and root_dir is not None:
        output_schema_path = str(
            resolve_codex_farm_output_schema_path(
                root_dir=root_dir,
                pipeline_id=args.pipeline,
            )
        )

    _emit_progress(
        enabled=bool(args.progress_events),
        event={
            "event": "run_started",
            "run_id": run_id,
            "total_tasks": len(file_names),
        },
    )

    for index, file_name in enumerate(file_names, start=1):
        _emit_progress(
            enabled=bool(args.progress_events),
            event={
                "event": "run_progress",
                "run_id": run_id,
                "status": "running" if index < len(file_names) else "done",
                "counts": {
                    "total": len(file_names),
                    "queued": max(len(file_names) - index, 0),
                    "running": 1 if index < len(file_names) else 0,
                    "done": index,
                    "error": 0,
                    "canceled": 0,
                },
                "progress": {
                    "completed": index,
                },
                "running_tasks": [{"input_path": str(in_dir / file_name)}],
            },
        )

    runner = FakeCodexFarmRunner()
    runner.run_pipeline(
        args.pipeline,
        in_dir,
        out_dir,
        os.environ,
        root_dir=root_dir,
        workspace_root=workspace_root,
        model=args.model,
        reasoning_effort=args.reasoning_effort,
        runtime_mode=str(args.runtime_mode or "").strip() or None,
        process_worker_count=int(args.workers) if str(args.workers or "").isdigit() else None,
    )

    payload = {
        "run_id": run_id,
        "status": "completed",
        "exit_code": 0,
        "pipeline_id": args.pipeline,
        "output_schema_path": output_schema_path or None,
        "telemetry_report": {
            "schema_version": 1,
            "provider": "fake-codex-farm",
            "input_file_count": len(file_names),
            "runtime_mode": str(args.runtime_mode or "").strip() or None,
            "workers_requested": int(args.workers) if str(args.workers or "").isdigit() else None,
            "workspace_root": str(workspace_root) if workspace_root is not None else None,
        },
    }
    sys.stdout.write(json.dumps(payload))
    sys.stdout.write("\n")
    return 0


def _pipeline_id_for_exec_schema(output_schema_path: str) -> str:
    file_name = Path(output_schema_path).name
    if file_name == "recipe.correction.v1.output.schema.json":
        return "recipe.correction.compact.v1"
    if file_name == "recipe.knowledge.v1.output.schema.json":
        return "recipe.knowledge.compact.v1"
    if file_name == "line-role.canonical.v1.output.schema.json":
        return "line-role.canonical.v1"
    return "line-role.canonical.v1"


def _run_exec(args: argparse.Namespace) -> int:
    prompt_text = sys.stdin.read()
    output_schema_path = str(args.output_schema or "").strip()
    pipeline_id = _infer_exec_pipeline_id(
        prompt_text,
        output_schema_path=output_schema_path,
    )
    if not output_schema_path:
        if _run_workspace_worker_exec(
            prompt_text=prompt_text,
            cd=args.cd,
            pipeline_id=pipeline_id,
        ):
            return 0
    parsed_payload = _extract_task_file_payload(prompt_text, cd=args.cd)
    if parsed_payload is None:
        parsed_payload = _extract_first_json_object(prompt_text)
    payload = parsed_payload if parsed_payload is not None else prompt_text
    response_payload = build_structural_pipeline_output(pipeline_id, payload)
    response_text = json.dumps(response_payload, sort_keys=True)
    usage = {
        "input_tokens": max(1, len(prompt_text) // 4),
        "cached_input_tokens": 0,
        "output_tokens": max(1, len(response_text) // 4),
        "reasoning_tokens": 0,
    }
    for event in (
        {"type": "thread.started"},
        {"type": "item.completed", "item": {"type": "agent_message", "text": response_text}},
        {"type": "turn.completed", "usage": usage},
    ):
        sys.stdout.write(json.dumps(event, sort_keys=True))
        sys.stdout.write("\n")
    return 0


def _run_autotune(args: argparse.Namespace) -> int:
    payload = {
        "schema_version": 1,
        "run_id": str(args.run_id or "").strip(),
        "pipeline_id": str(args.pipeline or "").strip() or None,
        "flag_overrides": [],
        "command_preview": "fake-codex-farm process ...",
        "provider": "fake-codex-farm",
    }
    sys.stdout.write(json.dumps(payload))
    sys.stdout.write("\n")
    return 0


def _run_errors(_args: argparse.Namespace) -> int:
    sys.stdout.write(json.dumps({"errors": []}))
    sys.stdout.write("\n")
    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="fake-codex-farm")
    subparsers = parser.add_subparsers(dest="command")

    models = subparsers.add_parser("models")
    models_subparsers = models.add_subparsers(dest="models_command")
    models_list = models_subparsers.add_parser("list")
    models_list.add_argument("--json", action="store_true")

    pipelines = subparsers.add_parser("pipelines")
    pipelines_subparsers = pipelines.add_subparsers(dest="pipelines_command")
    pipelines_list = pipelines_subparsers.add_parser("list")
    pipelines_list.add_argument("--root", required=True)
    pipelines_list.add_argument("--json", action="store_true")

    process = subparsers.add_parser("process")
    process.add_argument("--pipeline", required=True)
    process.add_argument("--in", dest="in_dir", required=True)
    process.add_argument("--out", dest="out_dir", required=True)
    process.add_argument("--json", action="store_true")
    process.add_argument("--output-schema")
    process.add_argument("--root")
    process.add_argument("--workspace-root")
    process.add_argument("--model")
    process.add_argument("--reasoning-effort")
    process.add_argument("--runtime-mode")
    process.add_argument("--recipeimport-benchmark-mode")
    process.add_argument("--recipeimport-benchmark-debug", action="store_true")
    process.add_argument("--progress-events", action="store_true")
    process.add_argument("--workers", default="1")

    run = subparsers.add_parser("run")
    run_subparsers = run.add_subparsers(dest="run_command")
    autotune = run_subparsers.add_parser("autotune")
    autotune.add_argument("--run-id", required=True)
    autotune.add_argument("--pipeline")
    autotune.add_argument("--json", action="store_true")
    errors = run_subparsers.add_parser("errors")
    errors.add_argument("--run-id", required=True)
    errors.add_argument("--json", action="store_true")

    exec_parser = subparsers.add_parser("exec")
    exec_parser.add_argument("--json", action="store_true")
    exec_parser.add_argument("--ephemeral", action="store_true")
    exec_parser.add_argument("--skip-git-repo-check", action="store_true")
    exec_parser.add_argument("--sandbox")
    exec_parser.add_argument("--cd")
    exec_parser.add_argument("--output-schema")
    exec_parser.add_argument("--model")
    exec_parser.add_argument("-c", dest="config_overrides", action="append", default=[])
    exec_parser.add_argument("stdin_marker", nargs="?")

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.command == "models" and args.models_command == "list":
        sys.stdout.write(json.dumps(_fake_models()))
        sys.stdout.write("\n")
        return 0
    if args.command == "pipelines" and args.pipelines_command == "list":
        sys.stdout.write(json.dumps(_pipeline_rows(Path(args.root).resolve())))
        sys.stdout.write("\n")
        return 0
    if args.command == "process":
        return _run_process(args)
    if args.command == "exec":
        return _run_exec(args)
    if args.command == "run" and args.run_command == "autotune":
        return _run_autotune(args)
    if args.command == "run" and args.run_command == "errors":
        return _run_errors(args)

    parser.print_help(sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
