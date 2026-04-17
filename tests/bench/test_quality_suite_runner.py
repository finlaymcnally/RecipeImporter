from __future__ import annotations

import tests.bench.quality_suite_runner_support as _support

# Reuse shared imports/helpers from the local support module.
globals().update({
    name: value
    for name, value in _support.__dict__.items()
    if not name.startswith("test_")
    and not (name.startswith("__") and name.endswith("__"))
})


def test_run_quality_suite_writes_artifacts_and_cache_roots(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    fixture = _run_quality_suite_failure_fixture(monkeypatch, tmp_path)
    run_root = fixture["run_root"]
    progress_messages = fixture["progress_messages"]
    observed_cache_roots = fixture["observed_cache_roots"]
    observed_prediction_reuse_roots = fixture["observed_prediction_reuse_roots"]
    observed_golden_roots = fixture["observed_golden_roots"]
    assert isinstance(run_root, Path)

    assert progress_messages
    assert "task 1/2" in progress_messages[0]
    assert (run_root / "suite_resolved.json").exists()
    assert (run_root / "experiments_resolved.json").exists()
    assert (run_root / "summary.json").exists()
    assert (run_root / "report.md").exists()

    resolved = json.loads((run_root / "experiments_resolved.json").read_text(encoding="utf-8"))
    assert Path(resolved["canonical_alignment_cache_root"]) == (
        tmp_path / ".cache" / "canonical_alignment"
    )
    assert Path(resolved["prediction_reuse_cache_root"]) == (
        tmp_path / ".cache" / "prediction_reuse"
    )
    assert observed_cache_roots
    assert observed_cache_roots[0] == (
        tmp_path / ".cache" / "canonical_alignment"
    )
    assert observed_prediction_reuse_roots
    assert observed_prediction_reuse_roots[0] == (
        tmp_path / ".cache" / "prediction_reuse"
    )
    assert observed_golden_roots
    assert observed_golden_roots[0] == (tmp_path / "gold")


def test_run_quality_suite_continues_after_failure_and_summarizes_results(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    fixture = _run_quality_suite_failure_fixture(monkeypatch, tmp_path)
    run_root = fixture["run_root"]
    assert isinstance(run_root, Path)

    summary = json.loads((run_root / "summary.json").read_text(encoding="utf-8"))
    rows = {row["id"]: row for row in summary["experiments"]}
    baseline = rows["baseline"]
    broken = rows["broken"]

    assert summary["successful_experiments"] == 1
    assert summary["failed_experiments"] == 1
    assert summary["format_counts"] == {".epub": 1}
    assert summary["selected_format_counts"] == {".epub": 1}
    assert baseline["status"] == "ok"
    assert broken["status"] == "failed"
    assert baseline["strict_f1_macro"] == pytest.approx(0.6)
    assert baseline["practical_f1_macro"] == pytest.approx(0.625)
    assert baseline["source_group_with_multiple_shards"] == 1
    assert baseline["source_success_rate"] == pytest.approx(1.0)
    assert baseline["run_settings_hash"]
    assert baseline["report_json_path"].startswith(
        "experiments/baseline/all_method_benchmark_multi_source_report.json"
    )
    assert Path(summary["prediction_reuse_cache_root"]) == (
        tmp_path / ".cache" / "prediction_reuse"
    )


def test_run_quality_suite_require_process_workers_fails_fast(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    suite = _build_suite(tmp_path)
    experiments_file = tmp_path / "experiments_strict.json"
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
        "cookimport.bench.qualitysuite.runtime._resolve_quality_experiment_executor_mode",
        lambda **_kwargs: ("thread", "forced-by-test"),
    )
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
    monkeypatch.setattr(
        "cookimport.cli._probe_all_method_process_pool_executor",
        lambda: (True, None),
    )

    seen_require_flags: list[bool] = []

    def _fake_run_all_method_multi_source(**kwargs):
        seen_require_flags.append(bool(kwargs.get("require_process_workers")))
        raise RuntimeError("simulated process-worker-required failure")

    monkeypatch.setattr(
        "cookimport.cli._run_all_method_benchmark_multi_source",
        _fake_run_all_method_multi_source,
    )

    with pytest.raises(RuntimeError, match="simulated process-worker-required failure"):
        run_quality_suite(
            suite,
            tmp_path / "runs",
            experiments_file=experiments_file,
            base_run_settings_file=base_run_settings_file,
            max_parallel_experiments=1,
            require_process_workers=True,
            progress_callback=None,
        )

    assert seen_require_flags == [True]
    run_dirs = sorted((tmp_path / "runs").iterdir())
    assert len(run_dirs) == 1
    run_root = run_dirs[0]
    assert not (run_root / "summary.json").exists()
    resolved = json.loads((run_root / "experiments_resolved.json").read_text(encoding="utf-8"))
    assert resolved["require_process_workers"] is True
    assert resolved["process_worker_probe_available"] is True
    assert resolved["process_worker_probe_error"] is None
