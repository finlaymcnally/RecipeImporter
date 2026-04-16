from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

from cookimport.bitter_recipe.paths import bitter_recipe_ledger_path


LEDGER_SCHEMA_VERSION = 1


def _utc_timestamp() -> str:
    from datetime import datetime

    return datetime.now().strftime("%Y-%m-%d_%H.%M.%S")


def empty_ledger() -> dict[str, Any]:
    return {"schema_version": LEDGER_SCHEMA_VERSION, "books": {}}


def load_ledger(root: Path | str | None = None) -> dict[str, Any]:
    ledger_path = bitter_recipe_ledger_path(root)
    if not ledger_path.exists():
        return empty_ledger()
    try:
        payload = json.loads(ledger_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return empty_ledger()
    if not isinstance(payload, dict):
        return empty_ledger()
    books = payload.get("books")
    if not isinstance(books, dict):
        return empty_ledger()
    return {
        "schema_version": int(payload.get("schema_version") or LEDGER_SCHEMA_VERSION),
        "books": deepcopy(books),
    }


def save_ledger(ledger: dict[str, Any], root: Path | str | None = None) -> Path:
    ledger_path = bitter_recipe_ledger_path(root)
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": int(ledger.get("schema_version") or LEDGER_SCHEMA_VERSION),
        "books": ledger.get("books") or {},
    }
    ledger_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return ledger_path


def ensure_book_record(
    ledger: dict[str, Any],
    *,
    source_slug: str,
    source_path: str | None = None,
) -> dict[str, Any]:
    books = ledger.setdefault("books", {})
    record = books.get(source_slug)
    if not isinstance(record, dict):
        record = {
            "source_slug": source_slug,
            "source_path": source_path,
            "status": "unstarted",
            "project_name": None,
            "latest_upload_run_root": None,
            "latest_upload_manifest_path": None,
            "latest_export_run_root": None,
            "latest_export_root": None,
            "latest_row_gold_labels_path": None,
            "review_marked_at": None,
            "uploaded_at": None,
            "exported_at": None,
            "last_error": None,
            "updated_at": _utc_timestamp(),
        }
        books[source_slug] = record
    elif source_path and not record.get("source_path"):
        record["source_path"] = source_path
    return record


def upsert_book_record(
    ledger: dict[str, Any],
    *,
    source_slug: str,
    source_path: str | None = None,
    **updates: Any,
) -> dict[str, Any]:
    record = ensure_book_record(ledger, source_slug=source_slug, source_path=source_path)
    record.update({key: value for key, value in updates.items()})
    record["updated_at"] = _utc_timestamp()
    return record


def get_book_record(ledger: dict[str, Any], source_slug: str) -> dict[str, Any] | None:
    books = ledger.get("books")
    if not isinstance(books, dict):
        return None
    record = books.get(source_slug)
    return record if isinstance(record, dict) else None


def iter_book_records(ledger: dict[str, Any]) -> list[dict[str, Any]]:
    books = ledger.get("books")
    if not isinstance(books, dict):
        return []
    rows = [record for record in books.values() if isinstance(record, dict)]
    return sorted(rows, key=lambda row: str(row.get("source_slug") or ""))
