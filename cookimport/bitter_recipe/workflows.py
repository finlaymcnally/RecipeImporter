from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from cookimport.bitter_recipe import adapters
from cookimport.bitter_recipe.ledger import (
    ensure_book_record,
    get_book_record,
    iter_book_records,
    load_ledger,
    save_ledger,
    upsert_book_record,
)
from cookimport.bitter_recipe.paths import (
    bitter_recipe_pulled_root,
    bitter_recipe_sent_root,
    list_importable_sources,
    source_slug_for_path,
)
from cookimport.bitter_recipe.settings import BitterRecipeSettings
from cookimport.plugins.registry import best_importer_for_path


_STATUS_ORDER = {
    "reviewed": 0,
    "exported": 1,
    "uploaded": 2,
    "failed": 3,
    "unstarted": 4,
}


def _timestamp() -> str:
    from datetime import datetime

    return datetime.now().strftime("%Y-%m-%d_%H.%M.%S")


def _load_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _validate_importable_source(path: Path) -> Path:
    resolved = path.expanduser()
    if not resolved.exists():
        raise RuntimeError(f"Source path not found: {resolved}")
    if not resolved.is_file():
        raise RuntimeError(f"Source path is not a file: {resolved}")
    _, score = best_importer_for_path(resolved)
    if score <= 0:
        raise RuntimeError(f"Source path is not importable by cookimport: {resolved}")
    return resolved


def _manifest_source_path(payload: dict[str, Any]) -> str | None:
    source_file = str(payload.get("source_file") or "").strip()
    if source_file:
        return source_file
    run_manifest_path = Path(payload.get("run_root") or "") / "run_manifest.json"
    if run_manifest_path.exists():
        run_manifest = _load_json(run_manifest_path)
        source = run_manifest.get("source")
        if isinstance(source, dict):
            candidate = str(source.get("path") or "").strip()
            if candidate:
                return candidate
    return None


def _discover_latest_uploads(settings: BitterRecipeSettings) -> dict[str, dict[str, Any]]:
    sent_root = bitter_recipe_sent_root(settings.bitter_recipe_root_path())
    latest: dict[str, tuple[float, dict[str, Any]]] = {}
    if not sent_root.exists():
        return {}
    for manifest_path in sent_root.glob("**/manifest.json"):
        payload = _load_json(manifest_path)
        source_path = _manifest_source_path(payload)
        if not source_path:
            continue
        slug = source_slug_for_path(source_path)
        try:
            mtime = manifest_path.stat().st_mtime
        except OSError:
            mtime = 0.0
        current = latest.get(slug)
        metadata = {
            "source_path": source_path,
            "project_name": str(payload.get("project_name") or "").strip() or None,
            "latest_upload_run_root": str(manifest_path.parent),
            "latest_upload_manifest_path": str(manifest_path),
            "uploaded_at": str(payload.get("created_at") or "") or None,
            "tasks_total": payload.get("tasks_total"),
            "tasks_uploaded": payload.get("uploaded_task_count"),
        }
        if current is None or mtime >= current[0]:
            latest[slug] = (mtime, metadata)
    return {slug: metadata for slug, (_mtime, metadata) in latest.items()}


def _discover_latest_exports(settings: BitterRecipeSettings) -> dict[str, dict[str, Any]]:
    pulled_root = bitter_recipe_pulled_root(settings.bitter_recipe_root_path())
    latest: dict[str, tuple[float, dict[str, Any]]] = {}
    if not pulled_root.exists():
        return {}
    for row_gold_path in pulled_root.glob("**/exports/row_gold_labels.jsonl"):
        run_root = row_gold_path.parent.parent
        slug = run_root.name
        try:
            mtime = row_gold_path.stat().st_mtime
        except OSError:
            mtime = 0.0
        exported_at = _timestamp()
        if mtime > 0:
            from datetime import datetime

            exported_at = datetime.fromtimestamp(mtime).strftime("%Y-%m-%d_%H.%M.%S")
        metadata = {
            "latest_export_run_root": str(run_root),
            "latest_export_root": str(row_gold_path.parent),
            "latest_row_gold_labels_path": str(row_gold_path),
            "exported_at": exported_at,
        }
        current = latest.get(slug)
        if current is None or mtime >= current[0]:
            latest[slug] = (mtime, metadata)
    return {slug: metadata for slug, (_mtime, metadata) in latest.items()}


def _derive_status(record: dict[str, Any]) -> str:
    if record.get("review_marked_at"):
        return "reviewed"
    export_path = str(record.get("latest_row_gold_labels_path") or "").strip()
    if export_path and Path(export_path).exists():
        return "exported"
    upload_root = str(record.get("latest_upload_run_root") or "").strip()
    if upload_root and Path(upload_root).exists():
        return "uploaded"
    if record.get("status") == "failed":
        return "failed"
    return "unstarted"


