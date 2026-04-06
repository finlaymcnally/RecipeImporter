from __future__ import annotations

from cookimport.analytics.dashboard_schema import BenchmarkRecord, DashboardData
from cookimport.analytics.dashboard_render import render_dashboard
from tests.analytics.test_stats_dashboard import (
    _run_benchmark_trend_host_width_drift_harness,
    _run_dashboard_page_runtime_smoke_harness,
    _run_previous_runs_pixel_overflow_harness,
)


def test_previous_runs_stays_within_viewport_pixels_after_rerenders(tmp_path):
    benchmark_records = []
    for index in range(72):
        benchmark_records.append(
            BenchmarkRecord(
                run_timestamp=f"2026-03-01T10:{index % 60:02d}:00",
                run_dir=f"/tmp/runs/{index}",
                file_name=f"book_{index}.pdf",
                strict_accuracy=0.5 + ((index % 10) * 0.01),
                macro_f1_excluding_other=0.4 + ((index % 7) * 0.01),
                source_file=(f"source_group_{index % 4}_" * 36) + str(index),
                source_label=(f"label_group_{index % 5}_" * 22) + str(index),
                artifact_dir=(
                    "/tmp/golden/benchmark-vs-golden/"
                    + ("cookbook_slug_" * 16)
                    + f"/2026-03-01_10.00.00/single-book-benchmark/book_{index % 3}"
                    + f"/2026-03-01_10.{index % 60:02d}.00/"
                    + ("codex-exec" if index % 2 else "vanilla")
                ),
                run_category="benchmark_eval",
                importer_name="pdfplumber",
                run_config={
                    "scenario_key": (f"scenario_{index % 3}_" * 24) + str(index)
                },
            )
        )
    dash_dir = tmp_path / "dash"
    render_dashboard(dash_dir, DashboardData(benchmark_records=benchmark_records))
    result = _run_previous_runs_pixel_overflow_harness(dash_dir / "index.html")
    assert result["max_doc_overflow_px"] <= 2
    assert result["max_section_overflow_px"] <= 2
    assert result["max_doc_scroll_delta_px"] <= 2


def test_benchmark_trend_hosts_do_not_gain_horizontal_drift_over_time(tmp_path):
    benchmark_records = []
    for index in range(72):
        benchmark_records.append(
            BenchmarkRecord(
                run_timestamp=f"2026-03-01T10:{index % 60:02d}:00",
                run_dir=f"/tmp/runs/{index}",
                file_name=f"book_{index}.pdf",
                strict_accuracy=0.5 + ((index % 10) * 0.01),
                macro_f1_excluding_other=0.4 + ((index % 7) * 0.01),
                source_file=(f"source_group_{index % 4}_" * 36) + str(index),
                source_label=(f"label_group_{index % 5}_" * 22) + str(index),
                artifact_dir=(
                    "/tmp/golden/benchmark-vs-golden/"
                    + ("cookbook_slug_" * 16)
                    + f"/2026-03-01_10.00.00/single-book-benchmark/book_{index % 3}"
                    + f"/2026-03-01_10.{index % 60:02d}.00/"
                    + ("codex-exec" if index % 2 else "vanilla")
                ),
                run_category="benchmark_eval",
                importer_name="pdfplumber",
                run_config={
                    "scenario_key": (f"scenario_{index % 3}_" * 24) + str(index)
                },
            )
        )
    dash_dir = tmp_path / "dash"
    render_dashboard(dash_dir, DashboardData(benchmark_records=benchmark_records))

    result = _run_benchmark_trend_host_width_drift_harness(dash_dir / "index.html")
    assert result["state_request_count"] >= 3
    assert result["highcharts_render_count"] >= 4
    assert result["max_trend_host_overflow_px"] <= 2
    assert result["max_compare_control_host_overflow_px"] <= 2
    assert result["trend_host_scroll_delta_px"] <= 2
    assert result["compare_control_host_scroll_delta_px"] <= 2


def test_dashboard_page_load_and_basic_interactions_have_no_runtime_errors(tmp_path):
    benchmark_records = []
    for index in range(12):
        benchmark_records.append(
            BenchmarkRecord(
                run_timestamp=f"2026-03-04T10:{index:02d}:00",
                run_dir=f"/tmp/runs/{index}",
                file_name=f"book_{index % 3}.pdf",
                strict_accuracy=0.55 + (index * 0.01),
                macro_f1_excluding_other=0.45 + (index * 0.008),
                all_token_use=1000 + (index * 120),
                source_file=f"/tmp/source/book_{index % 3}.epub",
                source_label=f"book_{index % 3}.epub",
                artifact_dir=f"/tmp/golden/run_{index}",
                run_category="benchmark_eval",
                importer_name="pdfplumber" if index % 2 else "epub",
                ai_assistance_profile="full_stack" if index % 2 else "deterministic",
            )
        )

    dash_dir = tmp_path / "dash"
    render_dashboard(dash_dir, DashboardData(benchmark_records=benchmark_records))

    result = _run_dashboard_page_runtime_smoke_harness(dash_dir / "index.html")
    assert result["page_errors"] == []
    assert result["console_errors"] == []
    assert result["previous_runs_count"] >= 1
