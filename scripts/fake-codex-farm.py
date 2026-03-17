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
from cookimport.llm.codex_farm_runner import (  # noqa: E402
    resolve_codex_farm_output_schema_path,
)


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
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
    if args.command == "run" and args.run_command == "autotune":
        return _run_autotune(args)
    if args.command == "run" and args.run_command == "errors":
        return _run_errors(args)

    parser.print_help(sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
