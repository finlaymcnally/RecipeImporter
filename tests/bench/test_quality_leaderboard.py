from __future__ import annotations

import json
from pathlib import Path

import pytest

from cookimport.bench.quality_leaderboard import (
    build_quality_leaderboard,
    write_quality_leaderboard_artifacts,
)


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


@pytest.mark.bench
def test_quality_leaderboard_ranks_by_mean_practical_then_strict(tmp_path: Path) -> None:
    run_dir = tmp_path / "quality_run"
    experiment_id = "baseline"
    experiment_dir = run_dir / "experiments" / experiment_id
    report_dir = experiment_dir / "reports"

    _write_json(
        run_dir / "experiments_resolved.json",
        {
            "schema_version": 2,
            "experiments": [
                {
                    "id": experiment_id,
                    "run_settings": {
                        "multi_recipe_splitter": "legacy",
                        "section_detector_backend": "legacy",
                    },
                }
            ],
        },
    )

    _write_json(
        experiment_dir / "all_method_benchmark_multi_source_report.json",
        {
            "sources": [
                {
                    "source_group_key": "source_a",
                    "report_json_path": "reports/source_a.json",
                },
                {
                    "source_group_key": "source_b",
                    "report_json_path": "reports/source_b.json",
                },
            ]
        },
    )

    config_a_dims = {
        "epub_extractor": "beautifulsoup",
        "multi_recipe_splitter": "legacy",
        "source_extension": ".epub",
    }
    config_b_dims = {
        "epub_extractor": "unstructured",
        "multi_recipe_splitter": "legacy",
        "source_extension": ".epub",
    }
    config_a_dims_pdf = dict(config_a_dims)
    config_a_dims_pdf["source_extension"] = ".pdf"
    config_b_dims_pdf = dict(config_b_dims)
    config_b_dims_pdf["source_extension"] = ".pdf"

    _write_json(
        report_dir / "source_a.json",
        {
            "variants": [
                {
                    "status": "ok",
                    "dimensions": config_a_dims,
                    "practical_f1": 0.60,
                    "f1": 0.50,
                    "duration_seconds": 10.0,
                },
                {
                    "status": "ok",
                    "dimensions": config_b_dims,
                    "practical_f1": 0.50,
                    "f1": 0.40,
                    "duration_seconds": 5.0,
                },
            ]
        },
    )
    _write_json(
        report_dir / "source_b.json",
        {
            "variants": [
                {
                    "status": "ok",
                    "dimensions": config_a_dims_pdf,
                    "practical_f1": 0.60,
                    "f1": 0.50,
                    "duration_seconds": 12.0,
                },
                {
                    "status": "ok",
                    "dimensions": config_b_dims_pdf,
                    "practical_f1": 0.40,
                    "f1": 0.30,
                    "duration_seconds": 4.0,
                },
            ]
        },
    )

    payload = build_quality_leaderboard(
        run_dir=run_dir,
        experiment_id=experiment_id,
        allow_partial_coverage=False,
        include_by_source_extension=True,
    )
    assert payload["total_source_groups"] == 2
    winner = payload["winner"]
    assert isinstance(winner, dict)
    assert winner["rank"] == 1
    assert winner["dimensions"]["epub_extractor"] == "beautifulsoup"
    assert winner["coverage_sources"] == 2
    assert abs(float(winner["mean_practical_f1"]) - 0.60) < 1e-9

    winner_settings = payload.get("winner_run_settings")
    assert isinstance(winner_settings, dict)
    assert winner_settings.get("epub_extractor") == "beautifulsoup"
    assert winner_settings.get("multi_recipe_splitter") == "legacy"

    pareto = payload.get("pareto_frontier")
    assert isinstance(pareto, dict)
    ranked_frontier = pareto.get("ranked_set")
    assert isinstance(ranked_frontier, list)
    assert len(ranked_frontier) == 2
    by_extension = payload.get("leaderboard_by_source_extension")
    assert isinstance(by_extension, dict)
    assert sorted(by_extension) == [".epub", ".pdf"]
    assert by_extension[".epub"]["leaderboard"][0]["config_id"] == winner["config_id"]
    assert by_extension[".pdf"]["leaderboard"][0]["config_id"] == winner["config_id"]

    out_dir = tmp_path / "out"
    paths = write_quality_leaderboard_artifacts(payload, out_dir=out_dir)
    assert paths.leaderboard_json.exists()
    assert paths.leaderboard_csv.exists()
    assert paths.pareto_json.exists()
    assert paths.pareto_csv.exists()
    assert paths.winner_dimensions_json.exists()
    assert paths.leaderboard_by_source_extension_json is not None
    assert paths.leaderboard_by_source_extension_json.exists()
    assert paths.leaderboard_by_source_extension_csv is not None
    assert paths.leaderboard_by_source_extension_csv.exists()


