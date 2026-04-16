from __future__ import annotations

from cookimport.bitter_recipe.ledger import (
    ensure_book_record,
    load_ledger,
    save_ledger,
    upsert_book_record,
)
from cookimport.bitter_recipe.paths import (
    bitter_recipe_ledger_path,
    bitter_recipe_pulled_root,
    bitter_recipe_sent_root,
    source_slug_for_path,
)
from cookimport.bitter_recipe.settings import (
    BitterRecipeSettings,
    load_settings,
    save_settings,
)


def test_settings_round_trip_and_paths(tmp_path) -> None:
    settings = BitterRecipeSettings(
        input_root=str(tmp_path / "input"),
        bitter_recipe_root=str(tmp_path / "bitter"),
        label_studio_url="http://localhost:8080",
        label_studio_api_key="token",
        segment_blocks=22,
        segment_overlap=4,
        segment_focus_blocks=18,
        default_prelabel=True,
    )

    path = save_settings(settings, tmp_path / "bitter-recipe.json")
    loaded = load_settings(path)

    assert loaded.input_root == settings.input_root
    assert loaded.bitter_recipe_root == settings.bitter_recipe_root
    assert loaded.segment_blocks == 22
    assert loaded.segment_focus_blocks == 18
    assert bitter_recipe_sent_root(loaded.bitter_recipe_root_path()) == (
        tmp_path / "bitter" / "sent-to-labelstudio"
    )
    assert bitter_recipe_pulled_root(loaded.bitter_recipe_root_path()) == (
        tmp_path / "bitter" / "pulled-from-labelstudio"
    )


def test_ledger_round_trip(tmp_path) -> None:
    ledger = load_ledger(tmp_path)
    ensure_book_record(
        ledger,
        source_slug="sample_book",
        source_path="data/input/sample_book.txt",
    )
    upsert_book_record(
        ledger,
        source_slug="sample_book",
        status="uploaded",
        project_name="sample_book source_rows_gold",
    )
    path = save_ledger(ledger, tmp_path)

    reloaded = load_ledger(tmp_path)

    assert path == bitter_recipe_ledger_path(tmp_path)
    assert reloaded["books"]["sample_book"]["status"] == "uploaded"
    assert (
        reloaded["books"]["sample_book"]["project_name"]
        == "sample_book source_rows_gold"
    )


def test_source_slug_for_path_normalizes_filename() -> None:
    assert source_slug_for_path("Salt Fat, Acid Heat Cutdown.epub") == (
        "salt_fat_acid_heat_cutdown"
    )
