from __future__ import annotations

from pathlib import Path

from cookimport.bitter_recipe.ledger import load_ledger
from cookimport.bitter_recipe.settings import BitterRecipeSettings
from cookimport.bitter_recipe.workflows import (
    export_book,
    mark_reviewed,
    prepare_book,
    refresh_status,
    status_rows,
)


def _settings(tmp_path: Path) -> BitterRecipeSettings:
    input_root = tmp_path / "input"
    input_root.mkdir(parents=True, exist_ok=True)
    return BitterRecipeSettings(
        input_root=str(input_root),
        bitter_recipe_root=str(tmp_path / "bitter"),
        label_studio_url="http://localhost:8080",
        label_studio_api_key="token",
    )


def test_refresh_status_discovers_unstarted_books(tmp_path) -> None:
    settings = _settings(tmp_path)
    source_path = Path(settings.input_root) / "sample_book.txt"
    source_path.write_text("hello\nworld\n", encoding="utf-8")

    ledger = refresh_status(settings)

    record = ledger["books"]["sample_book"]
    assert record["status"] == "unstarted"
    assert record["source_path"] == str(source_path)


def test_prepare_book_updates_ledger(tmp_path, monkeypatch) -> None:
    settings = _settings(tmp_path)
    source_path = Path(settings.input_root) / "sample_book.txt"
    source_path.write_text("hello\nworld\n", encoding="utf-8")
    run_root = tmp_path / "bitter" / "sent-to-labelstudio" / "2026-04-15_22.00.00" / "labelstudio" / "sample_book"
    run_root.mkdir(parents=True, exist_ok=True)
    manifest_path = run_root / "manifest.json"
    manifest_path.write_text("{}", encoding="utf-8")

    monkeypatch.setattr(
        "cookimport.bitter_recipe.workflows.adapters.prepare_import",
        lambda **_kwargs: {
            "project_name": "sample_book source_rows_gold",
            "run_root": run_root,
            "manifest_path": manifest_path,
            "tasks_total": 12,
            "tasks_uploaded": 12,
        },
    )

    prepare_book(source_path=source_path, settings=settings, prelabel=False)
    ledger = load_ledger(settings.bitter_recipe_root_path())
    record = ledger["books"]["sample_book"]

    assert record["status"] == "uploaded"
    assert record["project_name"] == "sample_book source_rows_gold"
    assert record["latest_upload_run_root"] == str(run_root)
    assert record["tasks_total"] == 12
    assert record["tasks_uploaded"] == 12


def test_export_and_mark_reviewed_update_ledger(tmp_path, monkeypatch) -> None:
    settings = _settings(tmp_path)
    source_path = Path(settings.input_root) / "sample_book.txt"
    source_path.write_text("hello\nworld\n", encoding="utf-8")
    refresh_status(settings)
    ledger = load_ledger(settings.bitter_recipe_root_path())
    ledger["books"]["sample_book"]["project_name"] = "sample_book source_rows_gold"
    ledger["books"]["sample_book"]["latest_upload_run_root"] = "uploaded-root"
    ledger["books"]["sample_book"]["status"] = "uploaded"
    from cookimport.bitter_recipe.ledger import save_ledger

    save_ledger(ledger, settings.bitter_recipe_root_path())

    export_root = tmp_path / "bitter" / "pulled-from-labelstudio" / "sample_book" / "exports"
    export_root.mkdir(parents=True, exist_ok=True)
    (export_root / "row_gold_labels.jsonl").write_text("", encoding="utf-8")

    monkeypatch.setattr(
        "cookimport.bitter_recipe.workflows.adapters.export_labels",
        lambda **_kwargs: {"export_root": export_root},
    )

    export_book(settings=settings, book="sample_book")
    rows = status_rows(settings)
    assert rows[0]["status"] == "exported"

    mark_reviewed(book="sample_book", settings=settings)
    rows = status_rows(settings)
    assert rows[0]["status"] == "reviewed"
