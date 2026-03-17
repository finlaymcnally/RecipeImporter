from __future__ import annotations

import click
import pytest
from typer.testing import CliRunner

from cookimport.cli import _normalize_llm_recipe_pipeline, app

runner = CliRunner()


def test_stage_help_exposes_codex_farm_flags() -> None:
    result = runner.invoke(app, ["stage", "--help"], env={"COLUMNS": "240"})
    assert result.exit_code == 0
    assert "--llm-recipe-pipeline" in result.stdout
    assert "--llm-knowledge-pipeline" in result.stdout
    assert "--codex-farm-cmd" in result.stdout
    assert "--codex-farm-root" in result.stdout
    assert "--codex-farm-workspace-root" in result.stdout
    assert "--codex-farm-context-blocks" in result.stdout
    assert "--codex-farm-knowledge-context-blocks" in result.stdout
    assert "--codex-farm-failure-mode" not in result.stdout
    assert "--ocr-device" not in result.stdout
    assert "--ocr-batch-size" not in result.stdout
    assert "--pdf-column-gap-ratio" not in result.stdout
    assert "--multi-recipe-splitter" not in result.stdout
    assert "--epub-unstructured-html-parser-version" not in result.stdout
    assert "--epub-unstructured-skip-headers-footers" not in result.stdout
    assert "--epub-unstructured-preprocess-mode" not in result.stdout
    assert "--web-schema-normalizer" not in result.stdout
    assert "--web-html-text-extractor" not in result.stdout
    assert "--web-schema-min-confidence" not in result.stdout
    assert "--web-schema-min-ingredients" not in result.stdout
    assert "--web-schema-min-instruction-steps" not in result.stdout
    assert "--ingredient-text-fix-backend" not in result.stdout
    assert "--recipe-scorer-backend" not in result.stdout
    assert "codex-farm-pipeline-pass" not in result.stdout
    assert "--codex-farm-pipeline-knowledge" not in result.stdout
    assert "--table-extraction" not in result.stdout
    assert "codex-recipe-shard-v1" in result.stdout
    assert "codex-farm-3pass-v1" not in result.stdout
    assert "codex-farm-2stage-repair-v1" not in result.stdout


def test_stage_accepts_recipe_codex_farm_pipeline_enablement() -> None:
    assert _normalize_llm_recipe_pipeline("codex-recipe-shard-v1") == (
        "codex-recipe-shard-v1"
    )


def test_stage_rejects_removed_recipe_codex_farm_pipeline_values() -> None:
    with pytest.raises(click.exceptions.Exit, match="1"):
        _normalize_llm_recipe_pipeline("codex-farm-3pass-v1")
    with pytest.raises(click.exceptions.Exit, match="1"):
        _normalize_llm_recipe_pipeline("codex-farm-2stage-repair-v1")


def test_benchmark_help_exposes_knowledge_codex_flags() -> None:
    result = runner.invoke(app, ["labelstudio-benchmark", "--help"], env={"COLUMNS": "240"})
    assert result.exit_code == 0
    assert "--llm-recipe-pipeline" in result.stdout
    assert "--llm-knowledge-pipeline" in result.stdout
    assert "--codex-farm-knowledge-context-blocks" in result.stdout
    assert "--ocr-device" not in result.stdout
    assert "--ocr-batch-size" not in result.stdout
    assert "--pdf-column-gap-ratio" not in result.stdout
    assert "--multi-recipe-splitter" not in result.stdout
    assert "--ingredient-text-fix-backend" not in result.stdout
    assert "--p6-time-backend" not in result.stdout
    assert "--recipe-scorer-backend" not in result.stdout
    assert "--line-role-guardrail-mode" not in result.stdout
    assert "--codex-farm-failure-mode" not in result.stdout
    assert "--codex-farm-pipeline-knowledge" not in result.stdout
    assert "--codex-farm-benchmark-selective-retry" not in result.stdout
    assert "--codex-farm-benchmark-selective-retry-max-attempts" not in result.stdout
