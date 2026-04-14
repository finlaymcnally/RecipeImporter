#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from cookimport.config.run_settings import RunSettings
from cookimport.labelstudio.archive import build_extracted_archive
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

        migration_result = migrate_freeform_export_to_row_gold(
            freeform_span_labels_jsonl_path=freeform_path,
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
        )
        _update_export_run_manifest(
            run_manifest_path=run_manifest_path,
            existing_manifest=run_manifest,
            source_file=source_file,
            source_hash=source_hash,
            source_rows_path=source_rows_path,
            written_paths=written_paths,
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
                "source_rows_path": str(source_rows_path),
                "row_gold_labels_path": str(written_paths["row_gold_path"]),
            }
        )
        print(
            f"{slug}: migrated {migration_result.migrated_labeled_row_count} rows "
            f"(ambiguous={migration_result.ambiguous_row_count}, "
            f"conflicts={migration_result.conflicting_row_count}, "
            f"seed_tasks={seed_package.task_count}) via {archive_source}"
        )

    batch_summary_path = args.pulled_root / "source_rows_migration_summary.json"
    batch_summary_path.write_text(
        json.dumps({"exports": batch_rows}, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    print(f"Wrote batch summary: {batch_summary_path}")
    return 0


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
