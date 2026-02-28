from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from cookimport.cli import app

runner = CliRunner()


def test_stage_help_exposes_codex_farm_flags() -> None:
    result = runner.invoke(app, ["stage", "--help"], env={"COLUMNS": "240"})
    assert result.exit_code == 0
    assert "--llm-recipe-pipeline" in result.stdout
    assert "--llm-knowledge-pipeline" in result.stdout
    assert "--llm-tags-pipeline" in result.stdout
    assert "--codex-farm-cmd" in result.stdout
    assert "--codex-farm-root" in result.stdout
    assert "--codex-farm-workspace-root" in result.stdout
    assert "--codex-farm-pipeline-pass1" in result.stdout
    assert "--codex-farm-pipeline-pass2" in result.stdout
    assert "--codex-farm-pipeline-pass3" in result.stdout
    assert "--codex-farm-pipeline-pass4-knowledge" in result.stdout
    assert "--codex-farm-pipeline-pass5-tags" in result.stdout
    assert "--codex-farm-context-blocks" in result.stdout
    assert "--codex-farm-knowledge-context-blocks" in result.stdout
    assert "--tag-catalog-json" in result.stdout
    assert "--codex-farm-failure-mode" in result.stdout
    assert "--table-extraction" in result.stdout
    assert "COOKIMPORT_ALLOW_CODEX_FARM" in result.stdout
    assert "codex-farm-3pass-v1" in result.stdout


def test_stage_rejects_recipe_codex_farm_pipeline_enablement(tmp_path: Path) -> None:
    source = tmp_path / "book.txt"
    source.write_text("toast", encoding="utf-8")

    result = runner.invoke(
        app,
        [
            "stage",
            str(source),
            "--out",
            str(tmp_path / "out"),
            "--llm-recipe-pipeline",
            "codex-farm-3pass-v1",
        ],
    )
    assert result.exit_code == 1
    combined_output = str(getattr(result, "output", "") or "")
    assert "COOKIMPORT_ALLOW_CODEX_FARM" in combined_output
    assert "Set COOKIMPORT_ALLOW_CODEX_FARM=1" in combined_output
