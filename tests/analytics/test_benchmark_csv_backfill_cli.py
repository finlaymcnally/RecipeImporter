from __future__ import annotations

import csv
import json
from pathlib import Path

from typer.testing import CliRunner

from cookimport.analytics.perf_report import _CSV_FIELDS
from cookimport.cli import app


runner = CliRunner()


def _write_benchmark_row(csv_path: Path, run_dir: Path) -> None:
    row = {field: "" for field in _CSV_FIELDS}
    row.update(
        {
            "run_timestamp": "2026-02-16T15:00:00",
            "run_dir": str(run_dir),
            "run_category": "benchmark_eval",
            "eval_scope": "freeform-spans",
        }
    )
    with csv_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=_CSV_FIELDS)
        writer.writeheader()
        writer.writerow(row)


def _write_prediction_manifest(
    eval_dir: Path,
    processed_report: Path,
    *,
    include_codex_runtime: bool = False,
) -> None:
    eval_dir.mkdir(parents=True, exist_ok=True)
    processed_report.parent.mkdir(parents=True, exist_ok=True)
    processed_report.write_text(json.dumps({"totalRecipes": 9}), encoding="utf-8")
    payload: dict[str, object] = {
        "recipe_count": 9,
        "processed_report_path": str(processed_report),
        "source_file": "book.epub",
    }
    if include_codex_runtime:
        payload["run_config"] = {
            "llm_recipe_pipeline": "codex-recipe-shard-v1",
            "codex_farm_model": "gpt-5.3-codex-spark",
            "codex_farm_reasoning_effort": "<default>",
        }
        payload["llm_codex_farm"] = {
            "process_runs": {
                "recipe_refine": {
                    "process_payload": {
                        "codex_model": "gpt-5.3-codex-spark",
                        "codex_reasoning_effort": None,
                        "telemetry": {
                            "rows": [
                                {
                                    "tokens_input": 111,
                                    "tokens_cached_input": 22,
                                    "tokens_output": 33,
                                    "tokens_reasoning": 4,
                                    "tokens_total": 148,
                                }
                            ]
                        },
                    }
                }
            }
        }
    (eval_dir / "manifest.json").write_text(
        json.dumps(payload),
        encoding="utf-8",
    )


def test_benchmark_csv_backfill_cli_dry_run_does_not_write(
    tmp_path: Path,
    monkeypatch,
) -> None:
    csv_path = tmp_path / "output" / ".history" / "performance_history.csv"
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    eval_dir = tmp_path / "golden" / "eval-vs-pipeline" / "2026-02-16_15.00.00"
    processed_report = (
        tmp_path / "output" / "2026-02-16_14.59.00" / "book.excel_import_report.json"
    )

    _write_benchmark_row(csv_path, eval_dir)
    _write_prediction_manifest(eval_dir, processed_report)

    captured_dashboard_calls: list[dict[str, object]] = []

    def fake_stats_dashboard(**kwargs):
        captured_dashboard_calls.append(kwargs)

    monkeypatch.setattr("cookimport.cli_commands.analytics.stats_dashboard", fake_stats_dashboard)

    result = runner.invoke(
        app,
        ["benchmark-csv-backfill", "--history-csv", str(csv_path), "--dry-run"],
    )
    assert result.exit_code == 0
    assert "Rows updated: 1" in result.stdout
    assert captured_dashboard_calls == []

    with csv_path.open("r", newline="", encoding="utf-8") as fh:
        row = next(csv.DictReader(fh))
    assert row["recipes"] == ""
    assert row["report_path"] == ""
    assert row["file_name"] == ""


