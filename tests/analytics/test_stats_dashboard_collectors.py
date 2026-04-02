from __future__ import annotations

import tests.analytics.stats_dashboard_support as _support

# Reuse shared imports/helpers from the local support module.
globals().update({
    name: value
    for name, value in _support.__dict__.items()
    if not name.startswith("test_")
    and not (name.startswith("__") and name.endswith("__"))
})


class TestCollectors:
    def test_csv_collector(self, tmp_path):
        _write_csv(tmp_path)
        data = collect_dashboard_data(
            output_root=tmp_path / "output",
            golden_root=tmp_path / "golden",
        )
        assert len(data.stage_records) == 2
        r0 = data.stage_records[0]
        assert r0.file_name == "cookbook_a.xlsx"
        assert r0.recipes == 20
        assert r0.total_seconds == 5.5
        assert r0.run_category == RunCategory.stage_import

    def test_csv_collector_derived_fields(self, tmp_path):
        _write_csv(tmp_path)
        data = collect_dashboard_data(
            output_root=tmp_path / "output",
            golden_root=tmp_path / "golden",
        )
        r1 = data.stage_records[1]
        assert r1.per_recipe_seconds == pytest.approx(0.246)
        assert r1.total_units == 73

    def test_report_json_fallback(self, tmp_path):
        _write_report_json(tmp_path)
        data = collect_dashboard_data(
            output_root=tmp_path / "output",
            golden_root=tmp_path / "golden",
            scan_reports=True,
        )
        # No CSV, so falls through to report scanning
        assert len(data.stage_records) == 1
        r = data.stage_records[0]
        assert r.file_name == "test_book.pdf"
        assert r.recipes == 15
        assert r.warnings_count == 1
        assert r.errors_count == 0
        assert r.run_config == {
            "epub_extractor": "beautifulsoup",
            "epub_extractor_requested": "beautifulsoup",
            "epub_extractor_effective": "beautifulsoup",
            "ocr_device": "auto",
            "ocr_batch_size": 1,
            "effective_workers": 10,
        }
        assert r.epub_extractor_requested is None
        assert r.epub_extractor_effective is None
        assert r.run_config_hash == "abc123def456"
        assert "epub_extractor=beautifulsoup" in str(r.run_config_summary)

    def test_csv_collector_stage_run_config_json(self, tmp_path):
        history_dir = history_csv_for_output(tmp_path / "output").parent
        history_dir.mkdir(parents=True)
        csv_path = history_dir / "performance_history.csv"
        stage_row = {field: "" for field in _CSV_FIELDS}
        stage_row.update(
            {
                "run_timestamp": "2026-02-12T11:00:00",
                "run_dir": str(tmp_path / "output" / "2026-02-12_11.00.00"),
                "file_name": "book.epub",
                "importer_name": "epub",
                "run_category": "stage_import",
                "total_seconds": "9.5",
                "recipes": "4",
                "epub_extractor_requested": "auto",
                "epub_extractor_effective": "beautifulsoup",
                "run_config_json": json.dumps(
                    {
                        "epub_extractor": "auto",
                        "epub_extractor_requested": "auto",
                        "epub_extractor_effective": "beautifulsoup",
                        "ocr_device": "auto",
                        "ocr_batch_size": 1,
                        "effective_workers": 10,
                    }
                ),
            }
        )
        with csv_path.open("w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=_CSV_FIELDS)
            writer.writeheader()
            writer.writerow(stage_row)

        data = collect_dashboard_data(
            output_root=tmp_path / "output",
            golden_root=tmp_path / "golden",
        )
        assert len(data.stage_records) == 1
        r = data.stage_records[0]
        assert r.file_name == "book.epub"
        assert r.importer_name == "epub"
        assert r.run_config == {
            "epub_extractor": "auto",
            "epub_extractor_requested": "auto",
            "epub_extractor_effective": "beautifulsoup",
            "ocr_device": "auto",
            "ocr_batch_size": 1,
            "effective_workers": 10,
        }
        assert r.epub_extractor_requested == "auto"
        assert r.epub_extractor_effective == "beautifulsoup"
        assert r.run_config_hash is not None
        assert "epub_extractor=auto" in str(r.run_config_summary)

    def test_csv_collector_stage_run_config_fallback_from_report(self, tmp_path):
        report_path = _write_report_json(tmp_path)
        history_dir = history_csv_for_output(tmp_path / "output").parent
        history_dir.mkdir(parents=True, exist_ok=True)
        csv_path = history_dir / "performance_history.csv"

        stage_row = {field: "" for field in _CSV_FIELDS}
        stage_row.update(
            {
                "run_timestamp": "2026-02-12T09:00:00",
                "run_dir": str(report_path.parent),
                "file_name": "test_book.pdf",
                "report_path": str(report_path),
                "run_category": "stage_import",
                "total_seconds": "8.0",
                "recipes": "15",
            }
        )
        with csv_path.open("w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=_CSV_FIELDS)
            writer.writeheader()
            writer.writerow(stage_row)

        data = collect_dashboard_data(
            output_root=tmp_path / "output",
            golden_root=tmp_path / "golden",
        )
        assert len(data.stage_records) == 1
        assert data.stage_records[0].run_config == {
            "epub_extractor": "beautifulsoup",
            "epub_extractor_requested": "beautifulsoup",
            "epub_extractor_effective": "beautifulsoup",
            "ocr_device": "auto",
            "ocr_batch_size": 1,
            "effective_workers": 10,
        }
        assert data.stage_records[0].epub_extractor_requested is None
        assert data.stage_records[0].epub_extractor_effective is None
        assert data.stage_records[0].run_config_hash == "abc123def456"
        assert "epub_extractor=beautifulsoup" in str(data.stage_records[0].run_config_summary)

    def test_csv_collector_stage_run_config_warning_when_report_missing(self, tmp_path):
        history_dir = history_csv_for_output(tmp_path / "output").parent
        history_dir.mkdir(parents=True, exist_ok=True)
        csv_path = history_dir / "performance_history.csv"

        stage_row = {field: "" for field in _CSV_FIELDS}
        stage_row.update(
            {
                "run_timestamp": "2026-02-12T09:00:00",
                "run_dir": str(tmp_path / "output" / "2026-02-12_09.00.00"),
                "file_name": "test_book.pdf",
                "report_path": str(
                    tmp_path / "output" / "2026-02-12_09.00.00"
                    / "test_book.excel_import_report.json"
                ),
                "run_category": "stage_import",
                "total_seconds": "8.0",
                "recipes": "15",
            }
        )
        with csv_path.open("w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=_CSV_FIELDS)
            writer.writeheader()
            writer.writerow(stage_row)

        data = collect_dashboard_data(
            output_root=tmp_path / "output",
            golden_root=tmp_path / "golden",
        )
        assert len(data.stage_records) == 1
        assert data.stage_records[0].run_config is None
        assert data.stage_records[0].run_config_warning == "missing report (stale row)"

    def test_benchmark_collector(self, tmp_path):
        _write_eval_report(tmp_path)
        data = collect_dashboard_data(
            output_root=tmp_path / "output",
            golden_root=tmp_path / "golden",
        )
        assert len(data.benchmark_records) == 1
        b = data.benchmark_records[0]
        assert b.precision == pytest.approx(0.05)
        assert b.recall == pytest.approx(0.25)
        assert b.f1 is not None  # computed by collector
        assert b.practical_precision == pytest.approx(0.7)
        assert b.practical_recall == pytest.approx(0.85)
        assert b.practical_f1 == pytest.approx(0.767741935483871)
        assert b.gold_total == 100
        assert b.gold_recipe_headers == 11
        assert b.boundary_correct == 10
        assert len(b.per_label) == 2
        assert b.supported_recall == pytest.approx(0.55)
        assert b.supported_practical_recall == pytest.approx(0.88)
        assert b.granularity_mismatch_likely is True
        assert b.pred_width_p50 == pytest.approx(28.0)
        assert b.gold_width_p50 == pytest.approx(1.0)

    def test_benchmark_collector_includes_nested_all_method_eval_reports(self, tmp_path):
        run_ts = "2026-02-23_16.01.06"
        all_method_root = (
            tmp_path
            / "golden"
            / "eval-vs-pipeline"
            / run_ts
            / "all-method-benchmark"
            / "thefoodlabcutdown"
        )
        config_a = all_method_root / "config_001_aaa"
        config_b = all_method_root / "config_002_bbb"
        config_a.mkdir(parents=True)
        config_b.mkdir(parents=True)
        (config_a / "eval_report.json").write_text(
            json.dumps(SAMPLE_EVAL_REPORT),
            encoding="utf-8",
        )
        report_b = dict(SAMPLE_EVAL_REPORT)
        report_b["precision"] = 0.11
        report_b["recall"] = 0.31
        report_b["f1"] = 0.16238095238095238
        (config_b / "eval_report.json").write_text(
            json.dumps(report_b),
            encoding="utf-8",
        )

        data = collect_dashboard_data(
            output_root=tmp_path / "output",
            golden_root=tmp_path / "golden",
        )
        assert len(data.benchmark_records) == 2
        assert {r.run_timestamp for r in data.benchmark_records} == {run_ts}
        assert all(
            "all-method-benchmark/thefoodlabcutdown/config_" in str(r.artifact_dir)
            for r in data.benchmark_records
        )

    def test_benchmark_collector_includes_nested_single_book_variant_eval_reports(
        self,
        tmp_path,
    ):
        run_ts = "2026-03-02_12.34.56"
        single_book_root = (
            tmp_path
            / "golden"
            / "benchmark-vs-golden"
            / run_ts
            / "single-book-benchmark"
        )
        vanilla_dir = single_book_root / "vanilla"
        codex_dir = single_book_root / "codex-exec"
        vanilla_dir.mkdir(parents=True)
        codex_dir.mkdir(parents=True)
        (vanilla_dir / "eval_report.json").write_text(
            json.dumps(SAMPLE_EVAL_REPORT),
            encoding="utf-8",
        )
        codex_report = dict(SAMPLE_EVAL_REPORT)
        codex_report["precision"] = 0.11
        codex_report["recall"] = 0.31
        codex_report["f1"] = 0.16238095238095238
        (codex_dir / "eval_report.json").write_text(
            json.dumps(codex_report),
            encoding="utf-8",
        )

        data = collect_dashboard_data(
            output_root=tmp_path / "output",
            golden_root=tmp_path / "golden",
        )
        records = [
            r
            for r in data.benchmark_records
            if "single-book-benchmark/" in str(r.artifact_dir)
        ]
        assert len(records) == 2
        assert {r.run_timestamp for r in records} == {run_ts}
        assert {Path(str(r.artifact_dir)).name for r in records} == {"vanilla", "codex-exec"}

    def test_benchmark_collector_normalizes_suffixed_run_dir_timestamps(self, tmp_path):
        run_dir_name = "2026-02-28_02.03.18_manual-top5-thefoodlab-all-matched"
        normalized_ts = "2026-02-28_02.03.18"
        all_method_root = (
            tmp_path
            / "golden"
            / "benchmark-vs-golden"
            / run_dir_name
            / "all-method-benchmark"
            / "thefoodlabcutdown"
        )
        config_a = all_method_root / "config_001_aaa"
        config_b = all_method_root / "config_002_bbb"
        config_a.mkdir(parents=True)
        config_b.mkdir(parents=True)
        (config_a / "eval_report.json").write_text(
            json.dumps(SAMPLE_EVAL_REPORT),
            encoding="utf-8",
        )
        (config_b / "eval_report.json").write_text(
            json.dumps(SAMPLE_EVAL_REPORT),
            encoding="utf-8",
        )

        data = collect_dashboard_data(
            output_root=tmp_path / "output",
            golden_root=tmp_path / "golden",
        )
        records = [
            r
            for r in data.benchmark_records
            if "all-method-benchmark/thefoodlabcutdown/config_" in str(r.artifact_dir)
        ]
        assert len(records) == 2
        assert {r.run_timestamp for r in records} == {normalized_ts}

    def test_csv_collector_benchmark_run_config_columns(self, tmp_path):
        history_dir = history_csv_for_output(tmp_path / "output").parent
        history_dir.mkdir(parents=True)
        csv_path = history_dir / "performance_history.csv"

        bench_row = {field: "" for field in _CSV_FIELDS}
        bench_row.update(
            {
                "run_timestamp": "2026-02-16T11:05:00",
                "run_dir": str(tmp_path / "golden" / "eval-vs-pipeline" / "2026-02-16_11.05.00"),
                "run_category": "benchmark_eval",
                "eval_scope": "freeform-spans",
                "precision": "0.2",
                "recall": "0.4",
                "run_config_hash": "cfg123",
                "run_config_summary": "epub_extractor=beautifulsoup | workers=7",
                "run_config_json": json.dumps({"epub_extractor": "beautifulsoup", "workers": 7}),
            }
        )
        with csv_path.open("w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=_CSV_FIELDS)
            writer.writeheader()
            writer.writerow(bench_row)

        data = collect_dashboard_data(
            output_root=tmp_path / "output",
            golden_root=tmp_path / "golden",
        )
        assert len(data.benchmark_records) == 1
        record = data.benchmark_records[0]
        assert record.run_config_hash == "cfg123"
        assert record.run_config_summary == "epub_extractor=beautifulsoup | workers=7"
        assert record.run_config == {"epub_extractor": "beautifulsoup", "workers": 7}

    def test_csv_collector_merges_nested_benchmark_history_csv_rows_and_skips_gated_runs(
        self, tmp_path
    ):
        output_root = tmp_path / "output"
        history_dir = history_csv_for_output(output_root).parent
        history_dir.mkdir(parents=True)
        primary_csv_path = history_dir / "performance_history.csv"

        primary_row = {field: "" for field in _CSV_FIELDS}
        primary_row.update(
            {
                "run_timestamp": "2026-03-03T01:00:40",
                "run_dir": str(
                    tmp_path
                    / "golden"
                    / "benchmark-vs-golden"
                    / "2026-03-03_12.23.20_line-role-gated-foodlab-det-strict"
                ),
                "file_name": "thefoodlabCUTDOWN.epub",
                "run_category": "benchmark_eval",
                "eval_scope": "canonical-text",
                "strict_accuracy": "0.3298",
                "macro_f1_excluding_other": "0.2575",
                "gold_total": "2353",
                "gold_matched": "776",
            }
        )
        with primary_csv_path.open("w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=_CSV_FIELDS)
            writer.writeheader()
            writer.writerow(primary_row)

        nested_history_dir = (
            output_root
            / "2026-03-03_01.24.28"
            / "single-book-benchmark"
            / "seaandsmokecutdown"
            / ".history"
        )
        nested_history_dir.mkdir(parents=True)
        nested_csv_path = nested_history_dir / "performance_history.csv"
        nested_row = {field: "" for field in _CSV_FIELDS}
        nested_row.update(
            {
                "run_timestamp": "2026-03-03T01:25:45",
                "run_dir": str(
                    tmp_path
                    / "golden"
                    / "benchmark-vs-golden"
                    / "2026-03-03_01.24.28"
                    / "single-book-benchmark"
                    / "seaandsmokecutdown"
                    / "vanilla"
                ),
                "file_name": "SeaAndSmokeCUTDOWN.epub",
                "run_category": "benchmark_eval",
                "eval_scope": "canonical-text",
                "strict_accuracy": "0.3849",
                "macro_f1_excluding_other": "0.4042",
                "gold_total": "595",
                "gold_matched": "229",
            }
        )
        with nested_csv_path.open("w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=_CSV_FIELDS)
            writer.writeheader()
            writer.writerow(nested_row)

        data = collect_dashboard_data(
            output_root=output_root,
            golden_root=tmp_path / "golden",
        )
        assert len(data.benchmark_records) == 1
        artifact_dirs = {str(record.artifact_dir) for record in data.benchmark_records}
        assert any(
            "2026-03-03_01.24.28/single-book-benchmark/seaandsmokecutdown/vanilla"
            in path
            for path in artifact_dirs
        )
        assert all("line-role-gated" not in path for path in artifact_dirs)

    def test_csv_collector_backfills_codex_runtime_from_manifest(
        self, tmp_path
    ):
        output_root = tmp_path / "output"
        history_dir = history_csv_for_output(output_root).parent
        history_dir.mkdir(parents=True)
        csv_path = history_dir / "performance_history.csv"

        eval_dir = (
            tmp_path
            / "golden"
            / "benchmark-vs-golden"
            / "2026-03-03_01.24.28"
            / "single-book-benchmark"
            / "seaandsmokecutdown"
            / "codex-exec"
        )
        eval_dir.mkdir(parents=True, exist_ok=True)
        (eval_dir / "manifest.json").write_text(
            json.dumps(
                {
                    "source_file": str(tmp_path / "input" / "SeaAndSmokeCUTDOWN.epub"),
                    "importer_name": "epub",
                    "recipe_count": 19,
                    "run_config": {
                        "llm_recipe_pipeline": "codex-recipe-shard-v1",
                        "workers": 7,
                    },
                    "llm_codex_farm": {
                        "process_runs": {
                            "recipe_refine": {
                                "process_payload": {
                                    "codex_model": "gpt-5.3-codex-spark",
                                    "codex_reasoning_effort": "<default>",
                                }
                            }
                        }
                    },
                }
            ),
            encoding="utf-8",
        )

        row = {field: "" for field in _CSV_FIELDS}
        row.update(
            {
                "run_timestamp": "2026-03-03T04:28:32",
                "run_dir": str(eval_dir),
                "file_name": "SeaAndSmokeCUTDOWN.epub",
                "run_category": "benchmark_eval",
                "eval_scope": "canonical-text",
                "strict_accuracy": "0.2739",
                "macro_f1_excluding_other": "0.3484",
                "gold_total": "595",
                "gold_matched": "163",
                "run_config_json": json.dumps(
                    {
                        "llm_recipe_pipeline": "codex-recipe-shard-v1",
                        "workers": 7,
                    }
                ),
            }
        )
        with csv_path.open("w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=_CSV_FIELDS)
            writer.writeheader()
            writer.writerow(row)

        data = collect_dashboard_data(
            output_root=output_root,
            golden_root=tmp_path / "golden",
        )
        assert len(data.benchmark_records) == 1
        record = data.benchmark_records[0]
        assert record.run_config is not None
        assert record.run_config.get("codex_farm_model") == "gpt-5.3-codex-spark"
        assert record.run_config.get("codex_farm_reasoning_effort") == "<default>"
        assert "codex_farm_model=gpt-5.3-codex-spark" in str(record.run_config_summary)
        assert "codex_farm_reasoning_effort=<default>" in str(record.run_config_summary)

    def test_csv_collector_backfills_codex_runtime_error_from_manifest(
        self, tmp_path
    ):
        output_root = tmp_path / "output"
        history_dir = history_csv_for_output(output_root).parent
        history_dir.mkdir(parents=True)
        csv_path = history_dir / "performance_history.csv"

        eval_dir = (
            tmp_path
            / "golden"
            / "benchmark-vs-golden"
            / "2026-03-03_01.24.28"
            / "single-book-benchmark"
            / "seaandsmokecutdown"
            / "codex-exec"
        )
        eval_dir.mkdir(parents=True, exist_ok=True)
        (eval_dir / "manifest.json").write_text(
            json.dumps(
                {
                    "source_file": str(tmp_path / "input" / "SeaAndSmokeCUTDOWN.epub"),
                    "importer_name": "epub",
                    "run_config": {
                        "llm_recipe_pipeline": "codex-recipe-shard-v1",
                        "workers": 7,
                    },
                    "llm_codex_farm": {
                        "enabled": True,
                        "fallbackApplied": True,
                        "fatalError": (
                            "codex-farm failed for recipe.schemaorg.v1 "
                            "(subprocess_exit=124)"
                        ),
                    },
                }
            ),
            encoding="utf-8",
        )

        row = {field: "" for field in _CSV_FIELDS}
        row.update(
            {
                "run_timestamp": "2026-03-03T04:28:32",
                "run_dir": str(eval_dir),
                "file_name": "SeaAndSmokeCUTDOWN.epub",
                "run_category": "benchmark_eval",
                "eval_scope": "canonical-text",
                "strict_accuracy": "0.2739",
                "macro_f1_excluding_other": "0.3484",
                "gold_total": "595",
                "gold_matched": "163",
                "run_config_json": json.dumps(
                    {
                        "llm_recipe_pipeline": "codex-recipe-shard-v1",
                        "workers": 7,
                        "codex_farm_model": "gpt-5.1-codex-mini",
                    }
                ),
            }
        )
        with csv_path.open("w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=_CSV_FIELDS)
            writer.writeheader()
            writer.writerow(row)

        data = collect_dashboard_data(
            output_root=output_root,
            golden_root=tmp_path / "golden",
        )
        assert len(data.benchmark_records) == 1
        record = data.benchmark_records[0]
        assert record.run_config is not None
        assert (
            record.run_config.get("codex_farm_runtime_error")
            == "codex-farm failed for recipe.schemaorg.v1 (subprocess_exit=124)"
        )

    def test_csv_collector_keeps_backfilled_ai_effort_rows(self, tmp_path):
        output_root = tmp_path / "output"
        history_dir = history_csv_for_output(output_root).parent
        history_dir.mkdir(parents=True)
        csv_path = history_dir / "performance_history.csv"

        row = {field: "" for field in _CSV_FIELDS}
        row.update(
            {
                "run_timestamp": "2026-03-03T01:28:32",
                "run_dir": str(
                    tmp_path
                    / "golden"
                    / "benchmark-vs-golden"
                    / "2026-03-03_01.24.28"
                    / "single-book-benchmark"
                    / "seaandsmokecutdown"
                    / "codex-exec"
                ),
                "file_name": "SeaAndSmokeCUTDOWN.epub",
                "run_category": "benchmark_eval",
                "eval_scope": "canonical-text",
                "strict_accuracy": "0.2739",
                "macro_f1_excluding_other": "0.3484",
                "gold_total": "595",
                "gold_matched": "163",
                "run_config_json": json.dumps(
                    {
                        "llm_recipe_pipeline": "codex-recipe-shard-v1",
                        "workers": 7,
                        "codex_farm_model": "gpt-5.3-codex-spark",
                        "codex_farm_reasoning_effort": "high",
                    }
                ),
                "run_config_summary": (
                    "llm_recipe_pipeline=codex-recipe-shard-v1 | workers=7 | "
                    "codex_farm_model=gpt-5.3-codex-spark | "
                    "codex_farm_reasoning_effort=high"
                ),
            }
        )
        with csv_path.open("w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=_CSV_FIELDS)
            writer.writeheader()
            writer.writerow(row)

        data = collect_dashboard_data(
            output_root=output_root,
            golden_root=tmp_path / "golden",
        )
        assert len(data.benchmark_records) == 1
        record = data.benchmark_records[0]
        assert record.run_config is not None
        assert record.run_config.get("codex_farm_model") == "gpt-5.3-codex-spark"
        assert record.run_config.get("codex_farm_reasoning_effort") == "high"
        assert "codex_farm_reasoning_effort=high" in str(record.run_config_summary)

    def test_benchmark_csv_recipes_backfill_from_processed_report_path(self, tmp_path):
        history_dir = history_csv_for_output(tmp_path / "output").parent
        history_dir.mkdir(parents=True)
        csv_path = history_dir / "performance_history.csv"
        processed_report = (
            tmp_path / "output" / "2026-02-16_11.00.00" / "book.excel_import_report.json"
        )
        processed_report.parent.mkdir(parents=True, exist_ok=True)
        processed_report.write_text(
            json.dumps({"totalRecipes": 23}),
            encoding="utf-8",
        )

        bench_row = {field: "" for field in _CSV_FIELDS}
        bench_row.update(
            {
                "run_timestamp": "2026-02-16T11:05:00",
                "run_dir": str(tmp_path / "golden" / "eval-vs-pipeline" / "2026-02-16_11.05.00"),
                "file_name": "book.epub",
                "report_path": str(processed_report),
                "run_category": "benchmark_eval",
                "eval_scope": "freeform-spans",
                "precision": "0.5",
                "recall": "0.6",
                "gold_total": "10",
                "gold_matched": "6",
                "pred_total": "12",
                # Intentionally leave recipes empty to validate report-path backfill.
                "recipes": "",
            }
        )
        with csv_path.open("w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=_CSV_FIELDS)
            writer.writeheader()
            writer.writerow(bench_row)

        data = collect_dashboard_data(
            output_root=tmp_path / "output",
            golden_root=tmp_path / "golden",
        )
        assert len(data.benchmark_records) == 1
        assert data.benchmark_records[0].recipes == 23

    def test_benchmark_collector_manifest_enrichment(self, tmp_path):
        eval_path = _write_eval_report(tmp_path)
        eval_dir = eval_path.parent
        eval_dir.mkdir(parents=True, exist_ok=True)
        processed_report_path = (
            tmp_path / "output" / "2026-02-12_11.22.33" / "book.excel_import_report.json"
        )
        processed_report_path.parent.mkdir(parents=True, exist_ok=True)
        processed_report_path.write_text(
            json.dumps({"totalRecipes": 17}),
            encoding="utf-8",
        )
        (eval_dir / "manifest.json").write_text(
            json.dumps(
                {
                    "task_count": 42,
                    "recipe_count": 19,
                    "source_file": "/tmp/source/book.epub",
                    "importer_name": "epub",
                    "run_config": {
                        "epub_extractor": "beautifulsoup",
                        "ocr_device": "auto",
                        "workers": 6,
                        "codex_farm_model": None,
                        "codex_farm_reasoning_effort": None,
                    },
                    "llm_codex_farm": {
                        "fatalError": (
                            "codex-farm failed for recipe.schemaorg.v1 "
                            "(subprocess_exit=124)"
                        ),
                        "codex_farm_model": None,
                        "codex_farm_reasoning_effort": None,
                        "process_runs": {
                            "recipe_refine": {
                                "process_payload": {
                                    "codex_model": "gpt-5.3-codex-spark",
                                    "codex_reasoning_effort": None,
                                    "telemetry_report": {
                                        "insights": {
                                            "model_reasoning_breakdown": [
                                                {
                                                    "model": "gpt-5.3-codex-spark",
                                                    "reasoning_effort": "<default>",
                                                }
                                            ]
                                        }
                                    },
                                }
                            }
                        },
                    },
                    "processed_report_path": str(processed_report_path),
                }
            ),
            encoding="utf-8",
        )
        (eval_dir / "coverage.json").write_text(
            json.dumps({"extracted_chars": 200, "chunked_chars": 150}),
            encoding="utf-8",
        )

        data = collect_dashboard_data(
            output_root=tmp_path / "output",
            golden_root=tmp_path / "golden",
        )
        assert len(data.benchmark_records) == 1
        b = data.benchmark_records[0]
        assert b.task_count == 42
        assert b.source_file == "/tmp/source/book.epub"
        assert b.importer_name == "epub"
        assert b.run_config is not None
        assert b.run_config.get("epub_extractor") == "beautifulsoup"
        assert b.run_config.get("ocr_device") == "auto"
        assert b.run_config.get("workers") == 6
        assert b.run_config.get("codex_farm_model") == "gpt-5.3-codex-spark"
        assert b.run_config.get("codex_farm_reasoning_effort") == "<default>"
        assert (
            b.run_config.get("codex_farm_runtime_error")
            == "codex-farm failed for recipe.schemaorg.v1 (subprocess_exit=124)"
        )
        assert b.processed_report_path == str(processed_report_path)
        assert b.recipes == 19
        assert b.extracted_chars == 200
        assert b.chunked_chars == 150
        assert b.coverage_ratio == pytest.approx(0.75)

    def test_combined_collection(self, tmp_path):
        _write_csv(tmp_path)
        _write_eval_report(tmp_path)
        data = collect_dashboard_data(
            output_root=tmp_path / "output",
            golden_root=tmp_path / "golden",
        )
        assert data.summary.total_stage_records == 2
        assert data.summary.total_benchmark_records == 1
        assert data.summary.total_recipes == 70  # 20 + 50

    def test_mixed_timestamp_formats_sort_by_time_and_summary_latest(self, tmp_path):
        history_dir = history_csv_for_output(tmp_path / "output").parent
        history_dir.mkdir(parents=True)
        csv_path = history_dir / "performance_history.csv"

        def _bench_row(ts: str, run_dir: Path, source_file: str) -> str:
            return _sample_csv_row(
                {
                    "run_timestamp": ts,
                    "run_dir": str(run_dir),
                    "file_name": source_file,
                    "run_category": "benchmark_eval",
                    "eval_scope": "freeform-spans",
                    "precision": "0.05",
                    "recall": "0.25",
                    "f1": "0.08333333333333333",
                    "gold_total": "100",
                    "gold_matched": "25",
                    "pred_total": "500",
                    "supported_precision": "0.08",
                    "supported_recall": "0.55",
                    "boundary_correct": "10",
                    "boundary_over": "8",
                    "boundary_under": "5",
                    "boundary_partial": "2",
                }
            )

        older_ts = "2026-02-15_23.25.45"
        newer_ts = "2026-02-15T23:59:24"
        older_dir = tmp_path / "golden" / "eval-vs-pipeline" / older_ts
        newer_dir = tmp_path / "golden" / "eval-vs-pipeline" / "2026-02-15_23.59.24"
        csv_path.write_text(
            SAMPLE_CSV_HEADER + "\n"
            + _bench_row(newer_ts, newer_dir, "book_newer.epub") + "\n"
            + _bench_row(older_ts, older_dir, "book_older.epub") + "\n",
            encoding="utf-8",
        )

        data = collect_dashboard_data(
            output_root=tmp_path / "output",
            golden_root=tmp_path / "golden",
        )
        assert [r.run_timestamp for r in data.benchmark_records] == [older_ts, newer_ts]
        assert data.summary.latest_benchmark_timestamp == newer_ts

    def test_csv_benchmark_rows_skip_pytest_temp_eval_artifacts(self, tmp_path):
        history_dir = history_csv_for_output(tmp_path / "output").parent
        history_dir.mkdir(parents=True)
        csv_path = history_dir / "performance_history.csv"

        def _bench_row(ts: str, run_dir: Path, source_file: str) -> str:
            return _sample_csv_row(
                {
                    "run_timestamp": ts,
                    "run_dir": str(run_dir),
                    "file_name": source_file,
                    "run_category": "benchmark_eval",
                    "eval_scope": "freeform-spans",
                    "precision": "0.05",
                    "recall": "0.25",
                    "f1": "0.08333333333333333",
                    "gold_total": "100",
                    "gold_matched": "25",
                    "pred_total": "500",
                    "supported_precision": "0.08",
                    "supported_recall": "0.55",
                    "boundary_correct": "10",
                    "boundary_over": "8",
                    "boundary_under": "5",
                    "boundary_partial": "2",
                }
            )

        keep_dir = tmp_path / "golden" / "eval-vs-pipeline" / "2026-02-16_00.04.14"
        skip_dir = tmp_path / "pytest-46" / "test_labelstudio_benchmark_pas0" / "eval"

        csv_path.write_text(
            SAMPLE_CSV_HEADER + "\n"
            + _bench_row("2026-02-16_00.04.14", keep_dir, "keep.epub") + "\n"
            + _bench_row("2026-02-15T23:59:24", skip_dir, "book.epub") + "\n",
            encoding="utf-8",
        )

        data = collect_dashboard_data(
            output_root=tmp_path / "output",
            golden_root=tmp_path / "golden",
        )
        assert len(data.benchmark_records) == 1
        assert data.benchmark_records[0].source_file == "keep.epub"

    def test_benchmark_scan_rows_skip_gated_eval_artifacts(self, tmp_path):
        keep_dir = (
            tmp_path
            / "golden"
            / "benchmark-vs-golden"
            / "2026-03-03_01.24.28"
            / "single-book-benchmark"
            / "seaandsmokecutdown"
            / "vanilla"
        )
        skip_dir = (
            tmp_path
            / "golden"
            / "benchmark-vs-golden"
            / "2026-03-03_02.10.00_foodlab-line-role-gated-fix7"
            / "single-book-benchmark"
            / "thefoodlabcutdown"
            / "codex-exec"
        )
        keep_dir.mkdir(parents=True, exist_ok=True)
        skip_dir.mkdir(parents=True, exist_ok=True)
        (keep_dir / "eval_report.json").write_text(
            json.dumps(SAMPLE_EVAL_REPORT),
            encoding="utf-8",
        )
        (skip_dir / "eval_report.json").write_text(
            json.dumps(SAMPLE_EVAL_REPORT),
            encoding="utf-8",
        )

        data = collect_dashboard_data(
            output_root=tmp_path / "output",
            golden_root=tmp_path / "golden",
        )
        assert len(data.benchmark_records) == 1
        assert "line-role-gated" not in str(data.benchmark_records[0].artifact_dir)

    def test_empty_roots(self, tmp_path):
        data = collect_dashboard_data(
            output_root=tmp_path / "output",
            golden_root=tmp_path / "golden",
        )
        assert len(data.stage_records) == 0
        assert len(data.benchmark_records) == 0

    def test_malformed_json_skipped(self, tmp_path):
        eval_dir = tmp_path / "golden" / "eval-vs-pipeline" / "2026-02-11_01.00.00"
        eval_dir.mkdir(parents=True)
        (eval_dir / "eval_report.json").write_text("{bad json", encoding="utf-8")

        data = collect_dashboard_data(
            output_root=tmp_path / "output",
            golden_root=tmp_path / "golden",
        )
        assert len(data.benchmark_records) == 0
        assert len(data.collector_warnings) > 0

    def test_job_parts_ignored(self, tmp_path):
        # .job_parts directory should never be scanned
        parts_dir = tmp_path / "output" / ".job_parts" / "test" / "job_0"
        parts_dir.mkdir(parents=True)
        (parts_dir / "test.excel_import_report.json").write_text(
            json.dumps(SAMPLE_REPORT_JSON), encoding="utf-8"
        )
        data = collect_dashboard_data(
            output_root=tmp_path / "output",
            golden_root=tmp_path / "golden",
            scan_reports=True,
        )
        assert len(data.stage_records) == 0

    def test_prediction_run_dir_is_collected_when_report_exists(self, tmp_path):
        pred_dir = (
            tmp_path / "golden" / "eval-vs-pipeline"
            / "2026-02-11_01.00.00" / "prediction-run"
        )
        pred_dir.mkdir(parents=True)
        (pred_dir / "eval_report.json").write_text(
            json.dumps(SAMPLE_EVAL_REPORT), encoding="utf-8"
        )
        data = collect_dashboard_data(
            output_root=tmp_path / "output",
            golden_root=tmp_path / "golden",
        )
        assert len(data.benchmark_records) == 1
        assert str(data.benchmark_records[0].artifact_dir).endswith("/prediction-run")
