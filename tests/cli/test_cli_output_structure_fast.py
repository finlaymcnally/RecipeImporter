from __future__ import annotations

import inspect
from pathlib import Path

import pytest

import cookimport.cli as cli


def _default_value(param: inspect.Parameter):
    default = param.default
    return getattr(default, "default", default)


def test_load_settings_defaults_to_top_tier_profile(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(cli, "DEFAULT_CONFIG_PATH", tmp_path / "missing-cookimport.json")

    settings = cli._load_settings()

    assert settings["epub_extractor"] == "unstructured"
    assert settings["epub_unstructured_html_parser_version"] == "v1"
    assert settings["epub_unstructured_skip_headers_footers"] is True
    assert settings["epub_unstructured_preprocess_mode"] == "semantic_v1"
    assert settings["llm_recipe_pipeline"] == "codex-farm-3pass-v1"
    assert settings["line_role_pipeline"] == "codex-line-role-v1"
    assert settings["atomic_block_splitter"] == "atomic-v1"


def test_stage_command_defaults_to_top_tier_profile() -> None:
    params = inspect.signature(cli.stage).parameters

    assert _default_value(params["epub_unstructured_skip_headers_footers"]) is True
    assert _default_value(params["epub_unstructured_preprocess_mode"]) == "semantic_v1"
    assert _default_value(params["llm_recipe_pipeline"]) == "codex-farm-3pass-v1"


def test_labelstudio_import_defaults_to_codex_recipe_pipeline() -> None:
    params = inspect.signature(cli.labelstudio_import).parameters

    assert _default_value(params["llm_recipe_pipeline"]) == "codex-farm-3pass-v1"


def test_labelstudio_benchmark_defaults_to_top_tier_profile() -> None:
    params = inspect.signature(cli.labelstudio_benchmark).parameters

    assert params["epub_unstructured_skip_headers_footers"].default is True
    assert params["epub_unstructured_preprocess_mode"].default == "semantic_v1"
    assert params["llm_recipe_pipeline"].default == "codex-farm-3pass-v1"
    assert params["atomic_block_splitter"].default == "atomic-v1"
    assert params["line_role_pipeline"].default == "codex-line-role-v1"
