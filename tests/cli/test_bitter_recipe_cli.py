from __future__ import annotations

from unittest.mock import patch

from typer.testing import CliRunner

from cookimport.cli import app

runner = CliRunner()


def test_bitter_recipe_help_lists_thin_commands() -> None:
    result = runner.invoke(app, ["bitter-recipe", "--help"], env={"COLUMNS": "240"})

    assert result.exit_code == 0
    assert "Corpus-first Label Studio workflow" in result.output
    assert "prepare" in result.output
    assert "export" in result.output
    assert "status" in result.output
    assert "mark-reviewed" in result.output
    assert "labelstudio-benchmark" not in result.output
    assert "compare-control" not in result.output


def test_bitter_recipe_status_command_renders_rows() -> None:
    with patch(
        "cookimport.bitter_recipe.app.workflows.status_rows",
        return_value=[
            {
                "status": "uploaded",
                "source_slug": "sample_book",
                "project_name": "sample_book source_rows_gold",
            }
        ],
    ):
        result = runner.invoke(app, ["bitter-recipe", "status"], env={"COLUMNS": "240"})

    assert result.exit_code == 0
    assert "sample_book" in result.output
    assert "uploaded" in result.output
