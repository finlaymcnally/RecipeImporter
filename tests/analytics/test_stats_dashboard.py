from __future__ import annotations

import tests.analytics.stats_dashboard_support as _support

# Reuse shared imports/helpers from the local support module.
globals().update({
    name: value
    for name, value in _support.__dict__.items()
    if not name.startswith("test_")
    and not (name.startswith("__") and name.endswith("__"))
})


class TestRenderer:
    def test_render_produces_files(self, tmp_path):
        data = DashboardData(
            stage_records=[
                StageRecord(file_name="a.xlsx", recipes=10, total_seconds=2.0),
            ],
            summary=DashboardSummary(total_stage_records=1, total_recipes=10),
        )
        html_path = render_dashboard(tmp_path / "dash", data)
        assert html_path.exists()
        assert (tmp_path / "dash" / "assets" / "dashboard_data.json").exists()
        assert (tmp_path / "dash" / "assets" / "dashboard_ui_state.json").exists()
        assert (tmp_path / "dash" / "assets" / "dashboard.js").exists()
        assert (tmp_path / "dash" / "assets" / "style.css").exists()

    def test_render_preserves_existing_program_ui_state(self, tmp_path):
        out_dir = tmp_path / "dash"
        state_path = out_dir / "assets" / "dashboard_ui_state.json"
        state_path.parent.mkdir(parents=True, exist_ok=True)
        original_payload = {
            "version": 1,
            "saved_at": "2026-03-03T18:22:00Z",
            "previous_runs": {"visible_columns": ["run_timestamp", "ai_model"]},
        }
        state_path.write_text(json.dumps(original_payload), encoding="utf-8")

        render_dashboard(out_dir, DashboardData())

        persisted_payload = json.loads(state_path.read_text(encoding="utf-8"))
        assert persisted_payload == original_payload

    def test_data_json_validates(self, tmp_path):
        data = DashboardData(
            stage_records=[
                StageRecord(file_name="b.epub", recipes=5),
            ],
            benchmark_records=[
                BenchmarkRecord(
                    precision=0.1,
                    recall=0.3,
                    importer_name="epub",
                    run_config={"epub_extractor": "beautifulsoup", "ocr_device": "auto"},
                ),
            ],
        )
        render_dashboard(tmp_path / "dash", data)
        raw = json.loads(
            (tmp_path / "dash" / "assets" / "dashboard_data.json").read_text()
        )
        # Verify it round-trips through the schema
        loaded = DashboardData.model_validate(raw)
        assert len(loaded.stage_records) == 1
        assert len(loaded.benchmark_records) == 1

    def test_html_includes_previous_runs_columns(self, tmp_path):
        data = DashboardData(
            benchmark_records=[
                BenchmarkRecord(
                    run_timestamp="2026-02-11_16.00.00",
                    artifact_dir="/tmp/eval",
                    strict_accuracy=0.2,
                    macro_f1_excluding_other=0.55,
                    precision=0.1,
                    recall=0.2,
                    practical_f1=0.55,
                    importer_name="epub",
                    source_file="/tmp/source/book.epub",
                    run_config={"epub_extractor": "beautifulsoup", "ocr_device": "auto"},
                ),
            ],
        )
        html_path = render_dashboard(tmp_path / "dash", data)
        html = html_path.read_text(encoding="utf-8")
        assert "Previous Runs" in html
        assert 'id="previous-runs-table"' in html
        assert 'class="previous-runs-header-row"' in html
        assert 'class="previous-runs-active-filters-row"' in html
        assert 'class="previous-runs-filter-spacer-row"' in html
        assert "<th>Timestamp</th>" not in html
        assert "<th>Strict Precision</th>" not in html
        assert "<th>Strict Recall</th>" not in html
        assert "<th>Practical F1</th>" not in html
        assert "<th>Strict F1</th>" not in html
        assert "strict_accuracy" in html
        assert "macro_f1_excluding_other" in html
        assert ">AI Model + Effort<" not in html
        assert "Run Config" not in html
        assert "<th>Artifact</th>" not in html

    def test_html_includes_previous_runs_filter_controls(self, tmp_path):
        html_path = render_dashboard(tmp_path / "dash", DashboardData())
        html = html_path.read_text(encoding="utf-8")
        assert 'id="previous-runs-filter-panel"' not in html
        assert 'id="previous-runs-filter-status"' not in html
        assert 'id="previous-runs-clear-filters"' in html
        assert 'id="previous-runs-columns-toggle"' in html
        assert 'id="previous-runs-columns-popup"' in html
        assert 'id="previous-runs-columns-checklist"' in html
        assert 'id="previous-runs-global-filter-mode"' in html
        assert 'id="previous-runs-column-reset"' in html
        assert 'id="previous-runs-preset-select"' in html
        assert 'id="previous-runs-preset-load"' in html
        assert 'id="previous-runs-preset-save-current"' in html
        assert 'id="previous-runs-preset-delete"' in html
        assert 'id="previous-runs-preset-status"' in html
        assert 'id="isolate-panel"' not in html
        assert 'id="isolate-combine"' not in html
        assert 'id="isolate-add"' not in html
        assert 'id="isolate-clear"' not in html
        assert 'id="isolate-rules"' not in html
        assert 'id="isolate-status"' not in html
        assert 'id="isolate-insights"' not in html
        assert 'id="compare-control-panel"' in html
        assert 'id="compare-control-panel-secondary"' in html
        assert 'id="compare-control-view-mode"' in html
        assert 'id="compare-control-view-mode-secondary"' in html
        assert 'id="compare-control-outcome-field"' in html
        assert 'id="compare-control-outcome-field-secondary"' in html
        assert 'id="compare-control-compare-field"' in html
        assert 'id="compare-control-compare-field-secondary"' in html
        assert 'id="compare-control-split-field"' in html
        assert 'id="compare-control-split-field-secondary"' in html
        assert 'id="compare-control-hold-fields"' in html
        assert 'id="compare-control-hold-fields-secondary"' in html
        assert 'id="compare-control-group-selection"' in html
        assert 'id="compare-control-group-selection-secondary"' in html
        assert 'id="compare-control-filter-subset"' in html
        assert 'id="compare-control-filter-subset-secondary"' in html
        assert 'id="compare-control-clear-selection"' in html
        assert 'id="compare-control-clear-selection-secondary"' in html
        assert 'id="compare-control-reset"' in html
        assert 'id="compare-control-reset-secondary"' in html
        assert 'id="compare-control-toggle-second-set"' in html
        assert 'id="compare-control-chart-layout"' in html
        assert 'id="compare-control-combined-axis-mode"' in html
        assert 'id="compare-control-workspace"' in html
        assert 'id="compare-control-column-secondary"' in html
        assert 'id="compare-control-status"' in html
        assert 'id="compare-control-status-secondary"' in html
        assert 'id="compare-control-results"' in html
        assert 'id="compare-control-results-secondary"' in html
        assert 'id="compare-control-analysis-section"' in html
        assert 'id="compare-control-trend-chart"' in html
        assert 'id="compare-control-trend-chart-secondary"' in html
        assert 'id="compare-control-trend-chart-combined"' in html
        assert 'id="compare-control-trend-fallback"' in html
        assert 'id="compare-control-trend-fallback-secondary"' in html
        assert 'id="compare-control-trend-fallback-combined"' in html
        assert 'id="previous-runs-history-panel"' in html
        assert 'id="benchmark-trend-field-checklist"' in html
        assert 'id="benchmark-trend-select-all"' in html
        assert 'id="benchmark-trend-clear"' in html
        assert 'id="benchmark-trend-fields-status"' in html
        assert 'id="quick-filters-panel"' in html
        assert 'id="quick-filters-advanced"' not in html
        assert 'id="previous-runs-presets-toggle"' not in html
        assert 'id="previous-runs-presets-popup"' not in html
        assert 'id="quick-filter-exclude-ai-tests"' in html
        assert 'id="quick-filter-official-only"' in html
        assert 'id="previous-runs-clear-all-filters"' in html
        assert 'id="quick-filter-exclude-ai-tests" type="checkbox" checked' not in html
        assert 'id="quick-filter-official-only" type="checkbox" checked' in html
        assert 'id="quick-filters-status"' in html

    def test_dashboard_js_orders_columns_popup_by_visible_order(self, tmp_path):
        dash_dir = tmp_path / "dash"
        render_dashboard(dash_dir, DashboardData())
        js = (dash_dir / "assets" / "dashboard.js").read_text(encoding="utf-8")
        assert "const checklistOrder = [...previousRunsVisibleColumns].filter(" in js
        assert "if (!visibleSet.has(fieldName)) {" in js

    def test_dashboard_js_tracks_previous_runs_column_filter_global_mode(self, tmp_path):
        dash_dir = tmp_path / "dash"
        render_dashboard(dash_dir, DashboardData())
        js = (dash_dir / "assets" / "dashboard.js").read_text(encoding="utf-8")
        assert 'let previousRunsColumnFilterGlobalMode = "and";' in js
        assert "Control: isolate synced to table filters." not in js
        assert "Control: table filters (isolate rules saved)." not in js
        assert "Column combine: " in js
        assert "OR across columns." in js

    def test_dashboard_js_supports_cross_column_or_filter_mode(self, tmp_path):
        dash_dir = tmp_path / "dash"
        render_dashboard(dash_dir, DashboardData())
        js = (dash_dir / "assets" / "dashboard.js").read_text(encoding="utf-8")
        assert "function normalizePreviousRunsColumnFilterGlobalMode(value)" in js
        assert "if (topMode === \"or\") {" in js
        assert "return groups.some(matchesGroup);" in js

    def test_dashboard_js_supports_compare_control_analysis(self, tmp_path):
        dash_dir = tmp_path / "dash"
        render_dashboard(dash_dir, DashboardData())
        js = (dash_dir / "assets" / "dashboard.js").read_text(encoding="utf-8")
        assert "const COMPARE_CONTROL_VIEW_MODES = new Set(" in js
        assert "const COMPARE_CONTROL_CHART_TYPES = new Set([\"scatter\", \"bar\"]);" in js
        assert "const COMPARE_CONTROL_CHART_LAYOUTS = new Set([\"stacked\", \"side_by_side\", \"combined\"]);" in js
        assert "const COMPARE_CONTROL_COMBINED_AXIS_MODES = new Set([\"single\", \"dual\"]);" in js
        assert "function normalizeCompareControlChartType(value)" in js
        assert "function normalizeCompareControlChartLayout(value)" in js
        assert "function normalizeCompareControlCombinedAxisMode(value)" in js
        assert "let compareControlChartActivated = false;" in js
        assert "let compareControlSecondaryChartActivated = false;" in js
        assert "let compareControlSecondSetEnabled = false;" in js
        assert "let compareControlChartLayout = \"stacked\";" in js
        assert "let compareControlCombinedAxisMode = \"single\";" in js
        assert "function activateCompareControlChart()" in js
        assert "function deactivateCompareControlChart()" in js
        assert "function shouldAutoActivateCompareControlChart(state, compareInfo)" in js
        assert "function normalizeCompareControlState(rawState)" in js
        assert "function buildCompareControlFieldCatalog(records)" in js
        assert "function chooseDefaultCompareOutcome(catalog)" in js
        assert "function analyzeCompareControlCategoricalRaw(records, outcomeField, compareField)" in js
        assert "function analyzeCompareControlNumericRaw(records, outcomeField, compareField)" in js
        assert "function analyzeCompareControlCategoricalControlled(records, outcomeField, compareField, holdFields)" in js
        assert "function analyzeCompareControlNumericControlled(records, outcomeField, compareField, holdFields)" in js
        assert "function compareControlSecondaryMetricFields(records, outcomeField, compareField)" in js
        assert "function compareControlWeakCoverageWarnings(analysis)" in js
        assert "function compareControlDefaultState()" in js
        assert "function compareControlStateForSet(setKey)" in js
        assert "function setCompareControlStateForSet(setKey, nextState)" in js
        assert "function setCompareControlSecondSetEnabled(enabled)" in js
        assert 'compareControlChartLayout = "side_by_side";' in js
        assert "function syncCompareControlLayoutChrome()" in js
        assert "function renderCompareControlPanel(context, config)" in js
        assert "function resetCompareControlState(setKey)" in js
        assert "function buildCompareControlScatterChartDefinition(context)" in js
        assert "function buildCompareControlBarChartDefinition(context)" in js
        assert "function compareControlAutoChartType(sourceState, context)" in js
        assert "function buildCompareControlChartDefinition(context)" in js
        assert "function buildCombinedCompareControlChartDefinition(primaryDefinition, secondaryDefinition)" in js
        assert "function renderCompareControlChartHost(config)" in js
        assert "function renderCompareControlDynamicChart(records, totalRows)" in js
        assert "function renderCompareControlDynamicChartForSet(records, totalRows, config)" in js
        assert "shouldAutoActivateCompareControlChart(state, compareInfo)" in js
        assert "function renderCompareControlSection()" in js
        assert "const filterResult = currentPreviousRunsFilterResult();" in js
        assert "if (!compareControlChartActivatedForSet(key)) {" in js
        assert "Use Compare & Control selections above to generate this chart." in js
        assert "window.Highcharts.chart(hostId, chartOptions);" in js
        assert "function compareControlRecordsForState(records, state, catalog)" in js
        assert "function setupCompareControlControlsForSet(config)" in js
        assert "function applyCompareControlSelectionSubset()" in js
        assert "function applyCompareControlSelectionSubsetForSet(setKey)" in js
        assert "Coverage warning:" in js
        assert "compare-control-groups-table" in js
        assert "compare-control-groups-table-wrap" in js
        assert "function compareControlTableNumber(value, smallDigits)" in js
        assert "function compareControlGroupDisplaySort(left, right, compareField)" in js
        assert 'if (compareFieldKey === "ai_effort") {' in js
        assert "const sortedGroupOptions = [...groupOptions].sort((left, right) => (" in js
        assert "const displayGroups = [...(analysis.groups || [])].sort((left, right) => (" in js
        assert "if (Math.abs(numeric) > 5) {" in js
        assert 'Math.round(numeric).toLocaleString("en-US")' in js
        assert 'custom.outcomeField === "all_token_use"' in js
        assert 'Math.round(outcomeNumber).toLocaleString("en-US")' in js
        assert 'htmlParts.push("<th>Group</th>");' in js
        assert 'return meta.label + " (" + fieldName + ")";' not in js
        assert '" [numeric]"' not in js
        assert 'class="isolate-rule-value isolate-rule-value-input"' not in js
        assert "function syncIsolateControls(records)" not in js

    def test_dashboard_js_supports_delayed_metric_hover_tooltips(self, tmp_path):
        dash_dir = tmp_path / "dash"
        render_dashboard(dash_dir, DashboardData())
        js = (dash_dir / "assets" / "dashboard.js").read_text(encoding="utf-8")
        html = (dash_dir / "index.html").read_text(encoding="utf-8")
        css = (dash_dir / "assets" / "style.css").read_text(encoding="utf-8")

        assert "const METRIC_TOOLTIP_HOVER_DELAY_MS = 1000;" in js
        assert "let metricTooltipDescriptions = Object.create(null);" in js
        assert "function buildMetricTooltipDescriptions()" in js
        assert "#previous-runs-section .metric-help-list li" in js
        assert "function metricTooltipTextForTarget(target)" in js
        assert "function setupMetricHoverTooltips()" in js
        assert "function refreshMetricTooltipTargets()" in js
        assert "const METRIC_TOOLTIP_AUTO_TARGET_SELECTOR = [" in js
        assert '".highcharts-legend-item tspan"' in js
        assert "function buildMetricTooltipAliasCatalog(descriptions)" in js
        assert "function metricTooltipResolveKeyFromText(text)" in js
        assert "document.querySelectorAll(METRIC_TOOLTIP_AUTO_TARGET_SELECTOR).forEach(node => {" in js
        assert "setMetricTooltipTarget(th, fieldName, meta.title || fieldName);" in js
        assert "setMetricTooltipTarget(labelText, fieldName, meta.title || meta.label || fieldName);" in js
        assert "data-metric-tooltip-key" in js
        assert "setupMetricHoverTooltips();" in js
        assert "refreshMetricTooltipTargets();" in js
        assert ".metric-hover-tooltip {" in css
        assert "[data-metric-tooltip-key] {" in css
        assert "[data-metric-tooltip-key]:hover," in css
        assert "th[data-metric-tooltip-key]:hover," in css
        assert "svg [data-metric-tooltip-key]:hover * {" in css
        assert 'data-metric-tooltip-key="gold_total"' in html
        assert 'data-metric-tooltip-key="boundary_correct"' in js
        assert 'data-metric-tooltip-key="gold_unmatched"' in js
        assert 'data-metric-tooltip-key="quality_per_million_tokens"' in js

    def test_compare_control_chart_styles_axis_titles_and_hides_placeholder_legend(
        self, tmp_path
    ):
        dash_dir = tmp_path / "dash"
        render_dashboard(dash_dir, DashboardData())
        js = (dash_dir / "assets" / "dashboard.js").read_text(encoding="utf-8")

        assert 'fontSize: "1rem"' in js
        assert 'next.title.margin = 18;' in js
        assert 'legend: { enabled: compareControlChartLegendEnabled(series) },' in js
        assert 'align: "left"' in js
        assert 'onlyName !== "All visible rows"' in js

    def test_dashboard_js_clamps_persisted_table_column_widths(self, tmp_path):
        dash_dir = tmp_path / "dash"
        render_dashboard(dash_dir, DashboardData())
        js = (dash_dir / "assets" / "dashboard.js").read_text(encoding="utf-8")
        assert "const DASHBOARD_TABLE_COLUMN_MIN_WIDTH = 72;" in js
        assert "const DASHBOARD_TABLE_COLUMN_MAX_WIDTH = 1200;" in js
        assert "function normalizeDashboardColumnWidth(value)" in js
        assert "Math.min(DASHBOARD_TABLE_COLUMN_MAX_WIDTH, width)" in js
        assert "Math.min(maxWidth, startWidth + (moveEvent.clientX - startX))" in js

    def test_compare_control_controlled_categorical_standardizes_strata(self, tmp_path):
        dash_dir = tmp_path / "dash"
        render_dashboard(dash_dir, DashboardData())
        js_path = dash_dir / "assets" / "dashboard.js"
        result = _run_compare_control_behavior_harness(js_path)
        assert result["raw_A"] == pytest.approx(0.83, abs=1e-9)
        assert result["raw_B"] == pytest.approx(0.37, abs=1e-9)
        assert result["controlled_A"] == pytest.approx(0.55, abs=1e-9)
        assert result["controlled_B"] == pytest.approx(0.65, abs=1e-9)
        assert result["raw_A"] > result["raw_B"]
        assert result["controlled_B"] > result["controlled_A"]

    def test_compare_control_uses_filtered_previous_runs_subset(self, tmp_path):
        dash_dir = tmp_path / "dash"
        render_dashboard(dash_dir, DashboardData())
        js_path = dash_dir / "assets" / "dashboard.js"
        result = _run_compare_control_chart_harness(js_path)
        assert result["filtered_source_record_count"] == 3
        assert result["filtered_source_labels"] == [
            "/tmp/book_a.epub",
            "/tmp/book_a.epub",
            "/tmp/book_a.epub",
        ]

    def test_compare_control_subset_stays_local_and_does_not_write_table_filters(
        self, tmp_path
    ):
        dash_dir = tmp_path / "dash"
        render_dashboard(dash_dir, DashboardData())
        js_path = dash_dir / "assets" / "dashboard.js"
        result = _run_compare_control_behavior_harness(js_path)
        assert result["subset_applied"] is True
        assert "Compare & Control only" in result["subset_message"]
        assert result["subset_mode"] == "and"
        assert result["subset_clause_count"] == 0
        assert result["subset_clause_values"] == []
        assert result["subset_clause_operators"] == []
        assert result["local_subset_rows"] == 10
        assert result["local_subset_groups"] == ["A"]

    def test_previous_runs_filter_clause_edit_updates_existing_clause(self, tmp_path):
        dash_dir = tmp_path / "dash"
        render_dashboard(dash_dir, DashboardData())
        js_path = dash_dir / "assets" / "dashboard.js"
        result = _run_previous_runs_filter_edit_harness(js_path)
        assert result["edit_draft_editing"] is True
        assert result["edit_draft_index"] == 0
        assert result["edit_draft_operator"] == "contains"
        assert result["edit_draft_value"] == "gpt-5.1-codex-mini"
        assert result["update_applied"] is True
        assert result["clauses_after_count"] == 2
        assert result["clause_0_operator"] == "starts_with"
        assert result["clause_0_value"] == "gpt-5.1"
        assert result["clause_1_operator"] == "contains"
        assert result["clause_1_value"] == "medium"
        assert result["invalid_draft_editing"] is False
        assert result["invalid_draft_index"] is None

    def test_compare_control_reset_state_restore_defaults(self, tmp_path):
        dash_dir = tmp_path / "dash"
        render_dashboard(dash_dir, DashboardData())
        js_path = dash_dir / "assets" / "dashboard.js"
        result = _run_compare_control_behavior_harness(js_path)
        reset_state = result.get("reset_state") or {}
        assert reset_state.get("compare_field") == ""
        assert reset_state.get("split_field") == ""
        assert reset_state.get("hold_constant_fields") == []
        assert reset_state.get("selected_groups") == []
        assert reset_state.get("view_mode") == "discover"
        assert reset_state.get("outcome_field") == "strict_accuracy"
        assert reset_state.get("x_axis_mode") == "date"

    def test_compare_control_secondary_fields_skip_constant_zero_metrics(
        self, tmp_path
    ):
        dash_dir = tmp_path / "dash"
        render_dashboard(dash_dir, DashboardData())
        js_path = dash_dir / "assets" / "dashboard.js"
        result = _run_compare_control_behavior_harness(js_path)
        secondary_fields = set(result.get("secondary_fields") or [])
        assert "benchmark_total_seconds" not in secondary_fields
        assert "benchmark_prediction_seconds" not in secondary_fields
        assert "benchmark_evaluation_seconds" not in secondary_fields
        assert "all_token_use" in secondary_fields
        assert "tokens_total" in secondary_fields

    def test_compare_control_dynamic_chart_builds_scatter_from_visible_rows(
        self, tmp_path
    ):
        dash_dir = tmp_path / "dash"
        render_dashboard(dash_dir, DashboardData())
        js_path = dash_dir / "assets" / "dashboard.js"
        result = _run_compare_control_chart_harness(js_path)
        assert result["numeric_chart_type"] == "scatter"
        assert result["numeric_series_count"] == 2
        assert result["numeric_point_total"] == 6
        assert result["numeric_title"] == "Strict Accuracy vs All Token Use"
        assert result["numeric_subtitle"] == "Raw comparison, split by Source"
        assert result["numeric_first_compare_value"] == pytest.approx(990)
        assert result["numeric_first_outcome_value"] == pytest.approx(0.60)
        assert result["numeric_first_split_label"] == "book_a.epub"
        assert result["time_chart_type"] == "scatter"
        assert result["time_series_count"] == 2
        assert result["time_point_total"] == 6
        assert result["time_title"] == "All Token Use over Timestamp"
        assert result["time_x_axis_type"] == "datetime"
        assert result["time_first_series_type"] == "scatter"
        assert result["time_first_compare_value"] == "2026-03-04T10:00:00"
        assert result["time_first_x_is_number"] is True
        assert result["time_first_outcome_value"] == pytest.approx(990)
        assert result["per_run_chart_type"] == "scatter"
        assert result["per_run_series_count"] == 2
        assert result["per_run_point_total"] == 6
        assert result["per_run_title"] == "All Token Use over Runs"
        assert result["per_run_x_axis_type"] == ""
        assert result["per_run_x_axis_allow_decimals"] is True
        assert result["per_run_first_compare_value"] == "#1"
        assert result["per_run_first_run_order"] == 1
        assert result["per_run_first_x_value"] == pytest.approx(1)
        assert result["per_run_first_outcome_value"] == pytest.approx(990)
        assert result["categorical_chart_type"] == "bar"
        assert result["categorical_series_count"] == 2
        assert result["categorical_title"] == "Average Strict Accuracy by Importer"
        assert result["categorical_subtitle"] == "Raw comparison, split by Source"
        assert result["categorical_categories_count"] == 2
        assert result["categorical_point_total"] == 4
        assert result["categorical_first_series_unique_colors"] >= 2
        assert result["categorical_first_series_first_color"].startswith("rgba(")
        assert result["categorical_epub_color_all"] == result["categorical_epub_color_subset"]
        assert result["categorical_epub_color_all"] == result["categorical_epub_color_reordered"]
        assert result["categorical_pdf_color_all"] == result["categorical_pdf_color_reordered"]
        assert result["categorical_first_compare_value"] in {"epub", "pdf"}
        assert result["discover_series_count"] == 0
        assert "Pick a Compare by field" in result["discover_empty_reason"]
        assert result["combined_single_chart_type"] == "bar"
        assert result["combined_single_series_count"] == 4
        assert result["combined_single_point_total"] == 8
        assert "shared Y axis" in result["combined_single_subtitle"]
        assert result["combined_single_categories_count"] >= 2
        assert result["combined_dual_y_axis_count"] == 2
        assert result["combined_dual_secondary_series_on_axis_1"] is True
        assert result["combined_mixed_series_count"] == 0
        assert "not available" in result["combined_mixed_empty_reason"]

    def test_html_includes_diagnostics_and_history_frames(self, tmp_path):
        data = DashboardData(
            stage_records=[
                StageRecord(
                    run_timestamp="2026-02-11_16.00.00",
                    file_name="book.epub",
                    importer_name="epub",
                    run_config={
                        "epub_extractor": "beautifulsoup",
                        "ocr_device": "auto",
                        "ocr_batch_size": 1,
                        "effective_workers": 10,
                    },
                    total_seconds=12.0,
                    recipes=6,
                    per_recipe_seconds=2.0,
                    artifact_dir="/tmp/output/2026-02-11_16.00.00",
                )
            ],
            summary=DashboardSummary(total_stage_records=1, total_recipes=6),
        )
        html_path = render_dashboard(tmp_path / "dash", data)
        html = html_path.read_text(encoding="utf-8")
        assert "All-Method Benchmark Runs" not in html
        assert "Diagnostics (Latest Benchmark)" in html
        assert 'id="runtime-section"' in html
        assert 'id="per-label-run-group-select"' in html
        assert "Default - most recent" in html
        assert 'id="per-label-rolling-window-size"' in html
        assert 'id="per-label-comparison-point-value"' in html
        assert 'class="per-label-rolling-group"' in html
        assert 'class="per-label-col-head">Run<br>Precision<br>' in html
        assert 'class="per-label-col-sub">(codex-exec)</span>' in html
        assert 'class="per-label-col-head">Run<br>Recall<br>' in html
        assert 'class="per-label-rolling-window-value">10</span>' in html
        assert 'Rolling <span class="per-label-comparison-mode-value">Delta</span>:' in html
        assert 'data-per-label-comparison-scope="rolling" data-per-label-comparison-metric="precision" data-per-label-comparison-variant="vanilla"' not in html
        assert 'data-per-label-comparison-scope="rolling" data-per-label-comparison-metric="recall" data-per-label-comparison-variant="vanilla"' not in html
        assert "Point value" in html
        assert 'id="compare-control-x-axis-date"' in html
        assert 'id="compare-control-x-axis-per-run"' in html
        assert "Previous Runs" in html
        assert 'class="table-wrap table-scroll"' in html
        assert "Stage / Import Throughput" not in html
        assert "Benchmark Evaluations" not in html

    def test_html_embeds_inline_data_for_file_scheme(self, tmp_path):
        data = DashboardData(
            stage_records=[
                StageRecord(file_name="local.xlsx", recipes=3, total_seconds=1.5),
            ],
            summary=DashboardSummary(total_stage_records=1, total_recipes=3),
        )
        html_path = render_dashboard(tmp_path / "dash", data)
        html = html_path.read_text(encoding="utf-8")
        assert 'id="dashboard-data-inline"' in html
        assert "__DASHBOARD_DATA_INLINE__" not in html
        assert '"file_name": "local.xlsx"' in html
        assert 'href="assets/style.css?v=' in html
        assert 'src="assets/dashboard.js?v=' in html
        assert 'http-equiv="Cache-Control"' in html

    def test_html_includes_highcharts_secondary_cdn_fallback(self, tmp_path):
        html_path = render_dashboard(tmp_path / "dash", DashboardData())
        html = html_path.read_text(encoding="utf-8")
        assert 'src="https://code.highcharts.com/stock/highstock.js"' in html
        assert "if (!window.Highcharts || typeof window.Highcharts.stockChart !== 'function')" in html
        assert "https://cdn.jsdelivr.net/npm/highcharts/highstock.js" in html
        assert 'src="https://code.highcharts.com/highcharts-more.js"' in html
        assert "if (!window.Highcharts || !window.Highcharts.seriesTypes || typeof window.Highcharts.seriesTypes.arearange !== 'function')" in html
        assert "https://cdn.jsdelivr.net/npm/highcharts/highcharts-more.js" in html

    def test_js_uses_timestamp_comparators_for_run_sorting(self, tmp_path):
        data = DashboardData(
            benchmark_records=[
                BenchmarkRecord(
                    run_timestamp="2026-02-15_23.25.45",
                    artifact_dir="/tmp/eval-older",
                    precision=0.1,
                    recall=0.2,
                ),
                BenchmarkRecord(
                    run_timestamp="2026-02-15T23:59:24",
                    artifact_dir="/tmp/eval-newer",
                    precision=0.2,
                    recall=0.3,
                ),
            ],
        )
        render_dashboard(tmp_path / "dash", data)
        js = (tmp_path / "dash" / "assets" / "dashboard.js").read_text(encoding="utf-8")
        assert "const m = text.match(/^(\\d{4})-(\\d{2})-(\\d{2})[T_](\\d{2})[.:](\\d{2})[.:](\\d{2})(?:_.+)?$/);" in js
        assert "useUTC: false" in js
        assert "const d = new Date(" in js
        assert "Number(m[1])" in js
        assert "function compareRunTimestampAsc(aTs, bTs)" in js
        assert "function compareRunTimestampDesc(aTs, bTs)" in js
        assert "compareRunTimestampDesc(a.run_timestamp, b.run_timestamp)" in js

    def test_js_renders_previous_runs_table_and_links_timestamp_to_artifact(
        self, tmp_path
    ):
        render_dashboard(tmp_path / "dash", DashboardData())
        js = (tmp_path / "dash" / "assets" / "dashboard.js").read_text(encoding="utf-8")
        assert "function renderPreviousRuns()" in js
        assert 'document.getElementById("previous-runs-section")' in js
        assert 'document.getElementById("previous-runs-table")' in js
        assert "function renderPreviousRunsCell(row, fieldName)" in js
        assert 'const href = row.href || "";' in js
        assert 'const ALL_METHOD_SEGMENT = "all-method-benchmark";' in js
        assert 'let previousRunsSortField = "run_timestamp";' in js
        assert 'let previousRunsSortDirection = "desc";' in js
        assert "function comparePreviousRunsRows(leftRow, rightRow)" in js
        assert "th.addEventListener(\"click\", event => {" in js
        assert "Click to sort A to Z / Z to A." in js
        assert "(?:_.+)?$/.test(text);" in js
        assert "runDirTimestamp: runDirTimestamp || fallbackTimestamp || null," in js
        assert 'href: "#all-method-summary-section"' in js
        assert "function renderAllMethodSummary()" in js
        assert 'document.getElementById("all-method-summary-section")' in js
        assert "function sourceLabelForRecord(record)" in js
        assert "function sourceSlugFromArtifactPath(pathValue)" in js
        assert "function importerLabelForRecord(record)" in js
        assert "all-method: " in js
        assert "function aiModelEffortLabelForRecord(record)" in js
        assert "function aiModelLabelForRecord(record)" in js
        assert "function aiEffortLabelForRecord(record)" in js
        assert "function aiAssistanceProfileForRecord(record)" in js
        assert "function aiAssistanceProfileLabelForRecord(record)" in js
        assert "function rawAiModelForRecord(record)" in js
        assert "function rawAiEffortForRecord(record)" in js
        assert 'const knowledgePipeline = runConfigValue(record, ["llm_knowledge_pipeline"]);' in js
        assert 'const recipePipelineKey = recipePipeline == null ? "" : String(recipePipeline).toLowerCase();' in js
        assert "const hasAnyPipelineSetting =" in js
        assert 'if (aiAssistanceProfileForRecord(record) === "deterministic") return null;' in js
        assert "function previousRunsAllTokenUseDisplay(row)" in js
        assert "function previousRunsAllTokenUseTitle(row)" in js
        assert "function previousRunsQualityPerMillionTokensTitle(row)" in js
        assert "function benchmarkQualityPerMillionTokensForRecord(record)" in js
        assert "function aggregateBenchmarkQuality(records, preferredMetricKey)" in js
        assert "function qualityPerMillionTokensValue(qualityScore, tokenTotal)" in js
        assert "function runtimeQualityPeerStats(records, currentRunGroupKey, preferredMetricKey)" in js
        assert "function runtimeQualityPeerSummaryText(stats)" in js
        assert "function formatTokenCountCompact(value)" in js
        assert "formatTokenCountCompact(parts.total)" in js
        assert "formatTokenCountCompact(parts.input)" in js
        assert "formatTokenCountCompact(parts.output)" in js
        assert 'const runtimeError = codexRuntimeErrorForRecord(record);' in js
        assert 'if (runtimeError) return "System error";' in js
        assert 'if (profile === "deterministic") return "AI off";' in js
        assert 'return aiAssistanceProfileLabelForRecord(record);' in js
        assert 'lower === "<default>"' in js
        assert "function renderLatestRuntime()" in js
        assert "function latestRuntimeSummaryForRecords(records)" in js
        assert "const latestRunGroup = latestRunGroupRecords(preferredRecords, record => !!record);" in js
        assert 'const latestTs = String(preferred[0].run_timestamp || "");' in js
        assert "const latestGroup = preferred.filter(" in js
        assert "const runtimeSummary = latestRuntimeSummaryForRecords(records);" in js
        assert 'runGroupRecordCount + " evals)"' in js
        assert "const totalTokenUse = runtimeSummary.tokenUseDisplay;" in js
        assert 'Quality / 1M tokens' in js
        assert "runtimeQualityPeerSummaryText(runtimeSummary.peerQualityStats)" in js
        assert "tokenUseDisplay: formatTokenCountCompact(" in js
        assert "previousRunsDiscountedTokenTotal(" in js
        assert "rawTotalTokenUse" not in js
        assert "AI Runtime" not in js
        assert "'<tr><td data-metric-tooltip-key=\"all_token_use\">Token use</td><td>' + esc(totalTokenUse) + '</td></tr>'" in js
        assert "Raw total tokens" not in js
        assert "link.href = href;" in js

    def test_js_supports_previous_runs_column_header_filters(
        self, tmp_path
    ):
        render_dashboard(tmp_path / "dash", DashboardData())
        js = (tmp_path / "dash" / "assets" / "dashboard.js").read_text(encoding="utf-8")
        assert "const PREVIOUS_RUNS_COLUMN_FILTER_OPERATORS = [" in js
        assert "const PREVIOUS_RUNS_UNARY_FILTER_OPERATORS = new Set(" in js
        assert "const PREVIOUS_RUNS_COLUMN_FILTER_MODES = [" in js
        assert "const PREVIOUS_RUNS_COLUMN_FILTER_MODE_LABEL = Object.fromEntries(" in js
        assert "const PREVIOUS_RUNS_FILTER_SUGGESTION_LIMIT = 8;" in js
        assert 'let perLabelRunGroupKey = "__default_most_recent__";' in js
        assert 'const PER_LABEL_RUN_GROUP_DEFAULT_KEY = "__default_most_recent__";' in js
        assert "const BENCHMARK_TREND_DEFAULT_FIELDS = [" in js
        assert "const BENCHMARK_TREND_PREFERRED_FIELDS = [" in js
        assert "const BENCHMARK_TREND_COLOR_OVERRIDES = {" in js
        assert "let benchmarkTrendFieldOptions = [];" in js
        assert "let benchmarkTrendSelectedFields = null;" in js
        assert "function normalizeBenchmarkTrendFieldList(values, options)" in js
        assert "function setupBenchmarkTrendFieldControls()" in js
        assert "function renderBenchmarkTrendFieldControls()" in js
        assert "function setBenchmarkTrendSelectedFields(nextFields, options)" in js
        assert "trend_fields: normalizeBenchmarkTrendFieldList(" in js
        assert '"source_label"' in js
        assert '"ai_model"' in js
        assert '"ai_effort"' in js
        assert '"all_token_use"' in js
        assert '"quality_per_million_tokens"' in js
        assert "let previousRunsQuickFilters = {" in js
        assert "exclude_ai_tests: false" in js
        assert "official_full_golden_only: true" in js
        assert "let previousRunsViewPresets = Object.create(null);" in js
        assert "let previousRunsSelectedPreset = \"\";" in js
        assert "const PREVIOUS_RUNS_PRESET_NAME_MAX = 80;" in js
        assert "const PREVIOUS_RUNS_PRESET_MAX_COUNT = 40;" in js
        assert 'const DASHBOARD_UI_STATE_STORAGE_KEY = "cookimport.stats_dashboard.ui_state.v1";' in js
        assert 'const DASHBOARD_UI_STATE_SERVER_PATH = "assets/dashboard_ui_state.json";' in js
        assert "const DASHBOARD_UI_STATE_SYNC_INTERVAL_MS = 3000;" in js
        assert "function loadDashboardUiState()" in js
        assert "function loadDashboardUiStateFromProgramStore()" in js
        assert "function startDashboardUiProgramSyncLoop()" in js
        assert "function persistDashboardUiState()" in js
        assert "function persistDashboardUiStateToProgramStore(payload)" in js
        assert "function persistDashboardUiStateToBrowserStorage(payload)" in js
        assert "function sanitizePreviousRunsPresetName(rawName)" in js
        assert "function sanitizePreviousRunsPresetState(rawPreset)" in js
        assert "function sanitizePreviousRunsPresetMap(rawPresets)" in js
        assert 'if (Object.prototype.hasOwnProperty.call(previousRuns, "compare_control")) {' in js
        assert "compareControlState = normalizeCompareControlState(compareControlState);" in js
        assert "compare_control: {" in js
        assert "second_set_enabled: Boolean(compareControlSecondSetEnabled)," in js
        assert "second_set: normalizeCompareControlState(compareControlSecondaryState)," in js
        assert "chart_layout: normalizeCompareControlChartLayout(compareControlChartLayout)," in js
        assert "combined_axis_mode: normalizeCompareControlCombinedAxisMode(" in js
        assert 'if (Object.prototype.hasOwnProperty.call(previousRuns, "per_label_run_group_key")) {' in js
        assert "per_label_run_group_key: normalizePerLabelRunGroupKey(perLabelRunGroupKey)," in js
        assert "function previousRunsPresetNames()" in js
        assert "function renderPreviousRunsPresetEditor()" in js
        assert "function captureCurrentPreviousRunsPresetState()" in js
        assert "function applyPreviousRunsPresetByName(rawName)" in js
        assert "function saveCurrentPreviousRunsViewPreset(rawName)" in js
        assert "function deletePreviousRunsPreset(rawName)" in js
        assert "let dashboardTableColumnWidths = Object.create(null);" in js
        assert "const tableColumnWidths = sanitizeDashboardTableColumnWidths(dashboardTableColumnWidths);" in js
        assert "table_column_widths: tableColumnWidths," in js
        assert "previous_runs_presets: previousRunsPresets," in js
        assert "selected_preset: selectedPresetName," in js
        assert "saved_at: savedAt," in js
        assert "setDashboardTableColumnWidth(previousRunsTableKey, fieldName, nextWidth);" in js
        assert "function setupResizableDashboardTable(table, options)" in js
        assert "function setupResizableDashboardTables()" in js
        assert 'clearDashboardTableColumnWidths("per-label-table");' in js
        assert "tableKey: \"boundary-table\"" not in js
        assert "tableKey: \"runtime-table\"" not in js
        assert "setupResizableDashboardTables();" in js
        assert "window.localStorage" in js
        assert "loadDashboardUiState();" in js
        assert "loadDashboardUiStateFromProgramStore()" in js
        assert "loadDashboardUiStateFromProgramStore({ force: true })" in js
        assert 'fetch(DASHBOARD_UI_STATE_SERVER_PATH, { cache: "no-store" })' in js
        assert "storage.setItem(DASHBOARD_UI_STATE_STORAGE_KEY, JSON.stringify(payload));" in js
        assert 'method: "PUT"' in js
        assert "if (dashboardUiStatePersistSuppressed) return;" in js
        assert "persistDashboardUiState();" in js
        assert "function setupPreviousRunsFilters()" in js
        assert "function setupPreviousRunsQuickFilters()" in js
        assert "function setupCompareControlControls()" in js
        assert "function setupPreviousRunsPresetControls()" in js
        assert "function setPreviousRunsPresetsPopupOpen(nextOpen)" not in js
        assert "function applyPreviousRunsQuickFilters(records, options)" in js
        assert "function isLikelyAiTestBenchmarkRecord(record)" in js
        assert "timestampSuffix = segment.match(" in js
        assert "(manual|smoke|test|debug|quick|probe|sample|trial)" in js
        assert "function isOfficialGoldenBenchmarkRecord(record)" in js
        assert 'if (!path.includes("/benchmark-vs-golden/")) return false;' in js
        assert 'if (!path.includes("/single-book-benchmark/")) return false;' in js
        assert 'const variant = benchmarkVariantForRecord(record);' in js
        assert '(variant === "vanilla" && profile === "deterministic")' in js
        assert '(variant === "codex-exec" && profile === "full_stack")' in js
        assert 'const clearBtn = document.getElementById("previous-runs-clear-filters");' in js
        assert 'const clearAllBtn = document.getElementById("previous-runs-clear-all-filters");' in js
        assert "function clearAllPreviousRunsFilters()" in js
        assert "function collectBenchmarkFieldPaths()" in js
        assert "function normalizePreviousRunsColumnFilterList(rawValue)" in js
        assert "function previousRunsColumnFilterClauses(fieldName)" in js
        assert "function previousRunsColumnFilterMode(fieldName)" in js
        assert "function setPreviousRunsColumnFilterMode(fieldName, mode)" in js
        assert "function addPreviousRunsColumnFilter(fieldName, operator, value)" in js
        assert "function updatePreviousRunsColumnFilterAt(fieldName, index, operator, value)" in js
        assert "function removePreviousRunsColumnFilterAt(fieldName, index)" in js
        assert "function activePreviousRunsColumnFilters()" in js
        assert "function previousRunsIconSvgPath(iconName)" in js
        assert "function setPreviousRunsIcon(button, iconName)" in js
        assert "function formatPreviousRunsColumnFilterSummary(fieldName, filter)" in js
        assert "function formatPreviousRunsColumnFiltersSummary(fieldName, clauses)" in js
        assert "function groupPreviousRunsFiltersByField(filters)" in js
        assert "function recordMatchesPreviousRunsFilterGroups(record, groupedFilters, globalMode)" in js
        assert "function previousRunsRecordsMatchingOtherFilters(excludedField)" in js
        assert "function previousRunsColumnSuggestionCandidates(fieldName, typedText)" in js
        assert "function previousRunsSuggestionScore(typedLower, candidateLower)" in js
        assert '"run_config.model"' in js
        assert "function evaluatePreviousRunsFilterOperator(value, operator, expected)" in js
        assert "function currentPreviousRunsFilterResult()" in js
        assert "const filterResult = currentPreviousRunsFilterResult();" in js
        assert "const PREVIOUS_RUNS_DEFAULT_COLUMNS = [" in js
        assert "const PREVIOUS_RUNS_COLUMN_META = {" in js
        assert "function setupPreviousRunsColumnsControls()" in js
        assert "function renderPreviousRunsTableColumns(table, columns)" in js
        assert "function renderPreviousRunsColumnEditor()" in js
        assert 'const toggleBtn = document.getElementById("previous-runs-presets-toggle");' not in js
        assert 'const popup = document.getElementById("previous-runs-presets-popup");' not in js
        assert 'const presetSelect = document.getElementById("previous-runs-preset-select");' in js
        assert 'const presetLoadBtn = document.getElementById("previous-runs-preset-load");' in js
        assert 'const presetSaveCurrentBtn = document.getElementById("previous-runs-preset-save-current");' in js
        assert 'const presetDeleteBtn = document.getElementById("previous-runs-preset-delete");' in js
        assert 'const filterRow = table.querySelector("thead tr.previous-runs-active-filters-row");' in js
        assert 'const spacerRow = table.querySelector("thead tr.previous-runs-filter-spacer-row");' in js
        assert "let previousRunsOpenFilterField = \"\";" in js
        assert "let previousRunsOpenFilterDraft = null;" in js
        assert "function openPreviousRunsColumnFilterEditor(fieldName, options)" in js
        assert "function closePreviousRunsColumnFilterEditor()" in js
        assert 'setPreviousRunsIcon(toggleBtn, isEditorOpen ? "minus" : "plus");' in js
        assert 'summaryItem.className = "previous-runs-column-filter-summary-item";' in js
        assert 'summaryEditBtn.className = "previous-runs-column-filter-summary-edit";' in js
        assert 'summaryEditBtn.setAttribute("aria-label", "Edit filter " + String(clauseIndex + 1));' in js
        assert 'summaryRemoveBtn.className = "previous-runs-column-filter-summary-remove";' in js
        assert 'setPreviousRunsIcon(summaryRemoveBtn, "close");' in js
        assert 'popover.className = "previous-runs-column-filter-popover";' in js
        assert 'modeWrap.className = "previous-runs-column-filter-mode";' in js
        assert 'modeButtons.className = "previous-runs-column-filter-mode-buttons";' in js
        assert "setPreviousRunsColumnFilterMode(fieldName, modeValue);" in js
        assert 'activeList.className = "previous-runs-column-filter-active-list";' in js
        assert 'setPreviousRunsIcon(removeBtn, "close");' in js
        assert "removePreviousRunsColumnFilterAt(fieldName, clauseIndex);" in js
        assert "addPreviousRunsColumnFilter(fieldName, operatorSelect.value || \"contains\", valueInput.value || \"\");" in js
        assert 'suggestionWrap.className = "previous-runs-column-filter-suggestions";' in js
        assert 'suggestionList.className = "previous-runs-column-filter-suggestions-list";' in js
        assert 'valueInput.dataset.topSuggestion = topCandidate;' in js
        assert "if (unary || meta.numeric) {" in js
        assert 'if (event.key === "Tab" && !event.shiftKey) {' in js
        assert "Tab completes top match." in js
        assert 'saveBtn.textContent = "Save";' in js
        assert 'closeBtn.textContent = "Close";' in js
        assert "let previousRunsDraggedColumn = null;" in js
        assert "function reorderPreviousRunsColumns(fromField, toField)" in js
        assert "th.draggable = true;" in js
        assert 'th.addEventListener("dragstart", event => {' in js
        assert 'th.addEventListener("drop", event => {' in js

    def test_js_per_label_aggregates_latest_run_timestamp_group(self, tmp_path):
        data = DashboardData(
            benchmark_records=[
                BenchmarkRecord(
                    run_timestamp="2026-02-27_17.54.41",
                    artifact_dir="/tmp/eval/latest/a",
                    precision=0.5,
                    recall=0.5,
                    per_label=[
                        BenchmarkLabelMetrics(
                            label="RECIPE_TITLE",
                            precision=1.0,
                            recall=0.5,
                            gold_total=10,
                            pred_total=5,
                        )
                    ],
                ),
                BenchmarkRecord(
                    run_timestamp="2026-02-27_17.54.41",
                    artifact_dir="/tmp/eval/latest/b",
                    precision=0.6,
                    recall=0.6,
                    per_label=[
                        BenchmarkLabelMetrics(
                            label="RECIPE_TITLE",
                            precision=0.5,
                            recall=1.0,
                            gold_total=4,
                            pred_total=8,
                        )
                    ],
                ),
                BenchmarkRecord(
                    run_timestamp="2026-02-26_17.47.33",
                    artifact_dir="/tmp/eval/older",
                    precision=0.7,
                    recall=0.7,
                    per_label=[
                        BenchmarkLabelMetrics(
                            label="RECIPE_TITLE",
                            precision=0.25,
                            recall=0.25,
                            gold_total=100,
                            pred_total=100,
                        )
                    ],
                ),
            ]
        )
        render_dashboard(tmp_path / "dash", data)
        js = (tmp_path / "dash" / "assets" / "dashboard.js").read_text(encoding="utf-8")
        assert "function isSpeedBenchmarkRecord(record)" in js
        assert '.replace(/\\\\/g, "/")' in js
        assert ".toLowerCase();" in js
        assert 'return path.includes("/bench/speed/runs/");' in js
        assert "function isAllMethodBenchmarkRecord(record)" in js
        assert 'return path.includes("/all-method-benchmark/");' in js
        assert "const preferredRecords = nonSpeed.length > 0 ? nonSpeed : sorted;" in js
        assert "const latestAllMethodRecords = preferredRecords.filter(r =>" in js
        assert "isAllMethodBenchmarkRecord(r)" in js
        assert "const candidateRecords = latestAllMethodRecords.length > 0" in js
        assert "function latestRunGroupRecords(records, hasData)" in js
        assert "const latestRunGroup = benchmarkRunGroupInfo(latestRecord);" in js
        assert "const latestRunGroupKey = String((latestRunGroup && latestRunGroup.runGroupKey) || \"\").trim();" in js
        assert "const latestRunRecords = (records || []).filter(record => {" in js
        assert "const recordRunGroup = benchmarkRunGroupInfo(record);" in js
        assert 'if (segment !== "benchmark-vs-golden") continue;' in js
        assert 'latestRunRecords.length + " evals)"' in js
        assert "function aggregatePerLabelRows(records)" in js
        assert "function setupPerLabelControls()" in js
        assert "function syncPerLabelRollingWindowUi()" in js
        assert "function syncPerLabelComparisonModeUi()" in js
        assert "function normalizePerLabelRollingWindowSize(value)" in js
        assert "function normalizePerLabelComparisonMode(value)" in js
        assert "function normalizePerLabelRunGroupKey(value)" in js
        assert "function perLabelRunGroups(records)" in js
        assert "function syncPerLabelRunGroupUi(runGroups)" in js
        assert "function rollingPerLabelByVariant(records, variant, windowSize, perLabelVariantMapper)" in js
        assert "const rollingWindowSize = normalizePerLabelRollingWindowSize(perLabelRollingWindowSize);" in js
        assert "per_label_comparison_mode: normalizePerLabelComparisonMode(perLabelComparisonMode)" in js
        assert "const runGroups = perLabelRunGroups(candidateRecords);" in js
        assert 'const runGroupSelect = document.getElementById("per-label-run-group-select");' in js
        assert 'defaultOption.textContent = "Default - most recent";' in js
        assert 'const checkbox = document.getElementById("per-label-comparison-point-value");' in js
        assert "const rawDelta = baselineNum - valueNum;" in js
        assert 'if (typeof candidate === "string" && candidate.trim() === "") return null;' in js
        assert "mapBenchmarkVariantForPerLabel(record" in js
        assert 'benchmarkVariantForRecord(record) === "vanilla"' in js
        assert 'fetch("assets/dashboard_data.json", { cache: "no-store" })' in js

    def test_js_boundary_prefers_non_speed_records_when_available(self, tmp_path):
        render_dashboard(tmp_path / "dash", DashboardData())
        js = (tmp_path / "dash" / "assets" / "dashboard.js").read_text(encoding="utf-8")
        assert "function renderBoundary()" in js
        assert "function isSpeedBenchmarkRecord(record)" in js
        assert "const hasBoundaryMetrics = function(record)" in js
        assert "const preferredRecords = nonSpeed.length > 0 ? nonSpeed : sorted;" in js
        assert "const latestAllMethodRecords = preferredRecords.filter(r =>" in js
        assert "const candidateRecords = latestAllMethodRecords.length > 0" in js
        assert "const latestRunGroup = latestRunGroupRecords(candidateRecords, hasBoundaryMetrics);" in js
        assert 'latestRunRecords.length + " evals)"' in js
        assert "Coverage: " in js
        assert "Matched (boundary unclassified)" in js
        assert '<th>% of gold</th>' in js
        assert '% of matched' not in js
        assert "Unmatched gold spans" in js

    def test_runtime_summary_aggregates_tokens_across_latest_run_group(self, tmp_path):
        dash_dir = tmp_path / "dash"
        render_dashboard(dash_dir, DashboardData())
        js_path = dash_dir / "assets" / "dashboard.js"
        records = [
            {
                "run_timestamp": "2026-03-04T08:12:01",
                "benchmark_variant": "vanilla",
                "artifact_dir": (
                    "/tmp/golden/benchmark-vs-golden/seaandsmokecutdown/"
                    "2026-03-04_08.00.00/single-book-benchmark/book_a/2026-03-04_08.12.01/vanilla"
                ),
                "run_config": {
                    "llm_recipe_pipeline": "off",
                    "line_role_pipeline": "off",
                },
                "strict_accuracy": 0.40,
                "tokens_input": 100,
                "tokens_cached_input": 0,
                "tokens_output": 20,
            },
            {
                "run_timestamp": "2026-03-04T08:11:01",
                "benchmark_variant": "codex-exec",
                "artifact_dir": (
                    "/tmp/golden/benchmark-vs-golden/seaandsmokecutdown/"
                    "2026-03-04_08.00.00/single-book-benchmark/book_b/2026-03-04_08.11.01/codex-exec"
                ),
                "run_config": {
                    "llm_recipe_pipeline": "codex-recipe-shard-v1",
                    "line_role_pipeline": "codex-line-role-route-v2",
                    "codex_farm_model": "gpt-5.3-codex-spark",
                    "codex_farm_reasoning_effort": "low",
                },
                "strict_accuracy": 0.80,
                "tokens_input": 1000,
                "tokens_cached_input": 500,
                "tokens_output": 200,
            },
            {
                "run_timestamp": "2026-03-04T08:10:01",
                "benchmark_variant": "codex-exec",
                "artifact_dir": (
                    "/tmp/golden/benchmark-vs-golden/seaandsmokecutdown/"
                    "2026-03-04_08.00.00/single-book-benchmark/book_c/2026-03-04_08.10.01/codex-exec"
                ),
                "run_config": {
                    "llm_recipe_pipeline": "codex-recipe-shard-v1",
                    "line_role_pipeline": "codex-line-role-route-v2",
                    "codex_farm_model": "gpt-5.3-codex-spark",
                    "codex_farm_reasoning_effort": "low",
                },
                "strict_accuracy": 0.70,
                "tokens_input": 2000,
                "tokens_cached_input": 1000,
                "tokens_output": 400,
            },
            {
                "run_timestamp": "2026-03-03T20:10:01",
                "artifact_dir": (
                    "/tmp/golden/benchmark-vs-golden/seaandsmokecutdown/"
                    "2026-03-03_20.00.00/single-book-benchmark/book_d/2026-03-03_20.10.01/codex-exec"
                ),
                "run_config": {
                    "llm_recipe_pipeline": "codex-recipe-shard-v1",
                    "line_role_pipeline": "codex-line-role-route-v2",
                    "codex_farm_model": "gpt-5.3-codex-spark",
                    "codex_farm_reasoning_effort": "medium",
                },
                "strict_accuracy": 0.95,
                "tokens_input": 9000,
                "tokens_cached_input": 0,
                "tokens_output": 1000,
            },
        ]
        result = _run_latest_runtime_summary_harness(js_path, records)
        assert result["run_group_label"] == "2026-03-04_08.00.00"
        assert result["run_group_record_count"] == 3
        assert result["token_use_value"] == 2370
        assert result["token_use_display"] == "2k"
        assert result["context_model"] == "gpt-5.3-codex-spark"
        assert result["context_effort"] == "low"
        assert result["context_pipeline"] == "codex-recipe-shard-v1"
        assert result["quality_metric_key"] == "strict_accuracy"
        assert result["quality_per_million_tokens"] == pytest.approx(267.229, rel=1e-4)
        assert result["quality_delta_vs_vanilla"] == pytest.approx(0.35)
        assert result[
            "quality_delta_per_million_extra_tokens_vs_vanilla"
        ] == pytest.approx(164.319, rel=1e-4)
        assert result["peer_rank"] == 1
        assert result["peer_total"] == 2
        assert result["peer_ratio_to_median"] == pytest.approx(1.4755, rel=1e-4)

    def test_previous_runs_quality_per_million_tokens_calculation(self, tmp_path):
        dash_dir = tmp_path / "dash"
        render_dashboard(dash_dir, DashboardData())
        js_path = dash_dir / "assets" / "dashboard.js"
        result = _run_previous_runs_quality_tokens_harness(js_path)
        assert result["record_quality_per_million_tokens"] == pytest.approx(
            543.47826087, rel=1e-6
        )
        assert result["record_conversion_seconds_per_recipe"] == pytest.approx(5.0)
        assert result["record_all_token_use_per_recipe"] == pytest.approx(230.0)
        assert result["all_method_quality_per_million_tokens"] == pytest.approx(125.0)
        assert result["missing_telemetry_ai_model"] == "gpt-5.1-codex-mini"
        assert result["missing_telemetry_token_display"] == "-"
        assert result["missing_telemetry_all_token_use"] is None
        assert result["explicit_zero_telemetry_token_display"] == "0 total | 0 in | 0 out"
        assert result["explicit_zero_telemetry_all_token_use"] == pytest.approx(0.0)
        assert result["runtime_error_ai_model"] == "System error"
        assert result["runtime_error_effort_label"] == "Recipe only"
        assert result["ai_off_effort_label"] == "AI off"
        assert result["vanilla_path_ai_off_effort_label"] == "AI off"
        assert result["line_role_only_effort_label"] == "Line-role only"
        assert result["line_role_only_profile_label"] == "Line-role only"
        assert result["path_only_codex_profile"] == "recipe_only"
        assert result["path_only_codex_variant"] == "recipe_only"
        assert result["path_only_codex_official"] is False
        assert result["path_only_vanilla_profile"] == "other"
        assert result["path_only_vanilla_variant"] == "other"
        assert result["path_only_vanilla_official"] is False
        assert result["path_only_rundir_codex_profile"] == "recipe_only"
        assert result["path_only_rundir_codex_variant"] == "recipe_only"
        assert result["path_only_rundir_codex_official"] is False
        assert result["path_only_rundir_vanilla_profile"] == "other"
        assert result["path_only_rundir_vanilla_variant"] == "other"
        assert result["path_only_rundir_vanilla_official"] is False
        assert result["unknown_effort_label"] == "Unknown"

    def test_per_label_full_stack_single_profile_uses_codex_exec_baseline(self, tmp_path):
        dash_dir = tmp_path / "dash"
        render_dashboard(dash_dir, DashboardData())
        js_path = dash_dir / "assets" / "dashboard.js"
        result = _run_per_label_variant_fallback_harness(js_path)

        assert result["singleProfileVariant"] == "full_stack"
        assert result["singleProfileMappedNoFallback"] == "full_stack"
        assert result["singleProfileMappedWithoutOfficial"] == "codex-exec"
        assert result["noOfficialHasCodexOrVanilla"] is False
        assert result["withOfficialHasCodexOrVanilla"] is True
        assert result["baseline_no_official_codex_precision"] == pytest.approx(0.2083333333, rel=1e-6)
        assert result["baseline_no_official_codex_recall"] == pytest.approx(0.4166666667, rel=1e-6)
        assert result["baseline_with_official_codex_precision"] is None
        assert result["baseline_vanilla_precision_no_official"] is None
        assert result["rolling_no_official_codex_precision"] == pytest.approx(0.2, rel=1e-6)
        assert result["rolling_no_official_codex_recall"] == pytest.approx(0.4, rel=1e-6)
