from __future__ import annotations

import json

from cookimport.config.last_run_store import load_last_run_settings, save_last_run_settings
from cookimport.config.run_settings import (
    RunSettings,
    compute_effective_workers,
    run_settings_ui_specs,
)


def test_run_settings_hash_and_summary_are_stable() -> None:
    settings = RunSettings()

    assert settings.stable_hash() == settings.stable_hash()
    assert settings.short_hash() == settings.stable_hash()[:12]
    assert settings.to_run_config_dict()["epub_extractor"] == "unstructured"
    assert "workers=7" in settings.summary()


def test_run_settings_schema_evolution_ignores_unknown_keys() -> None:
    settings = RunSettings.from_dict({"workers": 3, "unknown_new_field": "x"})

    assert settings.workers == 3
    assert settings.pdf_split_workers == 7
    assert "unknown_new_field" not in settings.to_run_config_dict()


def test_run_settings_ui_specs_cover_all_editable_fields() -> None:
    specs = run_settings_ui_specs()
    by_name = {spec.name for spec in specs}
    expected = {
        name
        for name, field in RunSettings.model_fields.items()
        if not dict(field.json_schema_extra or {}).get("ui_hidden")
    }
    assert by_name == expected


def test_last_run_store_round_trip_and_corrupt_recovery(tmp_path) -> None:
    output_root = tmp_path / "output"
    original = RunSettings(workers=9, epub_extractor="legacy")

    save_last_run_settings("import", output_root, original)
    loaded = load_last_run_settings("import", output_root)

    assert loaded == original

    store_path = output_root / ".history" / "last_run_settings_import.json"
    store_path.write_text("{broken", encoding="utf-8")
    assert load_last_run_settings("import", output_root) is None

    store_path.write_text(json.dumps({"workers": 5}), encoding="utf-8")
    migrated = load_last_run_settings("import", output_root)
    assert migrated is not None
    assert migrated.workers == 5


def test_compute_effective_workers_does_not_promote_markitdown_epub_splits() -> None:
    effective = compute_effective_workers(
        workers=4,
        epub_split_workers=12,
        epub_extractor="markitdown",
        all_epub=True,
    )

    assert effective == 4
