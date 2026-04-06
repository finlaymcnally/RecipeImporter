from __future__ import annotations

_JS_BOOTSTRAP = """\
(function () {
  "use strict";

  let DATA = null;
  let activeCategories = new Set(["stage_import", "benchmark_eval"]);
  let activeExtractors = new Set();
  let activeDays = 0; // 0 = all
  let selectedFileTrend = "";
  let throughputScaleMode = "clamp95";
  let previousRunsColumnFilters = Object.create(null);
  let previousRunsColumnFilterModes = Object.create(null);
  let previousRunsColumnFilterGlobalMode = "and";
  let previousRunsQuickFilters = {
    exclude_ai_tests: false,
    official_full_golden_only: true,
  };
  let previousRunsFieldOptions = [];
  let benchmarkTrendFieldOptions = [];
  let benchmarkTrendSelectedFields = null;
  let previousRunsVisibleColumns = [];
  let previousRunsColumnWidths = Object.create(null);
  let dashboardTableColumnWidths = Object.create(null);
  let previousRunsDraggedColumn = null;
  let previousRunsOpenFilterField = "";
  let previousRunsOpenFilterDraft = null;
  let previousRunsColumnsPopupOpen = false;
  let previousRunsFilterResultCache = null;
  let previousRunsViewPresets = Object.create(null);
  let previousRunsSelectedPreset = "";
  let previousRunsSortField = "run_timestamp";
  let previousRunsSortDirection = "desc";
  let benchmarkTrendChartsByHostId = Object.create(null);
  let benchmarkTrendResizeRafId = null;
  let dashboardResizeHandlersBound = false;
  let lastKnownViewportWidth = 0;
  let metricTooltipDescriptions = Object.create(null);
  let metricTooltipAliasesByText = Object.create(null);
  let metricTooltipAliasEntries = [];
  let metricTooltipNode = null;
  let metricTooltipTimerId = null;
  let metricTooltipPendingTarget = null;
  let metricTooltipActiveTarget = null;
  let metricTooltipMouseX = 0;
  let metricTooltipMouseY = 0;
  function compareControlDefaultState() {
    return {
      outcome_field: "strict_accuracy",
      compare_field: "",
      chart_type: "scatter",
      x_axis_mode: "date",
      hold_constant_fields: [],
      split_field: "",
      view_mode: "discover",
      selected_groups: [],
      discovery_preferences: {
        exclude_fields: [],
        prefer_fields: [],
        demote_patterns: [],
        max_cards: 10,
      },
    };
  }
  let compareControlState = compareControlDefaultState();
  let compareControlStatusMessage = "";
  let compareControlStatusIsError = false;
  let compareControlChartActivated = false;
  let compareControlSecondaryState = compareControlDefaultState();
  let compareControlSecondaryStatusMessage = "";
  let compareControlSecondaryStatusIsError = false;
  let compareControlSecondaryChartActivated = false;
  let compareControlSecondSetEnabled = false;
  let compareControlChartLayout = "stacked";
  let compareControlCombinedAxisMode = "single";
  let perLabelRollingWindowSize = 10;
  let perLabelComparisonMode = "delta";
  let perLabelRunGroupKey = "__default_most_recent__";
  // Keep wheel-zoom off across all Highcharts charts unless explicitly re-enabled.
  const HIGHCHARTS_MOUSE_WHEEL_ZOOM_ENABLED = false;
  const PER_LABEL_ROLLING_WINDOW_MIN = 1;
  const PER_LABEL_ROLLING_WINDOW_MAX = 50;
  const PER_LABEL_RUN_GROUP_DEFAULT_KEY = "__default_most_recent__";
  const QUALITY_PER_TOKEN_SCALE = 1000000;
  const BENCHMARK_QUALITY_METRIC_KEYS = [
    "strict_accuracy",
    "macro_f1_excluding_other",
    "f1",
  ];
  const BENCHMARK_TREND_DEFAULT_FIELDS = [
    "strict_accuracy",
    "macro_f1_excluding_other",
  ];
  const BENCHMARK_TREND_PREFERRED_FIELDS = [
    "strict_accuracy",
    "macro_f1_excluding_other",
    "precision",
    "recall",
    "f1",
    "practical_f1",
    "supported_precision",
    "supported_recall",
    "supported_practical_precision",
    "supported_practical_recall",
    "supported_practical_f1",
    "gold_total",
    "gold_matched",
    "recipes",
    "all_token_use",
    "quality_per_million_tokens",
    "tokens_total",
    "tokens_input",
    "tokens_cached_input",
    "tokens_output",
    "tokens_reasoning",
    "benchmark_total_seconds",
    "benchmark_prediction_seconds",
    "benchmark_evaluation_seconds",
    "benchmark_artifact_write_seconds",
  ];
  const BENCHMARK_TREND_COLOR_OVERRIDES = {
    strict_accuracy: {
      default: "#1f5ea8",
      vanilla: "#7daee8",
      "codex-exec": "#1f5ea8",
      other: "#7f96b3",
    },
    macro_f1_excluding_other: {
      default: "#127a52",
      vanilla: "#55b895",
      "codex-exec": "#127a52",
      other: "#6ea08c",
    },
  };
  const BENCHMARK_TREND_BASE_COLORS = [
    "#1f5ea8",
    "#127a52",
    "#a44717",
    "#8a3ea6",
    "#3b7c84",
    "#7a6335",
    "#6b5fb2",
    "#2c8c5f",
    "#9d4b6a",
    "#5a6f8a",
  ];
  const PREVIOUS_RUNS_COLUMN_FILTER_OPERATORS = [
    ["contains", "contains"],
    ["not_contains", "does not contain"],
    ["eq", "equals"],
    ["neq", "not equals"],
    ["starts_with", "starts with"],
    ["ends_with", "ends with"],
    ["gt", "> (numeric)"],
    ["gte", ">= (numeric)"],
    ["lt", "< (numeric)"],
    ["lte", "<= (numeric)"],
    ["regex", "matches regex"],
    ["is_empty", "is empty"],
    ["not_empty", "is not empty"],
  ];
  const PREVIOUS_RUNS_COLUMN_FILTER_OPERATOR_MAP = Object.fromEntries(
    PREVIOUS_RUNS_COLUMN_FILTER_OPERATORS
  );
  const PREVIOUS_RUNS_UNARY_FILTER_OPERATORS = new Set(["is_empty", "not_empty"]);
  const PREVIOUS_RUNS_COLUMN_FILTER_MODES = [
    ["and", "AND"],
    ["or", "OR"],
  ];
  const PREVIOUS_RUNS_COLUMN_FILTER_MODE_LABEL = Object.fromEntries(
    PREVIOUS_RUNS_COLUMN_FILTER_MODES
  );
  const PREVIOUS_RUNS_FILTER_SUGGESTION_LIMIT = 8;
  const DASHBOARD_TABLE_COLUMN_MIN_WIDTH = 72;
  const DASHBOARD_TABLE_COLUMN_MAX_WIDTH = 1200;
  const PREVIOUS_RUNS_PRESET_NAME_MAX = 80;
  const PREVIOUS_RUNS_PRESET_MAX_COUNT = 40;
  const METRIC_TOOLTIP_HOVER_DELAY_MS = 1000;
  const METRIC_TOOLTIP_OFFSET_X = 14;
  const METRIC_TOOLTIP_OFFSET_Y = 18;
  const METRIC_TOOLTIP_AUTO_TARGET_SELECTOR = [
    "th",
    "td:first-child",
    "label",
    "summary",
    "code",
    ".highcharts-axis-labels text",
    ".highcharts-axis-labels tspan",
    ".highcharts-legend-item text",
    ".highcharts-legend-item tspan",
    ".highcharts-axis-title text",
    ".highcharts-axis-title tspan",
  ].join(", ");
  const PREVIOUS_RUNS_DEFAULT_COLUMNS = [
    "run_timestamp",
    "strict_accuracy",
    "macro_f1_excluding_other",
    "gold_total",
    "gold_matched",
    "recipes",
    "all_token_use",
    "quality_per_million_tokens",
    "source_label",
    "importer_name",
    "ai_model",
    "ai_effort",
    "ai_assistance_profile",
  ];
  const PREVIOUS_RUNS_COLUMN_META = {
    run_timestamp: {
      label: "Timestamp",
      title: "When the benchmark happened. Link opens the run artifact folder.",
      numeric: false,
    },
    strict_accuracy: {
      label: "strict_accuracy",
      title: "Strict benchmark accuracy from canonical/stage scoring.",
      numeric: true,
    },
    macro_f1_excluding_other: {
      label: "macro_f1_excluding_other",
      title: "Macro F1 across labels excluding OTHER.",
      numeric: true,
    },
    gold_total: {
      label: "Gold",
      title: "How many gold spans were evaluated (span count, not recipes).",
      numeric: true,
    },
    gold_matched: {
      label: "Matched",
      title: "How many gold spans were matched under strict scoring.",
      numeric: true,
    },
    recipes: {
      label: "Recipes",
      title: "Predicted recipe count (when available). Separate from span scoring.",
      numeric: true,
    },
    all_token_use: {
      label: "All token use",
      title: "Combined token view (discounted_total/input/output). Discounted total applies cached-input tokens at 10% weight.",
      numeric: true,
    },
    quality_per_million_tokens: {
      label: "Quality / 1M tokens",
      title: "Quality-efficiency score: preferred quality metric (strict_accuracy, then macro_f1_excluding_other, then f1) per 1,000,000 discounted tokens.",
      numeric: true,
    },
    conversion_seconds_per_recipe: {
      label: "Conversion sec / recipe",
      title: "Single-book conversion time divided by predicted recipe count.",
      numeric: true,
    },
    "run_config.single_book_split_cache.conversion_seconds": {
      label: "Conversion seconds",
      title: "Single-book split-cache conversion time for this benchmark row.",
      numeric: true,
    },
    all_token_use_per_recipe: {
      label: "Token use / recipe",
      title: "Discounted token use divided by predicted recipe count.",
      numeric: true,
    },
    tokens_input: {
      label: "Tokens In",
      title: "Codex Exec input tokens summed for this benchmark run.",
      numeric: true,
    },
    tokens_cached_input: {
      label: "Tokens Cached In",
      title: "Codex Exec cached-input tokens summed for this benchmark run.",
      numeric: true,
    },
    tokens_output: {
      label: "Tokens Out",
      title: "Codex Exec output tokens summed for this benchmark run.",
      numeric: true,
    },
    tokens_reasoning: {
      label: "Tokens Reasoning",
      title: "Codex Exec reasoning tokens summed for this benchmark run.",
      numeric: true,
    },
    tokens_total: {
      label: "Tokens Total",
      title: "Codex Exec total tokens summed for this benchmark run.",
      numeric: true,
    },
    source_label: {
      label: "Source",
      title: "Which source file/book was evaluated.",
      numeric: false,
    },
    source_file_basename: {
      label: "Book",
      title: "Source file basename for the evaluated book.",
      numeric: false,
    },
    importer_name: {
      label: "Importer",
      title: "Importer used to generate predictions.",
      numeric: false,
    },
    ai_model: {
      label: "AI Model",
      title: "Best-effort AI model from benchmark run config metadata.",
      numeric: false,
    },
    ai_effort: {
      label: "AI Effort",
      title: "Best-effort AI thinking effort from benchmark run config metadata.",
      numeric: false,
    },
    ai_assistance_profile: {
      label: "AI Profile",
      title: "Semantic benchmark labeling based on which AI paths actually ran.",
      numeric: false,
    },
  };
  const PREVIOUS_RUNS_SCORE_FIELDS = new Set([
    "strict_accuracy",
    "macro_f1_excluding_other",
    "precision",
    "recall",
    "f1",
    "practical_f1",
    "supported_precision",
    "supported_recall",
    "supported_practical_precision",
    "supported_practical_recall",
    "supported_practical_f1",
  ]);
  const BENCHMARK_TREND_SKIP_FIELDS = new Set([
    "run_timestamp",
    "artifact_dir",
    "artifact_dir_basename",
    "report_path",
    "run_dir",
    "file_name",
    "source_file",
    "source_file_basename",
    "source_label",
    "importer_name",
    "run_config_hash",
    "run_config_summary",
    "per_label_json",
    "per_label",
  ]);
  const ANALYSIS_FIELD_PREFERRED = [
    "source_label",
    "source_file_basename",
    "importer_name",
    "ai_model",
    "ai_effort",
    "ai_assistance_profile",
    "quality_per_million_tokens",
    "all_token_use",
    "run_config.llm_recipe_pipeline",
    "run_config.epub_extractor",
    "run_config.epub_extractor_effective",
    "run_config.epub_unstructured_preprocess_mode",
    "run_config.epub_unstructured_skip_headers_footers",
    "run_config.codex_farm_reasoning_effort",
    "run_config.codex_farm_model",
  ];
  const COMPARE_CONTROL_DEFAULT_OUTCOME_FIELD = "strict_accuracy";
  const COMPARE_CONTROL_VIEW_MODES = new Set(["discover", "raw", "controlled"]);
  const COMPARE_CONTROL_CHART_TYPES = new Set(["scatter", "bar"]);
  const COMPARE_CONTROL_DEFAULT_CHART_TYPE = "scatter";
  const COMPARE_CONTROL_CHART_LAYOUTS = new Set(["stacked", "side_by_side", "combined"]);
  const COMPARE_CONTROL_DEFAULT_CHART_LAYOUT = "stacked";
  const COMPARE_CONTROL_COMBINED_AXIS_MODES = new Set(["single", "dual"]);
  const COMPARE_CONTROL_DEFAULT_COMBINED_AXIS_MODE = "single";
  const COMPARE_CONTROL_BAR_POINT_COLORS = [
    "rgba(143, 166, 186, 0.82)",
    "rgba(181, 194, 171, 0.82)",
    "rgba(199, 183, 203, 0.82)",
    "rgba(222, 198, 166, 0.82)",
    "rgba(168, 193, 198, 0.82)",
    "rgba(210, 186, 186, 0.82)",
    "rgba(190, 201, 215, 0.82)",
    "rgba(204, 201, 173, 0.82)",
  ];
  const COMPARE_CONTROL_OUTCOME_PREFERRED = [
    "strict_accuracy",
    "macro_f1_excluding_other",
    "precision",
    "recall",
    "f1",
    "practical_f1",
    "supported_practical_f1",
    "conversion_seconds_per_recipe",
    "all_token_use_per_recipe",
  ];
  const COMPARE_CONTROL_FIELD_SKIP = new Set([
    "artifact_dir",
    "artifact_dir_basename",
    "run_dir",
    "report_path",
    "run_config_summary",
    "run_config_hash",
    "per_label_json",
    "per_label",
  ]);
  const COMPARE_CONTROL_SECONDARY_METRIC_PREFERRED = [
    "benchmark_total_seconds",
    "benchmark_prediction_seconds",
    "benchmark_evaluation_seconds",
    "all_token_use",
    "quality_per_million_tokens",
    "tokens_total",
    "tokens_input",
    "tokens_output",
    "prompt_tokens",
    "completion_tokens",
    "total_tokens",
    "cost_usd",
    "benchmark_cost_usd",
    "run_cost_usd",
  ];
  const COMPARE_CONTROL_SECONDARY_FIELD_PATTERN = /(token|runtime|second|latency|cost|usd|price)/i;
  const COMPARE_CONTROL_SECONDARY_MAX_FIELDS = 4;
  const COMPARE_CONTROL_WARNING_ROW_COVERAGE_MIN = 0.6;
  const COMPARE_CONTROL_WARNING_STRATA_COVERAGE_MIN = 0.6;
  const COMPARE_CONTROL_WARNING_MIN_ROWS = 20;
  const COMPARE_CONTROL_WARNING_MIN_STRATA = 3;
  const COMPARE_CONTROL_DISCOVERY_DEFAULT_MAX_CARDS = 10;
  const COMPARE_CONTROL_DISCOVERY_MAX_CARDS = 40;
  const COMPARE_CONTROL_DISCOVERY_PREFER_FIELD_BOOST = 1.25;
  const COMPARE_CONTROL_DISCOVERY_DEMOTE_FACTOR = 0.2;
  const TABLE_COLLAPSE_DEFAULT_ROWS = {
    "recent-runs": 8,
    "file-trend-table": 8,
    "benchmark-table": 12,
  };
  const THROUGHPUT_SCALE_NOTES = {
    raw: "Raw sec/recipe values.",
    clamp95: "Values above the 95th percentile are clamped to keep day-to-day runs readable.",
    log: "Log scale (log10(sec/recipe + 1)) keeps large spikes visible without flattening small runs.",
  };
  const tableCollapsedState = Object.create(null);
  const DASHBOARD_UI_STATE_VERSION = 1;
  const DASHBOARD_UI_STATE_STORAGE_KEY = "cookimport.stats_dashboard.ui_state.v1";
  const DASHBOARD_UI_STATE_SERVER_PATH = "assets/dashboard_ui_state.json";
  const DASHBOARD_UI_STATE_SYNC_INTERVAL_MS = 3000;
  let dashboardUiStateLoadAttempted = false;
  let dashboardUiProgramStateLoadAttempted = false;
  let dashboardUiProgramStoreAvailable = false;
  let dashboardUiProgramSyncInFlight = false;
  let dashboardUiProgramSyncTimer = null;
  let dashboardUiStorageResolved = false;
  let dashboardUiStorage = null;
  let dashboardUiStateSavedAtMs = -1;
  let dashboardUiStatePersistSuppressed = false;

  function dashboardUiStorageHandle() {
    if (dashboardUiStorageResolved) return dashboardUiStorage;
    dashboardUiStorageResolved = true;
    if (typeof window === "undefined") return null;
    try {
      const storage = window.localStorage;
      if (!storage) return null;
      const probeKey = "__cookimport_dashboard_probe__";
      storage.setItem(probeKey, "1");
      storage.removeItem(probeKey);
      dashboardUiStorage = storage;
      return dashboardUiStorage;
    } catch (error) {
      dashboardUiStorage = null;
      return null;
    }
  }

  function persistDashboardUiStateToBrowserStorage(payload) {
    if (!payload || typeof payload !== "object" || Array.isArray(payload)) return;
    try {
      const storage = dashboardUiStorageHandle();
      if (storage) {
        storage.setItem(DASHBOARD_UI_STATE_STORAGE_KEY, JSON.stringify(payload));
      }
    } catch (error) {
      // Ignore storage failures (private mode, quota, sandboxed contexts).
    }
  }

  function normalizeDashboardColumnWidth(value) {
    const width = Number(value);
    if (!Number.isFinite(width) || width <= 0) return null;
    return Math.max(
      DASHBOARD_TABLE_COLUMN_MIN_WIDTH,
      Math.min(DASHBOARD_TABLE_COLUMN_MAX_WIDTH, width)
    );
  }

  function sanitizeColumnWidthsMap(rawMap) {
    if (!rawMap || typeof rawMap !== "object" || Array.isArray(rawMap)) {
      return Object.create(null);
    }
    const next = Object.create(null);
    Object.keys(rawMap).forEach(columnKey => {
      const key = String(columnKey || "").trim();
      if (!key) return;
      const width = normalizeDashboardColumnWidth(rawMap[columnKey]);
      if (width == null) return;
      next[key] = width;
    });
    return next;
  }

  function sanitizeDashboardTableColumnWidths(rawTableWidths) {
    if (!rawTableWidths || typeof rawTableWidths !== "object" || Array.isArray(rawTableWidths)) {
      return Object.create(null);
    }
    const next = Object.create(null);
    Object.keys(rawTableWidths).forEach(tableKey => {
      const key = String(tableKey || "").trim();
      if (!key) return;
      const columnWidths = sanitizeColumnWidthsMap(rawTableWidths[tableKey]);
      if (!Object.keys(columnWidths).length) return;
      next[key] = columnWidths;
    });
    return next;
  }

  function dashboardTableColumnWidth(tableKey, columnKey) {
    const table = String(tableKey || "").trim();
    const column = String(columnKey || "").trim();
    if (!table || !column) return null;
    const rawMap = dashboardTableColumnWidths[table];
    if (!rawMap || typeof rawMap !== "object" || Array.isArray(rawMap)) return null;
    return normalizeDashboardColumnWidth(rawMap[column]);
  }

  function setDashboardTableColumnWidth(tableKey, columnKey, width) {
    const table = String(tableKey || "").trim();
    const column = String(columnKey || "").trim();
    const nextWidth = normalizeDashboardColumnWidth(width);
    if (!table || !column || nextWidth == null) return;
    let rawMap = dashboardTableColumnWidths[table];
    if (!rawMap || typeof rawMap !== "object" || Array.isArray(rawMap)) {
      rawMap = Object.create(null);
      dashboardTableColumnWidths[table] = rawMap;
    }
    rawMap[column] = nextWidth;
  }

  function clearDashboardTableColumnWidths(tableKey) {
    const table = String(tableKey || "").trim();
    if (!table) return;
    delete dashboardTableColumnWidths[table];
  }

  function normalizePreviousRunsColumnFilterMode(value) {
    const key = String(value || "and").trim().toLowerCase();
    return key === "or" ? "or" : "and";
  }

  function normalizePreviousRunsColumnFilterGlobalMode(value) {
    return normalizePreviousRunsColumnFilterMode(value);
  }

  function normalizePerLabelRollingWindowSize(value) {
    const parsed = Number.parseInt(String(value == null ? "" : value).trim(), 10);
    if (!Number.isFinite(parsed)) return 10;
    return Math.max(PER_LABEL_ROLLING_WINDOW_MIN, Math.min(PER_LABEL_ROLLING_WINDOW_MAX, parsed));
  }

  function normalizePerLabelComparisonMode(value) {
    const key = String(value || "delta").trim().toLowerCase();
    return key === "point_value" ? "point_value" : "delta";
  }

  function normalizePerLabelRunGroupKey(value) {
    const key = String(value == null ? "" : value).trim();
    if (!key) return PER_LABEL_RUN_GROUP_DEFAULT_KEY;
    if (key === PER_LABEL_RUN_GROUP_DEFAULT_KEY) return PER_LABEL_RUN_GROUP_DEFAULT_KEY;
    return key;
  }

  function normalizeBenchmarkTrendFieldList(values, options) {
    const opts = options && typeof options === "object" && !Array.isArray(options)
      ? options
      : Object.create(null);
    const allowEmpty = Boolean(opts.allow_empty);
    const availableRaw = Array.isArray(opts.available_fields)
      ? opts.available_fields
      : benchmarkTrendFieldOptions;
    const available = uniqueStringList(availableRaw);
    const availableSet = new Set(available);
    const fromExplicitValues = Array.isArray(values);
    const seed = fromExplicitValues ? values : BENCHMARK_TREND_DEFAULT_FIELDS;
    const normalized = [];
    const seen = new Set();
    seed.forEach(fieldName => {
      const key = String(fieldName || "").trim();
      if (!key || seen.has(key)) return;
      if (availableSet.size && !availableSet.has(key)) return;
      seen.add(key);
      normalized.push(key);
    });
    if (normalized.length) return normalized;
    if (allowEmpty && fromExplicitValues) return [];

    const fallback = [];
    const fallbackSeen = new Set();
    BENCHMARK_TREND_DEFAULT_FIELDS.forEach(fieldName => {
      if (!fieldName || fallbackSeen.has(fieldName)) return;
      if (availableSet.size && !availableSet.has(fieldName)) return;
      fallbackSeen.add(fieldName);
      fallback.push(fieldName);
    });
    if (!fallback.length && available.length) {
      fallback.push(available[0]);
    }
    return fallback;
  }

  function normalizeCompareControlViewMode(value) {
    const key = String(value || "discover").trim().toLowerCase();
    return COMPARE_CONTROL_VIEW_MODES.has(key) ? key : "discover";
  }

  function normalizeCompareControlChartType(value) {
    const key = String(value || COMPARE_CONTROL_DEFAULT_CHART_TYPE).trim().toLowerCase();
    return COMPARE_CONTROL_CHART_TYPES.has(key) ? key : COMPARE_CONTROL_DEFAULT_CHART_TYPE;
  }

  function normalizeCompareControlXAxisMode(value) {
    const key = String(value || "date").trim().toLowerCase();
    return key === "per_run" ? "per_run" : "date";
  }

  function normalizeCompareControlChartLayout(value) {
    const key = String(value || COMPARE_CONTROL_DEFAULT_CHART_LAYOUT).trim().toLowerCase();
    return COMPARE_CONTROL_CHART_LAYOUTS.has(key)
      ? key
      : COMPARE_CONTROL_DEFAULT_CHART_LAYOUT;
  }

  function normalizeCompareControlCombinedAxisMode(value) {
    const key = String(value || COMPARE_CONTROL_DEFAULT_COMBINED_AXIS_MODE).trim().toLowerCase();
    return COMPARE_CONTROL_COMBINED_AXIS_MODES.has(key)
      ? key
      : COMPARE_CONTROL_DEFAULT_COMBINED_AXIS_MODE;
  }

  function normalizeCompareControlDiscoveryPreferences(rawPrefs) {
    const source = rawPrefs && typeof rawPrefs === "object" && !Array.isArray(rawPrefs)
      ? rawPrefs
      : Object.create(null);
    const maxCardsRaw = Number.parseInt(String(source.max_cards == null ? "" : source.max_cards).trim(), 10);
    const maxCards = Number.isFinite(maxCardsRaw)
      ? Math.max(1, Math.min(COMPARE_CONTROL_DISCOVERY_MAX_CARDS, maxCardsRaw))
      : COMPARE_CONTROL_DISCOVERY_DEFAULT_MAX_CARDS;
    return {
      exclude_fields: uniqueStringList(source.exclude_fields),
      prefer_fields: uniqueStringList(source.prefer_fields),
      demote_patterns: uniqueStringList(source.demote_patterns),
      max_cards: maxCards,
    };
  }

  function uniqueStringList(values) {
    const seen = new Set();
    const ordered = [];
    (Array.isArray(values) ? values : []).forEach(value => {
      const key = String(value || "").trim();
      if (!key || seen.has(key)) return;
      seen.add(key);
      ordered.push(key);
    });
    return ordered;
  }

  function normalizeCompareControlState(rawState) {
    const source = rawState && typeof rawState === "object" && !Array.isArray(rawState)
      ? rawState
      : Object.create(null);
    const base = compareControlDefaultState();
    return {
      outcome_field: String(source.outcome_field || base.outcome_field).trim() || base.outcome_field,
      compare_field: String(source.compare_field || "").trim(),
      chart_type: normalizeCompareControlChartType(source.chart_type),
      x_axis_mode: normalizeCompareControlXAxisMode(source.x_axis_mode),
      hold_constant_fields: uniqueStringList(source.hold_constant_fields),
      split_field: String(source.split_field || "").trim(),
      view_mode: normalizeCompareControlViewMode(source.view_mode),
      selected_groups: uniqueStringList(source.selected_groups),
      discovery_preferences: normalizeCompareControlDiscoveryPreferences(
        source.discovery_preferences
      ),
    };
  }

  function compareControlStateForSet(setKey) {
    return setKey === "secondary" ? compareControlSecondaryState : compareControlState;
  }

  function setCompareControlStateForSet(setKey, nextState) {
    const normalized = normalizeCompareControlState(nextState);
    if (setKey === "secondary") {
      compareControlSecondaryState = normalized;
      return compareControlSecondaryState;
    }
    compareControlState = normalized;
    return compareControlState;
  }

  function compareControlStatusForSet(setKey) {
    if (setKey === "secondary") {
      return {
        message: compareControlSecondaryStatusMessage,
        is_error: compareControlSecondaryStatusIsError,
      };
    }
    return {
      message: compareControlStatusMessage,
      is_error: compareControlStatusIsError,
    };
  }

  function setCompareControlStatusForSet(setKey, message, isError) {
    const text = String(message || "");
    const errorFlag = Boolean(isError);
    if (setKey === "secondary") {
      compareControlSecondaryStatusMessage = text;
      compareControlSecondaryStatusIsError = errorFlag;
      return;
    }
    compareControlStatusMessage = text;
    compareControlStatusIsError = errorFlag;
  }

  function clearCompareControlStatusForSet(setKey) {
    setCompareControlStatusForSet(setKey, "", false);
  }

  function activateCompareControlChartForSet(setKey) {
    if (setKey === "secondary") {
      compareControlSecondaryChartActivated = true;
      return;
    }
    compareControlChartActivated = true;
  }

  function deactivateCompareControlChartForSet(setKey) {
    if (setKey === "secondary") {
      compareControlSecondaryChartActivated = false;
      return;
    }
    compareControlChartActivated = false;
  }

  function compareControlChartActivatedForSet(setKey) {
    return setKey === "secondary"
      ? Boolean(compareControlSecondaryChartActivated)
      : Boolean(compareControlChartActivated);
  }

  function activateCompareControlChart() {
    activateCompareControlChartForSet("primary");
  }

  function deactivateCompareControlChart() {
    deactivateCompareControlChartForSet("primary");
  }

  function shouldAutoActivateCompareControlChart(state, compareInfo) {
    const activeState = state && typeof state === "object"
      ? state
      : compareControlDefaultState();
    if (!activeState.compare_field) return false;
    if (activeState.view_mode === "discover") return false;
    if (!compareInfo || typeof compareInfo !== "object") return false;
    return true;
  }

  function resetCompareControlState(setKey) {
    const key = setKey === "secondary" ? "secondary" : "primary";
    setCompareControlStateForSet(key, compareControlDefaultState());
    deactivateCompareControlChartForSet(key);
    setCompareControlStatusForSet(
      key,
      key === "secondary"
        ? "Set 2 reset to default state."
        : "Compare & Control reset to default state.",
      false
    );
  }

  function setCompareControlSecondSetEnabled(enabled) {
    compareControlSecondSetEnabled = Boolean(enabled);
    if (!compareControlSecondSetEnabled) {
      compareControlSecondaryState = compareControlDefaultState();
      deactivateCompareControlChartForSet("secondary");
      clearCompareControlStatusForSet("secondary");
      if (compareControlChartLayout !== "stacked") {
        compareControlChartLayout = "stacked";
      }
      return;
    }
    if (compareControlChartLayout === "stacked") {
      compareControlChartLayout = "side_by_side";
    }
  }

  function compareControlChartLayoutAllowsDualSets(layout) {
    return normalizeCompareControlChartLayout(layout) !== "combined";
  }

  function syncCompareControlLayoutChrome() {
    const section = document.getElementById("compare-control-analysis-section");
    const secondaryColumn = document.getElementById("compare-control-column-secondary");
    const secondaryPanel = document.getElementById("compare-control-panel-secondary");
    const secondaryResults = document.getElementById("compare-control-results-card-secondary");
    const chartLayoutSelect = document.getElementById("compare-control-chart-layout");
    const axisModeSelect = document.getElementById("compare-control-combined-axis-mode");
    const toggleBtn = document.getElementById("compare-control-toggle-second-set");
    const primaryChartCard = document.getElementById("compare-control-chart-card-primary");
    const secondaryChartCard = document.getElementById("compare-control-chart-card-secondary");
    const combinedChartCard = document.getElementById("compare-control-chart-card-combined");

    const secondEnabled = Boolean(compareControlSecondSetEnabled);
    let layout = normalizeCompareControlChartLayout(compareControlChartLayout);
    if (secondEnabled && layout !== "combined") {
      layout = "side_by_side";
      compareControlChartLayout = layout;
    }
    compareControlChartLayout = layout;
    compareControlCombinedAxisMode = normalizeCompareControlCombinedAxisMode(
      compareControlCombinedAxisMode
    );

    if (section) {
      section.classList.toggle("compare-control-dual-enabled", secondEnabled);
    }
    if (secondaryPanel) {
      secondaryPanel.hidden = !secondEnabled;
    }
    if (secondaryResults) {
      secondaryResults.hidden = !secondEnabled;
    }
    if (secondaryColumn) {
      secondaryColumn.hidden = !secondEnabled;
    }

    if (toggleBtn) {
      toggleBtn.textContent = secondEnabled
        ? "Collapse set 2"
        : "Expand set 2 from right";
      toggleBtn.setAttribute(
        "aria-label",
        secondEnabled
          ? "Collapse compare control set 2"
          : "Expand compare control set 2 from right"
      );
    }

    if (chartLayoutSelect) {
      chartLayoutSelect.value = secondEnabled ? layout : "stacked";
      Array.from(chartLayoutSelect.options).forEach(option => {
        const value = String(option.value || "").trim();
        if (!value) {
          option.disabled = false;
          return;
        }
        if (value === "stacked") {
          option.disabled = true;
          return;
        }
        option.disabled = !secondEnabled;
      });
      if (!secondEnabled) {
        chartLayoutSelect.disabled = true;
      } else {
        chartLayoutSelect.disabled = false;
      }
    }
    if (axisModeSelect) {
      axisModeSelect.value = compareControlCombinedAxisMode;
      const showAxisMode = secondEnabled && layout === "combined";
      axisModeSelect.disabled = !showAxisMode;
      axisModeSelect.hidden = !showAxisMode;
      const axisLabel = document.querySelector(
        'label[for="compare-control-combined-axis-mode"]'
      );
      if (axisLabel) {
        axisLabel.hidden = !showAxisMode;
      }
    }

    if (primaryChartCard) {
      primaryChartCard.hidden = Boolean(secondEnabled && layout === "combined");
    }
    if (secondaryChartCard) {
      const showSecondaryChart = secondEnabled && compareControlChartLayoutAllowsDualSets(layout);
      secondaryChartCard.hidden = !showSecondaryChart;
    }
    if (combinedChartCard) {
      combinedChartCard.hidden = !(secondEnabled && layout === "combined");
    }
  }

  function sanitizePreviousRunsPresetName(rawName) {
    const text = String(rawName || "").trim().replace(/\\s+/g, " ");
    if (!text) return "";
    return text.slice(0, PREVIOUS_RUNS_PRESET_NAME_MAX);
  }

  function sanitizePreviousRunsPresetState(rawPreset) {
    if (!rawPreset || typeof rawPreset !== "object" || Array.isArray(rawPreset)) {
      return null;
    }
    const visibleColumns = Array.isArray(rawPreset.visible_columns)
      ? rawPreset.visible_columns
        .map(fieldName => String(fieldName || "").trim())
        .filter(Boolean)
      : [];
    const columnFilters = Object.create(null);
    const columnFilterModes = Object.create(null);
    const rawColumnFilters = rawPreset.column_filters;
    if (rawColumnFilters && typeof rawColumnFilters === "object" && !Array.isArray(rawColumnFilters)) {
      Object.keys(rawColumnFilters).forEach(fieldName => {
        const key = String(fieldName || "").trim();
        if (!key) return;
        const normalized = normalizePreviousRunsColumnFilterList(rawColumnFilters[fieldName]);
        if (!normalized.length) return;
        columnFilters[key] = normalized;
      });
    }
    const rawColumnFilterModes = rawPreset.column_filter_modes;
    if (rawColumnFilterModes && typeof rawColumnFilterModes === "object" && !Array.isArray(rawColumnFilterModes)) {
      Object.keys(rawColumnFilterModes).forEach(fieldName => {
        const key = String(fieldName || "").trim();
        if (!key) return;
        if (!Object.prototype.hasOwnProperty.call(columnFilters, key)) return;
        columnFilterModes[key] = normalizePreviousRunsColumnFilterMode(rawColumnFilterModes[key]);
      });
    }
    const rawQuickFilters = rawPreset.quick_filters;
    const quickFilters = {
      exclude_ai_tests: false,
      official_full_golden_only: true,
    };
    if (rawQuickFilters && typeof rawQuickFilters === "object") {
      if (Object.prototype.hasOwnProperty.call(rawQuickFilters, "exclude_ai_tests")) {
        quickFilters.exclude_ai_tests = Boolean(rawQuickFilters.exclude_ai_tests);
      }
      if (Object.prototype.hasOwnProperty.call(rawQuickFilters, "official_full_golden_only")) {
        quickFilters.official_full_golden_only = Boolean(rawQuickFilters.official_full_golden_only);
      }
    }
    const rawSort = rawPreset.sort;
    const sort = {
      field: "run_timestamp",
      direction: "desc",
    };
    if (rawSort && typeof rawSort === "object" && !Array.isArray(rawSort)) {
      const sortField = String(rawSort.field || "").trim();
      if (sortField) sort.field = sortField;
      const sortDirection = String(rawSort.direction || "").toLowerCase();
      if (sortDirection === "asc" || sortDirection === "desc") {
        sort.direction = sortDirection;
      }
    }
    const columnFilterGlobalMode = Object.prototype.hasOwnProperty.call(rawPreset, "column_filter_global_mode")
      ? normalizePreviousRunsColumnFilterGlobalMode(rawPreset.column_filter_global_mode)
      : "and";
    return {
      visible_columns: visibleColumns,
      column_filters: columnFilters,
      column_filter_modes: columnFilterModes,
      column_filter_global_mode: columnFilterGlobalMode,
      quick_filters: quickFilters,
      column_widths: sanitizeColumnWidthsMap(rawPreset.column_widths),
      sort,
    };
  }

  function sanitizePreviousRunsPresetMap(rawPresets) {
    if (!rawPresets || typeof rawPresets !== "object" || Array.isArray(rawPresets)) {
      return Object.create(null);
    }
    const next = Object.create(null);
    Object.keys(rawPresets).forEach(rawName => {
      const name = sanitizePreviousRunsPresetName(rawName);
      if (!name) return;
      const preset = sanitizePreviousRunsPresetState(rawPresets[rawName]);
      if (!preset) return;
      next[name] = preset;
    });
    return next;
  }

  function dashboardUiStateSavedAtMsFromValue(rawValue) {
    const text = String(rawValue || "").trim();
    if (!text) return -1;
    const parsed = Date.parse(text);
    return Number.isFinite(parsed) ? parsed : -1;
  }

  function applyDashboardUiStatePayload(parsed, savedAtMs, options) {
    const opts = options && typeof options === "object" && !Array.isArray(options)
      ? options
      : Object.create(null);
    const preferIncoming = Boolean(opts.preferIncoming);
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) return false;
    const nextSavedAtMs = Number.isFinite(savedAtMs) ? savedAtMs : -1;
    if (
      !preferIncoming &&
      dashboardUiStateSavedAtMs >= 0 &&
      nextSavedAtMs >= 0 &&
      nextSavedAtMs <= dashboardUiStateSavedAtMs
    ) {
      return false;
    }
    if (!preferIncoming && dashboardUiStateSavedAtMs >= 0 && nextSavedAtMs < 0) return false;
    const version = Number(parsed.version || 0);
    if (version && version !== DASHBOARD_UI_STATE_VERSION) return false;
    dashboardTableColumnWidths = sanitizeDashboardTableColumnWidths(parsed.table_column_widths);
    previousRunsViewPresets = sanitizePreviousRunsPresetMap(parsed.previous_runs_presets);
    const previousRuns = parsed.previous_runs;
    if (!previousRuns || typeof previousRuns !== "object") {
      dashboardUiStateSavedAtMs = nextSavedAtMs >= 0 ? nextSavedAtMs : 0;
      return true;
    }

    if (Array.isArray(previousRuns.visible_columns)) {
      previousRunsVisibleColumns = previousRuns.visible_columns
        .map(fieldName => String(fieldName || "").trim())
        .filter(Boolean);
    }

    const rawColumnFilters = previousRuns.column_filters;
    if (rawColumnFilters && typeof rawColumnFilters === "object" && !Array.isArray(rawColumnFilters)) {
      const nextColumnFilters = Object.create(null);
      Object.keys(rawColumnFilters).forEach(fieldName => {
        const key = String(fieldName || "").trim();
        if (!key) return;
        const normalized = normalizePreviousRunsColumnFilterList(rawColumnFilters[fieldName]);
        if (!normalized.length) return;
        nextColumnFilters[key] = normalized;
      });
      previousRunsColumnFilters = nextColumnFilters;
    }
    const rawColumnFilterModes = previousRuns.column_filter_modes;
    if (rawColumnFilterModes && typeof rawColumnFilterModes === "object" && !Array.isArray(rawColumnFilterModes)) {
      const nextModes = Object.create(null);
      Object.keys(rawColumnFilterModes).forEach(fieldName => {
        const key = String(fieldName || "").trim();
        if (!key) return;
        if (!Object.prototype.hasOwnProperty.call(previousRunsColumnFilters, key)) return;
        nextModes[key] = normalizePreviousRunsColumnFilterMode(rawColumnFilterModes[fieldName]);
      });
      previousRunsColumnFilterModes = nextModes;
    }
    if (Object.prototype.hasOwnProperty.call(previousRuns, "column_filter_global_mode")) {
      previousRunsColumnFilterGlobalMode = normalizePreviousRunsColumnFilterGlobalMode(
        previousRuns.column_filter_global_mode
      );
    } else {
      previousRunsColumnFilterGlobalMode = "and";
    }

    const rawQuickFilters = previousRuns.quick_filters;
    if (rawQuickFilters && typeof rawQuickFilters === "object") {
      if (Object.prototype.hasOwnProperty.call(rawQuickFilters, "exclude_ai_tests")) {
        previousRunsQuickFilters.exclude_ai_tests = Boolean(rawQuickFilters.exclude_ai_tests);
      }
      if (Object.prototype.hasOwnProperty.call(rawQuickFilters, "official_full_golden_only")) {
        previousRunsQuickFilters.official_full_golden_only = Boolean(rawQuickFilters.official_full_golden_only);
      }
    }
    if (Object.prototype.hasOwnProperty.call(previousRuns, "per_label_rolling_window_size")) {
      perLabelRollingWindowSize = normalizePerLabelRollingWindowSize(
        previousRuns.per_label_rolling_window_size
      );
    }
    if (Object.prototype.hasOwnProperty.call(previousRuns, "per_label_comparison_mode")) {
      perLabelComparisonMode = normalizePerLabelComparisonMode(
        previousRuns.per_label_comparison_mode
      );
    }
    if (Object.prototype.hasOwnProperty.call(previousRuns, "per_label_run_group_key")) {
      perLabelRunGroupKey = normalizePerLabelRunGroupKey(
        previousRuns.per_label_run_group_key
      );
    }
    if (Object.prototype.hasOwnProperty.call(previousRuns, "trend_fields")) {
      benchmarkTrendSelectedFields = normalizeBenchmarkTrendFieldList(
        previousRuns.trend_fields,
        { allow_empty: true }
      );
    }

    const rawColumnWidths = previousRuns.column_widths;
    if (rawColumnWidths && typeof rawColumnWidths === "object" && !Array.isArray(rawColumnWidths)) {
      const nextColumnWidths = sanitizeColumnWidthsMap(rawColumnWidths);
      previousRunsColumnWidths = nextColumnWidths;
      Object.keys(nextColumnWidths).forEach(fieldName => {
        setDashboardTableColumnWidth("previous-runs-table", fieldName, nextColumnWidths[fieldName]);
      });
    } else {
      previousRunsColumnWidths = sanitizeColumnWidthsMap(
        dashboardTableColumnWidths["previous-runs-table"]
      );
    }

    const rawSort = previousRuns.sort;
    if (rawSort && typeof rawSort === "object" && !Array.isArray(rawSort)) {
      const sortField = String(rawSort.field || "").trim();
      if (sortField) {
        previousRunsSortField = sortField;
      }
      const sortDirection = String(rawSort.direction || "").toLowerCase();
      if (sortDirection === "asc" || sortDirection === "desc") {
        previousRunsSortDirection = sortDirection;
      }
    }

    if (Object.prototype.hasOwnProperty.call(previousRuns, "compare_control")) {
      const rawCompareControl = (
        previousRuns.compare_control &&
        typeof previousRuns.compare_control === "object" &&
        !Array.isArray(previousRuns.compare_control)
      )
        ? previousRuns.compare_control
        : Object.create(null);
      compareControlState = normalizeCompareControlState(rawCompareControl);
      compareControlSecondaryState = normalizeCompareControlState(rawCompareControl.second_set);
      compareControlSecondSetEnabled = Boolean(rawCompareControl.second_set_enabled);
      compareControlChartLayout = normalizeCompareControlChartLayout(
        rawCompareControl.chart_layout
      );
      compareControlCombinedAxisMode = normalizeCompareControlCombinedAxisMode(
        rawCompareControl.combined_axis_mode
      );
    } else {
      compareControlState = normalizeCompareControlState(compareControlState);
      compareControlSecondaryState = normalizeCompareControlState(compareControlSecondaryState);
      compareControlSecondSetEnabled = false;
      compareControlChartLayout = COMPARE_CONTROL_DEFAULT_CHART_LAYOUT;
      compareControlCombinedAxisMode = COMPARE_CONTROL_DEFAULT_COMBINED_AXIS_MODE;
    }
    if (!compareControlSecondSetEnabled) {
      compareControlChartLayout = COMPARE_CONTROL_DEFAULT_CHART_LAYOUT;
      compareControlSecondaryState = normalizeCompareControlState(compareControlDefaultState());
    }
    // Keep charts blank on load/restore until the user actively works in Compare & Control.
    deactivateCompareControlChartForSet("primary");
    deactivateCompareControlChartForSet("secondary");
    const selectedPreset = sanitizePreviousRunsPresetName(previousRuns.selected_preset);
    previousRunsSelectedPreset = Object.prototype.hasOwnProperty.call(previousRunsViewPresets, selectedPreset)
      ? selectedPreset
      : "";
    dashboardUiStateSavedAtMs = nextSavedAtMs >= 0 ? nextSavedAtMs : 0;
    return true;
  }

  function loadDashboardUiState() {
    if (dashboardUiStateLoadAttempted) return;
    dashboardUiStateLoadAttempted = true;
    const storage = dashboardUiStorageHandle();
    if (!storage) return;
    let parsed = null;
    try {
      parsed = JSON.parse(storage.getItem(DASHBOARD_UI_STATE_STORAGE_KEY) || "null");
    } catch (error) {
      return;
    }
    if (!parsed || typeof parsed !== "object") return;
    applyDashboardUiStatePayload(
      parsed,
      dashboardUiStateSavedAtMsFromValue(parsed.saved_at)
    );
  }

  function loadDashboardUiStateFromProgramStore() {
    const options = arguments.length > 0 ? arguments[0] : null;
    const force = Boolean(options && options.force);
    const preferIncoming = Boolean(options && options.preferIncoming);
    if (!force && dashboardUiProgramStateLoadAttempted) return Promise.resolve(false);
    if (!force) {
      dashboardUiProgramStateLoadAttempted = true;
    }
    if (dashboardUiProgramSyncInFlight) return Promise.resolve(false);
    if (typeof fetch !== "function") return Promise.resolve(false);
    dashboardUiProgramSyncInFlight = true;
    return fetch(DASHBOARD_UI_STATE_SERVER_PATH, { cache: "no-store" })
      .then(response => {
        if (!response.ok) throw new Error("HTTP " + response.status);
        return response.json();
      })
      .then(parsed => {
        dashboardUiProgramStoreAvailable = true;
        const applied = applyDashboardUiStatePayload(
          parsed,
          dashboardUiStateSavedAtMsFromValue(parsed && parsed.saved_at),
          { preferIncoming }
        );
        if (applied) {
          persistDashboardUiStateToBrowserStorage(parsed);
        }
        return applied;
      })
      .catch(() => false)
      .finally(() => {
        dashboardUiProgramSyncInFlight = false;
      });
  }

  function startDashboardUiProgramSyncLoop() {
    if (typeof window === "undefined") return;
    if (dashboardUiProgramSyncTimer != null) return;
    dashboardUiProgramSyncTimer = window.setInterval(() => {
      loadDashboardUiStateFromProgramStore({ force: true }).then(applied => {
        if (!applied) return;
        const previous = dashboardUiStatePersistSuppressed;
        dashboardUiStatePersistSuppressed = true;
        try {
          setupPreviousRunsQuickFilters();
          setupPreviousRunsGlobalFilterModeControl();
          setupCompareControlControls();
          setupPerLabelControls();
          setupBenchmarkTrendFieldControls();
          renderPreviousRunsColumnEditor();
          renderAll();
        } finally {
          dashboardUiStatePersistSuppressed = previous;
        }
      });
    }, DASHBOARD_UI_STATE_SYNC_INTERVAL_MS);
  }

  function buildDashboardUiStatePayload() {
    const savedAt = new Date().toISOString();
    dashboardUiStateSavedAtMs = dashboardUiStateSavedAtMsFromValue(savedAt);
    const visibleColumns = previousRunsVisibleColumns
      .map(fieldName => String(fieldName || "").trim())
      .filter(Boolean);
    const columnFilters = Object.create(null);
    const columnFilterModes = Object.create(null);
    Object.keys(previousRunsColumnFilters).forEach(fieldName => {
      const clauses = previousRunsColumnFilterClauses(fieldName);
      if (!clauses.length) return;
      columnFilters[fieldName] = clauses.map(clause => ({
        operator: clause.operator,
        value: clause.value,
      }));
      columnFilterModes[fieldName] = previousRunsColumnFilterMode(fieldName);
    });
    const columnWidths = Object.create(null);
    Object.keys(previousRunsColumnWidths).forEach(fieldName => {
      const key = String(fieldName || "").trim();
      if (!key) return;
      const width = normalizeDashboardColumnWidth(previousRunsColumnWidths[fieldName]);
      if (width == null) return;
      columnWidths[key] = width;
      setDashboardTableColumnWidth("previous-runs-table", key, width);
    });
    const tableColumnWidths = sanitizeDashboardTableColumnWidths(dashboardTableColumnWidths);
    if (Object.keys(columnWidths).length) {
      tableColumnWidths["previous-runs-table"] = Object.assign(Object.create(null), columnWidths);
    } else {
      delete tableColumnWidths["previous-runs-table"];
    }
    const previousRunsPresets = Object.create(null);
    Object.keys(previousRunsViewPresets).forEach(rawName => {
      const name = sanitizePreviousRunsPresetName(rawName);
      if (!name) return;
      const preset = sanitizePreviousRunsPresetState(previousRunsViewPresets[rawName]);
      if (!preset) return;
      previousRunsPresets[name] = preset;
    });
    const selectedPreset = sanitizePreviousRunsPresetName(previousRunsSelectedPreset);
    const selectedPresetName = Object.prototype.hasOwnProperty.call(previousRunsPresets, selectedPreset)
      ? selectedPreset
      : "";
    const payload = {
      version: DASHBOARD_UI_STATE_VERSION,
      previous_runs: {
        visible_columns: visibleColumns,
        column_filters: columnFilters,
        column_filter_modes: columnFilterModes,
        column_filter_global_mode: normalizePreviousRunsColumnFilterGlobalMode(
          previousRunsColumnFilterGlobalMode
        ),
        quick_filters: {
          exclude_ai_tests: Boolean(previousRunsQuickFilters.exclude_ai_tests),
          official_full_golden_only: Boolean(previousRunsQuickFilters.official_full_golden_only),
        },
        per_label_rolling_window_size: normalizePerLabelRollingWindowSize(perLabelRollingWindowSize),
        per_label_comparison_mode: normalizePerLabelComparisonMode(perLabelComparisonMode),
        per_label_run_group_key: normalizePerLabelRunGroupKey(perLabelRunGroupKey),
        trend_fields: normalizeBenchmarkTrendFieldList(
          benchmarkTrendSelectedFields,
          { allow_empty: true }
        ),
        column_widths: columnWidths,
        sort: {
          field: String(previousRunsSortField || "run_timestamp"),
          direction: previousRunsSortDirection === "asc" ? "asc" : "desc",
        },
        compare_control: {
          ...normalizeCompareControlState(compareControlState),
          second_set_enabled: Boolean(compareControlSecondSetEnabled),
          second_set: normalizeCompareControlState(compareControlSecondaryState),
          chart_layout: normalizeCompareControlChartLayout(compareControlChartLayout),
          combined_axis_mode: normalizeCompareControlCombinedAxisMode(
            compareControlCombinedAxisMode
          ),
        },
        selected_preset: selectedPresetName,
      },
      previous_runs_presets: previousRunsPresets,
      table_column_widths: tableColumnWidths,
      saved_at: savedAt,
    };
    return payload;
  }

  function persistDashboardUiStateToProgramStore(payload) {
    if (!payload || typeof payload !== "object" || Array.isArray(payload)) return;
    if (typeof fetch !== "function") return;
    try {
      fetch(DASHBOARD_UI_STATE_SERVER_PATH, {
        method: "PUT",
        cache: "no-store",
        keepalive: true,
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify(payload),
      }).catch(() => {
        // Ignore program-side sync failures when dashboard is opened as plain static HTML.
      });
    } catch (error) {
      // Ignore program-side sync failures when dashboard is opened as plain static HTML.
    }
  }

  function persistDashboardUiState() {
    if (dashboardUiStatePersistSuppressed) return;
    const payload = buildDashboardUiStatePayload();
    persistDashboardUiStateToBrowserStorage(payload);
    persistDashboardUiStateToProgramStore(payload);
  }

  // ---- Load data ----
  function showLoadError(msg) {
    document.querySelector("main").innerHTML =
      '<p class="empty-note">' + msg + "</p>";
  }

  function loadInlineData() {
    const inline = document.getElementById("dashboard-data-inline");
    if (!inline) return null;
    const raw = (inline.textContent || "").trim();
    if (!raw) return null;
    return JSON.parse(raw);
  }

  function loadFromFetch(previousError) {
    fetch("assets/dashboard_data.json", { cache: "no-store" })
      .then(r => {
        if (!r.ok) throw new Error("HTTP " + r.status);
        return r.json();
      })
      .then(d => { DATA = d; init(); })
      .catch(e => {
        if (previousError) {
          showLoadError("Failed to load dashboard data: " + previousError + "; " + e);
          return;
        }
        showLoadError("Failed to load dashboard_data.json: " + e);
      });
  }

  try {
    const inlineData = loadInlineData();
    if (inlineData) {
      DATA = inlineData;
      init();
    } else {
      loadFromFetch(null);
    }
  } catch (e) {
    loadFromFetch(e);
  }

  function init() {
    applyHighchartsGlobalDefaults();
    loadDashboardUiState();
    loadDashboardUiStateFromProgramStore({ preferIncoming: true })
      .then(() => {
        setupMetricHoverTooltips();
        renderHeader();
        setupPreviousRunsFilters();
        renderAll();
        setupDashboardResizeHandlers();
        startDashboardUiProgramSyncLoop();
      });
  }

  function applyHighchartsGlobalDefaults() {
    if (
      typeof window === "undefined" ||
      !window.Highcharts ||
      typeof window.Highcharts.setOptions !== "function"
    ) {
      return;
    }
    window.Highcharts.setOptions({
      time: {
        useUTC: false,
      },
      chart: {
        zooming: {
          mouseWheel: {
            enabled: HIGHCHARTS_MOUSE_WHEEL_ZOOM_ENABLED,
          },
        },
      },
    });
  }

  function normalizeMetricTooltipKey(value) {
    return String(value || "").trim().toLowerCase();
  }

  function compressMetricTooltipText(text) {
    return String(text || "")
      .replace(/\\s+/g, " ")
      .trim();
  }

  function escapeRegexPattern(text) {
    return String(text || "").replace(/[.*+?^${}()|[\\]\\\\]/g, "\\\\$&");
  }

  function registerMetricTooltipDescription(map, key, text) {
    const normalizedKey = normalizeMetricTooltipKey(key);
    const normalizedText = compressMetricTooltipText(text);
    if (!normalizedKey || !normalizedText) return;
    map[normalizedKey] = normalizedText;
  }

  function normalizeMetricTooltipLookupText(text) {
    return String(text || "")
      .toLowerCase()
      .replace(/&/g, " and ")
      .replace(/[_.\\/]+/g, " ")
      .replace(/[^a-z0-9+%\\s-]+/g, " ")
      .replace(/\\s+/g, " ")
      .trim();
  }

  function registerMetricTooltipAlias(aliasMap, alias, key) {
    const normalizedAlias = normalizeMetricTooltipLookupText(alias);
    const normalizedKey = normalizeMetricTooltipKey(key);
    if (!normalizedAlias || !normalizedKey) return;
    if (Object.prototype.hasOwnProperty.call(aliasMap, normalizedAlias)) return;
    aliasMap[normalizedAlias] = normalizedKey;
  }

  function buildMetricTooltipDescriptions() {
    const map = Object.create(null);
    Object.keys(PREVIOUS_RUNS_COLUMN_META).forEach(fieldName => {
      const meta = PREVIOUS_RUNS_COLUMN_META[fieldName];
      if (!meta) return;
      registerMetricTooltipDescription(map, fieldName, meta.title || "");
      registerMetricTooltipDescription(map, meta.label || "", meta.title || "");
    });

    document
      .querySelectorAll("#previous-runs-section .metric-help-list li")
      .forEach(item => {
        if (!(item instanceof HTMLElement)) return;
        const code = item.querySelector("code");
        if (!(code instanceof HTMLElement)) return;
        const key = compressMetricTooltipText(code.textContent || "");
        if (!key) return;
        const fullText = compressMetricTooltipText(item.textContent || "");
        const keyPrefix = new RegExp("^" + escapeRegexPattern(key) + "\\\\s*:\\\\s*", "i");
        const description = fullText.replace(keyPrefix, "");
        registerMetricTooltipDescription(map, key, description);
      });

    if (!map.gold && map.gold_total) map.gold = map.gold_total;
    if (!map.matched && map.gold_matched) map.matched = map.gold_matched;
    if (!map.pred && map.pred_total) map.pred = map.pred_total;
    if (!map["token use"] && map.all_token_use) map["token use"] = map.all_token_use;
    if (!map.rows && map.task_count) map.rows = map.task_count;
    if (!map.model && map.ai_model) map.model = map.ai_model;
    if (!map["thinking effort"] && map.ai_effort) map["thinking effort"] = map.ai_effort;
    return map;
  }

  function buildMetricTooltipAliasCatalog(descriptions) {
    const aliases = Object.create(null);
    Object.keys(descriptions || {}).forEach(rawKey => {
      const key = normalizeMetricTooltipKey(rawKey);
      if (!key) return;
      registerMetricTooltipAlias(aliases, key, key);
      registerMetricTooltipAlias(aliases, key.replace(/_/g, " "), key);
      registerMetricTooltipAlias(aliases, key.replace(/\\./g, " "), key);
      registerMetricTooltipAlias(aliases, key.replace(/[_.]+/g, " "), key);
      if (key.startsWith("run_config.")) {
        registerMetricTooltipAlias(aliases, key.slice("run_config.".length), key);
      }
    });
    Object.keys(PREVIOUS_RUNS_COLUMN_META).forEach(fieldName => {
      const meta = PREVIOUS_RUNS_COLUMN_META[fieldName];
      const key = normalizeMetricTooltipKey(fieldName);
      if (!meta || !key) return;
      registerMetricTooltipAlias(aliases, fieldName, key);
      registerMetricTooltipAlias(aliases, meta.label || "", key);
      registerMetricTooltipAlias(aliases, String(meta.label || "").replace(/[()]/g, " "), key);
    });
    [
      ["gold", "gold_total"],
      ["pred", "pred_total"],
      ["matched", "gold_matched"],
      ["quality metric", "strict_accuracy"],
      ["run precision", "precision"],
      ["run recall", "recall"],
      ["delta precision", "precision"],
      ["delta recall", "recall"],
      ["rows", "task_count"],
      ["model", "ai_model"],
      ["thinking effort", "ai_effort"],
    ].forEach(([alias, key]) => registerMetricTooltipAlias(aliases, alias, key));
    return aliases;
  }

  function metricTooltipAliasEntryList(aliasMap) {
    return Object.keys(aliasMap)
      .map(alias => ({
        alias,
        key: aliasMap[alias],
      }))
      .sort((left, right) => right.alias.length - left.alias.length);
  }

  function metricTooltipResolveKeyFromText(text) {
    const normalizedText = normalizeMetricTooltipLookupText(text);
    if (!normalizedText) return "";
    if (Object.prototype.hasOwnProperty.call(metricTooltipAliasesByText, normalizedText)) {
      return metricTooltipAliasesByText[normalizedText];
    }
    const padded = " " + normalizedText + " ";
    for (let idx = 0; idx < metricTooltipAliasEntries.length; idx += 1) {
      const entry = metricTooltipAliasEntries[idx];
      if (!entry || !entry.alias) continue;
      if (padded.includes(" " + entry.alias + " ")) {
        return entry.key;
      }
    }
    if (padded.includes(" precision ")) return "precision";
    if (padded.includes(" recall ")) return "recall";
    if (padded.includes(" practical f1 ")) return "practical_f1";
    if (padded.includes(" f1 ")) return "f1";
    if (padded.includes(" strict accuracy ")) return "strict_accuracy";
    if (padded.includes(" macro f1 excluding other ")) return "macro_f1_excluding_other";
    return "";
  }

  function metricTooltipTargetDataKey(target) {
    if (!(target instanceof Element)) return "";
    const dataset = target.dataset || {};
    return String(dataset.metricTooltipKey || "");
  }

  function metricTooltipTextForTarget(target) {
    if (!(target instanceof Element)) return "";
    const dataset = target.dataset || {};
    const key = normalizeMetricTooltipKey(metricTooltipTargetDataKey(target));
    if (!key) return "";
    if (Object.prototype.hasOwnProperty.call(metricTooltipDescriptions, key)) {
      return metricTooltipDescriptions[key];
    }
    if (key.startsWith("run_config.")) {
      return "Run-config field recorded in benchmark metadata for this run.";
    }
    const fallback = compressMetricTooltipText(dataset.metricTooltipFallback || "");
    if (fallback) return fallback;
    if (key === "task_count") {
      return "How many benchmark rows/tasks are represented in this grouped value.";
    }
    if (key) {
      const prettyKey = key.replace(/^run_config\\./, "run config ").replace(/[_.]+/g, " ").trim();
      if (prettyKey) {
        return "Dashboard benchmark field: " + prettyKey + ".";
      }
    }
    return "";
  }

  function clearMetricTooltipTimer() {
    if (metricTooltipTimerId != null) {
      window.clearTimeout(metricTooltipTimerId);
      metricTooltipTimerId = null;
    }
    metricTooltipPendingTarget = null;
  }

  function hideMetricTooltip() {
    clearMetricTooltipTimer();
    metricTooltipActiveTarget = null;
    if (metricTooltipNode) {
      metricTooltipNode.hidden = true;
      metricTooltipNode.textContent = "";
    }
  }

  function positionMetricTooltip() {
    if (!metricTooltipNode || metricTooltipNode.hidden) return;
    const width = metricTooltipNode.offsetWidth;
    const height = metricTooltipNode.offsetHeight;
    const viewportWidth = window.innerWidth || document.documentElement.clientWidth || 0;
    const viewportHeight = window.innerHeight || document.documentElement.clientHeight || 0;
    let left = metricTooltipMouseX + METRIC_TOOLTIP_OFFSET_X;
    let top = metricTooltipMouseY + METRIC_TOOLTIP_OFFSET_Y;
    if (left + width + 8 > viewportWidth) {
      left = Math.max(8, viewportWidth - width - 8);
    }
    if (top + height + 8 > viewportHeight) {
      top = Math.max(8, metricTooltipMouseY - height - 10);
    }
    metricTooltipNode.style.left = left + "px";
    metricTooltipNode.style.top = top + "px";
  }

  function showMetricTooltipForTarget(target) {
    if (!(target instanceof Element)) return;
    const text = metricTooltipTextForTarget(target);
    if (!text || !metricTooltipNode) return;
    metricTooltipActiveTarget = target;
    metricTooltipNode.textContent = text;
    metricTooltipNode.hidden = false;
    positionMetricTooltip();
  }

  function metricTooltipHoverTarget(node) {
    if (!(node instanceof Element)) return null;
    const target = node.closest("[data-metric-tooltip-key]");
    return target instanceof Element ? target : null;
  }

  function scheduleMetricTooltip(target) {
    if (!(target instanceof Element)) return;
    const previewText = metricTooltipTextForTarget(target);
    if (!previewText) {
      hideMetricTooltip();
      return;
    }
    clearMetricTooltipTimer();
    metricTooltipPendingTarget = target;
    metricTooltipTimerId = window.setTimeout(() => {
      const pending = metricTooltipPendingTarget;
      clearMetricTooltipTimer();
      if (!pending) return;
      showMetricTooltipForTarget(pending);
    }, METRIC_TOOLTIP_HOVER_DELAY_MS);
  }

  function setMetricTooltipTarget(node, metricKey, fallbackText) {
    if (!(node instanceof Element) || !("dataset" in node)) return;
    const normalizedKey = normalizeMetricTooltipKey(metricKey);
    if (!normalizedKey) return;
    node.dataset.metricTooltipKey = normalizedKey;
    const fallback = compressMetricTooltipText(
      fallbackText == null ? node.getAttribute("title") || "" : fallbackText
    );
    if (fallback) {
      node.dataset.metricTooltipFallback = fallback;
    } else {
      delete node.dataset.metricTooltipFallback;
    }
    if (node.hasAttribute("title")) {
      node.removeAttribute("title");
    }
  }

  function setupMetricHoverTooltips() {
    metricTooltipDescriptions = buildMetricTooltipDescriptions();
    metricTooltipAliasesByText = buildMetricTooltipAliasCatalog(metricTooltipDescriptions);
    metricTooltipAliasEntries = metricTooltipAliasEntryList(metricTooltipAliasesByText);
    if (document.body && document.body.dataset.metricTooltipBound === "1") return;

    const tooltip = document.createElement("div");
    tooltip.className = "metric-hover-tooltip";
    tooltip.hidden = true;
    tooltip.setAttribute("role", "tooltip");
    document.body.appendChild(tooltip);
    metricTooltipNode = tooltip;

    document.addEventListener("mouseover", event => {
      const nextTarget = metricTooltipHoverTarget(event.target);
      const previousTarget = metricTooltipHoverTarget(event.relatedTarget);
      if (nextTarget && previousTarget && nextTarget === previousTarget) return;
      if (!nextTarget) {
        hideMetricTooltip();
        return;
      }
      scheduleMetricTooltip(nextTarget);
    });

    document.addEventListener("mouseout", event => {
      const fromTarget = metricTooltipHoverTarget(event.target);
      const toTarget = metricTooltipHoverTarget(event.relatedTarget);
      if (!fromTarget) return;
      if (toTarget && toTarget === fromTarget) return;
      if (metricTooltipPendingTarget === fromTarget) {
        clearMetricTooltipTimer();
      }
      if (metricTooltipActiveTarget === fromTarget) {
        hideMetricTooltip();
      }
    });

    document.addEventListener(
      "mousemove",
      event => {
        metricTooltipMouseX = event.clientX;
        metricTooltipMouseY = event.clientY;
        if (metricTooltipActiveTarget) {
          positionMetricTooltip();
        }
      },
      { passive: true },
    );

    document.addEventListener("scroll", () => {
      if (metricTooltipActiveTarget) hideMetricTooltip();
    }, true);
    document.addEventListener("mousedown", () => hideMetricTooltip());
    document.addEventListener("keydown", event => {
      if (event.key === "Escape") hideMetricTooltip();
    });

    if (document.body) {
      document.body.dataset.metricTooltipBound = "1";
    }
  }

  function refreshMetricTooltipTargets() {
    document.querySelectorAll("[data-metric-tooltip-key]").forEach(node => {
      if (!(node instanceof Element)) return;
      const key = String(node.dataset.metricTooltipKey || "").trim();
      if (!key) return;
      setMetricTooltipTarget(node, key, null);
    });
    document.querySelectorAll(METRIC_TOOLTIP_AUTO_TARGET_SELECTOR).forEach(node => {
      if (!(node instanceof Element)) return;
      if (node.closest(".metric-hover-tooltip")) return;
      const existingKey = String(node.dataset.metricTooltipKey || "").trim();
      if (existingKey) {
        setMetricTooltipTarget(node, existingKey, null);
        return;
      }
      const text = compressMetricTooltipText(node.textContent || "");
      if (!text || text.length > 140) return;
      const resolvedKey = metricTooltipResolveKeyFromText(text);
      if (!resolvedKey) return;
      setMetricTooltipTarget(node, resolvedKey, null);
    });
  }

  // ---- Header ----
"""
