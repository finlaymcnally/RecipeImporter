"""Quality benchmark CLI wiring tests."""

from __future__ import annotations

import tests.bench.test_bench as _base

# Reuse shared imports/helpers from the base bench test module.
globals().update({
    name: value
    for name, value in _base.__dict__.items()
    if not name.startswith("test_")
    and not (name.startswith("__") and name.endswith("__"))
})

def test_bench_quality_discover_writes_suite(tmp_path: Path) -> None:
    input_root = tmp_path / "input"
    input_root.mkdir(parents=True, exist_ok=True)
    (input_root / "alpha.epub").write_text("epub", encoding="utf-8")

    gold_root = tmp_path / "gold"
    exports = gold_root / "alpha" / "exports"
    exports.mkdir(parents=True, exist_ok=True)
    (exports / "freeform_span_labels.jsonl").write_text(
        '{"source_file":"alpha.epub","label":"OTHER"}\n',
        encoding="utf-8",
    )
    (exports / "canonical_text.txt").write_text("abc", encoding="utf-8")

    suite_out = tmp_path / "quality_suite.json"
    cli.bench_quality_discover(
        gold_root=gold_root,
        input_root=input_root,
        out=suite_out,
        max_targets=1,
        seed=42,
    )

    payload = json.loads(suite_out.read_text(encoding="utf-8"))
    assert payload["targets"]
    assert payload["selected_target_ids"]
    assert payload["selection"]["algorithm_version"] == "quality_representative_v2"


def test_bench_quality_discover_formats_filter(tmp_path: Path) -> None:
    input_root = tmp_path / "input"
    input_root.mkdir(parents=True, exist_ok=True)
    (input_root / "alpha.epub").write_text("epub", encoding="utf-8")
    (input_root / "gamma.pdf").write_text("pdf", encoding="utf-8")

    gold_root = tmp_path / "gold"
    alpha_exports = gold_root / "alpha" / "exports"
    alpha_exports.mkdir(parents=True, exist_ok=True)
    (alpha_exports / "freeform_span_labels.jsonl").write_text(
        '{"source_file":"alpha.epub","label":"OTHER"}\n',
        encoding="utf-8",
    )
    (alpha_exports / "canonical_text.txt").write_text("abc", encoding="utf-8")
    gamma_exports = gold_root / "gamma" / "exports"
    gamma_exports.mkdir(parents=True, exist_ok=True)
    (gamma_exports / "freeform_span_labels.jsonl").write_text(
        '{"source_file":"gamma.pdf","label":"OTHER"}\n',
        encoding="utf-8",
    )
    (gamma_exports / "canonical_text.txt").write_text("abcd", encoding="utf-8")

    suite_out = tmp_path / "quality_suite_pdf.json"
    cli.bench_quality_discover(
        gold_root=gold_root,
        input_root=input_root,
        out=suite_out,
        seed=42,
        formats=".pdf",
        prefer_curated=False,
    )

    payload = json.loads(suite_out.read_text(encoding="utf-8"))
    target_ids = [row["target_id"] for row in payload["targets"]]
    assert target_ids == ["gamma"]
    assert payload["selection"]["formats_filter"] == [".pdf"]
    assert payload["selection"]["selected_format_counts"] == {".pdf": 1}