def test_benchmark_csv_backfill_cli_writes_updates(
    tmp_path: Path,
    monkeypatch,
) -> None:
    csv_path = tmp_path / "output" / ".history" / "performance_history.csv"
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    eval_dir = tmp_path / "golden" / "eval-vs-pipeline" / "2026-02-16_15.30.00"
    processed_report = (
        tmp_path / "output" / "2026-02-16_15.29.00" / "book.excel_import_report.json"
    )

    _write_benchmark_row(csv_path, eval_dir)
    _write_prediction_manifest(eval_dir, processed_report)

    captured_dashboard: dict[str, object] = {}

    def fake_stats_dashboard(**kwargs):
        captured_dashboard.update(kwargs)

    def fake_refresh_dashboard_after_history_write(
        *,
        csv_path,
        output_root=None,
        golden_root,
        dashboard_out_dir=None,
        reason=None,
    ):
        del reason
        if output_root is None:
            from cookimport import cli_support as runtime

            output_root = runtime._infer_output_root_from_history_csv(csv_path)
        fake_stats_dashboard(
            output_root=output_root,
            golden_root=golden_root,
            out_dir=dashboard_out_dir or (csv_path.parent / "dashboard"),
            open_browser=False,
            since_days=None,
            scan_reports=False,
            scan_benchmark_reports=False,
        )

    monkeypatch.setattr(
        "cookimport.cli_commands.analytics._refresh_dashboard_after_history_write",
        fake_refresh_dashboard_after_history_write,
    )

    result = runner.invoke(
        app,
        ["benchmark-csv-backfill", "--history-csv", str(csv_path)],
    )
    assert result.exit_code == 0
    assert "Rows updated: 1" in result.stdout
    assert "Recipes filled: 1" in result.stdout
    assert "Report paths filled: 1" in result.stdout
    assert captured_dashboard["output_root"] == (
        csv_path.parent.parent / "__dashboard_refresh__"
    )
    assert captured_dashboard["out_dir"] == csv_path.parent / "dashboard"
    assert captured_dashboard["open_browser"] is False
    assert captured_dashboard["since_days"] is None
    assert captured_dashboard["scan_reports"] is False
    assert captured_dashboard["scan_benchmark_reports"] is False

    with csv_path.open("r", newline="", encoding="utf-8") as fh:
        row = next(csv.DictReader(fh))
    assert row["recipes"] == "9"
    assert row["report_path"] == str(processed_report)
    assert row["file_name"] == "book.epub"


def test_benchmark_csv_backfill_cli_backfills_codex_runtime_config(
    tmp_path: Path,
    monkeypatch,
) -> None:
    csv_path = tmp_path / "output" / ".history" / "performance_history.csv"
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    eval_dir = tmp_path / "golden" / "eval-vs-pipeline" / "2026-02-16_15.35.00"
    processed_report = (
        tmp_path / "output" / "2026-02-16_15.34.00" / "book.excel_import_report.json"
    )
    codex_home = tmp_path / "codex-home"
    codex_home.mkdir(parents=True, exist_ok=True)
    (codex_home / "models_cache.json").write_text(
        json.dumps(
            {
                "models": [
                    {
                        "slug": "gpt-5.3-codex-spark",
                        "default_reasoning_level": "high",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("CODEX_HOME", str(codex_home))

    _write_benchmark_row(csv_path, eval_dir)
    _write_prediction_manifest(
        eval_dir,
        processed_report,
        include_codex_runtime=True,
    )
    monkeypatch.setattr(
        "cookimport.cli_commands.analytics._refresh_dashboard_after_history_write",
        lambda **_: None,
    )

    result = runner.invoke(
        app,
        ["benchmark-csv-backfill", "--history-csv", str(csv_path)],
    )
    assert result.exit_code == 0
    assert "Run config fields filled: 1" in result.stdout
    assert "Codex model fields filled: 1" in result.stdout
    assert "Codex effort fields filled: 1" in result.stdout
    assert "Token rows filled: 1" in result.stdout
    assert "Token fields filled: 5" in result.stdout

    with csv_path.open("r", newline="", encoding="utf-8") as fh:
        row = next(csv.DictReader(fh))
    run_config = json.loads(row["run_config_json"])
    assert run_config["codex_farm_model"] == "gpt-5.3-codex-spark"
    assert run_config["codex_farm_reasoning_effort"] == "high"
    assert row["run_config_hash"] != ""
    assert "codex_farm_model=gpt-5.3-codex-spark" in row["run_config_summary"]
    assert "codex_farm_reasoning_effort=high" in row["run_config_summary"]
    assert row["tokens_input"] == "111"
    assert row["tokens_cached_input"] == "22"
    assert row["tokens_output"] == "33"
    assert row["tokens_reasoning"] == "4"
    assert row["tokens_total"] == "148"
