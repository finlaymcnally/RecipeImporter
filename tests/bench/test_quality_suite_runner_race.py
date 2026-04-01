from __future__ import annotations

import tests.bench.quality_suite_runner_support as _support

# Reuse shared imports/helpers from the local support module.
globals().update({
    name: value
    for name, value in _support.__dict__.items()
    if not name.startswith("test_")
    and not (name.startswith("__") and name.endswith("__"))
})


def test_quality_suite_race_prunes_configs_between_rounds(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    fixture = _run_quality_suite_race_prune_fixture(monkeypatch, tmp_path)
    observed_round_variant_counts = fixture["observed_round_variant_counts"]

    counts = [(targets, variants) for _root, targets, variants in observed_round_variant_counts]
    assert counts == [(1, 4), (2, 4), (3, 3)]


def test_quality_suite_race_records_final_pruned_strategy_payload(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    fixture = _run_quality_suite_race_prune_fixture(monkeypatch, tmp_path)
    strategy_payload = fixture["strategy_payload"]

    assert strategy_payload["strategy"] == "race"
    assert strategy_payload["final"]["variants_effective"] == 3


def _run_quality_suite_race_exhaustive_fallback_fixture(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> dict[str, object]:
    suite = _build_suite_multi(tmp_path)
    experiments_file = tmp_path / "experiments.json"
    _write_json(
        experiments_file,
        {
            "schema_version": 1,
            "experiments": [
                {"id": "baseline", "run_settings_patch": {}},
            ],
        },
    )

    monkeypatch.setattr(
        "cookimport.cli._resolve_all_method_codex_choice",
        lambda _include_codex: (False, None),
    )
    monkeypatch.setattr(
        "cookimport.cli._resolve_all_method_markdown_extractors_choice",
        lambda: False,
    )

    class _FakeRunSettings:
        def __init__(self, digest: str) -> None:
            self._digest = digest

        def stable_hash(self) -> str:
            return self._digest

    class _FakeVariant:
        def __init__(self, digest: str) -> None:
            self.run_settings = _FakeRunSettings(digest)

    all_hashes = ["h1", "h2"]

    def _fake_build_target_variants(**kwargs):
        targets = kwargs["targets"]
        output = []
        for target in targets:
            variants = [_FakeVariant(digest) for digest in all_hashes]
            output.append((target, variants))
        return output

    monkeypatch.setattr(
        "cookimport.cli._build_all_method_target_variants",
        _fake_build_target_variants,
    )

    observed_round_variant_counts: list[tuple[int, int]] = []

    def _fake_run_all_method_multi_source(**kwargs):
        root_output_dir = Path(kwargs["root_output_dir"])
        target_variants = kwargs["target_variants"]
        variant_count = sum(len(rows) for _target, rows in target_variants)
        target_count = len(target_variants)
        observed_round_variant_counts.append((target_count, variant_count))

        sources_payload: list[dict[str, object]] = []
        for target, variants in target_variants:
            source_group_key = str(target.gold_display)
            source_report_path = (
                root_output_dir
                / "sources"
                / source_group_key
                / "all_method_benchmark_report.json"
            )
            variant_rows = []
            for variant in variants:
                digest = variant.run_settings.stable_hash()
                practical = {"h1": 0.90, "h2": 0.80}[digest]
                strict = {"h1": 0.88, "h2": 0.78}[digest]
                variant_rows.append(
                    {
                        "status": "ok",
                        "run_config_hash": digest,
                        "run_config_summary": f"hash={digest}",
                        "practical_f1": practical,
                        "f1": strict,
                        "duration_seconds": {"h1": 20.0, "h2": 15.0}[digest],
                    }
                )
            _write_json(source_report_path, {"variants": variant_rows})
            sources_payload.append(
                {
                    "source_group_key": source_group_key,
                    "status": "ok",
                    "source_shard_total": 1,
                    "report_json_path": str(
                        source_report_path.relative_to(root_output_dir)
                    ),
                    "winner_metrics": {"precision": 0.9, "recall": 0.9, "f1": 0.9},
                }
            )

        report_json_path = root_output_dir / "all_method_benchmark_multi_source_report.json"
        _write_json(
            report_json_path,
            {
                "matched_target_count": target_count,
                "total_config_runs_planned": variant_count,
                "total_config_runs_completed": variant_count,
                "total_config_runs_successful": variant_count,
                "evaluation_signatures_unique": variant_count,
                "evaluation_runs_executed": variant_count,
                "evaluation_results_reused_in_run": 0,
                "evaluation_results_reused_cross_run": 0,
                "sources": sources_payload,
            },
        )
        report_md_path = root_output_dir / "all_method_benchmark_multi_source_report.md"
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
        search_strategy="race",
        race_probe_targets=1,
        race_mid_targets=2,
        race_keep_ratio=0.5,
        race_finalists=9,
        progress_callback=None,
    )
    strategy_payload = json.loads(
        (
            run_root
            / "experiments"
            / "baseline"
            / "search_strategy.json"
        ).read_text(encoding="utf-8")
    )
    return {
        "observed_round_variant_counts": observed_round_variant_counts,
        "strategy_payload": strategy_payload,
    }


def test_quality_suite_race_auto_switches_to_exhaustive_when_no_pruning_possible(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    fixture = _run_quality_suite_race_exhaustive_fallback_fixture(monkeypatch, tmp_path)
    observed_round_variant_counts = fixture["observed_round_variant_counts"]

    assert observed_round_variant_counts == [(3, 6)]


def test_quality_suite_race_records_exhaustive_fallback_reason(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    fixture = _run_quality_suite_race_exhaustive_fallback_fixture(monkeypatch, tmp_path)
    strategy_payload = fixture["strategy_payload"]

    assert strategy_payload["requested_strategy"] == "race"
    assert strategy_payload["effective_strategy"] == "exhaustive"
    assert strategy_payload["reason"] == "race_no_prune_variant_count_le_finalists"
    assert strategy_payload["variants_effective"] == 6
    assert strategy_payload["race_finalists"] == 9
