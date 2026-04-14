#!/usr/bin/env python3

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
from pathlib import Path
from typing import Any

from cookimport.config.run_settings import RunSettings
from cookimport.labelstudio.archive import build_extracted_archive
from cookimport.labelstudio.export import run_labelstudio_export
from cookimport.labelstudio.migrate_to_source_rows import (
    build_row_labelstudio_seed_package,
    migrate_freeform_export_to_row_gold,
    write_migration_result,
)
from cookimport.parsing.source_rows import build_source_rows, write_source_rows
from cookimport.plugins import registry
from cookimport.plugins import epub, excel, paprika, pdf, recipesage, text, webschema  # noqa: F401
from cookimport.plugins.text import _source_blocks_from_text_lines


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Batch-migrate pulled Label Studio gold exports to row-authoritative artifacts."
        )
    )
    parser.add_argument(
        "--pulled-root",
        type=Path,
        default=Path("data/golden/pulled-from-labelstudio"),
        help="Root containing one folder per pulled Label Studio export.",
    )
    parser.add_argument(
        "--sent-root",
        type=Path,
        default=Path("data/golden/sent-to-labelstudio"),
        help="Root containing older sent-to-labelstudio import artifacts.",
    )
    parser.add_argument(
        "--input-root",
        type=Path,
        default=Path("data/input"),
        help="Root used to resolve non-absolute source filenames.",
    )
    parser.add_argument(
        "--only",
        action="append",
        default=[],
        help="Restrict migration to one or more export folder names.",
    )
    parser.add_argument(
        "--prefer-live-row-gold",
        action="store_true",
        help=(
            "When a migrated replacement Label Studio project exists, export its "
            "current annotations first and migrate from that live project instead "
            "of the older pulled export."
        ),
    )
    parser.add_argument(
        "--label-studio-url",
        default=None,
        help="Label Studio base URL. Defaults to saved settings/env or localhost.",
    )
    parser.add_argument(
        "--label-studio-api-key",
        default=None,
        help="Label Studio API key. Defaults to saved settings/env when available.",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    export_roots = sorted(
        path.parent
        for path in args.pulled_root.glob("*/exports/freeform_span_labels.jsonl")
    )
    only = {value.strip() for value in args.only if value.strip()}
    if only:
        export_roots = [
            path for path in export_roots if path.parent.name in only
        ]
    if not export_roots:
        raise SystemExit("No pulled Label Studio exports found.")

    sent_manifest_index = _index_sent_manifests(args.sent_root)
    batch_rows: list[dict[str, Any]] = []
    label_studio_credentials = _resolve_labelstudio_credentials(
        label_studio_url=args.label_studio_url,
        label_studio_api_key=args.label_studio_api_key,
    )
    if args.prefer_live_row_gold and label_studio_credentials is None:
        raise SystemExit(
            "--prefer-live-row-gold requires Label Studio credentials via "
            "--label-studio-api-key, LABEL_STUDIO_API_KEY, or cookimport.local.json"
        )

    for export_root in export_roots:
        project_root = export_root.parent
        slug = project_root.name
        freeform_path = export_root / "freeform_span_labels.jsonl"
        run_manifest_path = project_root / "run_manifest.json"
        summary_path = export_root / "summary.json"

        run_manifest = _load_json_object(run_manifest_path)
        summary = _load_json_object(summary_path)
        source_file, source_hash = _resolve_source_identity(
            run_manifest=run_manifest,
            freeform_path=freeform_path,
        )
        archive_blocks, archive_source = _resolve_archive_blocks(
            summary=summary,
            sent_manifest_index=sent_manifest_index,
            source_hash=source_hash,
            source_file=source_file,
            input_root=args.input_root,
        )

        source_rows_path = export_root / "source_rows.jsonl"
        source_rows = build_source_rows(archive_blocks, source_hash=source_hash)
        write_source_rows(source_rows_path, source_rows)

        migration_span_path = freeform_path
        span_source = "pulled_export"
        live_export_summary: dict[str, Any] | None = None
        if args.prefer_live_row_gold and label_studio_credentials is not None:
            live_export_summary = _maybe_export_live_row_gold_project(
                project_root=project_root,
                pulled_root=args.pulled_root,
                label_studio_url=label_studio_credentials[0],
                label_studio_api_key=label_studio_credentials[1],
            )
            if live_export_summary is not None:
                migration_span_path = Path(
                    live_export_summary["freeform_span_labels_path"]
                )
                span_source = str(live_export_summary["span_source"])

        migration_result = migrate_freeform_export_to_row_gold(
            freeform_span_labels_jsonl_path=migration_span_path,
            source_rows_jsonl_path=source_rows_path,
        )
        seed_package = build_row_labelstudio_seed_package(
            migration_result=migration_result,
            source_rows_jsonl_path=source_rows_path,
        )
        written_paths = write_migration_result(
            output_dir=export_root,
            migration_result=migration_result,
            seed_package=seed_package,
        )

        _update_export_summary(
            summary_path=summary_path,
            existing_summary=summary,
            source_rows_path=source_rows_path,
            written_paths=written_paths,
            migration_result=migration_result,
            seed_package=seed_package,
            archive_source=archive_source,
            migration_span_path=migration_span_path,
            migration_span_source=span_source,
            live_export_summary=live_export_summary,
        )
        _update_export_run_manifest(
            run_manifest_path=run_manifest_path,
            existing_manifest=run_manifest,
            source_file=source_file,
            source_hash=source_hash,
            source_rows_path=source_rows_path,
            written_paths=written_paths,
            migration_span_path=migration_span_path,
        )

        batch_rows.append(
            {
                "slug": slug,
                "source_file": source_file,
                "source_hash": source_hash,
                "archive_source": archive_source,
                "migrated_labeled_row_count": migration_result.migrated_labeled_row_count,
                "ambiguous_row_count": migration_result.ambiguous_row_count,
                "conflicting_row_count": migration_result.conflicting_row_count,
                "unlabeled_row_count": migration_result.unlabeled_row_count,
                "seed_task_count": seed_package.task_count,
                "seeded_annotation_count": seed_package.seeded_annotation_count,
                "migration_span_source": span_source,
                "migration_span_path": str(migration_span_path),
                "source_rows_path": str(source_rows_path),
                "row_gold_labels_path": str(written_paths["row_gold_path"]),
            }
        )
        print(
            f"{slug}: migrated {migration_result.migrated_labeled_row_count} rows "
            f"(ambiguous={migration_result.ambiguous_row_count}, "
            f"conflicts={migration_result.conflicting_row_count}, "
            f"seed_tasks={seed_package.task_count}) via {archive_source}; "
            f"labels from {span_source}"
        )

    batch_summary_path = args.pulled_root / "source_rows_migration_summary.json"
    batch_summary_path.write_text(
        json.dumps({"exports": batch_rows}, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    print(f"Wrote batch summary: {batch_summary_path}")
    return 0


def _resolve_labelstudio_credentials(
    *,
    label_studio_url: str | None,
    label_studio_api_key: str | None,
) -> tuple[str, str] | None:
    url = str(label_studio_url or os.getenv("LABEL_STUDIO_URL") or "").strip()
    api_key = str(
        label_studio_api_key or os.getenv("LABEL_STUDIO_API_KEY") or ""
    ).strip()
    if not url:
        url = _load_saved_setting("label_studio_url") or "http://localhost:8080"
    if not api_key:
        api_key = _load_saved_setting("label_studio_api_key") or ""
    if not api_key:
        return None
    return url, api_key


def _load_saved_setting(key: str) -> str | None:
    for path in (Path("cookimport.local.json"), Path("cookimport.json")):
        if not path.exists() or not path.is_file():
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(payload, dict):
            continue
        value = str(payload.get(key) or "").strip()
        if value:
            return value
    return None


def _maybe_export_live_row_gold_project(
    *,
    project_root: Path,
    pulled_root: Path,
    label_studio_url: str,
    label_studio_api_key: str,
) -> dict[str, Any] | None:
    summary_path = project_root / "exports" / "row_gold_labelstudio_project.json"
    if not summary_path.exists() or not summary_path.is_file():
        return None
    summary = _load_json_object(summary_path)
    project_name = str(summary.get("row_gold_project_name") or "").strip()
    if not project_name:
        return None
    project_id = str(summary.get("row_gold_project_id") or "").strip() or "unknown"
    backup_root = (
        pulled_root
        / project_root.name
        / "live_row_gold_backups"
        / f"{dt.datetime.now().strftime('%Y-%m-%d_%H.%M.%S')}_project-{project_id}"
    )
    export_result = run_labelstudio_export(
        project_name=project_name,
        output_dir=pulled_root,
        label_studio_url=label_studio_url,
        label_studio_api_key=label_studio_api_key,
        run_dir=backup_root,
    )
    export_root = Path(export_result["export_root"])
    freeform_span_labels_path = export_root / "freeform_span_labels.jsonl"
    if not freeform_span_labels_path.exists():
        raise FileNotFoundError(
            f"Live row-gold export missing freeform spans: {freeform_span_labels_path}"
        )
    return {
        "project_name": project_name,
        "project_id": project_id,
        "backup_run_root": str(export_root.parent),
        "freeform_span_labels_path": str(freeform_span_labels_path),
        "span_source": f"live_row_gold:{project_name}",
    }


def _resolve_source_identity(
    *,
    run_manifest: dict[str, Any],
    freeform_path: Path,
) -> tuple[str, str]:
    source_payload = run_manifest.get("source")
    if isinstance(source_payload, dict):
        source_file = str(source_payload.get("path") or "").strip()
        source_hash = str(source_payload.get("source_hash") or "").strip()
        if source_file and source_hash:
            return source_file, source_hash

    for row in _read_jsonl(freeform_path):
        source_file = str(row.get("source_file") or "").strip()
        source_hash = str(row.get("source_hash") or "").strip()
        if source_file and source_hash:
            return source_file, source_hash
    raise ValueError(f"Unable to resolve source identity for {freeform_path}")


def _resolve_archive_blocks(
    *,
    summary: dict[str, Any],
    sent_manifest_index: dict[str, Path],
    source_hash: str,
    source_file: str,
    input_root: Path,
) -> tuple[list[dict[str, Any]], str]:
    manifest_path_raw = summary.get("manifest_path")
    if isinstance(manifest_path_raw, str) and manifest_path_raw.strip():
        import_root = Path(manifest_path_raw).expanduser().resolve().parent
        archive_path = import_root / "extracted_archive.json"
        if archive_path.exists():
            return _read_json_list(archive_path), f"saved_import:{import_root}"

    sent_manifest_path = sent_manifest_index.get(source_hash)
    if sent_manifest_path is not None:
        archive_path = sent_manifest_path.parent / "extracted_archive.json"
        if archive_path.exists():
            return _read_json_list(archive_path), f"sent_manifest:{sent_manifest_path.parent}"

    resolved_source = _resolve_source_path(source_file=source_file, input_root=input_root)
    return _build_archive_from_source(resolved_source), f"reconverted_source:{resolved_source}"


def _resolve_source_path(*, source_file: str, input_root: Path) -> Path:
    candidate = Path(source_file).expanduser()
    if candidate.is_absolute() and candidate.exists():
        return candidate
    matches = sorted(input_root.glob(f"**/{candidate.name}"))
    if len(matches) == 1:
        return matches[0]
    if not matches:
        raise FileNotFoundError(f"Could not resolve source file {source_file!r}")
    raise FileExistsError(
        f"Multiple source files matched {source_file!r}: {', '.join(str(path) for path in matches)}"
    )


def _build_archive_from_source(source_path: Path) -> list[dict[str, Any]]:
    importer, score = registry.best_importer_for_path(source_path)
    if importer is None or score <= 0:
        raise ValueError(f"No importer available for {source_path}")
    mapping = importer.inspect(source_path).mapping_stub
    result = importer.convert(
        source_path,
        mapping,
        progress_callback=None,
        run_settings=RunSettings(),
    )
    if list(result.source_blocks or []):
        archive = build_extracted_archive(result, list(result.raw_artifacts or []))
        return [
            {
                "index": int(block.index),
                "text": str(block.text),
                "location": dict(block.location),
                "source_kind": block.source_kind,
            }
            for block in archive
        ]

    extract_text = getattr(importer, "_extract_text", None)
    if callable(extract_text):
        raw_text = str(extract_text(source_path) or "")
        return _source_blocks_from_text_lines(raw_text.splitlines())

    raise ValueError(f"Importer returned no source blocks for {source_path}")


def _index_sent_manifests(sent_root: Path) -> dict[str, Path]:
    manifest_index: dict[str, Path] = {}
    for manifest_path in sorted(sent_root.glob("**/manifest.json")):
        payload = _load_json_object(manifest_path)
        source_hash = str(payload.get("source_hash") or "").strip()
        if source_hash:
            manifest_index[source_hash] = manifest_path
    return manifest_index


def _update_export_summary(
    *,
    summary_path: Path,
    existing_summary: dict[str, Any],
    source_rows_path: Path,
    written_paths: dict[str, Path],
    migration_result: Any,
    seed_package: Any,
    archive_source: str,
    migration_span_path: Path,
    migration_span_source: str,
    live_export_summary: dict[str, Any] | None,
) -> None:
    summary = dict(existing_summary)
    output = dict(summary.get("output") or {})
    output.update(
        {
            "source_rows": str(source_rows_path),
            "row_gold_labels": str(written_paths["row_gold_path"]),
            "row_gold_ambiguous": str(written_paths["ambiguous_path"]),
            "row_gold_conflicts": str(written_paths["conflicts_path"]),
            "row_seed_tasks": str(written_paths["seed_tasks_path"]),
            "migration_freeform_span_labels": str(migration_span_path),
        }
    )
    summary["output"] = output
    summary["row_gold"] = {
        "row_count": migration_result.migrated_labeled_row_count,
        "multilabel_row_count": migration_result.conflicting_row_count,
        "ambiguous_row_count": migration_result.ambiguous_row_count,
        "unlabeled_row_count": migration_result.unlabeled_row_count,
        "seed_task_count": seed_package.task_count,
        "seeded_annotation_count": seed_package.seeded_annotation_count,
        "archive_source": archive_source,
        "migration_span_source": migration_span_source,
        "live_export": live_export_summary,
    }
    summary_path.write_text(
        json.dumps(summary, indent=2, sort_keys=True),
        encoding="utf-8",
    )


def _update_export_run_manifest(
    *,
    run_manifest_path: Path,
    existing_manifest: dict[str, Any],
    source_file: str,
    source_hash: str,
    source_rows_path: Path,
    written_paths: dict[str, Path],
    migration_span_path: Path,
) -> None:
    manifest = dict(existing_manifest)
    artifacts = dict(manifest.get("artifacts") or {})
    artifacts.update(
        {
            "source_rows_jsonl": _relative_or_absolute(source_rows_path, run_manifest_path.parent),
            "row_gold_labels_jsonl": _relative_or_absolute(written_paths["row_gold_path"], run_manifest_path.parent),
            "row_gold_ambiguous_jsonl": _relative_or_absolute(written_paths["ambiguous_path"], run_manifest_path.parent),
            "row_gold_conflicts_jsonl": _relative_or_absolute(written_paths["conflicts_path"], run_manifest_path.parent),
            "row_seed_tasks_jsonl": _relative_or_absolute(written_paths["seed_tasks_path"], run_manifest_path.parent),
            "migration_summary_json": _relative_or_absolute(written_paths["summary_path"], run_manifest_path.parent),
            "migration_freeform_span_labels_jsonl": _relative_or_absolute(
                migration_span_path,
                run_manifest_path.parent,
            ),
        }
    )
    manifest["artifacts"] = artifacts
    source_payload = dict(manifest.get("source") or {})
    source_payload["path"] = source_file
    source_payload["source_hash"] = source_hash
    manifest["source"] = source_payload
    run_manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True),
        encoding="utf-8",
    )


def _relative_or_absolute(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def _load_json_object(path: Path) -> dict[str, Any]:
    if not path.exists() or not path.is_file():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, dict):
        return payload
    return {}


def _read_json_list(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError(f"Expected list payload in {path}")
    return [row for row in payload if isinstance(row, dict)]


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        text = raw_line.strip()
        if not text:
            continue
        payload = json.loads(text)
        if isinstance(payload, dict):
            rows.append(payload)
    return rows


if __name__ == "__main__":
    raise SystemExit(main())