def _run_bench_quality_run_fixture(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> dict[str, object]:
    monkeypatch.delenv("COOKIMPORT_IO_PACE_EVERY_WRITES", raising=False)
    monkeypatch.delenv("COOKIMPORT_IO_PACE_SLEEP_MS", raising=False)

    source_file = tmp_path / "alpha.epub"
    source_file.write_text("epub", encoding="utf-8")
    gold_spans = tmp_path / "gold" / "exports" / "freeform_span_labels.jsonl"
    gold_spans.parent.mkdir(parents=True, exist_ok=True)
    gold_spans.write_text('{"source_file":"alpha.epub"}\n', encoding="utf-8")

    loaded_suite = BenchQualitySuite(
        name="quality_suite",
        generated_at="2026-02-28_12.00.00",
        gold_root=str((tmp_path / "gold").resolve()),
        input_root=str(tmp_path.resolve()),
        seed=42,
        max_targets=1,
        selection={
            "algorithm_version": "quality_representative_v2",
            "seed": 42,
            "max_targets": 1,
            "matched_count": 1,
            "strata_counts": {"small:sparse": 1},
        },
        targets=[
            BenchQualityTarget(
                target_id="alpha",
                source_file=str(source_file.resolve()),
                gold_spans_path=str(gold_spans.resolve()),
                source_hint="alpha.epub",
                canonical_text_chars=3,
                gold_span_rows=1,
                label_count=1,
                size_bucket="small",
                label_bucket="sparse",
            )
        ],
        selected_target_ids=["alpha"],
        unmatched=[],
    )
    suite_path = tmp_path / "suite.json"
    suite_path.write_text("{}", encoding="utf-8")
    experiments_file = tmp_path / "experiments.json"
    experiments_file.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "experiments": [{"id": "baseline", "run_settings_patch": {}}],
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    base_settings_file = tmp_path / "base_settings.json"
    base_settings_file.write_text("{}", encoding="utf-8")
    run_root = tmp_path / "runs" / "2026-02-28_12.00.00"
    run_root.mkdir(parents=True, exist_ok=True)
    (run_root / "report.md").write_text("", encoding="utf-8")
    (run_root / "summary.json").write_text("{}", encoding="utf-8")

    captured: dict[str, object] = {}

    monkeypatch.setattr(
        "cookimport.bench.quality_suite.load_quality_suite",
        lambda _suite_path: loaded_suite,
    )
    monkeypatch.setattr(
        "cookimport.bench.quality_suite.validate_quality_suite",
        lambda _suite, repo_root: [],
    )
    monkeypatch.setattr(
        "cookimport.cli._run_with_progress_status",
        lambda *, run, **_kwargs: run(lambda _message: None),
    )

    def _fake_run_quality_suite(
        suite,
        out_dir,
        *,
        experiments_file,
        base_run_settings_file,
        progress_callback,
        **_kwargs,
    ):
        _ = progress_callback
        captured["io_pace_every_writes_env"] = os.getenv("COOKIMPORT_IO_PACE_EVERY_WRITES")
        captured["io_pace_sleep_ms_env"] = os.getenv("COOKIMPORT_IO_PACE_SLEEP_MS")
        captured["max_parallel_experiments"] = _kwargs.get("max_parallel_experiments")
        captured["require_process_workers"] = _kwargs.get("require_process_workers")
        captured["resume_run_dir"] = _kwargs.get("resume_run_dir")
        captured["include_codex_farm_requested"] = _kwargs.get(
            "include_codex_farm_requested"
        )
        captured["codex_farm_confirmed"] = _kwargs.get("codex_farm_confirmed")
        captured["suite"] = suite
        captured["out_dir"] = out_dir
        captured["experiments_file"] = experiments_file
        captured["base_run_settings_file"] = base_run_settings_file
        return run_root

    monkeypatch.setattr(
        "cookimport.bench.quality_runner.run_quality_suite",
        _fake_run_quality_suite,
    )
    bridge_calls: list[dict[str, object]] = []

    def _fake_bridge_for_run(**kwargs):
        bridge_calls.append(dict(kwargs))
        return (run_root / "agent_compare_control", None)

    monkeypatch.setattr(
        "cookimport.cli._write_qualitysuite_agent_bridge_bundle_for_run",
        _fake_bridge_for_run,
    )
    monkeypatch.setattr("typer.secho", lambda *_args, **_kwargs: None)

    cli.bench_quality_run(
        suite=suite_path,
        experiments_file=experiments_file,
        out_dir=tmp_path / "runs",
        resume_run_dir=run_root,
        base_run_settings_file=base_settings_file,
        qualitysuite_agent_bridge=True,
    )
    return {
        "captured": captured,
        "bridge_calls": bridge_calls,
        "loaded_suite": loaded_suite,
        "experiments_file": experiments_file,
        "base_settings_file": base_settings_file,
        "run_root": run_root,
    }


def test_bench_quality_run_wires_runner(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    fixture = _run_bench_quality_run_fixture(monkeypatch, tmp_path)
    captured = fixture["captured"]
    loaded_suite = fixture["loaded_suite"]
    experiments_file = fixture["experiments_file"]
    base_settings_file = fixture["base_settings_file"]
    run_root = fixture["run_root"]

    assert captured["suite"] == loaded_suite
    assert captured["experiments_file"] == experiments_file
    assert captured["base_run_settings_file"] == base_settings_file
    assert captured["resume_run_dir"] == run_root
    assert captured["max_parallel_experiments"] is None
    assert captured["require_process_workers"] is False
    assert captured["include_codex_farm_requested"] is False
    assert captured["codex_farm_confirmed"] is False
    assert captured["io_pace_every_writes_env"] == "200"
    assert captured["io_pace_sleep_ms_env"] == "5.0"


def test_bench_quality_run_writes_agent_bridge_and_restores_io_pace_env(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    fixture = _run_bench_quality_run_fixture(monkeypatch, tmp_path)
    bridge_calls = fixture["bridge_calls"]
    run_root = fixture["run_root"]

    assert len(bridge_calls) == 1
    assert bridge_calls[0]["run_root"] == run_root
    assert bridge_calls[0]["output_root"] == cli.DEFAULT_OUTPUT
    assert bridge_calls[0]["golden_root"] == cli.DEFAULT_GOLDEN
    assert bridge_calls[0]["since_days"] is None
    assert os.getenv("COOKIMPORT_IO_PACE_EVERY_WRITES") is None
    assert os.getenv("COOKIMPORT_IO_PACE_SLEEP_MS") is None


def test_bench_quality_run_rejects_missing_resume_run_dir(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    failures: list[str] = []

    def _fake_fail(message: str) -> None:
        failures.append(message)
        raise typer.Exit(1)

    monkeypatch.setattr("cookimport.cli._fail", _fake_fail)

    with pytest.raises(typer.Exit) as excinfo:
        cli.bench_quality_run(
            suite=tmp_path / "suite.json",
            experiments_file=tmp_path / "experiments.json",
            out_dir=tmp_path / "runs",
            resume_run_dir=tmp_path / "does-not-exist",
        )

    assert excinfo.value.exit_code == 1
    assert failures
    assert "--resume-run-dir must point to an existing directory" in failures[0]


def test_bench_quality_run_rejects_include_codex_farm(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    failures: list[str] = []

    def _fake_fail(message: str) -> None:
        failures.append(message)
        raise typer.Exit(1)

    monkeypatch.setattr("cookimport.cli._fail", _fake_fail)

    with pytest.raises(typer.Exit) as excinfo:
        cli.bench_quality_run(
            suite=tmp_path / "suite.json",
            experiments_file=tmp_path / "experiments.json",
            out_dir=tmp_path / "runs",
            include_codex_farm=True,
        )

    assert excinfo.value.exit_code == 1
    assert failures
    assert "--include-codex-farm" in failures[0]


def test_bench_quality_run_rejects_codex_farm_model_override(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    failures: list[str] = []

    def _fake_fail(message: str) -> None:
        failures.append(message)
        raise typer.Exit(1)

    monkeypatch.setattr("cookimport.cli._fail", _fake_fail)

    with pytest.raises(typer.Exit) as excinfo:
        cli.bench_quality_run(
            suite=tmp_path / "suite.json",
            experiments_file=tmp_path / "experiments.json",
            out_dir=tmp_path / "runs",
            codex_farm_model="gpt-5.3-codex-spark",
        )

    assert excinfo.value.exit_code == 1
    assert failures
    assert "--codex-farm-model" in failures[0]


def test_bench_quality_lightweight_series_is_disabled(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    failures: list[str] = []

    def _fake_fail(message: str) -> None:
        failures.append(message)
        raise typer.Exit(1)

    monkeypatch.setattr("cookimport.cli._fail", _fake_fail)

    gold_root = tmp_path / "gold"
    input_root = tmp_path / "input"
    experiments_file = tmp_path / "experiments.json"
    thresholds_file = tmp_path / "thresholds.json"
    profile_file = tmp_path / "profile.json"

    with pytest.raises(typer.Exit) as excinfo:
        cli.bench_quality_lightweight_series(
            gold_root=gold_root,
            input_root=input_root,
            profile_file=profile_file,
            experiments_file=experiments_file,
            thresholds_file=thresholds_file,
            out_dir=tmp_path / "lightweight",
            max_parallel_experiments=3,
            require_process_workers=True,
        )

    assert excinfo.value.exit_code == 1
    assert failures
    assert failures[0] == cli.QUALITY_LIGHTWEIGHT_SERIES_DISABLED_MESSAGE


def test_bench_quality_lightweight_series_disabled_before_resume_validation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    failures: list[str] = []

    def _fake_fail(message: str) -> None:
        failures.append(message)
        raise typer.Exit(1)

    monkeypatch.setattr("cookimport.cli._fail", _fake_fail)

    with pytest.raises(typer.Exit) as excinfo:
        cli.bench_quality_lightweight_series(
            gold_root=tmp_path / "gold",
            input_root=tmp_path / "input",
            profile_file=tmp_path / "profile.json",
            experiments_file=tmp_path / "experiments.json",
            thresholds_file=tmp_path / "thresholds.json",
            out_dir=tmp_path / "lightweight",
            resume_series_dir=tmp_path / "missing-series-dir",
        )

    assert excinfo.value.exit_code == 1
    assert failures
    assert failures[0] == cli.QUALITY_LIGHTWEIGHT_SERIES_DISABLED_MESSAGE


def test_bench_quality_compare_fail_on_regression_exits(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    baseline = tmp_path / "baseline"
    candidate = tmp_path / "candidate"
    baseline.mkdir(parents=True, exist_ok=True)
    candidate.mkdir(parents=True, exist_ok=True)
    out_dir = tmp_path / "comparisons"

    monkeypatch.setattr(
        "cookimport.bench.quality_compare.compare_quality_runs",
        lambda **_kwargs: {
            "metric_deltas": {},
            "overall": {"verdict": "FAIL", "reasons": ["regression"]},
        },
    )
    monkeypatch.setattr(
        "cookimport.bench.quality_compare.format_quality_compare_report",
        lambda _payload: "report",
    )
    monkeypatch.setattr(
        "cookimport.cli._write_qualitysuite_agent_bridge_bundle_for_compare",
        lambda **_kwargs: (out_dir / "agent_compare_control", None),
    )
    monkeypatch.setattr("typer.secho", lambda *_args, **_kwargs: None)

    with pytest.raises(typer.Exit) as excinfo:
        cli.bench_quality_compare(
            baseline=baseline,
            candidate=candidate,
            out_dir=out_dir,
            strict_f1_drop_max=0.005,
            practical_f1_drop_max=0.005,
            source_success_rate_drop_max=0.0,
            fail_on_regression=True,
        )

    assert excinfo.value.exit_code == 1


def test_bench_quality_compare_forwards_selection_and_mismatch_flags(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    baseline = tmp_path / "baseline"
    candidate = tmp_path / "candidate"
    baseline.mkdir(parents=True, exist_ok=True)
    candidate.mkdir(parents=True, exist_ok=True)

    captured: dict[str, object] = {}

    def _fake_compare_quality_runs(**kwargs):
        captured.update(kwargs)
        return {
            "metric_deltas": {},
            "overall": {"verdict": "PASS", "reasons": []},
        }

    monkeypatch.setattr(
        "cookimport.bench.quality_compare.compare_quality_runs",
        _fake_compare_quality_runs,
    )
    monkeypatch.setattr(
        "cookimport.bench.quality_compare.format_quality_compare_report",
        lambda _payload: "report",
    )
    bridge_calls: list[dict[str, object]] = []

    def _fake_bridge_for_compare(**kwargs):
        bridge_calls.append(dict(kwargs))
        return (tmp_path / "comparisons" / "agent_compare_control", None)

    monkeypatch.setattr(
        "cookimport.cli._write_qualitysuite_agent_bridge_bundle_for_compare",
        _fake_bridge_for_compare,
    )
    monkeypatch.setattr("typer.secho", lambda *_args, **_kwargs: None)

    cli.bench_quality_compare(
        baseline=baseline,
        candidate=candidate,
        out_dir=tmp_path / "comparisons",
        baseline_experiment_id="baseline",
        candidate_experiment_id="candidate",
        strict_f1_drop_max=0.005,
        practical_f1_drop_max=0.005,
        source_success_rate_drop_max=0.0,
        fail_on_regression=False,
        allow_settings_mismatch=True,
        qualitysuite_agent_bridge=True,
        qualitysuite_agent_bridge_since_days=14,
    )

    assert captured["baseline_experiment_id"] == "baseline"
    assert captured["candidate_experiment_id"] == "candidate"
    assert captured["allow_settings_mismatch"] is True
    assert len(bridge_calls) == 1
    assert bridge_calls[0]["comparison_root"].is_dir()
    assert bridge_calls[0]["output_root"] == cli.DEFAULT_OUTPUT
    assert bridge_calls[0]["golden_root"] == cli.DEFAULT_GOLDEN
    assert bridge_calls[0]["since_days"] == 14


def test_bench_quality_leaderboard_saves_qualitysuite_winner_profile(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "quality_run"
    run_dir.mkdir(parents=True, exist_ok=True)
    out_dir = tmp_path / "leaderboards" / "baseline" / "2026-02-28_12.00.00"
    out_dir.mkdir(parents=True, exist_ok=True)

    payload = {
        "winner_run_settings": {
            "epub_extractor": "unstructured",
            "epub_unstructured_html_parser_version": "v2",
            "epub_unstructured_preprocess_mode": "br_split_v1",
            "llm_recipe_pipeline": "off",
        },
        "winner": {
            "rank": 1,
            "config_id": "winnerid",
            "coverage_sources": 1,
            "mean_practical_f1": 0.5,
            "mean_strict_f1": 0.4,
            "median_duration_seconds": 8.0,
        },
        "leaderboard": [],
        "total_source_groups": 1,
    }
    captured: dict[str, object] = {}

    class _Paths:
        def __init__(self, root: Path) -> None:
            self.out_dir = root
            self.leaderboard_json = root / "leaderboard.json"
            self.leaderboard_csv = root / "leaderboard.csv"
            self.pareto_json = root / "pareto_frontier.json"
            self.pareto_csv = root / "pareto_frontier.csv"
            self.winner_run_settings_json = root / "winner_run_settings.json"
            self.winner_dimensions_json = root / "winner_dimensions.json"

    monkeypatch.setattr(
        "cookimport.bench.quality_leaderboard.build_quality_leaderboard",
        lambda **_kwargs: payload,
    )
    monkeypatch.setattr(
        "cookimport.bench.quality_leaderboard.write_quality_leaderboard_artifacts",
        lambda _payload, *, out_dir: _Paths(out_dir),
    )

    def _fake_save_qualitysuite_winner_run_settings(output_dir, settings):
        captured["output_dir"] = output_dir
        captured["settings"] = settings

    monkeypatch.setattr(
        "cookimport.cli.save_qualitysuite_winner_run_settings",
        _fake_save_qualitysuite_winner_run_settings,
    )
    monkeypatch.setattr("typer.secho", lambda *_args, **_kwargs: None)
    monkeypatch.setattr("typer.echo", lambda *_args, **_kwargs: None)

    cli.bench_quality_leaderboard(
        experiment_id="baseline",
        run_dir=run_dir,
        out_dir=out_dir,
        top_n=5,
    )

    assert str(captured["output_dir"]).endswith("data/output")
    assert isinstance(captured["settings"], cli.RunSettings)
    settings = captured["settings"]
    assert settings.epub_extractor.value == "unstructured"
    assert settings.epub_unstructured_html_parser_version.value == "v2"
    assert settings.epub_unstructured_preprocess_mode.value == "br_split_v1"