def refresh_status(settings: BitterRecipeSettings) -> dict[str, Any]:
    ledger = load_ledger(settings.bitter_recipe_root_path())
    for source_path in list_importable_sources(settings.input_root_path()):
        ensure_book_record(
            ledger,
            source_slug=source_slug_for_path(source_path),
            source_path=str(source_path),
        )

    for slug, metadata in _discover_latest_uploads(settings).items():
        upsert_book_record(
            ledger,
            source_slug=slug,
            source_path=metadata.get("source_path"),
            project_name=metadata.get("project_name"),
            latest_upload_run_root=metadata.get("latest_upload_run_root"),
            latest_upload_manifest_path=metadata.get("latest_upload_manifest_path"),
            uploaded_at=metadata.get("uploaded_at"),
        )

    for slug, metadata in _discover_latest_exports(settings).items():
        upsert_book_record(
            ledger,
            source_slug=slug,
            latest_export_run_root=metadata.get("latest_export_run_root"),
            latest_export_root=metadata.get("latest_export_root"),
            latest_row_gold_labels_path=metadata.get("latest_row_gold_labels_path"),
            exported_at=metadata.get("exported_at"),
        )

    for record in iter_book_records(ledger):
        record["status"] = _derive_status(record)

    save_ledger(ledger, settings.bitter_recipe_root_path())
    return ledger


def prepare_book(
    *,
    source_path: Path,
    settings: BitterRecipeSettings,
    project_name: str | None = None,
    prelabel: bool | None = None,
) -> dict[str, Any]:
    resolved = _validate_importable_source(source_path)
    slug = source_slug_for_path(resolved)
    ledger = refresh_status(settings)
    upsert_book_record(
        ledger,
        source_slug=slug,
        source_path=str(resolved),
        status="preparing",
        last_error=None,
    )
    save_ledger(ledger, settings.bitter_recipe_root_path())
    try:
        result = adapters.prepare_import(
            source_path=resolved,
            settings=settings,
            project_name=project_name,
            prelabel=prelabel,
        )
    except Exception as exc:  # noqa: BLE001
        ledger = load_ledger(settings.bitter_recipe_root_path())
        upsert_book_record(
            ledger,
            source_slug=slug,
            source_path=str(resolved),
            status="failed",
            last_error=str(exc),
        )
        save_ledger(ledger, settings.bitter_recipe_root_path())
        raise

    ledger = load_ledger(settings.bitter_recipe_root_path())
    record = upsert_book_record(
        ledger,
        source_slug=slug,
        source_path=str(resolved),
        status="uploaded",
        project_name=result.get("project_name"),
        latest_upload_run_root=str(result.get("run_root") or ""),
        latest_upload_manifest_path=str(result.get("manifest_path") or ""),
        uploaded_at=_timestamp(),
        last_error=None,
    )
    record["tasks_total"] = result.get("tasks_total")
    record["tasks_uploaded"] = result.get("tasks_uploaded")
    record["status"] = _derive_status(record)
    save_ledger(ledger, settings.bitter_recipe_root_path())
    return result


def _resolve_export_target(
    ledger: dict[str, Any],
    *,
    book: str | None = None,
    project_name: str | None = None,
) -> tuple[str, dict[str, Any] | None]:
    if book:
        record = get_book_record(ledger, book)
        if record is None:
            raise RuntimeError(f"Unknown bitter-recipe book slug: {book}")
        resolved_project_name = str(record.get("project_name") or "").strip()
        if not resolved_project_name:
            raise RuntimeError(f"Book '{book}' has no recorded Label Studio project name.")
        return resolved_project_name, record
    if project_name:
        for record in iter_book_records(ledger):
            if str(record.get("project_name") or "").strip() == project_name:
                return project_name, record
        return project_name, None
    raise RuntimeError("Choose a book slug or provide --project-name for export.")


def export_book(
    *,
    settings: BitterRecipeSettings,
    book: str | None = None,
    project_name: str | None = None,
) -> dict[str, Any]:
    ledger = refresh_status(settings)
    resolved_project_name, record = _resolve_export_target(
        ledger,
        book=book,
        project_name=project_name,
    )
    result = adapters.export_labels(
        project_name=resolved_project_name,
        settings=settings,
    )
    slug = book or (
        str(record.get("source_slug"))
        if isinstance(record, dict)
        else source_slug_for_path(Path(result["export_root"]).parent)
    )
    ledger = load_ledger(settings.bitter_recipe_root_path())
    current = upsert_book_record(
        ledger,
        source_slug=slug,
        project_name=resolved_project_name,
        status="exported",
        latest_export_run_root=str(result["export_root"].parent),
        latest_export_root=str(result["export_root"]),
        latest_row_gold_labels_path=str(result["export_root"] / "row_gold_labels.jsonl"),
        exported_at=_timestamp(),
        last_error=None,
    )
    current["status"] = _derive_status(current)
    save_ledger(ledger, settings.bitter_recipe_root_path())
    return result


def mark_reviewed(
    *,
    book: str,
    settings: BitterRecipeSettings,
) -> dict[str, Any]:
    ledger = refresh_status(settings)
    record = get_book_record(ledger, book)
    if record is None:
        raise RuntimeError(f"Unknown bitter-recipe book slug: {book}")
    updated = upsert_book_record(
        ledger,
        source_slug=book,
        review_marked_at=_timestamp(),
        status="reviewed",
    )
    updated["status"] = "reviewed"
    save_ledger(ledger, settings.bitter_recipe_root_path())
    return updated


def status_rows(
    settings: BitterRecipeSettings,
    *,
    refresh: bool = True,
) -> list[dict[str, Any]]:
    ledger = refresh_status(settings) if refresh else load_ledger(settings.bitter_recipe_root_path())
    rows = iter_book_records(ledger)
    rows.sort(
        key=lambda row: (
            _STATUS_ORDER.get(str(row.get("status") or "unstarted"), 99),
            str(row.get("source_slug") or ""),
        )
    )
    return rows
