from __future__ import annotations

import tests.bench.quality_suite_runner_support as _support

# Reuse shared imports/helpers from the local support module.
globals().update({
    name: value
    for name, value in _support.__dict__.items()
    if not name.startswith("test_")
    and not (name.startswith("__") and name.endswith("__"))
})


def test_run_quality_suite_checkpoints_partial_progress_before_resume(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    fixture = _run_quality_suite_resume_fixture(monkeypatch, tmp_path)
    attempts = fixture["attempts"]
    run_root = fixture["run_root"]
    partial_checkpoint = fixture["partial_checkpoint"]
    partial_summary = fixture["partial_summary"]

    assert attempts["baseline"] == 1
    assert attempts["candidate"] == 2
    assert (run_root / "experiments" / "baseline" / "quality_experiment_result.json").exists()
    assert partial_checkpoint["experiment_count_total"] == 2
    assert partial_checkpoint["experiment_count_completed"] == 1
    assert partial_checkpoint["status"] == "in_progress"
    assert partial_checkpoint["pending_experiment_ids"] == ["candidate"]
    assert [row["id"] for row in partial_summary["experiments"]] == ["baseline"]


def test_run_quality_suite_resumes_partial_run_to_complete_summary(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    fixture = _run_quality_suite_resume_fixture(monkeypatch, tmp_path)
    run_root = fixture["run_root"]
    resumed_run_root = fixture["resumed_run_root"]
    summary = fixture["summary"]
    checkpoint = fixture["checkpoint"]

    assert resumed_run_root == run_root
    assert [row["id"] for row in summary["experiments"]] == ["baseline", "candidate"]
    assert all(row["status"] == "ok" for row in summary["experiments"])
    assert checkpoint["status"] == "complete"
    assert checkpoint["experiment_count_completed"] == 2
    assert checkpoint["pending_experiment_ids"] == []


def test_run_quality_suite_resume_rejects_mismatched_experiments(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    suite = _build_suite(tmp_path)
    experiments_file = tmp_path / "experiments_resume_guard.json"
    _write_json(
        experiments_file,
        {
            "schema_version": 1,
            "experiments": [{"id": "baseline", "run_settings_patch": {}}],
        },
    )
    base_run_settings_file = tmp_path / "base_run_settings.json"
    _write_json(base_run_settings_file, {"workers": 2})

    monkeypatch.setattr(
        "cookimport.cli._resolve_all_method_codex_choice",
        lambda _include_codex: (False, None),
    )
    monkeypatch.setattr(
        "cookimport.cli._resolve_all_method_markdown_extractors_choice",
        lambda: False,
    )
    monkeypatch.setattr(
        "cookimport.cli._build_all_method_target_variants",
        lambda **_kwargs: [],
    )

    def _fake_run_all_method_multi_source(**kwargs):
        root_output_dir = Path(kwargs["root_output_dir"])
        root_output_dir.mkdir(parents=True, exist_ok=True)
        source_report = (
            root_output_dir
            / "sources"
            / root_output_dir.name
            / "all_method_benchmark_report.json"
        )
        _write_json(
            source_report,
            {
                "winner_by_f1": {
                    "precision": 0.6,
                    "recall": 0.6,
                    "f1": 0.6,
                    "practical_precision": 0.7,
                    "practical_recall": 0.7,
                    "practical_f1": 0.7,
                }
            },
        )
        report_md_path = root_output_dir / "all_method_benchmark_multi_source_report.md"
        _write_json(
            report_md_path.with_suffix(".json"),
            {
                "matched_target_count": 1,
                "total_config_runs_planned": 1,
                "total_config_runs_completed": 1,
                "total_config_runs_successful": 1,
                "evaluation_signatures_unique": 1,
                "evaluation_runs_executed": 1,
                "evaluation_results_reused_in_run": 0,
                "evaluation_results_reused_cross_run": 0,
                "sources": [
                    {
                        "source_group_key": root_output_dir.name,
                        "status": "ok",
                        "source_shard_total": 1,
                        "report_json_path": str(
                            source_report.relative_to(root_output_dir)
                        ),
                        "winner_metrics": {"precision": 0.6, "recall": 0.6, "f1": 0.6},
                    }
                ],
            },
        )
        report_md_path.write_text("report", encoding="utf-8")
        return report_md_path

    monkeypatch.setattr(
        "cookimport.cli._run_all_method_benchmark_multi_source",
        _fake_run_all_method_multi_source,
    )

    run_root = run_quality_suite(
        suite,
        tmp_path / "runs",
        experiments_file=experiments_file,
        base_run_settings_file=base_run_settings_file,
        search_strategy="exhaustive",
        max_parallel_experiments=1,
        progress_callback=None,
    )

    mismatched_experiments = tmp_path / "experiments_resume_guard_mismatch.json"
    _write_json(
        mismatched_experiments,
        {
            "schema_version": 1,
            "experiments": [
                {"id": "baseline", "run_settings_patch": {}},
                {"id": "candidate", "run_settings_patch": {"workers": 3}},
            ],
        },
    )

    with pytest.raises(ValueError) as excinfo:
        run_quality_suite(
            suite,
            tmp_path / "runs",
            experiments_file=mismatched_experiments,
            base_run_settings_file=base_run_settings_file,
            search_strategy="exhaustive",
            max_parallel_experiments=1,
            resume_run_dir=run_root,
            progress_callback=None,
        )

    assert "experiment layout does not match" in str(excinfo.value)


def test_run_quality_suite_rejects_unknown_patch_keys(tmp_path: Path) -> None:
    suite = _build_suite(tmp_path)
    experiments_file = tmp_path / "experiments_bad.json"
    _write_json(
        experiments_file,
        {
            "schema_version": 1,
            "experiments": [
                {"id": "baseline", "run_settings_patch": {"unknown_knob": 1}},
            ],
        },
    )
    base_run_settings_file = tmp_path / "base_run_settings.json"
    _write_json(base_run_settings_file, {})

    with pytest.raises(ValueError) as excinfo:
        run_quality_suite(
            suite,
            tmp_path / "runs",
            experiments_file=experiments_file,
            base_run_settings_file=base_run_settings_file,
            progress_callback=None,
        )

    assert "unknown run_settings_patch key" in str(excinfo.value)


def test_run_quality_suite_rejects_include_codex_farm(
    tmp_path: Path,
) -> None:
    suite = _build_suite(tmp_path)
    experiments_file = tmp_path / "experiments.json"
    _write_json(
        experiments_file,
        {
            "schema_version": 1,
            "experiments": [{"id": "baseline", "run_settings_patch": {}}],
        },
    )
    base_run_settings_file = tmp_path / "base_run_settings.json"
    _write_json(base_run_settings_file, {})

    with pytest.raises(ValueError) as excinfo:
        run_quality_suite(
            suite,
            tmp_path / "runs",
            experiments_file=experiments_file,
            base_run_settings_file=base_run_settings_file,
            include_codex_farm_requested=True,
            codex_farm_confirmed=True,
            progress_callback=None,
        )

    assert "forbids Codex Farm permutations" in str(excinfo.value)


def test_run_quality_suite_rejects_codex_farm_enabled_requested_settings(
    tmp_path: Path,
) -> None:
    suite = _build_suite(tmp_path)
    experiments_file = tmp_path / "experiments_codex_requested.json"
    _write_json(
        experiments_file,
        {
            "schema_version": 1,
            "experiments": [{"id": "baseline", "run_settings_patch": {}}],
        },
    )
    base_run_settings_file = tmp_path / "base_run_settings.json"
    _write_json(
        base_run_settings_file,
        {"llm_recipe_pipeline": "codex-recipe-shard-v1"},
    )

    with pytest.raises(ValueError) as excinfo:
        run_quality_suite(
            suite,
            tmp_path / "runs",
            experiments_file=experiments_file,
            base_run_settings_file=base_run_settings_file,
            progress_callback=None,
        )

    assert "forbids Codex Farm-enabled requested settings" in str(excinfo.value)
