from __future__ import annotations

import tests.analytics.stats_dashboard_support as _support

# Reuse shared imports/helpers from the local support module.
globals().update({
    name: value
    for name, value in _support.__dict__.items()
    if not name.startswith("test_")
    and not (name.startswith("__") and name.endswith("__"))
})


class TestBenchmarkCsv:
    def test_benchmark_csv_append(self, tmp_path):
        """append_benchmark_csv writes a row with benchmark columns populated."""
        csv_path = tmp_path / "history.csv"
        append_benchmark_csv(
            SAMPLE_EVAL_REPORT,
            csv_path,
            run_timestamp="2026-02-11T16:00:00",
            run_dir="/some/eval/dir",
            eval_scope="freeform-spans",
            source_file="my_book.pdf",
        )
        with csv_path.open("r", newline="", encoding="utf-8") as fh:
            reader = csv.DictReader(fh)
            rows = list(reader)

        assert len(rows) == 1
        row = rows[0]
        assert row["run_category"] == "benchmark_eval"
        assert row["eval_scope"] == "freeform-spans"
        assert float(row["precision"]) == pytest.approx(0.05)
        assert float(row["recall"]) == pytest.approx(0.25)
        assert float(row["f1"]) == pytest.approx(0.08333333333333333)
        assert float(row["practical_precision"]) == pytest.approx(0.7)
        assert float(row["practical_recall"]) == pytest.approx(0.85)
        assert float(row["practical_f1"]) == pytest.approx(0.767741935483871)
        assert row["gold_total"] == "100"
        assert row["gold_recipe_headers"] == "11"
        assert row["gold_matched"] == "25"
        assert row["pred_total"] == "500"
        assert float(row["supported_precision"]) == pytest.approx(0.08)
        assert float(row["supported_recall"]) == pytest.approx(0.55)
        assert float(row["supported_practical_precision"]) == pytest.approx(0.72)
        assert float(row["supported_practical_recall"]) == pytest.approx(0.88)
        assert float(row["supported_practical_f1"]) == pytest.approx(0.792)
        assert row["granularity_mismatch_likely"] == "1"
        assert float(row["pred_width_p50"]) == pytest.approx(28.0)
        assert float(row["gold_width_p50"]) == pytest.approx(1.0)
        assert row["boundary_correct"] == "10"
        assert row["boundary_over"] == "8"
        assert row["boundary_under"] == "5"
        assert row["boundary_partial"] == "2"
        assert row["file_name"] == "my_book.pdf"
        assert row["importer_name"] == "pdf"
        assert row["report_path"] == ""
        assert row["tokens_total"] == ""
        # Stage-only fields should be empty
        assert row["recipes"] == ""
        assert row["total_seconds"] == ""

    def test_benchmark_csv_append_with_recipes_and_processed_report_path(self, tmp_path):
        csv_path = tmp_path / "history.csv"
        append_benchmark_csv(
            SAMPLE_EVAL_REPORT,
            csv_path,
            run_timestamp="2026-02-11T16:00:00",
            run_dir="/some/eval/dir",
            eval_scope="freeform-spans",
            source_file="my_book.pdf",
            recipes=31,
            processed_report_path="/tmp/output/2026-02-11_15.59.00/my_book.excel_import_report.json",
            run_config={"epub_extractor": "beautifulsoup", "workers": 7},
            tokens_input=300,
            tokens_cached_input=50,
            tokens_output=80,
            tokens_reasoning=10,
            tokens_total=390,
            timing={
                "total_seconds": 21.5,
                "prediction_seconds": 17.0,
                "evaluation_seconds": 3.1,
                "artifact_write_seconds": 1.0,
                "history_append_seconds": 0.4,
                "parsing_seconds": 11.2,
                "writing_seconds": 4.0,
                "ocr_seconds": 0.6,
                "checkpoints": {
                    "prediction_load_seconds": 0.8,
                    "gold_load_seconds": 0.3,
                    "evaluate_seconds": 2.0,
                },
            },
        )
        with csv_path.open("r", newline="", encoding="utf-8") as fh:
            reader = csv.DictReader(fh)
            rows = list(reader)

        assert len(rows) == 1
        row = rows[0]
        assert row["recipes"] == "31"
        assert row["importer_name"] == "pdf"
        assert (
            row["report_path"]
            == "/tmp/output/2026-02-11_15.59.00/my_book.excel_import_report.json"
        )
        assert float(row["total_seconds"]) == pytest.approx(21.5)
        assert float(row["parsing_seconds"]) == pytest.approx(11.2)
        assert float(row["writing_seconds"]) == pytest.approx(4.0)
        assert float(row["ocr_seconds"]) == pytest.approx(0.6)
        assert float(row["benchmark_prediction_seconds"]) == pytest.approx(17.0)
        assert float(row["benchmark_evaluation_seconds"]) == pytest.approx(3.1)
        assert float(row["benchmark_artifact_write_seconds"]) == pytest.approx(1.0)
        assert float(row["benchmark_history_append_seconds"]) == pytest.approx(0.4)
        assert float(row["benchmark_total_seconds"]) == pytest.approx(21.5)
        assert float(row["benchmark_prediction_load_seconds"]) == pytest.approx(0.8)
        assert float(row["benchmark_gold_load_seconds"]) == pytest.approx(0.3)
        assert float(row["benchmark_evaluate_seconds"]) == pytest.approx(2.0)
        assert row["tokens_input"] == "300"
        assert row["tokens_cached_input"] == "50"
        assert row["tokens_output"] == "80"
        assert row["tokens_reasoning"] == "10"
        assert row["tokens_total"] == "390"
        assert row["run_config_hash"] != ""
        assert "epub_extractor=beautifulsoup" in row["run_config_summary"]
        assert row["run_config_json"] != ""

    def test_benchmark_csv_timing_falls_back_to_processed_report(self, tmp_path):
        csv_path = tmp_path / "history.csv"
        processed_report = (
            tmp_path
            / "output"
            / "2026-02-11_15.59.00"
            / "my_book.excel_import_report.json"
        )
        processed_report.parent.mkdir(parents=True, exist_ok=True)
        processed_report.write_text(
            json.dumps(
                {
                    "totalRecipes": 31,
                    "timing": {
                        "total_seconds": 18.0,
                        "prediction_seconds": 18.0,
                        "parsing_seconds": 9.2,
                        "writing_seconds": 3.1,
                        "ocr_seconds": 0.4,
                        "checkpoints": {
                            "processed_output_write_seconds": 2.4,
                        },
                    },
                }
            ),
            encoding="utf-8",
        )

        append_benchmark_csv(
            SAMPLE_EVAL_REPORT,
            csv_path,
            run_timestamp="2026-02-11T16:00:00",
            run_dir="/some/eval/dir",
            eval_scope="freeform-spans",
            source_file="my_book.pdf",
            processed_report_path=str(processed_report),
        )
        with csv_path.open("r", newline="", encoding="utf-8") as fh:
            row = next(csv.DictReader(fh))

        assert float(row["total_seconds"]) == pytest.approx(18.0)
        assert float(row["parsing_seconds"]) == pytest.approx(9.2)
        assert float(row["writing_seconds"]) == pytest.approx(3.1)
        assert float(row["ocr_seconds"]) == pytest.approx(0.4)
        assert float(row["benchmark_prediction_seconds"]) == pytest.approx(18.0)
        assert float(row["benchmark_total_seconds"]) == pytest.approx(18.0)

    def test_csv_with_mixed_rows(self, tmp_path):
        """CSV with both stage and benchmark rows; collector produces both."""
        history_dir = history_csv_for_output(tmp_path / "output").parent
        history_dir.mkdir(parents=True)
        csv_path = history_dir / "performance_history.csv"
        csv_path.write_text(
            SAMPLE_CSV_HEADER + "\n"
            + SAMPLE_CSV_ROW1 + "\n"
            + SAMPLE_CSV_BENCH_ROW + "\n",
            encoding="utf-8",
        )
        data = collect_dashboard_data(
            output_root=tmp_path / "output",
            golden_root=tmp_path / "golden",
        )
        assert len(data.stage_records) == 1
        assert data.stage_records[0].file_name == "cookbook_a.xlsx"
        assert len(data.benchmark_records) == 1
        b = data.benchmark_records[0]
        assert b.precision == pytest.approx(0.05)
        assert b.recall == pytest.approx(0.25)
        assert b.practical_precision == pytest.approx(0.70)
        assert b.practical_recall == pytest.approx(0.85)
        assert b.practical_f1 == pytest.approx(0.767741935483871)
        assert b.gold_total == 100
        assert b.boundary_correct == 10
        assert b.supported_recall == pytest.approx(0.55)
        assert b.supported_practical_recall == pytest.approx(0.88)
        assert b.granularity_mismatch_likely is True
        assert b.source_file == "my_book.pdf"
        assert b.tokens_input == 1234
        assert b.tokens_cached_input == 234
        assert b.tokens_output == 345
        assert b.tokens_reasoning == 12
        assert b.tokens_total == 1591
        assert b.recipes is None
        assert b.gold_recipe_headers == 11

    def test_csv_and_json_benchmark_rows_merge_by_artifact_dir(self, tmp_path):
        history_dir = history_csv_for_output(tmp_path / "output").parent
        history_dir.mkdir(parents=True)
        eval_dir = tmp_path / "golden" / "eval-vs-pipeline" / "2026-02-11_16.00.00"
        eval_dir.mkdir(parents=True)
        (eval_dir / "eval_report.json").write_text(
            json.dumps(SAMPLE_EVAL_REPORT), encoding="utf-8"
        )

        csv_path = history_dir / "performance_history.csv"
        bench_row = _sample_csv_row(
            {
                "run_timestamp": "2026-02-11T16:00:00",
                "run_dir": str(eval_dir),
                "file_name": "my_book.pdf",
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
        csv_path.write_text(
            SAMPLE_CSV_HEADER + "\n" + bench_row + "\n",
            encoding="utf-8",
        )

        data = collect_dashboard_data(
            output_root=tmp_path / "output",
            golden_root=tmp_path / "golden",
            scan_benchmark_reports=True,
        )
        assert len(data.benchmark_records) == 1
        b = data.benchmark_records[0]
        assert b.artifact_dir == str(eval_dir)
        assert b.source_file == "my_book.pdf"
        assert b.recipes == 14
        assert b.gold_recipe_headers == 11
        assert len(b.per_label) == 2

    def test_csv_benchmark_rows_do_not_auto_supplement_older_json_history(self, tmp_path):
        history_dir = history_csv_for_output(tmp_path / "output").parent
        history_dir.mkdir(parents=True)
        older_eval_dir = (
            tmp_path
            / "golden"
            / "benchmark-vs-golden"
            / "2026-02-10_12.00.00"
        )
        older_eval_dir.mkdir(parents=True)
        (older_eval_dir / "eval_report.json").write_text(
            json.dumps(SAMPLE_EVAL_REPORT), encoding="utf-8"
        )
        newer_eval_dir = (
            tmp_path
            / "golden"
            / "benchmark-vs-golden"
            / "2026-02-11_16.00.00"
        )
        newer_eval_dir.mkdir(parents=True)

        csv_path = history_dir / "performance_history.csv"
        bench_row = _sample_csv_row(
            {
                "run_timestamp": "2026-02-11T16:00:00",
                "run_dir": str(newer_eval_dir),
                "file_name": "my_book.pdf",
                "run_category": "benchmark_eval",
                "precision": "0.05",
                "recall": "0.25",
                "f1": "0.08333333333333333",
            }
        )
        csv_path.write_text(
            SAMPLE_CSV_HEADER + "\n" + bench_row + "\n",
            encoding="utf-8",
        )

        data = collect_dashboard_data(
            output_root=tmp_path / "output",
            golden_root=tmp_path / "golden",
        )
        assert len(data.benchmark_records) == 1
        assert data.benchmark_records[0].run_timestamp == "2026-02-11T16:00:00"
        assert str(data.benchmark_records[0].artifact_dir) == str(newer_eval_dir)

    def test_csv_benchmark_rows_do_not_json_merge_without_opt_in_scan(self, tmp_path):
        history_dir = history_csv_for_output(tmp_path / "output").parent
        history_dir.mkdir(parents=True)
        eval_dir = tmp_path / "golden" / "eval-vs-pipeline" / "2026-02-11_16.00.00"
        eval_dir.mkdir(parents=True)
        (eval_dir / "eval_report.json").write_text(
            json.dumps(SAMPLE_EVAL_REPORT), encoding="utf-8"
        )

        csv_path = history_dir / "performance_history.csv"
        bench_row = _sample_csv_row(
            {
                "run_timestamp": "2026-02-11T16:00:00",
                "run_dir": str(eval_dir),
                "file_name": "my_book.pdf",
                "run_category": "benchmark_eval",
                "precision": "0.05",
                "recall": "0.25",
                "f1": "0.08333333333333333",
            }
        )
        csv_path.write_text(
            SAMPLE_CSV_HEADER + "\n" + bench_row + "\n",
            encoding="utf-8",
        )

        data = collect_dashboard_data(
            output_root=tmp_path / "output",
            golden_root=tmp_path / "golden",
        )
        assert len(data.benchmark_records) == 1
        record = data.benchmark_records[0]
        assert record.recipes is None
        assert record.gold_recipe_headers is None

    def test_benchmark_csv_per_label_json_roundtrip(self, tmp_path):
        history_dir = history_csv_for_output(tmp_path / "output").parent
        history_dir.mkdir(parents=True, exist_ok=True)
        csv_path = history_dir / "performance_history.csv"
        append_benchmark_csv(
            SAMPLE_EVAL_REPORT,
            csv_path,
            run_timestamp="2026-02-11T16:00:00",
            run_dir=str(tmp_path / "golden" / "eval-vs-pipeline" / "2026-02-11_16.00.00"),
            eval_scope="freeform-spans",
            source_file="book.epub",
        )

        data = collect_dashboard_data(
            output_root=tmp_path / "output",
            golden_root=tmp_path / "golden",
        )
        assert len(data.benchmark_records) == 1
        labels = {entry.label for entry in data.benchmark_records[0].per_label}
        assert labels == {"RECIPE_TITLE", "INGREDIENT_LINE"}

    def test_benchmark_csv_schema_migration(self, tmp_path):
        """Existing CSV without new columns gets migrated when appending."""
        csv_path = tmp_path / "history.csv"
        # Write old-format CSV (missing benchmark columns)
        old_header = (
            "run_timestamp,run_dir,file_name,report_path,importer_name,"
            "total_seconds,parsing_seconds,writing_seconds,ocr_seconds,"
            "recipes,standalone_blocks,total_units,per_recipe_seconds,per_unit_seconds,"
            "output_files,output_bytes,"
            "dominant_stage,dominant_stage_seconds,dominant_checkpoint,dominant_checkpoint_seconds"
        )
        old_row = (
            "2026-02-10T10:00:00,/some/dir,test.xlsx,,,"
            "5.5,1.2,3.8,0.0,"
            "20,10,30,0.275,0.183,"
            "10,50000,"
            "writing,3.8,write_final_seconds,3.5"
        )
        csv_path.write_text(old_header + "\n" + old_row + "\n", encoding="utf-8")

        # Append a benchmark row — should trigger schema migration
        append_benchmark_csv(
            SAMPLE_EVAL_REPORT,
            csv_path,
            run_timestamp="2026-02-11T16:00:00",
            run_dir="/some/eval/dir",
            eval_scope="freeform-spans",
        )

        with csv_path.open("r", newline="", encoding="utf-8") as fh:
            reader = csv.DictReader(fh)
            assert list(reader.fieldnames) == _CSV_FIELDS
            rows = list(reader)

        assert len(rows) == 2
        # Old row should have empty benchmark fields after migration
        assert rows[0]["run_category"] == ""
        assert rows[0]["precision"] == ""
        assert rows[0]["recipes"] == "20"
        # New row should have benchmark fields populated
        assert rows[1]["run_category"] == "benchmark_eval"
        assert float(rows[1]["precision"]) == pytest.approx(0.05)

    def test_backfill_benchmark_csv_from_manifest(self, tmp_path):
        history_dir = history_csv_for_output(tmp_path / "output").parent
        history_dir.mkdir(parents=True)
        csv_path = history_dir / "performance_history.csv"

        eval_dir = tmp_path / "golden" / "eval-vs-pipeline" / "2026-02-16_14.05.00"
        eval_dir.mkdir(parents=True, exist_ok=True)
        processed_report = (
            tmp_path / "output" / "2026-02-16_14.04.00" / "book.excel_import_report.json"
        )
        processed_report.parent.mkdir(parents=True, exist_ok=True)
        processed_report.write_text(json.dumps({"totalRecipes": 12}), encoding="utf-8")
        (eval_dir / "manifest.json").write_text(
            json.dumps(
                {
                    "recipe_count": 12,
                    "processed_report_path": str(processed_report),
                    "source_file": "book.epub",
                }
            ),
            encoding="utf-8",
        )

        bench_row = {field: "" for field in _CSV_FIELDS}
        bench_row.update(
            {
                "run_timestamp": "2026-02-16T14:05:00",
                "run_dir": str(eval_dir),
                "run_category": "benchmark_eval",
                "eval_scope": "freeform-spans",
            }
        )
        with csv_path.open("w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=_CSV_FIELDS)
            writer.writeheader()
            writer.writerow(bench_row)

        summary = backfill_benchmark_history_csv(csv_path)
        assert summary.benchmark_rows == 1
        assert summary.rows_updated == 1
        assert summary.recipes_filled == 1
        assert summary.report_paths_filled == 1
        assert summary.source_files_filled == 1
        assert summary.rows_still_missing_recipes == 0

        with csv_path.open("r", newline="", encoding="utf-8") as fh:
            row = next(csv.DictReader(fh))
        assert row["recipes"] == "12"
        assert row["report_path"] == str(processed_report)
        assert row["file_name"] == "book.epub"

    def test_backfill_benchmark_csv_sums_bench_suite_item_recipes(self, tmp_path):
        history_dir = history_csv_for_output(tmp_path / "output").parent
        history_dir.mkdir(parents=True)
        csv_path = history_dir / "performance_history.csv"
        run_dir = tmp_path / "golden" / "bench" / "runs" / "2026-02-16_14.20.00"
        (run_dir / "per_item" / "a" / "pred_run").mkdir(parents=True, exist_ok=True)
        (run_dir / "per_item" / "b" / "pred_run").mkdir(parents=True, exist_ok=True)
        (run_dir / "per_item" / "a" / "pred_run" / "manifest.json").write_text(
            json.dumps({"recipe_count": 4}),
            encoding="utf-8",
        )
        processed_report = (
            tmp_path / "output" / "2026-02-16_14.19.00" / "item-b.excel_import_report.json"
        )
        processed_report.parent.mkdir(parents=True, exist_ok=True)
        processed_report.write_text(json.dumps({"totalRecipes": 7}), encoding="utf-8")
        (run_dir / "per_item" / "b" / "pred_run" / "manifest.json").write_text(
            json.dumps({"processed_report_path": str(processed_report)}),
            encoding="utf-8",
        )

        bench_row = {field: "" for field in _CSV_FIELDS}
        bench_row.update(
            {
                "run_timestamp": "2026-02-16T14:21:00",
                "run_dir": str(run_dir),
                "run_category": "benchmark_eval",
                "eval_scope": "bench-suite",
                "file_name": "my-suite",
            }
        )
        with csv_path.open("w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=_CSV_FIELDS)
            writer.writeheader()
            writer.writerow(bench_row)

        summary = backfill_benchmark_history_csv(csv_path)
        assert summary.benchmark_rows == 1
        assert summary.rows_updated == 1
        assert summary.recipes_filled == 1
        assert summary.report_paths_filled == 0
        assert summary.source_files_filled == 0
        assert summary.rows_still_missing_recipes == 0

        with csv_path.open("r", newline="", encoding="utf-8") as fh:
            row = next(csv.DictReader(fh))
        assert row["recipes"] == "11"
        assert row["report_path"] == ""

    def test_backfill_benchmark_csv_fills_line_role_tokens_from_manifest(self, tmp_path):
        history_dir = history_csv_for_output(tmp_path / "output").parent
        history_dir.mkdir(parents=True)
        csv_path = history_dir / "performance_history.csv"
        eval_dir = tmp_path / "golden" / "eval-vs-pipeline" / "2026-02-16_14.30.00"
        eval_dir.mkdir(parents=True, exist_ok=True)
        telemetry_path = eval_dir / "line-role-pipeline" / "telemetry_summary.json"
        telemetry_path.parent.mkdir(parents=True, exist_ok=True)
        telemetry_path.write_text(
            json.dumps(
                {
                    "summary": {
                        "tokens_input": 40,
                        "tokens_cached_input": 4,
                        "tokens_output": 6,
                        "tokens_reasoning": 1,
                        "tokens_total": 46,
                    }
                }
            ),
            encoding="utf-8",
        )
        (eval_dir / "manifest.json").write_text(
            json.dumps(
                {
                    "source_file": "book.epub",
                    "line_role_pipeline_telemetry_path": str(telemetry_path),
                }
            ),
            encoding="utf-8",
        )

        bench_row = {field: "" for field in _CSV_FIELDS}
        bench_row.update(
            {
                "run_timestamp": "2026-02-16T14:31:00",
                "run_dir": str(eval_dir),
                "run_category": "benchmark_eval",
                "eval_scope": "freeform-spans",
            }
        )
        with csv_path.open("w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=_CSV_FIELDS)
            writer.writeheader()
            writer.writerow(bench_row)

        summary = backfill_benchmark_history_csv(csv_path)

        assert summary.token_rows_filled == 1
        assert summary.token_fields_filled == 5
        with csv_path.open("r", newline="", encoding="utf-8") as fh:
            row = next(csv.DictReader(fh))
        assert row["tokens_input"] == "40"
        assert row["tokens_cached_input"] == "4"
        assert row["tokens_output"] == "6"
        assert row["tokens_reasoning"] == "1"
        assert row["tokens_total"] == "46"

    def test_backfill_benchmark_csv_fills_line_role_tokens_from_run_manifest_artifact(
        self, tmp_path
    ):
        history_dir = history_csv_for_output(tmp_path / "output").parent
        history_dir.mkdir(parents=True)
        csv_path = history_dir / "performance_history.csv"
        eval_dir = tmp_path / "golden" / "eval-vs-pipeline" / "2026-02-16_14.35.00"
        eval_dir.mkdir(parents=True, exist_ok=True)
        telemetry_path = eval_dir / "line-role-pipeline" / "telemetry_summary.json"
        telemetry_path.parent.mkdir(parents=True, exist_ok=True)
        telemetry_path.write_text(
            json.dumps(
                {
                    "summary": {
                        "tokens_input": 14,
                        "tokens_cached_input": 1,
                        "tokens_output": 3,
                        "tokens_reasoning": 2,
                        "tokens_total": 17,
                    }
                }
            ),
            encoding="utf-8",
        )
        (eval_dir / "run_manifest.json").write_text(
            json.dumps(
                {
                    "artifacts": {
                        "line_role_pipeline_telemetry_json": str(telemetry_path)
                    }
                }
            ),
            encoding="utf-8",
        )

        bench_row = {field: "" for field in _CSV_FIELDS}
        bench_row.update(
            {
                "run_timestamp": "2026-02-16T14:35:30",
                "run_dir": str(eval_dir),
                "run_category": "benchmark_eval",
                "eval_scope": "freeform-spans",
            }
        )
        with csv_path.open("w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=_CSV_FIELDS)
            writer.writeheader()
            writer.writerow(bench_row)

        summary = backfill_benchmark_history_csv(csv_path)

        assert summary.token_rows_filled == 1
        assert summary.token_fields_filled == 5
        with csv_path.open("r", newline="", encoding="utf-8") as fh:
            row = next(csv.DictReader(fh))
        assert row["tokens_input"] == "14"
        assert row["tokens_cached_input"] == "1"
        assert row["tokens_output"] == "3"
        assert row["tokens_reasoning"] == "2"
        assert row["tokens_total"] == "17"

    def test_backfill_benchmark_csv_sums_knowledge_and_nested_line_role_tokens(
        self, tmp_path
    ):
        history_dir = history_csv_for_output(tmp_path / "output").parent
        history_dir.mkdir(parents=True)
        csv_path = history_dir / "performance_history.csv"
        eval_dir = tmp_path / "golden" / "eval-vs-pipeline" / "2026-02-16_14.37.00"
        eval_dir.mkdir(parents=True, exist_ok=True)
        telemetry_path = eval_dir / "line-role-pipeline" / "telemetry_summary.json"
        telemetry_path.parent.mkdir(parents=True, exist_ok=True)
        telemetry_path.write_text(
            json.dumps(
                {
                    "summary": {
                        "batch_count": 2,
                        "attempt_count": 2,
                    },
                    "batches": [
                        {
                            "attempts": [
                                {
                                    "process_run": {
                                        "process_payload": {
                                            "telemetry_report": {
                                                "summary": {
                                                    "matched_rows": 1,
                                                    "tokens_total": 13,
                                                }
                                            }
                                        }
                                    }
                                }
                            ]
                        },
                        {
                            "attempts": [
                                {
                                    "process_run": {
                                        "process_payload": {
                                            "telemetry_report": {
                                                "summary": {
                                                    "matched_rows": 1,
                                                    "tokens_total": 17,
                                                }
                                            }
                                        }
                                    }
                                }
                            ]
                        },
                    ],
                }
            ),
            encoding="utf-8",
        )
        (eval_dir / "manifest.json").write_text(
            json.dumps(
                {
                    "source_file": "book.epub",
                    "line_role_pipeline_telemetry_path": str(telemetry_path),
                    "llm_codex_farm": {
                        "process_runs": {
                            "recipe_refine": {
                                "process_payload": {
                                    "telemetry": {
                                        "rows": [
                                            {
                                                "tokens_input": 40,
                                                "tokens_cached_input": 4,
                                                "tokens_output": 6,
                                                "tokens_reasoning": 1,
                                                "tokens_total": 46,
                                            }
                                        ]
                                    }
                                }
                            }
                        },
                        "knowledge": {
                            "process_run": {
                                "process_payload": {
                                    "telemetry": {
                                        "rows": [
                                            {
                                                "tokens_input": 70,
                                                "tokens_cached_input": 7,
                                                "tokens_output": 8,
                                                "tokens_reasoning": 0,
                                                "tokens_total": 78,
                                            }
                                        ]
                                    }
                                }
                            }
                        },
                    },
                }
            ),
            encoding="utf-8",
        )

        bench_row = {field: "" for field in _CSV_FIELDS}
        bench_row.update(
            {
                "run_timestamp": "2026-02-16T14:37:30",
                "run_dir": str(eval_dir),
                "run_category": "benchmark_eval",
                "eval_scope": "freeform-spans",
                "tokens_input": "40",
                "tokens_cached_input": "4",
                "tokens_output": "6",
                "tokens_reasoning": "1",
                "tokens_total": "46",
            }
        )
        with csv_path.open("w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=_CSV_FIELDS)
            writer.writeheader()
            writer.writerow(bench_row)

        summary = backfill_benchmark_history_csv(csv_path)

        assert summary.token_rows_filled == 1
        assert summary.token_fields_filled == 4
        with csv_path.open("r", newline="", encoding="utf-8") as fh:
            row = next(csv.DictReader(fh))
        assert row["tokens_input"] == "110"
        assert row["tokens_cached_input"] == "11"
        assert row["tokens_output"] == "14"
        assert row["tokens_reasoning"] == "1"
        assert row["tokens_total"] == "154"

    def test_backfill_benchmark_csv_leaves_line_role_tokens_blank_when_usage_incomplete(
        self, tmp_path
    ):
        history_dir = history_csv_for_output(tmp_path / "output").parent
        history_dir.mkdir(parents=True)
        csv_path = history_dir / "performance_history.csv"
        eval_dir = tmp_path / "golden" / "eval-vs-pipeline" / "2026-02-16_14.39.00"
        eval_dir.mkdir(parents=True, exist_ok=True)
        telemetry_path = eval_dir / "line-role-pipeline" / "telemetry_summary.json"
        telemetry_path.parent.mkdir(parents=True, exist_ok=True)
        telemetry_path.write_text(
            json.dumps(
                {
                    "summary": {
                        "attempt_count": 2,
                        "attempts_with_usage": 1,
                        "attempts_without_usage": 1,
                        "tokens_input": 0,
                        "tokens_cached_input": 0,
                        "tokens_output": 0,
                        "tokens_reasoning": 0,
                        "tokens_total": 0,
                        "visible_input_tokens": 77,
                        "visible_output_tokens": 4,
                        "command_execution_count_total": 2,
                    }
                }
            ),
            encoding="utf-8",
        )
        (eval_dir / "manifest.json").write_text(
            json.dumps(
                {
                    "source_file": "book.epub",
                    "line_role_pipeline_telemetry_path": str(telemetry_path),
                }
            ),
            encoding="utf-8",
        )

        bench_row = {field: "" for field in _CSV_FIELDS}
        bench_row.update(
            {
                "run_timestamp": "2026-02-16T14:39:30",
                "run_dir": str(eval_dir),
                "run_category": "benchmark_eval",
                "eval_scope": "freeform-spans",
            }
        )
        with csv_path.open("w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=_CSV_FIELDS)
            writer.writeheader()
            writer.writerow(bench_row)

        summary = backfill_benchmark_history_csv(csv_path)

        assert summary.token_rows_filled == 0
        assert summary.token_fields_filled == 0
        with csv_path.open("r", newline="", encoding="utf-8") as fh:
            row = next(csv.DictReader(fh))
        assert row["tokens_input"] == ""
        assert row["tokens_cached_input"] == ""
        assert row["tokens_output"] == ""
        assert row["tokens_reasoning"] == ""
        assert row["tokens_total"] == ""

    def test_backfill_benchmark_csv_leaves_bad_line_role_zero_summary_blank(
        self, tmp_path
    ):
        history_dir = history_csv_for_output(tmp_path / "output").parent
        history_dir.mkdir(parents=True)
        csv_path = history_dir / "performance_history.csv"
        eval_dir = tmp_path / "golden" / "eval-vs-pipeline" / "2026-02-16_14.39.30"
        eval_dir.mkdir(parents=True, exist_ok=True)
        telemetry_path = eval_dir / "line-role-pipeline" / "telemetry_summary.json"
        telemetry_path.parent.mkdir(parents=True, exist_ok=True)
        telemetry_path.write_text(
            json.dumps(
                {
                    "summary": {
                        "attempt_count": 2,
                        "attempts_with_usage": 2,
                        "attempts_without_usage": 0,
                        "tokens_input": 0,
                        "tokens_cached_input": 0,
                        "tokens_output": 0,
                        "tokens_reasoning": 0,
                        "tokens_total": 0,
                        "visible_input_tokens": 77,
                        "visible_output_tokens": 4,
                        "command_execution_count_total": 2,
                    }
                }
            ),
            encoding="utf-8",
        )
        (eval_dir / "manifest.json").write_text(
            json.dumps(
                {
                    "source_file": "book.epub",
                    "line_role_pipeline_telemetry_path": str(telemetry_path),
                }
            ),
            encoding="utf-8",
        )

        bench_row = {field: "" for field in _CSV_FIELDS}
        bench_row.update(
            {
                "run_timestamp": "2026-02-16T14:39:45",
                "run_dir": str(eval_dir),
                "run_category": "benchmark_eval",
                "eval_scope": "freeform-spans",
            }
        )
        with csv_path.open("w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=_CSV_FIELDS)
            writer.writeheader()
            writer.writerow(bench_row)

        summary = backfill_benchmark_history_csv(csv_path)

        assert summary.token_rows_filled == 0
        assert summary.token_fields_filled == 0
        with csv_path.open("r", newline="", encoding="utf-8") as fh:
            row = next(csv.DictReader(fh))
        assert row["tokens_input"] == ""
        assert row["tokens_cached_input"] == ""
        assert row["tokens_output"] == ""
        assert row["tokens_reasoning"] == ""
        assert row["tokens_total"] == ""

    def test_dashboard_collector_sums_codex_farm_and_line_role_manifest_tokens(self, tmp_path):
        history_dir = history_csv_for_output(tmp_path / "output").parent
        history_dir.mkdir(parents=True)
        csv_path = history_dir / "performance_history.csv"
        eval_dir = tmp_path / "golden" / "eval-vs-pipeline" / "2026-02-16_14.40.00"
        eval_dir.mkdir(parents=True, exist_ok=True)
        telemetry_path = eval_dir / "line-role-pipeline" / "telemetry_summary.json"
        telemetry_path.parent.mkdir(parents=True, exist_ok=True)
        telemetry_path.write_text(
            json.dumps(
                {
                    "summary": {
                        "batch_count": 2,
                        "attempt_count": 2,
                    },
                    "batches": [
                        {
                            "attempts": [
                                {
                                    "process_run": {
                                        "process_payload": {
                                            "telemetry_report": {
                                                "summary": {
                                                    "matched_rows": 1,
                                                    "tokens_total": 23,
                                                }
                                            }
                                        }
                                    }
                                }
                            ]
                        },
                        {
                            "attempts": [
                                {
                                    "process_run": {
                                        "process_payload": {
                                            "telemetry_report": {
                                                "summary": {
                                                    "matched_rows": 1,
                                                    "tokens_total": 34,
                                                }
                                            }
                                        }
                                    }
                                }
                            ]
                        },
                    ],
                }
            ),
            encoding="utf-8",
        )
        (eval_dir / "run_manifest.json").write_text(
            json.dumps(
                {
                    "source_file": "book.epub",
                    "artifacts": {
                        "line_role_pipeline_telemetry_json": str(telemetry_path)
                    },
                    "llm_codex_farm": {
                        "process_runs": {
                            "recipe_refine": {
                                "process_payload": {
                                    "telemetry": {
                                        "rows": [
                                            {
                                                "tokens_input": 101,
                                                "tokens_cached_input": 9,
                                                "tokens_output": 12,
                                                "tokens_reasoning": 1,
                                                "tokens_total": 114,
                                            }
                                        ]
                                    }
                                }
                            }
                        },
                        "knowledge": {
                            "process_run": {
                                "process_payload": {
                                    "telemetry": {
                                        "rows": [
                                            {
                                                "tokens_input": 200,
                                                "tokens_cached_input": 20,
                                                "tokens_output": 30,
                                                "tokens_reasoning": 0,
                                                "tokens_total": 230,
                                            }
                                        ]
                                    }
                                }
                            }
                        }
                    },
                }
            ),
            encoding="utf-8",
        )

        bench_row = _sample_csv_row(
            {
                "run_timestamp": "2026-02-16T14:41:00",
                "run_dir": str(eval_dir),
                "file_name": "book.epub",
                "run_category": "benchmark_eval",
                "eval_scope": "freeform-spans",
                "precision": "0.05",
                "recall": "0.25",
                "f1": "0.08",
                "tokens_input": "101",
                "tokens_cached_input": "9",
                "tokens_output": "12",
                "tokens_reasoning": "1",
                "tokens_total": "114",
            }
        )
        csv_path.write_text(SAMPLE_CSV_HEADER + "\n" + bench_row + "\n", encoding="utf-8")

        data = collect_dashboard_data(
            output_root=tmp_path / "output",
            golden_root=tmp_path / "golden",
        )

        assert len(data.benchmark_records) == 1
        record = data.benchmark_records[0]
        assert record.tokens_input == 301
        assert record.tokens_cached_input == 29
        assert record.tokens_output == 42
        assert record.tokens_reasoning == 1
        assert record.tokens_total == 401
