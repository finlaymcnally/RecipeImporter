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
    assert (
        settings.to_run_config_dict()["epub_unstructured_html_parser_version"] == "v1"
    )
    assert settings.to_run_config_dict()["epub_unstructured_skip_headers_footers"] is False
    assert settings.to_run_config_dict()["epub_unstructured_preprocess_mode"] == "br_split_v1"
    assert settings.to_run_config_dict()["table_extraction"] == "off"
    assert settings.to_run_config_dict()["llm_recipe_pipeline"] == "off"
    assert settings.to_run_config_dict()["llm_knowledge_pipeline"] == "off"
    assert settings.to_run_config_dict()["llm_tags_pipeline"] == "off"
    assert settings.to_run_config_dict()["codex_farm_cmd"] == "codex-farm"
    assert settings.to_run_config_dict()["codex_farm_pipeline_pass1"] == "recipe.chunking.v1"
    assert settings.to_run_config_dict()["codex_farm_pipeline_pass2"] == "recipe.schemaorg.v1"
    assert settings.to_run_config_dict()["codex_farm_pipeline_pass3"] == "recipe.final.v1"
    assert (
        settings.to_run_config_dict()["codex_farm_pipeline_pass4_knowledge"]
        == "recipe.knowledge.v1"
    )
    assert (
        settings.to_run_config_dict()["codex_farm_pipeline_pass5_tags"]
        == "recipe.tags.v1"
    )
    assert settings.to_run_config_dict()["codex_farm_context_blocks"] == 30
    assert settings.to_run_config_dict()["codex_farm_knowledge_context_blocks"] == 12
    assert settings.to_run_config_dict()["tag_catalog_json"] == "data/tagging/tag_catalog.json"
    assert settings.to_run_config_dict()["codex_farm_failure_mode"] == "fail"
    assert "codex_farm_workspace_root" not in settings.to_run_config_dict()
    assert "workers=7" in settings.summary()


def test_run_settings_schema_evolution_ignores_unknown_keys() -> None:
    settings = RunSettings.from_dict({"workers": 3, "unknown_new_field": "x"})

    assert settings.workers == 3
    assert settings.pdf_split_workers == 7
    assert "unknown_new_field" not in settings.to_run_config_dict()


def test_run_settings_forces_recipe_codex_farm_pipeline_off() -> None:
    settings = RunSettings.from_dict({"llm_recipe_pipeline": "codex-farm-3pass-v1"})

    assert settings.llm_recipe_pipeline.value == "off"


def test_run_settings_ui_specs_cover_all_editable_fields() -> None:
    specs = run_settings_ui_specs()
    by_name = {spec.name for spec in specs}
    expected = {
        name
        for name, field in RunSettings.model_fields.items()
        if not dict(field.json_schema_extra or {}).get("ui_hidden")
    }
    assert by_name == expected
    llm_recipe_spec = next(spec for spec in specs if spec.name == "llm_recipe_pipeline")
    assert llm_recipe_spec.choices == ("off",)
    llm_tags_spec = next(spec for spec in specs if spec.name == "llm_tags_pipeline")
    assert llm_tags_spec.choices == ("off", "codex-farm-tags-v1")


def test_last_run_store_round_trip_and_corrupt_recovery(tmp_path) -> None:
    output_root = tmp_path / "output"
    original = RunSettings(workers=9, epub_extractor="legacy")

    save_last_run_settings("import", output_root, original)
    loaded = load_last_run_settings("import", output_root)

    assert loaded == original

    store_path = output_root.parent / ".history" / "last_run_settings_import.json"
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


def test_compute_effective_workers_promotes_unstructured_epub_splits() -> None:
    effective = compute_effective_workers(
        workers=4,
        epub_split_workers=12,
        epub_extractor="unstructured",
        all_epub=True,
    )

    assert effective == 12


def test_run_settings_migrates_legacy_auto_extractor_to_unstructured() -> None:
    settings = RunSettings.from_dict({"epub_extractor": "auto"}, warn_context="test")

    assert settings.epub_extractor.value == "unstructured"