@pytest.mark.bench
def test_quality_leaderboard_prefers_run_config_hash_for_identity(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "quality_run"
    experiment_id = "baseline"
    experiment_dir = run_dir / "experiments" / experiment_id
    source_dir = experiment_dir / "source_a"
    source_dir.mkdir(parents=True, exist_ok=True)

    _write_json(
        run_dir / "experiments_resolved.json",
        {
            "schema_version": 2,
            "experiments": [
                {
                    "id": experiment_id,
                    "run_settings": {
                        "multi_recipe_splitter": "legacy",
                    },
                }
            ],
        },
    )
    _write_json(
        experiment_dir / "all_method_benchmark_multi_source_report.json",
        {
            "sources": [
                {
                    "source_group_key": "source_a",
                    "report_json_path": "source_a/all_method_benchmark_report.json",
                }
            ]
        },
    )

    dims = {
        "epub_extractor": "beautifulsoup",
        "multi_recipe_splitter": "legacy",
        "source_extension": ".epub",
    }
    _write_json(
        source_dir / "all_method_benchmark_report.json",
        {
            "variants": [
                {
                    "status": "ok",
                    "dimensions": dims,
                    "run_config_hash": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
                    "run_config_summary": "epub_extractor=beautifulsoup",
                    "practical_f1": 0.10,
                    "f1": 0.10,
                    "duration_seconds": 5.0,
                },
                {
                    "status": "ok",
                    "dimensions": dims,
                    "run_config_hash": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
                    "run_config_summary": "epub_extractor=beautifulsoup",
                    "practical_f1": 0.20,
                    "f1": 0.20,
                    "duration_seconds": 6.0,
                },
            ]
        },
    )

    payload = build_quality_leaderboard(
        run_dir=run_dir,
        experiment_id=experiment_id,
        allow_partial_coverage=False,
    )
    leaderboard = payload.get("leaderboard")
    assert isinstance(leaderboard, list)
    assert len(leaderboard) == 2
    assert leaderboard[0]["run_config_hash"] == "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
    assert leaderboard[1]["run_config_hash"] == "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"


@pytest.mark.bench
def test_quality_leaderboard_winner_settings_prefers_prediction_run_config(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "quality_run"
    experiment_id = "baseline"
    experiment_dir = run_dir / "experiments" / experiment_id
    source_dir = experiment_dir / "source_a"
    config_dir = source_dir / "config_001_example"
    config_dir.mkdir(parents=True, exist_ok=True)

    _write_json(
        run_dir / "experiments_resolved.json",
        {
            "schema_version": 2,
            "experiments": [
                {
                    "id": experiment_id,
                    "run_settings": {
                        "epub_extractor": "beautifulsoup",
                        "instruction_step_segmentation_policy": "off",
                        "workers": 10,
                        "pdf_split_workers": 10,
                        "epub_split_workers": 10,
                    },
                }
            ],
        },
    )

    _write_json(
        experiment_dir / "all_method_benchmark_multi_source_report.json",
        {
            "sources": [
                {
                    "source_group_key": "source_a",
                    "report_json_path": "source_a/all_method_benchmark_report.json",
                }
            ]
        },
    )

    _write_json(
        source_dir / "all_method_benchmark_report.json",
        {
            "variants": [
                {
                    "status": "ok",
                    "dimensions": {
                        "epub_extractor": "unstructured",
                        "epub_unstructured_html_parser_version": "v2",
                        "epub_unstructured_preprocess_mode": "semantic_v1",
                    },
                    "run_config_hash": "winnerhash1234winnerhash1234",
                    "run_config_summary": "epub_extractor=unstructured",
                    "config_dir": "config_001_example",
                    "practical_f1": 0.9,
                    "f1": 0.8,
                    "duration_seconds": 3.0,
                }
            ]
        },
    )

    _write_json(
        config_dir / "run_manifest.json",
        {
            "run_config": {
                "epub_extractor": "beautifulsoup",
                "instruction_step_segmentation_policy": "off",
                "prediction_run_config": {
                    "effective_workers": 3,
                    "workers": 3,
                    "pdf_split_workers": 3,
                    "epub_split_workers": 3,
                    "epub_extractor": "unstructured",
                    "epub_unstructured_html_parser_version": "v2",
                    "epub_unstructured_preprocess_mode": "semantic_v1",
                    "instruction_step_segmentation_policy": "auto",
                    "llm_recipe_pipeline": "off",
                },
            }
        },
    )

    payload = build_quality_leaderboard(
        run_dir=run_dir,
        experiment_id=experiment_id,
        allow_partial_coverage=False,
    )

    winner_settings = payload.get("winner_run_settings")
    assert isinstance(winner_settings, dict)
    assert winner_settings.get("epub_extractor") == "unstructured"
    assert winner_settings.get("epub_unstructured_html_parser_version") == "v2"
    assert winner_settings.get("epub_unstructured_preprocess_mode") == "semantic_v1"
    assert winner_settings.get("instruction_step_segmentation_policy") == "auto"
    assert winner_settings.get("workers") == 10
    assert winner_settings.get("pdf_split_workers") == 10
    assert winner_settings.get("epub_split_workers") == 10
    assert "effective_workers" not in winner_settings


@pytest.mark.bench
def test_quality_leaderboard_includes_line_role_artifacts_when_present(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "quality_run"
    experiment_id = "baseline"
    experiment_dir = run_dir / "experiments" / experiment_id
    source_dir = experiment_dir / "source_a"
    config_dir = source_dir / "config_001_example"
    line_role_dir = config_dir / "line-role-pipeline"
    line_role_dir.mkdir(parents=True, exist_ok=True)

    _write_json(
        run_dir / "experiments_resolved.json",
        {
            "schema_version": 2,
            "experiments": [
                {
                    "id": experiment_id,
                    "run_settings": {
                        "multi_recipe_splitter": "legacy",
                    },
                }
            ],
        },
    )
    _write_json(
        experiment_dir / "all_method_benchmark_multi_source_report.json",
        {
            "sources": [
                {
                    "source_group_key": "source_a",
                    "report_json_path": "source_a/all_method_benchmark_report.json",
                }
            ]
        },
    )
    _write_json(
        source_dir / "all_method_benchmark_report.json",
        {
            "variants": [
                {
                    "status": "ok",
                    "dimensions": {
                        "epub_extractor": "unstructured",
                        "source_extension": ".epub",
                    },
                    "run_config_hash": "winnerhash1234winnerhash1234",
                    "run_config_summary": "epub_extractor=unstructured",
                    "config_dir": "config_001_example",
                    "practical_f1": 0.9,
                    "f1": 0.8,
                    "duration_seconds": 3.0,
                }
            ]
        },
    )
    (line_role_dir / "joined_line_table.jsonl").write_text("", encoding="utf-8")
    (line_role_dir / "line_role_flips_vs_baseline.jsonl").write_text(
        "", encoding="utf-8"
    )
    _write_json(
        line_role_dir / "slice_metrics.json",
        {
            "schema_version": "line_role_slice_metrics.v1",
            "line_count": 1,
            "slices": {"outside_recipe": {"line_count": 1}},
        },
    )
    _write_json(
        line_role_dir / "knowledge_budget.json",
        {
            "schema_version": "line_role_knowledge_budget.v1",
            "line_count": 1,
            "knowledge_pred_total": 0,
            "knowledge_pred_inside_recipe": 0,
            "knowledge_pred_outside_recipe": 0,
            "knowledge_inside_ratio": 0.0,
        },
    )
    _write_json(
        line_role_dir / "regression_gates.json",
        {"overall": {"verdict": "PASS"}, "gates": []},
    )

    payload = build_quality_leaderboard(
        run_dir=run_dir,
        experiment_id=experiment_id,
        allow_partial_coverage=False,
    )
    leaderboard = payload.get("leaderboard")
    assert isinstance(leaderboard, list)
    assert leaderboard
    winner = leaderboard[0]
    assert winner.get("line_role_gates_verdict") == "PASS"
    line_role_payload = winner.get("line_role")
    assert isinstance(line_role_payload, dict)
    assert (
        line_role_payload.get("line_role_dir")
        == "experiments/baseline/source_a/config_001_example/line-role-pipeline"
    )
