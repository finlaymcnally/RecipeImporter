from __future__ import annotations

import inspect
from pathlib import Path

import pytest

import cookimport.cli as cli
from cookimport.config.run_settings import RunSettings


def _default_value(param: inspect.Parameter):
    default = param.default
    return getattr(default, "default", default)


def _serialized(value):
    return getattr(value, "value", value)


def test_load_settings_matches_current_run_settings_defaults(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(cli, "DEFAULT_CONFIG_PATH", tmp_path / "missing-cookimport.json")
    monkeypatch.setattr(cli, "DEFAULT_LOCAL_CONFIG_PATH", tmp_path / "missing-cookimport.local.json")

    settings = cli._load_settings()
    expected = RunSettings().to_run_config_dict()

    for key in (
        "epub_extractor",
        "epub_unstructured_html_parser_version",
        "epub_unstructured_skip_headers_footers",
        "epub_unstructured_preprocess_mode",
        "llm_recipe_pipeline",
        "line_role_pipeline",
        "atomic_block_splitter",
    ):
        assert settings[key] == expected[key]


def test_stage_command_defaults_follow_run_settings_defaults() -> None:
    params = inspect.signature(cli.stage).parameters
    defaults = RunSettings()

    assert (
        _default_value(params["epub_unstructured_skip_headers_footers"])
        == defaults.epub_unstructured_skip_headers_footers
    )
    assert (
        _default_value(params["epub_unstructured_preprocess_mode"])
        == _serialized(defaults.epub_unstructured_preprocess_mode)
    )
    assert _default_value(params["llm_recipe_pipeline"]) == _serialized(
        defaults.llm_recipe_pipeline
    )


def test_labelstudio_import_defaults_follow_run_settings_defaults() -> None:
    params = inspect.signature(cli.labelstudio_import).parameters
    defaults = RunSettings()

    assert _default_value(params["llm_recipe_pipeline"]) == _serialized(
        defaults.llm_recipe_pipeline
    )


def test_labelstudio_benchmark_defaults_to_safe_opt_in_profile() -> None:
    params = inspect.signature(cli.labelstudio_benchmark).parameters

    assert params["epub_unstructured_skip_headers_footers"].default is True
    assert params["epub_unstructured_preprocess_mode"].default == "br_split_v1"
    assert params["llm_recipe_pipeline"].default == "off"
    assert params["atomic_block_splitter"].default == "off"
    assert params["line_role_pipeline"].default == "off"
