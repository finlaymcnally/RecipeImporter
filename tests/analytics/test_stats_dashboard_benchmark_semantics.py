from __future__ import annotations

import tests.analytics.stats_dashboard_support as _support

# Reuse shared imports/helpers from the local support module.
globals().update({
    name: value
    for name, value in _support.__dict__.items()
    if not name.startswith("test_")
    and not (name.startswith("__") and name.endswith("__"))
})


class TestBenchmarkSemantics:
    def test_path_only_rundir_codex_exec_rows_no_longer_recover_codex_variant(self):
        record = {
            "run_dir": (
                "/tmp/golden/benchmark-vs-golden/2026-03-03_13.07.22/"
                "single-book-benchmark/seaandsmokecutdown/codex-exec"
            ),
            "report_path": (
                "/tmp/output/2026-03-03_13.07.22/single-book-benchmark/"
                "seaandsmokecutdown/codex-exec/2026-03-03_13.07.43/report.json"
            ),
            "run_config": {
                "llm_recipe_pipeline": "codex-recipe-shard-v1",
                "line_role_pipeline": "off",
            },
        }
        assert ai_assistance_profile_for_record(record) == "recipe_only"
        assert benchmark_variant_for_record(record) == "recipe_only"
        assert is_official_golden_benchmark_record(record) is False

    def test_js_init_skips_removed_control_setup(self, tmp_path):
        render_dashboard(tmp_path / "dash", DashboardData())
        js = (tmp_path / "dash" / "assets" / "dashboard.js").read_text(encoding="utf-8")
        assert "setupFilters();" not in js
        assert "setupExtractorFilters();" not in js
        assert "setupThroughputModeControls();" not in js
        assert "setupGlobalCollapseControls();" not in js
        assert "renderPreviousRuns();" in js

    def test_benchmark_trend_chart_uses_fixed_height(self, tmp_path):
        render_dashboard(tmp_path / "dash", DashboardData())
        js = (tmp_path / "dash" / "assets" / "dashboard.js").read_text(encoding="utf-8")
        css = (tmp_path / "dash" / "assets" / "style.css").read_text(encoding="utf-8")
        assert ".highcharts-host {" in css
        assert "height: 800px;" in css
        assert "const HIGHCHARTS_MOUSE_WHEEL_ZOOM_ENABLED = false;" in js
        assert "window.Highcharts.setOptions({" in js
        assert "mouseWheel: {" in js
        assert "enabled: HIGHCHARTS_MOUSE_WHEEL_ZOOM_ENABLED" in js
        assert "function renderBenchmarkTrendChartHost(config)" in js
        assert "window.Highcharts.stockChart(hostId, {" in js
        assert 'hostId: "benchmark-trend-chart"' in js
        assert 'hostId: "compare-control-trend-chart"' in js
        assert "renderCompareControlSection();" in js
        assert "Compare/Control Benchmark Score Trends" not in js
        assert "chart: {" in js
        assert "height: 800," in js
        assert "rangeSelector: {" in js
        assert '{ type: "all", text: "All" }' in js
        assert "selected: 5," in js
        assert "navigator: {\n        enabled: false,\n      }," in js
        assert "scrollbar: {\n        enabled: false,\n      }," in js
        assert "const allRunTimestamps = sorted" in js
        assert "const timelineMin = allRunTimestamps.length ? allRunTimestamps[0] : null;" in js
        assert "const timelineMax = allRunTimestamps.length ? allRunTimestamps[allRunTimestamps.length - 1] : null;" in js
        assert "const emptyReason = selectedTrendFields.length" in js
        assert "No trend fields selected. Pick one or more fields above." in js
        assert "const xAxisConfig = {" in js
        assert "if (timelineMin != null) xAxisConfig.min = timelineMin;" in js
        assert "if (timelineMax != null) xAxisConfig.max = timelineMax;" in js
        assert "xAxis: xAxisConfig," in js
        assert "setupDashboardResizeHandlers();" in js
        assert 'window.addEventListener("resize", handleDashboardWindowResize, { passive: true });' in js
        assert "function benchmarkVariantForRecord(record)" in js
        assert "function benchmarkRunGroupInfo(record)" in js
        assert "runGroupTimestampText" in js
        assert "function benchmarkRunGroupXAxisTimestampMs(record, runGroup)" in js
        assert "const xMs = benchmarkRunGroupXAxisTimestampMs(record, runGroup);" in js
        assert "if (xMs == null) return null;" in js
        assert "function trendSeriesPointForRunGroup(series, runGroupKey, hoveredX)" in js
        assert "function rollingTrendWindowSize(count)" in js
        assert "function medianFromSortedNumbers(values)" in js
        assert "function aggregateTrendSeriesPoints(points)" in js
        assert "function buildRollingTrend(points)" in js
        assert "function withTrendOverlays(baseSeriesList)" in js
        assert "function isTrendOverlaySeries(series)" in js
        assert "function buildBenchmarkTrendSeries(records)" in js
        assert "function benchmarkTrendMetricColors(metricKey, metricIndex)" in js
        assert "function benchmarkTrendShiftHexColor(baseColor, shift)" in js
        assert "const hasPairedVariants =" in js
        assert 'name: metric.key + " (" + variant + ")"' in js
        assert "series: trendSeries," in js
        assert 'type: "scatter"' in js
        assert 'name: baseSeries.name + " trend"' not in js
        assert 'type: "arearange"' not in js
        assert 'name: baseSeries.name + " rolling range"' not in js
        assert 'name: baseSeries.name + " rolling trend"' in js
        assert "lineWidth: 0," in js
        assert "shared: false," in js
        assert "formatter: function()" in js
        assert "if (!series || series.visible === false || isTrendOverlaySeries(series)) return;" in js
        assert "trendSeriesPointForRunGroup(series, runGroupKey, hoveredX)" in js
        assert "runGroupKey" in js
        assert "runGroupLabel" in js
        assert "&#9679;" in js
        assert "Run-group values:" not in js

    def test_benchmark_trend_pairs_variant_points_on_same_run_group_x_axis(self, tmp_path):
        dash_dir = tmp_path / "dash"
        render_dashboard(dash_dir, DashboardData())
        js_path = dash_dir / "assets" / "dashboard.js"
        records = [
            {
                "run_timestamp": "2026-03-01T10:01:00",
                "artifact_dir": (
                    "/tmp/golden/benchmark-vs-golden/seaandsmokecutdown/"
                    "2026-03-01_10.00.00/single-book-benchmark/seaandsmokecutdown/"
                    "2026-03-01_10.01.00/vanilla"
                ),
                "run_config": {
                    "llm_recipe_pipeline": "off",
                    "line_role_pipeline": "off",
                },
                "strict_accuracy": 0.42,
            },
            {
                "run_timestamp": "2026-03-01T10:06:00",
                "artifact_dir": (
                    "/tmp/golden/benchmark-vs-golden/seaandsmokecutdown/"
                    "2026-03-01_10.00.00/single-book-benchmark/seaandsmokecutdown/"
                    "2026-03-01_10.06.00/codex-exec"
                ),
                "run_config": {
                    "llm_recipe_pipeline": "codex-recipe-shard-v1",
                    "line_role_pipeline": "codex-line-role-route-v2",
                },
                "strict_accuracy": 0.58,
            },
        ]
        result = _run_benchmark_trend_alignment_harness(js_path, records)
        assert result["vanilla_series_points"] == 1
        assert result["codex_series_points"] == 1
        assert result["vanilla_run_group_key"] == "2026-03-01_10.00.00"
        assert result["codex_run_group_key"] == "2026-03-01_10.00.00"
        assert result["vanilla_x"] == result["codex_x"]

    def test_benchmark_trend_supports_arbitrary_selected_numeric_fields(self, tmp_path):
        dash_dir = tmp_path / "dash"
        render_dashboard(dash_dir, DashboardData())
        js_path = dash_dir / "assets" / "dashboard.js"
        records = [
            {
                "run_timestamp": "2026-03-01T10:01:00",
                "artifact_dir": (
                    "/tmp/golden/benchmark-vs-golden/seaandsmokecutdown/"
                    "2026-03-01_10.00.00/single-book-benchmark/seaandsmokecutdown/"
                    "2026-03-01_10.01.00/vanilla"
                ),
                "run_config": {
                    "llm_recipe_pipeline": "off",
                    "line_role_pipeline": "off",
                },
                "tokens_total": 1500,
            },
            {
                "run_timestamp": "2026-03-01T10:06:00",
                "artifact_dir": (
                    "/tmp/golden/benchmark-vs-golden/seaandsmokecutdown/"
                    "2026-03-01_10.00.00/single-book-benchmark/seaandsmokecutdown/"
                    "2026-03-01_10.06.00/codex-exec"
                ),
                "run_config": {
                    "llm_recipe_pipeline": "codex-recipe-shard-v1",
                    "line_role_pipeline": "codex-line-role-route-v2",
                },
                "tokens_total": 2300,
            },
        ]
        result = _run_benchmark_trend_alignment_harness(
            js_path,
            records,
            trend_fields=["tokens_total"],
        )
        assert result["selected_fields"] == ["tokens_total"]
        assert result["vanilla_series_points"] == 0
        assert result["codex_series_points"] == 0
        assert result["token_vanilla_series_points"] == 1
        assert result["token_codex_series_points"] == 1

    def test_benchmark_trend_keeps_deterministic_hybrid_points_when_paired_variants_exist(self, tmp_path):
        dash_dir = tmp_path / "dash"
        render_dashboard(dash_dir, DashboardData())
        js_path = dash_dir / "assets" / "dashboard.js"
        records = [
            {
                "run_timestamp": "2026-03-01T10:01:00",
                "artifact_dir": (
                    "/tmp/golden/benchmark-vs-golden/seaandsmokecutdown/"
                    "2026-03-01_10.00.00/single-book-benchmark/seaandsmokecutdown/vanilla"
                ),
                "run_config": {
                    "llm_recipe_pipeline": "off",
                    "line_role_pipeline": "off",
                },
                "strict_accuracy": 0.42,
            },
            {
                "run_timestamp": "2026-03-01T10:06:00",
                "artifact_dir": (
                    "/tmp/golden/benchmark-vs-golden/seaandsmokecutdown/"
                    "2026-03-01_10.00.00/single-book-benchmark/seaandsmokecutdown/codex-exec"
                ),
                "run_config": {
                    "llm_recipe_pipeline": "codex-recipe-shard-v1",
                    "line_role_pipeline": "codex-line-role-route-v2",
                },
                "strict_accuracy": 0.58,
            },
            {
                "run_timestamp": "2026-03-15T15:38:16",
                "artifact_dir": (
                    "/tmp/golden/benchmark-vs-golden/2026-03-15_15.37.33/"
                    "single-book-benchmark/saltfatacidheatcutdown/line_role_only"
                ),
                "benchmark_variant": "deterministic",
                "run_config": {
                    "llm_recipe_pipeline": "off",
                    "line_role_pipeline": "deterministic-route-v2",
                },
                "strict_accuracy": 0.5238744884038199,
            },
        ]
        result = _run_benchmark_trend_alignment_harness(js_path, records)
        assert result["vanilla_series_points"] == 2
        assert result["codex_series_points"] == 1
        assert result["deterministic_run_group_key"] == "2026-03-15_15.37.33"
        assert result["deterministic_trend_variant"] == "vanilla"
        assert result["deterministic_point_variant"] == "vanilla"
        assert result["deterministic_point_run_timestamp"] == "2026-03-15T15:38:16"

    def test_benchmark_trend_rebuckets_misc_other_runs_into_binary_variants(self, tmp_path):
        dash_dir = tmp_path / "dash"
        render_dashboard(dash_dir, DashboardData())
        js_path = dash_dir / "assets" / "dashboard.js"
        records = [
            {
                "run_timestamp": "2026-03-04T10:43:28",
                "artifact_dir": "data/output/labelstudio-benchmark/profeedback-2026-03-04_10.41.51-foodlab-02-det",
                "benchmark_variant": "other",
                "run_config": {
                    "llm_recipe_pipeline": "off",
                    "line_role_pipeline": "off",
                },
                "strict_accuracy": 0.41,
            },
            {
                "run_timestamp": "2026-03-04T10:50:28",
                "artifact_dir": "data/output/labelstudio-benchmark/profeedback-2026-03-04_10.41.51-foodlab-03-codex-line",
                "benchmark_variant": "other",
                "run_config": {
                    "llm_recipe_pipeline": "codex-recipe-shard-v1",
                    "line_role_pipeline": "off",
                },
                "strict_accuracy": 0.63,
            },
        ]
        result = _run_benchmark_trend_alignment_harness(js_path, records)
        assert result["vanilla_series_points"] == 1
        assert result["codex_series_points"] == 1

    def test_benchmark_trend_points_include_source_metadata_for_tooltips(self, tmp_path):
        dash_dir = tmp_path / "dash"
        render_dashboard(dash_dir, DashboardData())
        js_path = dash_dir / "assets" / "dashboard.js"
        records = [
            {
                "run_timestamp": "2026-03-01T10:01:00",
                "source_file": "/data/input/Sea And Smoke.epub",
                "artifact_dir": (
                    "/tmp/golden/benchmark-vs-golden/seaandsmokecutdown/"
                    "2026-03-01_10.00.00/single-book-benchmark/seaandsmokecutdown/"
                    "2026-03-01_10.01.00/vanilla"
                ),
                "run_config": {
                    "llm_recipe_pipeline": "off",
                    "line_role_pipeline": "off",
                },
                "strict_accuracy": 0.42,
            },
            {
                "run_timestamp": "2026-03-01T10:06:00",
                "source_file": "/data/input/Sea And Smoke.epub",
                "artifact_dir": (
                    "/tmp/golden/benchmark-vs-golden/seaandsmokecutdown/"
                    "2026-03-01_10.00.00/single-book-benchmark/seaandsmokecutdown/"
                    "2026-03-01_10.06.00/codex-exec"
                ),
                "run_config": {
                    "llm_recipe_pipeline": "codex-recipe-shard-v1",
                    "line_role_pipeline": "codex-line-role-route-v2",
                },
                "strict_accuracy": 0.58,
            },
        ]
        result = _run_benchmark_trend_alignment_harness(js_path, records)
        assert result["vanilla_series_points"] == 1
        assert result["codex_series_points"] == 1
        assert result["vanilla_point_source_label"] == "Sea And Smoke.epub"
        assert result["codex_point_source_label"] == "Sea And Smoke.epub"
        assert result["vanilla_point_source_title"] == "/data/input/Sea And Smoke.epub"
        assert result["codex_point_source_title"] == "/data/input/Sea And Smoke.epub"
        assert result["vanilla_point_variant"] == "vanilla"
        assert result["codex_point_variant"] == "codex-exec"
        assert result["vanilla_point_run_timestamp"] == "2026-03-01T10:01:00"
        assert result["codex_point_run_timestamp"] == "2026-03-01T10:06:00"

    def test_benchmark_trend_overlay_recomputes_tail_windows(self, tmp_path):
        dash_dir = tmp_path / "dash"
        render_dashboard(dash_dir, DashboardData())
        js_path = dash_dir / "assets" / "dashboard.js"
        points = [
            {"x": index + 1, "y": value, "custom": {"runGroupKey": f"group-{index + 1}"}}
            for index, value in enumerate([0, 0, 0, 0, 10, 20, 30, 40])
        ]
        result = _run_benchmark_trend_overlay_tail_harness(js_path, points)
        assert result["window_size"] == 5
        assert result["trend_point_count"] == len(points)
        assert len(result["tail"]) == 2
        assert result["tail"][0]["y"] == pytest.approx(25.0)
        assert result["tail"][1]["y"] == pytest.approx(30.0)

    def test_benchmark_trend_host_rerender_starts_from_clean_host(self, tmp_path):
        dash_dir = tmp_path / "dash"
        render_dashboard(dash_dir, DashboardData())
        js_path = dash_dir / "assets" / "dashboard.js"
        result = _run_benchmark_trend_host_rerender_harness(js_path)
        assert result["stockchart_calls"] == 2
        assert result["first_before_empty"] is True
        assert result["second_before_empty"] is True

    def test_previous_runs_table_has_horizontal_scroll_css(self, tmp_path):
        render_dashboard(tmp_path / "dash", DashboardData())
        css = (tmp_path / "dash" / "assets" / "style.css").read_text(encoding="utf-8")
        assert ".diagnostics-grid {" in css
        assert "grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);" in css
        assert "--previous-runs-visible-body-rows: 10;" in css
        assert ".quick-filters-panel {" in css
        assert ".quick-filters-list {" in css
        assert ".quick-filters-advanced {" not in css
        assert ".quick-filters-advanced-body {" not in css
        assert ".quick-filters-actions {" in css
        assert "justify-content: space-between;" in css
        assert ".quick-filters-presets-control {" not in css
        assert ".previous-runs-presets-toggle {" not in css
        assert ".previous-runs-presets-popup {" not in css
        assert ".previous-runs-sections {" in css
        assert ".previous-runs-subsection {" in css
        assert "#previous-runs-section {" in css
        assert "overflow-x: hidden;" in css
        previous_runs_sections_block = re.search(
            r"\.previous-runs-sections \{([^}]*)\}",
            css,
            re.DOTALL,
        )
        assert previous_runs_sections_block is not None
        assert "grid-template-columns: minmax(0, 1fr);" in previous_runs_sections_block.group(1)
        previous_runs_subsection_block = re.search(
            r"\.previous-runs-subsection \{([^}]*)\}",
            css,
            re.DOTALL,
        )
        assert previous_runs_subsection_block is not None
        assert "min-width: 0;" in previous_runs_subsection_block.group(1)
        assert ".compare-control-panel {" in css
        assert ".compare-control-global-actions {" in css
        assert ".compare-control-workspace {" in css
        assert ".compare-control-set-column {" in css
        assert ".compare-control-controls-split {" in css
        assert "#compare-control-analysis-section.compare-control-dual-enabled .compare-control-controls-split {" in css
        assert "#compare-control-analysis-section.compare-control-dual-enabled .compare-control-workspace {" in css
        assert "#compare-control-analysis-section.compare-control-dual-enabled .compare-control-set-panel {" in css
        assert "#compare-control-analysis-section.compare-control-dual-enabled .compare-control-results-stack {" in css
        assert "#compare-control-panel-secondary {" in css
        assert "transform: translateX(22px);" in css
        compare_control_results_block = re.search(
            r"\.compare-control-results \{([^}]*)\}",
            css,
            re.DOTALL,
        )
        assert compare_control_results_block is not None
        compare_results_css = compare_control_results_block.group(1)
        assert "overflow-wrap: anywhere;" in compare_results_css
        assert "word-break: break-word;" in compare_results_css
        assert ".compare-control-groups-table-wrap {" in css
        assert ".compare-control-groups-table {" in css
        assert ".compare-control-groups-table th {" in css
        assert "height: 2.5rem;" in css
        assert "line-height: 1.12;" in css
        assert "vertical-align: top;" in css
        assert ".compare-control-results-stack {" in css
        assert ".compare-control-results-card {" in css
        assert ".compare-control-results-card-primary {" in css
        assert ".compare-control-results-card-secondary {" in css
        assert ".compare-control-chart-grid {" in css
        assert ".compare-control-chart-grid.layout-side-by-side {" in css
        assert ".compare-control-chart-grid.layout-combined {" in css
        assert ".compare-control-chart-card {" in css
        assert ".compare-control-chart-card-secondary {" in css
        assert ".compare-control-chart-card-combined {" in css
        assert ".compare-control-controls {" in css
        assert ".compare-control-results {" in css
        assert "#previous-runs-clear-all-filters {" in css
        assert "margin-left: auto;" in css
        assert "#quick-filters-status {" in css
        assert ".previous-runs-presets-panel {" in css
        assert "#previous-runs-preset-select {" in css
        assert ".previous-runs-presets-actions {" in css
        assert ".previous-runs-presets-controls {" in css
        assert "grid-template-columns: auto minmax(180px, 280px);" in css
        assert ".table-scroll {" in css
        assert "min-height: calc(" in css
        assert "max-height: calc(" in css
        assert "overflow-y: auto;" in css
        assert "--previous-runs-filter-row-height: 2.18rem;" in css
        assert "--previous-runs-spacer-row-height: 2.18rem;" in css
        assert "#previous-runs-table {" in css
        assert "border-collapse: separate;" in css
        assert "border-spacing: 0;" in css
        assert "width: max-content;" in css
        assert "min-width: clamp(880px, 100%, 1600px);" in css
        assert "#previous-runs-table th," in css
        assert "white-space: nowrap;" in css
        assert "@media (max-width: 900px) {" in css
        assert "#previous-runs-table td.num {" in css
        assert "word-break: break-word;" in css
        th_block = re.search(r"#previous-runs-table th \{([^}]*)\}", css, re.DOTALL)
        assert th_block is not None
        assert "position: relative;" not in th_block.group(1)
        assert "#previous-runs-table th.previous-runs-draggable {" in css
        assert "#previous-runs-table th.previous-runs-drag-target {" in css
        assert ".previous-runs-resize-handle," in css
        assert ".dashboard-table-resize-handle {" in css
        assert ".dashboard-resizable-table th," in css
        assert "#previous-runs-table thead tr.previous-runs-header-row th:not(:last-child)," in css
        assert ".dashboard-resizable-table thead tr:first-child th:not(:last-child) {" in css
        assert "border-right: 1px solid #d6e0ea;" in css
        assert "#runtime-summary,\n#boundary-summary {" in css
        assert "overflow-x: hidden;" in css
        assert "#per-label-section {" in css
        assert "overflow-x: auto;" in css
        assert "cursor: col-resize;" in css

    def test_render_builds_all_method_standalone_pages(self, tmp_path):
        all_method_root = (
            tmp_path
            / "golden"
            / "eval-vs-pipeline"
            / "2026-02-23_16.01.06"
            / "all-method-benchmark"
            / "thefoodlabcutdown"
        )
        all_method_root_second = (
            tmp_path
            / "golden"
            / "eval-vs-pipeline"
            / "2026-02-23_16.01.06"
            / "all-method-benchmark"
            / "dinnerfor2cutdown"
        )
        data = DashboardData(
            benchmark_records=[
                BenchmarkRecord(
                    run_timestamp="2026-02-23T16:04:10",
                    artifact_dir=str(
                        all_method_root
                        / "config_001_aaa_extractor_beautifulsoup"
                    ),
                    precision=0.12,
                    recall=0.44,
                    f1=0.19,
                    practical_f1=0.54,
                    recipes=7,
                    gold_recipe_headers=10,
                    source_file="/tmp/thefoodlabCUTDOWN.epub",
                    importer_name="epub",
                    run_config_summary="epub_extractor=beautifulsoup | workers=7",
                    run_config_hash="hash001",
                ),
                BenchmarkRecord(
                    run_timestamp="2026-02-23T16:05:10",
                    artifact_dir=str(
                        all_method_root
                        / "config_002_bbb_extractor_markdown"
                    ),
                    precision=0.20,
                    recall=0.60,
                    f1=0.30,
                    practical_f1=0.62,
                    recipes=9,
                    gold_recipe_headers=10,
                    source_file="/tmp/thefoodlabCUTDOWN.epub",
                    importer_name="epub",
                    run_config_summary="epub_extractor=markdown | workers=7",
                    run_config_hash="hash002",
                ),
                BenchmarkRecord(
                    run_timestamp="2026-02-23T16:06:10",
                    artifact_dir=str(
                        all_method_root
                        / "config_003_ccc_extractor_auto__parser_v2__skiphf_true__pre_br_split_v1"
                    ),
                    precision=0.08,
                    recall=0.30,
                    f1=0.13,
                    practical_f1=0.40,
                    recipes=8,
                    gold_recipe_headers=10,
                    source_file="/tmp/thefoodlabCUTDOWN.epub",
                    importer_name="epub",
                    run_config_hash="hash003",
                ),
                BenchmarkRecord(
                    run_timestamp="2026-02-23T16:07:10",
                    artifact_dir=str(
                        all_method_root_second
                        / "config_001_aaa_extractor_beautifulsoup"
                    ),
                    precision=0.25,
                    recall=0.58,
                    f1=0.35,
                    practical_f1=0.68,
                    recipes=10,
                    gold_recipe_headers=12,
                    source_file="/tmp/DinnerFor2CUTDOWN.epub",
                    importer_name="epub",
                    run_config_summary="epub_extractor=beautifulsoup | workers=7",
                    run_config_hash="hash001",
                ),
                BenchmarkRecord(
                    run_timestamp="2026-02-23T16:08:10",
                    artifact_dir=str(
                        all_method_root_second
                        / "config_002_bbb_extractor_markdown"
                    ),
                    precision=0.31,
                    recall=0.66,
                    f1=0.42,
                    practical_f1=0.81,
                    recipes=12,
                    gold_recipe_headers=12,
                    source_file="/tmp/DinnerFor2CUTDOWN.epub",
                    importer_name="epub",
                    run_config_summary="epub_extractor=markdown | workers=7",
                    run_config_hash="hash002",
                ),
            ]
        )
        html_path = render_dashboard(tmp_path / "dash", data)
        html = html_path.read_text(encoding="utf-8")
        assert "All-Method Benchmark Runs" not in html
        assert "all-method-benchmark/index.html" not in html

        all_method_dir = tmp_path / "dash" / "all-method-benchmark"
        run_detail_path = (
            all_method_dir
            / "all-method-benchmark-run__2026-02-23_16.01.06.html"
        )
        assert run_detail_path.exists()
        detail_path = (
            all_method_dir
            / "all-method-benchmark__2026-02-23_16.01.06__thefoodlabcutdown.html"
        )
        assert detail_path.exists()
        detail_path_second = (
            all_method_dir
            / "all-method-benchmark__2026-02-23_16.01.06__dinnerfor2cutdown.html"
        )
        assert detail_path_second.exists()

        detail_html = detail_path.read_text(encoding="utf-8")
        assert 'class="all-method-quick-nav"' in detail_html
        assert 'href="#detail-summary"' in detail_html
        assert 'href="#detail-charts"' in detail_html
        assert 'href="#detail-ranked-table"' in detail_html
        assert 'id="detail-charts"' in detail_html
        assert 'id="detail-ranked-table"' in detail_html
        assert 'class="section-details"' in detail_html
        assert "Run Summary" in detail_html
        assert "Compact stats only (no per-config labels)" in detail_html
        assert "<th>Stat</th><th>N</th><th>Min</th><th>Median</th><th>Mean</th><th>Max</th>" in detail_html
        assert "Metric Bar Charts" in detail_html
        assert "One bar per run/configuration for each metric category." in detail_html
        assert "All axes use fixed 0-100%; recipes is percent identified vs golden recipe headers for this source." in detail_html
        assert "Run 01" in detail_html
        assert "metric-bar-fill" in detail_html
        assert "Metric Web Charts (Radar)" in detail_html
        assert "Each web is one run/configuration." in detail_html
        assert "All axes use fixed 0-100%; recipes is percent identified vs golden recipe headers for this source." in detail_html
        assert "metric-radar-svg" in detail_html
        assert "Run 01: config_002_bbb_extractor_markdown" in detail_html
        assert "<strong>Golden recipes:</strong> 10" in detail_html
        strict_precision_block = detail_html.split("<h3>Strict Precision</h3>", 1)[1].split(
            "</section>", 1
        )[0]
        assert 'style="width:20.00%"' in strict_precision_block
        assert 'style="width:100.00%"' not in strict_precision_block
        recipes_identified_block = detail_html.split("<h3>Recipes Identified %</h3>", 1)[1].split(
            "</section>", 1
        )[0]
        assert 'style="width:90.00%"' in recipes_identified_block
        assert 'style="width:70.00%"' in recipes_identified_block
        assert "Strict Precision" in detail_html
        assert "Practical F1" in detail_html
        assert ">Extractor</span></th>" in detail_html
        assert ">Parser</span></th>" in detail_html
        assert ">Skip HF</th>" in detail_html
        assert ">Preprocess</th>" in detail_html
        assert "<td>auto</td>" in detail_html
        assert "<td>v2</td>" in detail_html
        assert "<td>true</td>" in detail_html
        assert "<td>br_split_v1</td>" in detail_html
        assert "<td>markdown</td>" in detail_html
        assert "<td>-</td>" in detail_html
        assert "Ranked Configurations" in detail_html
        assert detail_html.find("config_002_bbb_extractor_markdown") < detail_html.find(
            "config_001_aaa_extractor_beautifulsoup"
        )
        assert "strict_f1=0.3000" in detail_html
        assert 'href="../index.html#previous-runs-section"' in detail_html

        run_detail_html = run_detail_path.read_text(encoding="utf-8")
        assert 'href="../index.html#previous-runs-section"' in run_detail_html
        assert 'class="all-method-quick-nav"' in run_detail_html
        assert 'href="#run-summary"' in run_detail_html
        assert 'href="#run-charts"' in run_detail_html
        assert 'href="#run-config-table"' in run_detail_html
        assert 'href="#run-drilldown"' in run_detail_html
        assert 'id="run-charts"' in run_detail_html
        assert 'id="run-config-table"' in run_detail_html
        assert 'id="run-drilldown"' in run_detail_html
        assert "Run Summary" in run_detail_html
        assert "Compact stats across aggregated config rows" in run_detail_html
        assert "Metric Bar Charts" in run_detail_html
        assert "One bar per aggregated configuration for each metric category." in run_detail_html
        assert "All axes use fixed 0-100%; recipes is percent identified vs golden recipe headers for each book." in run_detail_html
        assert "Config 01" in run_detail_html
        assert "metric-bar-fill" in run_detail_html
        assert "Metric Web Charts (Radar)" in run_detail_html
        assert "Each web is one aggregated configuration." in run_detail_html
        assert "All axes use fixed 0-100%; recipes is percent identified vs golden recipe headers for each book." in run_detail_html
        assert "metric-radar-svg" in run_detail_html
        assert "Config 01: config_002_bbb_extractor_markdown" in run_detail_html
        assert "Per-Cookbook Average Metric Bar Charts" in run_detail_html
        assert "One bar per cookbook. Values are averaged across all configs that ran for that cookbook." in run_detail_html
        assert "Labels use Book 01/Book 02 order from Per-Book Drilldown." in run_detail_html
        assert "Highest avg strict precision:" in run_detail_html
        assert "Highest avg strict recall:" in run_detail_html
        assert "Book 01" in run_detail_html
        assert "Per-Cookbook Average Web Charts (Radar)" in run_detail_html
        assert "Each web is one cookbook with metrics averaged across all configs that ran for that cookbook." in run_detail_html
        assert "Book 01: DinnerFor2CUTDOWN.epub (configs=2)" in run_detail_html
        avg_book_precision_block = run_detail_html.split("<h3>Avg Strict Precision</h3>", 1)[1].split(
            "</section>", 1
        )[0]
        assert 'style="width:13.33%"' in avg_book_precision_block
        assert 'style="width:28.00%"' in avg_book_precision_block
        avg_book_recipes_identified_block = run_detail_html.split("<h3>Avg Recipes Identified %</h3>", 1)[1].split(
            "</section>", 1
        )[0]
        assert 'style="width:80.00%"' in avg_book_recipes_identified_block
        assert 'style="width:91.67%"' in avg_book_recipes_identified_block
        mean_precision_block = run_detail_html.split("<h3>Mean Strict Precision</h3>", 1)[1].split(
            "</section>", 1
        )[0]
        assert 'style="width:25.50%"' in mean_precision_block
        assert 'style="width:100.00%"' not in mean_precision_block
        mean_recipes_identified_block = run_detail_html.split("<h3>Recipes Identified %</h3>", 1)[1].split(
            "</section>", 1
        )[0]
        assert 'style="width:95.00%"' in mean_recipes_identified_block
        assert "Mean Strict Precision" in run_detail_html
        assert "Mean Practical F1" in run_detail_html
        assert "Config Performance Across Books" in run_detail_html
        assert "Per-Book Drilldown" in run_detail_html
        assert "Open book details" in run_detail_html
        assert "all-method-benchmark__2026-02-23_16.01.06__thefoodlabcutdown.html" in run_detail_html
        assert "all-method-benchmark__2026-02-23_16.01.06__dinnerfor2cutdown.html" in run_detail_html
        assert run_detail_html.find("config_002_bbb_extractor_markdown") < run_detail_html.find(
            "config_001_aaa_extractor_beautifulsoup"
        )

    def test_all_method_renders_report_variants_without_eval_reports(self, tmp_path):
        golden_root = tmp_path / "golden"
        all_method_root = (
            golden_root
            / "eval-vs-pipeline"
            / "2026-02-23_16.01.06"
            / "all-method-benchmark"
            / "thefoodlabcutdown"
        )
        all_method_root.mkdir(parents=True, exist_ok=True)

        for idx in range(1, 4):
            config_dir = all_method_root / f"config_{idx:03d}_cfg{idx}_extractor_beautifulsoup"
            config_dir.mkdir(parents=True, exist_ok=True)
            (config_dir / "manifest.json").write_text(
                json.dumps(
                    {
                        "importer_name": "epub",
                        "source_file": "/tmp/thefoodlabCUTDOWN.epub",
                        "recipe_count": 10 + idx,
                        "run_config": {"epub_extractor": "beautifulsoup"},
                    }
                ),
                encoding="utf-8",
            )

        (all_method_root / "all_method_benchmark_report.json").write_text(
            json.dumps(
                {
                    "created_at": "2026-02-23T16:10:00",
                    "source_file": "/tmp/thefoodlabCUTDOWN.epub",
                    "variants": [
                        {
                            "config_dir": "config_001_cfg1_extractor_beautifulsoup",
                            "evaluation_representative_config_dir": "config_001_cfg1_extractor_beautifulsoup",
                            "evaluation_result_source": "executed",
                            "eval_report_json": "config_001_cfg1_extractor_beautifulsoup/eval_report.json",
                            "precision": 0.10,
                            "recall": 0.20,
                            "f1": 0.1333,
                            "practical_precision": 0.40,
                            "practical_recall": 0.50,
                            "practical_f1": 0.4444,
                            "run_config_hash": "hash001",
                            "run_config_summary": "epub_extractor=beautifulsoup",
                        },
                        {
                            "config_dir": "config_002_cfg2_extractor_beautifulsoup",
                            "evaluation_representative_config_dir": "config_001_cfg1_extractor_beautifulsoup",
                            "evaluation_result_source": "reused_in_run",
                            "eval_report_json": "config_001_cfg1_extractor_beautifulsoup/eval_report.json",
                            "precision": 0.10,
                            "recall": 0.20,
                            "f1": 0.1333,
                            "practical_precision": 0.40,
                            "practical_recall": 0.50,
                            "practical_f1": 0.4444,
                            "run_config_hash": "hash002",
                            "run_config_summary": "epub_extractor=beautifulsoup",
                        },
                        {
                            "config_dir": "config_003_cfg3_extractor_beautifulsoup",
                            "evaluation_representative_config_dir": "config_001_cfg1_extractor_beautifulsoup",
                            "evaluation_result_source": "reused_in_run",
                            "eval_report_json": "config_001_cfg1_extractor_beautifulsoup/eval_report.json",
                            "precision": 0.10,
                            "recall": 0.20,
                            "f1": 0.1333,
                            "practical_precision": 0.40,
                            "practical_recall": 0.50,
                            "practical_f1": 0.4444,
                            "run_config_hash": "hash003",
                            "run_config_summary": "epub_extractor=beautifulsoup",
                        },
                    ],
                }
            ),
            encoding="utf-8",
        )

        data = DashboardData(
            golden_root=str(golden_root),
            benchmark_records=[
                BenchmarkRecord(
                    run_timestamp="2026-02-23T16:04:10",
                    artifact_dir=str(all_method_root / "config_001_cfg1_extractor_beautifulsoup"),
                    precision=0.10,
                    recall=0.20,
                    f1=0.1333,
                    practical_f1=0.4444,
                    recipes=11,
                    gold_recipe_headers=20,
                    source_file="/tmp/thefoodlabCUTDOWN.epub",
                    importer_name="epub",
                    run_config_hash="hash001",
                )
            ],
        )
        render_dashboard(tmp_path / "dash", data)

        all_method_index = tmp_path / "dash" / "all-method-benchmark" / "index.html"
        assert not all_method_index.exists()

        run_detail_html = (
            tmp_path
            / "dash"
            / "all-method-benchmark"
            / "all-method-benchmark-run__2026-02-23_16.01.06.html"
        ).read_text(encoding="utf-8")
        assert "<strong>Run folder:</strong> 2026-02-23_16.01.06" in run_detail_html
        assert "<strong>Configs aggregated:</strong> 3" in run_detail_html

        detail_path = (
            tmp_path
            / "dash"
            / "all-method-benchmark"
            / "all-method-benchmark__2026-02-23_16.01.06__thefoodlabcutdown.html"
        )
        detail_html = detail_path.read_text(encoding="utf-8")
        assert "config_001_cfg1_extractor_beautifulsoup" in detail_html
        assert "config_002_cfg2_extractor_beautifulsoup" in detail_html
        assert "config_003_cfg3_extractor_beautifulsoup" in detail_html

    def test_render_includes_single_profile_sweep_runs(self, tmp_path):
        golden_root = tmp_path / "golden"
        single_profile_root = (
            golden_root
            / "benchmark-vs-golden"
            / "2026-02-28_03.35.11"
            / "single-profile-benchmark"
        )
        hash_value = "abcdef1234567890abcdef1234567890abcdef1234567890abcdef1234567890"
        data = DashboardData(
            golden_root=str(golden_root),
            benchmark_records=[
                BenchmarkRecord(
                    run_timestamp="2026-02-28_03.35.11",
                    artifact_dir=str(single_profile_root / "01_book_a"),
                    precision=0.35,
                    recall=0.45,
                    f1=0.3938,
                    practical_f1=0.55,
                    recipes=10,
                    gold_recipe_headers=12,
                    source_file="/tmp/book_a.epub",
                    importer_name="epub",
                    run_config_summary="epub_extractor=beautifulsoup",
                    run_config_hash=hash_value,
                ),
                BenchmarkRecord(
                    run_timestamp="2026-02-28_03.35.11",
                    artifact_dir=str(single_profile_root / "02_book_b"),
                    precision=0.40,
                    recall=0.50,
                    f1=0.4444,
                    practical_f1=0.60,
                    recipes=11,
                    gold_recipe_headers=13,
                    source_file="/tmp/book_b.epub",
                    importer_name="epub",
                    run_config_summary="epub_extractor=beautifulsoup",
                    run_config_hash=hash_value,
                ),
            ],
        )
        render_dashboard(tmp_path / "dash", data)

        all_method_dir = tmp_path / "dash" / "all-method-benchmark"
        assert not (all_method_dir / "index.html").exists()

        run_detail_html = (
            all_method_dir
            / "all-method-benchmark-run__2026-02-28_03.35.11.html"
        ).read_text(encoding="utf-8")
        assert "<strong>Book jobs:</strong> 2" in run_detail_html
        assert "<strong>Configs aggregated:</strong> 1" in run_detail_html
        assert "profile_abcdef123456" in run_detail_html
        assert "all-method-benchmark__2026-02-28_03.35.11__01_book_a.html" in run_detail_html
        assert "all-method-benchmark__2026-02-28_03.35.11__02_book_b.html" in run_detail_html

    def test_render_all_method_section_when_no_groups(self, tmp_path):
        golden_root = tmp_path / "golden-empty"
        golden_root.mkdir(parents=True, exist_ok=True)
        data = DashboardData(
            golden_root=str(golden_root),
            benchmark_records=[
                BenchmarkRecord(
                    run_timestamp="2026-02-23T16:05:10",
                    artifact_dir="/tmp/eval/2026-02-23_16.05.10",
                    precision=0.20,
                    recall=0.60,
                    f1=0.30,
                )
            ]
        )
        html_path = render_dashboard(tmp_path / "dash", data)
        html = html_path.read_text(encoding="utf-8")
        assert "all-method-benchmark/index.html" not in html
        assert "No all-method benchmark runs found in benchmark history." not in html
        assert not (tmp_path / "dash" / "all-method-benchmark" / "index.html").exists()
        assert not (tmp_path / "dash" / "all-method-benchmark.html").exists()

    def test_idempotent(self, tmp_path):
        data = DashboardData()
        render_dashboard(tmp_path / "dash", data)
        render_dashboard(tmp_path / "dash", data)  # should not error
        assert (tmp_path / "dash" / "index.html").exists()
