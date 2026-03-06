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
      codexfarm: "#1f5ea8",
      other: "#7f96b3",
    },
    macro_f1_excluding_other: {
      default: "#127a52",
      vanilla: "#55b895",
      codexfarm: "#127a52",
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
      title: "Single-offline conversion time divided by predicted recipe count.",
      numeric: true,
    },
    "run_config.single_offline_split_cache.conversion_seconds": {
      label: "Conversion seconds",
      title: "Single-offline split-cache conversion time for this benchmark row.",
      numeric: true,
    },
    all_token_use_per_recipe: {
      label: "Token use / recipe",
      title: "Discounted token use divided by predicted recipe count.",
      numeric: true,
    },
    tokens_input: {
      label: "Tokens In",
      title: "CodexFarm input tokens summed for this benchmark run.",
      numeric: true,
    },
    tokens_cached_input: {
      label: "Tokens Cached In",
      title: "CodexFarm cached-input tokens summed for this benchmark run.",
      numeric: true,
    },
    tokens_output: {
      label: "Tokens Out",
      title: "CodexFarm output tokens summed for this benchmark run.",
      numeric: true,
    },
    tokens_reasoning: {
      label: "Tokens Reasoning",
      title: "CodexFarm reasoning tokens summed for this benchmark run.",
      numeric: true,
    },
    tokens_total: {
      label: "Tokens Total",
      title: "CodexFarm total tokens summed for this benchmark run.",
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
    "run_timestamp",
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
    const text = String(rawName || "").trim().replace(/\s+/g, " ");
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

  function applyDashboardUiStatePayload(parsed, savedAtMs) {
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) return false;
    const nextSavedAtMs = Number.isFinite(savedAtMs) ? savedAtMs : -1;
    if (dashboardUiStateSavedAtMs >= 0 && nextSavedAtMs >= 0 && nextSavedAtMs <= dashboardUiStateSavedAtMs) {
      return false;
    }
    if (dashboardUiStateSavedAtMs >= 0 && nextSavedAtMs < 0) return false;
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
          dashboardUiStateSavedAtMsFromValue(parsed && parsed.saved_at)
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
    fetch("assets/dashboard_data.json")
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
    loadDashboardUiStateFromProgramStore()
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
      .replace(/\s+/g, " ")
      .trim();
  }

  function escapeRegexPattern(text) {
    return String(text || "").replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
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
      .replace(/[_.\/]+/g, " ")
      .replace(/[^a-z0-9+%\s-]+/g, " ")
      .replace(/\s+/g, " ")
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
        const keyPrefix = new RegExp("^" + escapeRegexPattern(key) + "\\s*:\\s*", "i");
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
      registerMetricTooltipAlias(aliases, key.replace(/\./g, " "), key);
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
      const prettyKey = key.replace(/^run_config\./, "run config ").replace(/[_.]+/g, " ").trim();
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
  function renderHeader() {
    const m = document.getElementById("header-meta");
    const s = DATA.summary;
    const parts = [];
    parts.push("<span>Generated: " + DATA.generated_at.replace("T", " ").slice(0, 19) + "</span>");
    parts.push("<span>Stage records: " + s.total_stage_records + "</span>");
    parts.push("<span>Benchmark records: " + s.total_benchmark_records + "</span>");
    parts.push("<span>Total recipes: " + s.total_recipes + "</span>");
    if (s.total_runtime_seconds != null)
      parts.push("<span>Total runtime: " + s.total_runtime_seconds.toFixed(1) + "s</span>");
    m.innerHTML = parts.join("");
  }

  // ---- Filters ----
  function setupFilters() {
    const cf = document.getElementById("category-filters");
    const cats = [
      ["stage_import", "Stage imports", true],
      ["benchmark_eval", "Benchmarks", true],
      ["labelstudio_import", "Label Studio imports", false],
      ["benchmark_prediction", "Benchmark predictions", false],
    ];
    cats.forEach(([val, lbl, checked]) => {
      const id = "cat-" + val;
      const label = document.createElement("label");
      const cb = document.createElement("input");
      cb.type = "checkbox"; cb.checked = checked; cb.value = val; cb.id = id;
      if (checked) activeCategories.add(val);
      cb.addEventListener("change", () => {
        if (cb.checked) activeCategories.add(val); else activeCategories.delete(val);
        renderAll();
      });
      label.appendChild(cb);
      label.appendChild(document.createTextNode(" " + lbl));
      cf.appendChild(label);
    });

    document.querySelectorAll("#date-filters button").forEach(btn => {
      btn.addEventListener("click", () => {
        document.querySelectorAll("#date-filters button").forEach(b => b.classList.remove("active"));
        btn.classList.add("active");
        activeDays = parseInt(btn.dataset.days, 10);
        renderAll();
      });
    });
  }

  function setupExtractorFilters() {
    const ef = document.getElementById("extractor-filters");
    if (!ef) return;
    ef.innerHTML = "";
    const extractors = Array.from(
      new Set(
        (DATA.stage_records || [])
          .map(record => epubExtractorEffective(record) || epubExtractorRequested(record))
          .filter(Boolean)
      )
    ).sort((a, b) => a.localeCompare(b));

    activeExtractors = new Set(extractors);
    if (extractors.length === 0) {
      const note = document.createElement("span");
      note.className = "empty-note";
      note.textContent = "No EPUB extractor data";
      ef.appendChild(note);
      return;
    }

    extractors.forEach(extractor => {
      const id = "extractor-" + extractor;
      const label = document.createElement("label");
      const cb = document.createElement("input");
      cb.type = "checkbox";
      cb.checked = true;
      cb.value = extractor;
      cb.id = id;
      cb.addEventListener("change", () => {
        if (cb.checked) activeExtractors.add(extractor);
        else activeExtractors.delete(extractor);
        renderAll();
      });
      label.appendChild(cb);
      label.appendChild(document.createTextNode(" " + extractor));
      ef.appendChild(label);
    });
  }

  function setupThroughputModeControls() {
    const root = document.getElementById("throughput-mode-controls");
    if (!root) return;
    root.querySelectorAll("button[data-mode]").forEach(btn => {
      if (!btn.dataset.bound) {
        btn.addEventListener("click", () => {
          throughputScaleMode = btn.dataset.mode || "clamp95";
          root.querySelectorAll("button[data-mode]").forEach(other => {
            other.classList.toggle("active", other === btn);
          });
          renderThroughput();
        });
        btn.dataset.bound = "1";
      }
    });
  }

  // ---- Filtering helpers ----
  function parseTs(ts) {
    if (ts == null) return null;
    const text = String(ts).trim();
    if (!text) return null;

    // Parse canonical timestamp forms explicitly to avoid browser Date.parse quirks:
    // YYYY-MM-DD_HH.MM.SS and YYYY-MM-DDTHH:MM:SS
    const m = text.match(/^(\d{4})-(\d{2})-(\d{2})[T_](\d{2})[.:](\d{2})[.:](\d{2})(?:_.+)?$/);
    if (m) {
      const d = new Date(
        Number(m[1]),
        Number(m[2]) - 1,
        Number(m[3]),
        Number(m[4]),
        Number(m[5]),
        Number(m[6]),
      );
      return isNaN(d.getTime()) ? null : d;
    }

    // Fallback for ISO strings with timezone offsets.
    const normalized = text.replace(/_(\d{2})[.:](\d{2})[.:](\d{2})$/, "T$1:$2:$3");
    const d = new Date(normalized);
    return isNaN(d.getTime()) ? null : d;
  }

  function isTimestampTokenText(value) {
    const text = String(value || "").trim();
    if (!text) return false;
    return /^\d{4}-\d{2}-\d{2}[T_]\d{2}[.:]\d{2}[.:]\d{2}(?:_.+)?$/.test(text);
  }

  function compareRunTimestampAsc(aTs, bTs) {
    const a = parseTs(aTs);
    const b = parseTs(bTs);
    if (a && b) return a - b;
    if (a) return -1;
    if (b) return 1;
    return (aTs || "").localeCompare(bTs || "");
  }

  function compareRunTimestampDesc(aTs, bTs) {
    return compareRunTimestampAsc(bTs, aTs);
  }

  function isRecent(ts) {
    if (activeDays === 0) return true;
    const d = parseTs(ts);
    if (!d) return true;
    const cutoff = new Date(Date.now() - activeDays * 86400000);
    return d >= cutoff;
  }

  function filteredStage() {
    return DATA.stage_records.filter(r =>
      activeCategories.has(r.run_category) &&
      isRecent(r.run_timestamp) &&
      stagePassesExtractorFilter(r)
    );
  }

  function filteredBenchmarks() {
    return DATA.benchmark_records.filter(r =>
      activeCategories.has(r.run_category) && isRecent(r.run_timestamp)
    );
  }

  function benchmarkArtifactPath(record) {
    const pathCandidates = [
      String((record && record.artifact_dir) || "").trim(),
      String((record && record.run_dir) || "").trim(),
      String((record && record.report_path) || "").trim(),
    ];
    for (let i = 0; i < pathCandidates.length; i++) {
      const candidate = pathCandidates[i];
      if (!candidate) continue;
      return candidate.replace(/\\/g, "/").toLowerCase();
    }
    return "";
  }

  function isSpeedBenchmarkRecord(record) {
    const path = benchmarkArtifactPath(record);
    return path.includes("/bench/speed/runs/");
  }

  function isAllMethodBenchmarkRecord(record) {
    const path = benchmarkArtifactPath(record);
    return path.includes("/all-method-benchmark/");
  }

  function isLikelyAiTestBenchmarkRecord(record) {
    const path = benchmarkArtifactPath(record);
    if (!path) return false;
    if (path.includes("/bench/")) return true;
    if (/(^|\/)pytest-\d+(\/|$)/.test(path)) return true;
    if (/(^|\/)test_[^/]+(\/|$)/.test(path)) return true;
    const parts = path.split("/").filter(Boolean);
    for (let i = 0; i < parts.length; i++) {
      const segment = String(parts[i] || "").toLowerCase();
      const timestampSuffix = segment.match(
        /^(\d{4}-\d{2}-\d{2}[t_]\d{2}[.:]\d{2}[.:]\d{2})_(.+)$/
      );
      if (!timestampSuffix) continue;
      const suffix = String(timestampSuffix[2] || "").toLowerCase();
      if (/(^|[-_])(manual|smoke|test|debug|quick|probe|sample|trial)([-_]|$)/.test(suffix)) {
        return true;
      }
    }
    return false;
  }

  function isOfficialGoldenBenchmarkRecord(record) {
    const path = benchmarkArtifactPath(record);
    if (!path) return false;
    if (!path.includes("/benchmark-vs-golden/")) return false;
    if (!path.includes("/single-offline-benchmark/")) return false;
    const pathVariant = benchmarkVariantFromPathOrPipeline(record);
    const profile = aiAssistanceProfileForRecord(record);
    return (
      (pathVariant === "vanilla" && profile === "deterministic") ||
      (pathVariant === "codexfarm" && profile === "full_stack")
    );
  }

  function activePreviousRunsQuickFilterLabels(enabled) {
    const state = enabled || {
      exclude_ai_tests: Boolean(previousRunsQuickFilters.exclude_ai_tests),
      official_full_golden_only: Boolean(previousRunsQuickFilters.official_full_golden_only),
    };
    const labels = [];
    if (state.exclude_ai_tests) labels.push("exclude AI test/smoke runs");
    if (state.official_full_golden_only) {
      labels.push("official single-offline vanilla/codexfarm runs only");
    }
    return labels;
  }

  function updatePreviousRunsQuickFiltersStatus(context) {
    const status = document.getElementById("quick-filters-status");
    if (!status) return;
    const sourceTotal = Number((context && context.source_total) || 0);
    const filteredTotal = Number((context && context.filtered_total) || 0);
    const labels = activePreviousRunsQuickFilterLabels(context ? context.enabled : null);
    const summary = labels.length ? labels.join("; ") : "none";
    const removedParts = [];
    if (context && context.removed_ai_tests > 0) {
      removedParts.push(String(context.removed_ai_tests) + " test rows");
    }
    if (context && context.removed_unofficial > 0) {
      removedParts.push(String(context.removed_unofficial) + " unofficial rows");
    }
    const removedText = removedParts.length
      ? " Removed: " + removedParts.join(", ") + "."
      : "";
    status.textContent =
      "Quick filters: " +
      summary +
      ". Showing " +
      filteredTotal +
      " of " +
      sourceTotal +
      " benchmark rows." +
      removedText;
  }

  function applyPreviousRunsQuickFilters(records, options) {
    const baseRecords = Array.isArray(records) ? records : [];
    const updateStatus = !options || options.updateStatus !== false;
    const enabled = {
      exclude_ai_tests: Boolean(previousRunsQuickFilters.exclude_ai_tests),
      official_full_golden_only: Boolean(previousRunsQuickFilters.official_full_golden_only),
    };
    let filtered = baseRecords;
    let removedAiTests = 0;
    let removedUnofficial = 0;

    if (enabled.exclude_ai_tests) {
      const next = [];
      filtered.forEach(record => {
        if (isLikelyAiTestBenchmarkRecord(record)) {
          removedAiTests += 1;
          return;
        }
        next.push(record);
      });
      filtered = next;
    }

    if (enabled.official_full_golden_only) {
      const next = [];
      filtered.forEach(record => {
        if (!isOfficialGoldenBenchmarkRecord(record)) {
          removedUnofficial += 1;
          return;
        }
        next.push(record);
      });
      filtered = next;
    }

    const context = {
      source_total: baseRecords.length,
      filtered_total: filtered.length,
      removed_ai_tests: removedAiTests,
      removed_unofficial: removedUnofficial,
      enabled,
    };
    if (updateStatus) {
      updatePreviousRunsQuickFiltersStatus(context);
    }
    return {
      records: filtered,
      context,
    };
  }

  function stagePassesExtractorFilter(record) {
    const extractor = epubExtractorEffective(record) || epubExtractorRequested(record);
    if (!extractor) return true;
    if (activeExtractors.size === 0) return false;
    return activeExtractors.has(extractor);
  }

  // ---- Previous-runs column filters ----
  function clearPreviousRunsTableColumnFilters() {
    previousRunsColumnFilters = Object.create(null);
    previousRunsColumnFilterModes = Object.create(null);
    previousRunsColumnFilterGlobalMode = "and";
    closePreviousRunsColumnFilterEditor();
  }

  function clearAllPreviousRunsFilters() {
    clearPreviousRunsTableColumnFilters();
    previousRunsQuickFilters.exclude_ai_tests = false;
    previousRunsQuickFilters.official_full_golden_only = false;
    setupPreviousRunsQuickFilters();
  }

  function setupPreviousRunsFilters() {
    previousRunsFieldOptions = collectBenchmarkFieldPaths();
    setupBenchmarkTrendFieldControls();
    setupPerLabelControls();
    ensurePreviousRunsColumns();
    setupPreviousRunsColumnsControls();
    setupPreviousRunsQuickFilters();
    setupPreviousRunsGlobalFilterModeControl();
    setupPreviousRunsPresetControls();
    setupCompareControlControls();
    const clearBtn = document.getElementById("previous-runs-clear-filters");
    if (clearBtn && !clearBtn.dataset.bound) {
      clearBtn.addEventListener("click", () => {
        clearPreviousRunsTableColumnFilters();
        renderAll();
      });
      clearBtn.dataset.bound = "1";
    }
    const clearAllBtn = document.getElementById("previous-runs-clear-all-filters");
    if (clearAllBtn && !clearAllBtn.dataset.bound) {
      clearAllBtn.addEventListener("click", () => {
        clearAllPreviousRunsFilters();
        renderAll();
      });
      clearAllBtn.dataset.bound = "1";
    }
    renderPreviousRunsColumnEditor();
  }

  function setupPreviousRunsGlobalFilterModeControl() {
    const select = document.getElementById("previous-runs-global-filter-mode");
    if (!select) return;
    const normalized = normalizePreviousRunsColumnFilterGlobalMode(
      previousRunsColumnFilterGlobalMode
    );
    previousRunsColumnFilterGlobalMode = normalized;
    if (select.value !== normalized) {
      select.value = normalized;
    }
    if (select.dataset.bound) return;
    select.addEventListener("change", () => {
      previousRunsColumnFilterGlobalMode = normalizePreviousRunsColumnFilterGlobalMode(
        select.value
      );
      renderAll();
    });
    select.dataset.bound = "1";
  }

  function setupPreviousRunsQuickFilters() {
    const excludeTests = document.getElementById("quick-filter-exclude-ai-tests");
    const officialOnly = document.getElementById("quick-filter-official-only");
    if (excludeTests) {
      excludeTests.checked = Boolean(previousRunsQuickFilters.exclude_ai_tests);
      if (!excludeTests.dataset.bound) {
        excludeTests.addEventListener("change", () => {
          previousRunsQuickFilters.exclude_ai_tests = Boolean(excludeTests.checked);
          renderAll();
        });
        excludeTests.dataset.bound = "1";
      }
    }
    if (officialOnly) {
      officialOnly.checked = Boolean(previousRunsQuickFilters.official_full_golden_only);
      if (!officialOnly.dataset.bound) {
        officialOnly.addEventListener("change", () => {
          previousRunsQuickFilters.official_full_golden_only = Boolean(officialOnly.checked);
          renderAll();
        });
        officialOnly.dataset.bound = "1";
      }
    }
  }

  function setBenchmarkTrendSelectedFields(nextFields, options) {
    const opts = options && typeof options === "object" && !Array.isArray(options)
      ? options
      : Object.create(null);
    benchmarkTrendSelectedFields = normalizeBenchmarkTrendFieldList(
      nextFields,
      {
        allow_empty: Boolean(opts.allow_empty),
        available_fields: Array.isArray(opts.available_fields)
          ? opts.available_fields
          : benchmarkTrendFieldOptions,
      },
    );
    return benchmarkTrendSelectedFields.slice();
  }

  function setupBenchmarkTrendFieldControls() {
    benchmarkTrendFieldOptions = collectBenchmarkTrendFieldPaths();
    const hasExplicitSelection = Array.isArray(benchmarkTrendSelectedFields);
    setBenchmarkTrendSelectedFields(
      benchmarkTrendSelectedFields,
      {
        allow_empty: hasExplicitSelection,
        available_fields: benchmarkTrendFieldOptions,
      },
    );
    renderBenchmarkTrendFieldControls();

    const selectAllBtn = document.getElementById("benchmark-trend-select-all");
    if (selectAllBtn && !selectAllBtn.dataset.bound) {
      selectAllBtn.addEventListener("click", () => {
        setBenchmarkTrendSelectedFields(
          benchmarkTrendFieldOptions,
          { allow_empty: false, available_fields: benchmarkTrendFieldOptions },
        );
        renderBenchmarkTrendFieldControls();
        renderBenchmarkTrendChart();
        persistDashboardUiState();
      });
      selectAllBtn.dataset.bound = "1";
    }
    const clearBtn = document.getElementById("benchmark-trend-clear");
    if (clearBtn && !clearBtn.dataset.bound) {
      clearBtn.addEventListener("click", () => {
        setBenchmarkTrendSelectedFields(
          [],
          { allow_empty: true, available_fields: benchmarkTrendFieldOptions },
        );
        renderBenchmarkTrendFieldControls();
        renderBenchmarkTrendChart();
        persistDashboardUiState();
      });
      clearBtn.dataset.bound = "1";
    }
  }

  function renderBenchmarkTrendFieldControls() {
    const host = document.getElementById("benchmark-trend-field-checklist");
    const status = document.getElementById("benchmark-trend-fields-status");
    const selectAllBtn = document.getElementById("benchmark-trend-select-all");
    const clearBtn = document.getElementById("benchmark-trend-clear");
    if (!host) return;
    host.innerHTML = "";

    const options = Array.isArray(benchmarkTrendFieldOptions)
      ? benchmarkTrendFieldOptions
      : [];
    const selected = new Set(
      setBenchmarkTrendSelectedFields(
        benchmarkTrendSelectedFields,
        {
          allow_empty: Array.isArray(benchmarkTrendSelectedFields),
          available_fields: options,
        },
      ),
    );

    if (!options.length) {
      host.innerHTML = '<p class="compare-control-inline-note">No numeric benchmark fields are available in this dashboard payload.</p>';
      if (status) {
        status.textContent = "No numeric benchmark fields available.";
      }
      if (selectAllBtn) selectAllBtn.disabled = true;
      if (clearBtn) clearBtn.disabled = true;
      return;
    }

    options.forEach(fieldName => {
      const row = document.createElement("label");
      row.className = "benchmark-trend-field-option";
      const checkbox = document.createElement("input");
      checkbox.type = "checkbox";
      checkbox.value = fieldName;
      checkbox.checked = selected.has(fieldName);
      checkbox.addEventListener("change", () => {
        const next = benchmarkTrendSelectedFields.slice();
        const idx = next.indexOf(fieldName);
        if (checkbox.checked) {
          if (idx === -1) next.push(fieldName);
        } else if (idx >= 0) {
          next.splice(idx, 1);
        }
        setBenchmarkTrendSelectedFields(
          next,
          { allow_empty: true, available_fields: benchmarkTrendFieldOptions },
        );
        renderBenchmarkTrendFieldControls();
        renderBenchmarkTrendChart();
        persistDashboardUiState();
      });
      row.appendChild(checkbox);

      const labelText = document.createElement("span");
      labelText.textContent = benchmarkTrendFieldLabel(fieldName);
      setMetricTooltipTarget(
        labelText,
        fieldName,
        benchmarkTrendFieldLabel(fieldName)
      );
      row.appendChild(labelText);
      host.appendChild(row);
    });

    if (status) {
      if (selected.size === 0) {
        status.textContent = "No fields selected. Check one or more fields to plot them.";
      } else {
        status.textContent = "Plotting " + selected.size + " field(s).";
      }
    }
    if (selectAllBtn) selectAllBtn.disabled = selected.size >= options.length;
    if (clearBtn) clearBtn.disabled = selected.size === 0;
  }

  function previousRunsAvailableColumnFields() {
    const ordered = [];
    const seen = new Set();
    PREVIOUS_RUNS_DEFAULT_COLUMNS.concat(previousRunsFieldOptions).forEach(fieldName => {
      const key = String(fieldName || "").trim();
      if (!key || seen.has(key)) return;
      seen.add(key);
      ordered.push(key);
    });
    return ordered;
  }

  function ensurePreviousRunsColumns() {
    const available = new Set(previousRunsAvailableColumnFields());
    if (!available.has(previousRunsSortField)) {
      previousRunsSortField = "run_timestamp";
      previousRunsSortDirection = "desc";
    }
    const seed = previousRunsVisibleColumns.length
      ? previousRunsVisibleColumns
      : PREVIOUS_RUNS_DEFAULT_COLUMNS;
    const next = [];
    const seen = new Set();
    seed.forEach(fieldName => {
      const key = String(fieldName || "").trim();
      if (!key || !available.has(key) || seen.has(key)) return;
      seen.add(key);
      next.push(key);
    });
    if (!next.length) {
      const fallback = previousRunsAvailableColumnFields()[0] || "run_timestamp";
      next.push(fallback);
    }
    previousRunsVisibleColumns = next;
    prunePreviousRunsColumnFilters();
  }

  function prunePreviousRunsColumnFilters() {
    const available = new Set(previousRunsAvailableColumnFields());
    const next = Object.create(null);
    const nextModes = Object.create(null);
    Object.keys(previousRunsColumnFilters).forEach(fieldName => {
      if (!available.has(fieldName)) return;
      const clauses = previousRunsColumnFilterClauses(fieldName);
      if (!clauses.length) return;
      next[fieldName] = clauses.map(clause => ({
        operator: clause.operator,
        value: clause.value,
      }));
      nextModes[fieldName] = previousRunsColumnFilterMode(fieldName);
    });
    previousRunsColumnFilters = next;
    previousRunsColumnFilterModes = nextModes;
    if (previousRunsOpenFilterField && !available.has(previousRunsOpenFilterField)) {
      closePreviousRunsColumnFilterEditor();
    }
  }

  function normalizePreviousRunsColumnFilterClause(rawClause) {
    if (!rawClause || typeof rawClause !== "object" || Array.isArray(rawClause)) return null;
    const operator = PREVIOUS_RUNS_COLUMN_FILTER_OPERATOR_MAP[rawClause.operator]
      ? String(rawClause.operator)
      : "contains";
    const unary = PREVIOUS_RUNS_UNARY_FILTER_OPERATORS.has(operator);
    const value = unary ? "" : String(rawClause.value || "");
    if (!unary && value.trim() === "") return null;
    return {
      operator,
      value,
    };
  }

  function normalizePreviousRunsColumnFilterList(rawValue) {
    if (!rawValue) return [];
    const sourceList = Array.isArray(rawValue) ? rawValue : [rawValue];
    const next = [];
    const seen = new Set();
    sourceList.forEach(candidate => {
      const clause = normalizePreviousRunsColumnFilterClause(candidate);
      if (!clause) return;
      const dedupeKey = clause.operator + "::" + normalizeRuleValue(clause.value);
      if (seen.has(dedupeKey)) return;
      seen.add(dedupeKey);
      next.push(clause);
    });
    return next;
  }

  function previousRunsColumnFilterClauses(fieldName) {
    const raw = previousRunsColumnFilters[fieldName];
    if (!raw) return [];
    return normalizePreviousRunsColumnFilterList(raw);
  }

  function previousRunsColumnFilterMode(fieldName) {
    const key = String(fieldName || "").trim();
    if (!key) return "and";
    if (!Object.prototype.hasOwnProperty.call(previousRunsColumnFilters, key)) {
      return "and";
    }
    return normalizePreviousRunsColumnFilterMode(previousRunsColumnFilterModes[key]);
  }

  function setPreviousRunsColumnFilterMode(fieldName, mode) {
    const key = String(fieldName || "").trim();
    if (!key) return false;
    if (!Object.prototype.hasOwnProperty.call(previousRunsColumnFilters, key)) {
      delete previousRunsColumnFilterModes[key];
      return false;
    }
    previousRunsColumnFilterModes[key] = normalizePreviousRunsColumnFilterMode(mode);
    return true;
  }

  function openPreviousRunsColumnFilterEditor(fieldName, options) {
    const key = String(fieldName || "");
    const meta = previousRunsColumnMeta(key);
    const opts = options && typeof options === "object" && !Array.isArray(options)
      ? options
      : Object.create(null);
    const fallbackOperator = meta.numeric ? "eq" : "contains";
    const draftOperator = PREVIOUS_RUNS_COLUMN_FILTER_OPERATOR_MAP[opts.operator]
      ? String(opts.operator)
      : fallbackOperator;
    const unary = PREVIOUS_RUNS_UNARY_FILTER_OPERATORS.has(draftOperator);
    const clauses = previousRunsColumnFilterClauses(key);
    const rawEditIndex = Number(opts.edit_index);
    const editIndex = Number.isInteger(rawEditIndex)
      && rawEditIndex >= 0
      && rawEditIndex < clauses.length
      ? rawEditIndex
      : null;
    previousRunsOpenFilterField = key;
    previousRunsOpenFilterDraft = {
      operator: draftOperator,
      value: unary ? "" : String(opts.value || ""),
      edit_index: editIndex,
    };
  }

  function closePreviousRunsColumnFilterEditor() {
    previousRunsOpenFilterField = "";
    previousRunsOpenFilterDraft = null;
  }

  function currentPreviousRunsColumnFilterDraft(fieldName) {
    const meta = previousRunsColumnMeta(fieldName);
    const fallbackOperator = meta.numeric ? "eq" : "contains";
    const clauses = previousRunsColumnFilterClauses(fieldName);
    const fallback = {
      operator: fallbackOperator,
      value: "",
      active: false,
      editing: false,
      edit_index: null,
    };
    if (
      previousRunsOpenFilterField !== fieldName ||
      !previousRunsOpenFilterDraft ||
      typeof previousRunsOpenFilterDraft !== "object"
    ) {
      return fallback;
    }
    const draftOperator = PREVIOUS_RUNS_COLUMN_FILTER_OPERATOR_MAP[previousRunsOpenFilterDraft.operator]
      ? String(previousRunsOpenFilterDraft.operator)
      : fallback.operator;
    const unary = PREVIOUS_RUNS_UNARY_FILTER_OPERATORS.has(draftOperator);
    const rawEditIndex = previousRunsOpenFilterDraft.edit_index;
    const editIndex = Number.isInteger(rawEditIndex)
      && rawEditIndex >= 0
      && rawEditIndex < clauses.length
      ? rawEditIndex
      : null;
    return {
      operator: draftOperator,
      value: unary ? "" : String(previousRunsOpenFilterDraft.value || ""),
      active: unary ? true : String(previousRunsOpenFilterDraft.value || "").trim() !== "",
      editing: editIndex != null,
      edit_index: editIndex,
    };
  }

  function previousRunsColumnMeta(fieldName) {
    const meta = PREVIOUS_RUNS_COLUMN_META[fieldName];
    if (meta) return meta;
    return {
      label: fieldName,
      title: fieldName,
      numeric: false,
    };
  }

  function previousRunsColumnFilterState(fieldName) {
    const clauses = previousRunsColumnFilterClauses(fieldName);
    const fallbackOperator = previousRunsColumnMeta(fieldName).numeric ? "eq" : "contains";
    if (!clauses.length) {
      return {
        operator: fallbackOperator,
        value: "",
        active: false,
      };
    }
    const operator = clauses[0].operator;
    const value = clauses[0].value;
    const unary = PREVIOUS_RUNS_UNARY_FILTER_OPERATORS.has(operator);
    const active = unary ? true : String(value || "").trim() !== "";
    return {
      operator,
      value,
      active,
    };
  }

  function setPreviousRunsColumnFilterClauses(fieldName, clauses) {
    const key = String(fieldName || "").trim();
    if (!key) return false;
    const normalized = normalizePreviousRunsColumnFilterList(clauses);
    if (!normalized.length) {
      delete previousRunsColumnFilters[key];
      delete previousRunsColumnFilterModes[key];
      return false;
    }
    previousRunsColumnFilters[key] = normalized;
    previousRunsColumnFilterModes[key] = normalizePreviousRunsColumnFilterMode(
      previousRunsColumnFilterModes[key]
    );
    return true;
  }

  function setPreviousRunsColumnFilter(fieldName, operator, value) {
    const clause = normalizePreviousRunsColumnFilterClause({
      operator,
      value,
    });
    if (!clause) {
      clearPreviousRunsColumnFilter(fieldName);
      return false;
    }
    return setPreviousRunsColumnFilterClauses(fieldName, [clause]);
  }

  function addPreviousRunsColumnFilter(fieldName, operator, value) {
    const clause = normalizePreviousRunsColumnFilterClause({
      operator,
      value,
    });
    if (!clause) return false;
    const existing = previousRunsColumnFilterClauses(fieldName);
    const nextKey = clause.operator + "::" + normalizeRuleValue(clause.value);
    const hasMatch = existing.some(candidate => (
      candidate.operator + "::" + normalizeRuleValue(candidate.value) === nextKey
    ));
    if (hasMatch) {
      return false;
    }
    existing.push(clause);
    setPreviousRunsColumnFilterClauses(fieldName, existing);
    return true;
  }

  function updatePreviousRunsColumnFilterAt(fieldName, index, operator, value) {
    const clause = normalizePreviousRunsColumnFilterClause({
      operator,
      value,
    });
    if (!clause) return false;
    const clauses = previousRunsColumnFilterClauses(fieldName);
    const idx = Number(index);
    if (!Number.isInteger(idx) || idx < 0 || idx >= clauses.length) return false;
    const nextKey = clause.operator + "::" + normalizeRuleValue(clause.value);
    const duplicateIndex = clauses.findIndex((candidate, candidateIndex) => (
      candidateIndex !== idx
      && candidate.operator + "::" + normalizeRuleValue(candidate.value) === nextKey
    ));
    if (duplicateIndex >= 0) {
      clauses.splice(idx, 1);
      setPreviousRunsColumnFilterClauses(fieldName, clauses);
      return true;
    }
    clauses[idx] = clause;
    setPreviousRunsColumnFilterClauses(fieldName, clauses);
    return true;
  }

  function removePreviousRunsColumnFilterAt(fieldName, index) {
    const clauses = previousRunsColumnFilterClauses(fieldName);
    if (!clauses.length) return false;
    const idx = Number(index);
    if (!Number.isInteger(idx) || idx < 0 || idx >= clauses.length) return false;
    clauses.splice(idx, 1);
    setPreviousRunsColumnFilterClauses(fieldName, clauses);
    return true;
  }

  function clearPreviousRunsColumnFilter(fieldName) {
    if (!Object.prototype.hasOwnProperty.call(previousRunsColumnFilters, fieldName)) {
      return false;
    }
    delete previousRunsColumnFilters[fieldName];
    delete previousRunsColumnFilterModes[fieldName];
    return true;
  }

  function activePreviousRunsColumnFilters() {
    const ordered = [];
    const seenFields = new Set();
    const orderedFields = [];
    previousRunsVisibleColumns.forEach(fieldName => {
      if (Object.prototype.hasOwnProperty.call(previousRunsColumnFilters, fieldName)) {
        seenFields.add(fieldName);
        orderedFields.push(fieldName);
      }
    });
    Object.keys(previousRunsColumnFilters)
      .sort((left, right) => String(left).localeCompare(String(right)))
      .forEach(fieldName => {
        if (seenFields.has(fieldName)) return;
        seenFields.add(fieldName);
        orderedFields.push(fieldName);
      });
    orderedFields.forEach(fieldName => {
      const clauses = previousRunsColumnFilterClauses(fieldName);
      const combine_mode = previousRunsColumnFilterMode(fieldName);
      clauses.forEach((clause, clauseIndex) => {
        ordered.push({
          field: fieldName,
          operator: clause.operator,
          value: clause.value,
          combine_mode,
          clause_index: clauseIndex,
        });
      });
    });
    return ordered;
  }

  function previousRunsIconSvgPath(iconName) {
    if (iconName === "plus") return "M8 3.25v9.5M3.25 8h9.5";
    if (iconName === "minus") return "M3.25 8h9.5";
    return "M4.3 4.3l7.4 7.4M11.7 4.3l-7.4 7.4";
  }

  function setPreviousRunsIcon(button, iconName) {
    if (!(button instanceof HTMLElement)) return;
    const svgNS = "http://www.w3.org/2000/svg";
    const svg = document.createElementNS(svgNS, "svg");
    svg.setAttribute("viewBox", "0 0 16 16");
    svg.setAttribute("aria-hidden", "true");
    svg.setAttribute("focusable", "false");
    svg.classList.add("previous-runs-icon-svg");
    const path = document.createElementNS(svgNS, "path");
    path.setAttribute("d", previousRunsIconSvgPath(iconName));
    path.setAttribute("fill", "none");
    path.setAttribute("stroke", "currentColor");
    path.setAttribute("stroke-width", "1.8");
    path.setAttribute("stroke-linecap", "round");
    path.setAttribute("stroke-linejoin", "round");
    svg.appendChild(path);
    button.replaceChildren(svg);
  }

  function formatPreviousRunsColumnFilterSummary(fieldName, filter) {
    const label = PREVIOUS_RUNS_COLUMN_FILTER_OPERATOR_MAP[filter.operator] || filter.operator;
    if (PREVIOUS_RUNS_UNARY_FILTER_OPERATORS.has(filter.operator)) {
      return label;
    }
    return label + " " + String(filter.value || "");
  }

  function formatPreviousRunsColumnFiltersSummary(fieldName, clauses) {
    const list = Array.isArray(clauses) ? clauses : [];
    if (!list.length) return "No filter";
    const mode = previousRunsColumnFilterMode(fieldName);
    const joinLabel = " " + String(PREVIOUS_RUNS_COLUMN_FILTER_MODE_LABEL[mode] || mode).toUpperCase() + " ";
    const shown = list
      .slice(0, 2)
      .map(clause => formatPreviousRunsColumnFilterSummary(fieldName, clause));
    if (list.length <= 2) {
      return shown.join(joinLabel);
    }
    return shown.join(joinLabel) + joinLabel + "+" + (list.length - 2) + " more";
  }

  function groupPreviousRunsFiltersByField(filters) {
    const groupsByField = new Map();
    const orderedGroups = [];
    (filters || []).forEach(filter => {
      const fieldName = String(filter.field || "").trim();
      if (!fieldName) return;
      let group = groupsByField.get(fieldName);
      if (!group) {
        group = {
          field: fieldName,
          mode: normalizePreviousRunsColumnFilterMode(filter.combine_mode),
          clauses: [],
        };
        groupsByField.set(fieldName, group);
        orderedGroups.push(group);
      }
      group.mode = normalizePreviousRunsColumnFilterMode(filter.combine_mode || group.mode);
      group.clauses.push({
        operator: String(filter.operator || "contains"),
        value: String(filter.value || ""),
      });
    });
    return orderedGroups;
  }

  function recordMatchesPreviousRunsFilterGroups(record, groupedFilters, globalMode) {
    const groups = (groupedFilters || []).filter(group => (
      group && Array.isArray(group.clauses) && group.clauses.length
    ));
    if (!groups.length) return true;
    const topMode = normalizePreviousRunsColumnFilterGlobalMode(globalMode);
    const matchesGroup = group => {
      if (!group || !Array.isArray(group.clauses) || !group.clauses.length) return true;
      const mode = normalizePreviousRunsColumnFilterMode(group.mode);
      const evaluate = clause => {
        const value = previousRunsFieldValue(record, group.field);
        return evaluatePreviousRunsFilterOperator(value, clause.operator, clause.value);
      };
      if (mode === "or") {
        return group.clauses.some(evaluate);
      }
      return group.clauses.every(evaluate);
    };
    if (topMode === "or") {
      return groups.some(matchesGroup);
    }
    return groups.every(matchesGroup);
  }

  function setupCompareControlControlsForSet(config) {
    const cfg = config && typeof config === "object" ? config : Object.create(null);
    const setKey = cfg.set_key === "secondary" ? "secondary" : "primary";
    const panel = document.getElementById(String(cfg.panel_id || ""));
    const viewMode = document.getElementById(String(cfg.view_mode_id || ""));
    const outcomeField = document.getElementById(String(cfg.outcome_field_id || ""));
    const compareField = document.getElementById(String(cfg.compare_field_id || ""));
    const splitField = document.getElementById(String(cfg.split_field_id || ""));
    const holdFields = document.getElementById(String(cfg.hold_fields_id || ""));
    const groupSelection = document.getElementById(String(cfg.group_selection_id || ""));
    const results = document.getElementById(String(cfg.results_id || ""));
    const filterSubset = document.getElementById(String(cfg.filter_subset_id || ""));
    const clearSelection = document.getElementById(String(cfg.clear_selection_id || ""));
    const resetButton = document.getElementById(String(cfg.reset_id || ""));
    if (
      !panel ||
      !viewMode ||
      !outcomeField ||
      !compareField ||
      !splitField ||
      !holdFields ||
      !groupSelection ||
      !results ||
      !filterSubset ||
      !clearSelection ||
      !resetButton
    ) {
      return;
    }

    function rerenderCompareControl() {
      renderCompareControlSection();
      persistDashboardUiState();
    }

    if (!viewMode.dataset.bound) {
      viewMode.addEventListener("change", () => {
        const state = compareControlStateForSet(setKey);
        activateCompareControlChartForSet(setKey);
        state.view_mode = normalizeCompareControlViewMode(viewMode.value);
        setCompareControlStateForSet(setKey, state);
        rerenderCompareControl();
      });
      viewMode.dataset.bound = "1";
    }
    if (!outcomeField.dataset.bound) {
      outcomeField.addEventListener("change", () => {
        const state = compareControlStateForSet(setKey);
        activateCompareControlChartForSet(setKey);
        state.outcome_field = String(outcomeField.value || "").trim();
        setCompareControlStateForSet(setKey, state);
        rerenderCompareControl();
      });
      outcomeField.dataset.bound = "1";
    }
    if (!compareField.dataset.bound) {
      compareField.addEventListener("change", () => {
        const state = compareControlStateForSet(setKey);
        activateCompareControlChartForSet(setKey);
        state.compare_field = String(compareField.value || "").trim();
        state.selected_groups = [];
        if (!state.compare_field) {
          state.view_mode = "discover";
        }
        setCompareControlStateForSet(setKey, state);
        rerenderCompareControl();
      });
      compareField.dataset.bound = "1";
    }
    if (!splitField.dataset.bound) {
      splitField.addEventListener("change", () => {
        const state = compareControlStateForSet(setKey);
        activateCompareControlChartForSet(setKey);
        state.split_field = String(splitField.value || "").trim();
        setCompareControlStateForSet(setKey, state);
        rerenderCompareControl();
      });
      splitField.dataset.bound = "1";
    }
    if (!holdFields.dataset.bound) {
      holdFields.addEventListener("change", event => {
        const target = event.target;
        if (!(target instanceof HTMLInputElement)) return;
        if (!target.classList.contains("compare-control-hold-checkbox")) return;
        const fieldName = String(target.value || "").trim();
        if (!fieldName) return;
        const state = compareControlStateForSet(setKey);
        const current = new Set(uniqueStringList(state.hold_constant_fields));
        if (target.checked) {
          current.add(fieldName);
        } else {
          current.delete(fieldName);
        }
        activateCompareControlChartForSet(setKey);
        state.hold_constant_fields = Array.from(current);
        setCompareControlStateForSet(setKey, state);
        rerenderCompareControl();
      });
      holdFields.dataset.bound = "1";
    }
    if (!groupSelection.dataset.bound) {
      groupSelection.addEventListener("change", event => {
        const target = event.target;
        if (!(target instanceof HTMLInputElement)) return;
        if (!target.classList.contains("compare-control-group-checkbox")) return;
        const groupKey = String(target.value || "").trim();
        if (!groupKey) return;
        const state = compareControlStateForSet(setKey);
        const current = new Set(uniqueStringList(state.selected_groups));
        if (target.checked) {
          current.add(groupKey);
        } else {
          current.delete(groupKey);
        }
        activateCompareControlChartForSet(setKey);
        state.selected_groups = Array.from(current);
        setCompareControlStateForSet(setKey, state);
        rerenderCompareControl();
      });
      groupSelection.dataset.bound = "1";
    }
    if (!results.dataset.bound) {
      results.addEventListener("click", event => {
        const target = event.target;
        if (!(target instanceof HTMLElement)) return;
        const card = target.closest(".compare-control-discovery-card");
        if (!(card instanceof HTMLElement)) return;
        const fieldName = String(card.getAttribute("data-compare-field") || "").trim();
        if (!fieldName) return;
        const state = compareControlStateForSet(setKey);
        activateCompareControlChartForSet(setKey);
        state.compare_field = fieldName;
        state.view_mode = "raw";
        state.selected_groups = [];
        setCompareControlStateForSet(setKey, state);
        setCompareControlStatusForSet(setKey, "Selected " + fieldName + " from discovery.", false);
        rerenderCompareControl();
      });
      results.dataset.bound = "1";
    }
    if (!filterSubset.dataset.bound) {
      filterSubset.addEventListener("click", () => {
        activateCompareControlChartForSet(setKey);
        const applied = applyCompareControlSelectionSubsetForSet(setKey);
        setCompareControlStatusForSet(setKey, applied.message, !applied.applied);
        rerenderCompareControl();
      });
      filterSubset.dataset.bound = "1";
    }
    if (!clearSelection.dataset.bound) {
      clearSelection.addEventListener("click", () => {
        const state = compareControlStateForSet(setKey);
        activateCompareControlChartForSet(setKey);
        state.selected_groups = [];
        setCompareControlStateForSet(setKey, state);
        setCompareControlStatusForSet(setKey, "Cleared selected groups.", false);
        rerenderCompareControl();
      });
      clearSelection.dataset.bound = "1";
    }
    if (!resetButton.dataset.bound) {
      resetButton.addEventListener("click", () => {
        resetCompareControlState(setKey);
        rerenderCompareControl();
      });
      resetButton.dataset.bound = "1";
    }
  }

  function setupCompareControlControls() {
    setupCompareControlControlsForSet({
      set_key: "primary",
      panel_id: "compare-control-panel",
      view_mode_id: "compare-control-view-mode",
      outcome_field_id: "compare-control-outcome-field",
      compare_field_id: "compare-control-compare-field",
      split_field_id: "compare-control-split-field",
      hold_fields_id: "compare-control-hold-fields",
      group_selection_id: "compare-control-group-selection",
      results_id: "compare-control-results",
      filter_subset_id: "compare-control-filter-subset",
      clear_selection_id: "compare-control-clear-selection",
      reset_id: "compare-control-reset",
    });
    setupCompareControlControlsForSet({
      set_key: "secondary",
      panel_id: "compare-control-panel-secondary",
      view_mode_id: "compare-control-view-mode-secondary",
      outcome_field_id: "compare-control-outcome-field-secondary",
      compare_field_id: "compare-control-compare-field-secondary",
      split_field_id: "compare-control-split-field-secondary",
      hold_fields_id: "compare-control-hold-fields-secondary",
      group_selection_id: "compare-control-group-selection-secondary",
      results_id: "compare-control-results-secondary",
      filter_subset_id: "compare-control-filter-subset-secondary",
      clear_selection_id: "compare-control-clear-selection-secondary",
      reset_id: "compare-control-reset-secondary",
    });

    const toggleSecondSet = document.getElementById("compare-control-toggle-second-set");
    if (toggleSecondSet && !toggleSecondSet.dataset.bound) {
      toggleSecondSet.addEventListener("click", () => {
        const nextEnabled = !Boolean(compareControlSecondSetEnabled);
        setCompareControlSecondSetEnabled(nextEnabled);
        syncCompareControlLayoutChrome();
        renderCompareControlSection();
        persistDashboardUiState();
      });
      toggleSecondSet.dataset.bound = "1";
    }

    const chartLayout = document.getElementById("compare-control-chart-layout");
    if (chartLayout && !chartLayout.dataset.bound) {
      chartLayout.addEventListener("change", () => {
        compareControlChartLayout = normalizeCompareControlChartLayout(chartLayout.value);
        syncCompareControlLayoutChrome();
        renderCompareControlSection();
        persistDashboardUiState();
      });
      chartLayout.dataset.bound = "1";
    }

    const combinedAxisMode = document.getElementById("compare-control-combined-axis-mode");
    if (combinedAxisMode && !combinedAxisMode.dataset.bound) {
      combinedAxisMode.addEventListener("change", () => {
        compareControlCombinedAxisMode = normalizeCompareControlCombinedAxisMode(
          combinedAxisMode.value
        );
        renderCompareControlSection();
        persistDashboardUiState();
      });
      combinedAxisMode.dataset.bound = "1";
    }

    syncCompareControlLayoutChrome();
  }

  function compareControlFieldLabel(fieldName) {
    return analysisFieldLabel(fieldName);
  }

  function compareControlChartLabelText(rawLabel) {
    const text = String(rawLabel || "").trim();
    if (!text) return "";
    const normalized = text.replace(/[_-]+/g, " ").replace(/\s+/g, " ").trim();
    const uppercaseWords = new Set(["ai", "api", "csv", "epub", "f1", "html", "id", "json", "llm", "ocr", "pdf", "url"]);
    return normalized
      .split(" ")
      .filter(Boolean)
      .map(word => {
        const lower = word.toLowerCase();
        if (uppercaseWords.has(lower)) return lower.toUpperCase();
        if (/^\d+$/.test(word)) return word;
        return lower.charAt(0).toUpperCase() + lower.slice(1);
      })
      .join(" ");
  }

  function compareControlChartFieldLabel(fieldName) {
    return compareControlChartLabelText(compareControlFieldLabel(fieldName) || fieldName);
  }

  function compareControlPlaceholderLabelForSort(rawLabel) {
    const label = String(rawLabel || "").trim().toLowerCase();
    if (!label) return true;
    return (
      label === "-" ||
      label === "(empty)" ||
      label === "unknown" ||
      label === "none" ||
      label === "n/a" ||
      label === "na"
    );
  }

  function compareControlEffortOrderValue(rawLabel) {
    const key = String(rawLabel || "").trim().toLowerCase().replace(/[\s_-]+/g, "");
    if (!key) return 999;
    const order = {
      minimal: 0,
      low: 1,
      medium: 2,
      high: 3,
      xhigh: 4,
      veryhigh: 4,
      max: 5,
      aioff: 6,
    };
    return Object.prototype.hasOwnProperty.call(order, key) ? order[key] : 999;
  }

  function compareControlGroupDisplaySort(left, right, compareField) {
    const leftLabel = String((left && left.label) || "").trim();
    const rightLabel = String((right && right.label) || "").trim();
    const leftPlaceholder = compareControlPlaceholderLabelForSort(leftLabel);
    const rightPlaceholder = compareControlPlaceholderLabelForSort(rightLabel);
    if (leftPlaceholder !== rightPlaceholder) {
      return leftPlaceholder ? 1 : -1;
    }
    const compareFieldKey = String(compareField || "").trim().toLowerCase();
    if (compareFieldKey === "ai_effort") {
      const leftOrder = compareControlEffortOrderValue(leftLabel);
      const rightOrder = compareControlEffortOrderValue(rightLabel);
      if (leftOrder !== rightOrder) return leftOrder - rightOrder;
    }
    return leftLabel.localeCompare(rightLabel, undefined, { numeric: true, sensitivity: "base" });
  }

  function compareControlFieldSortValue(fieldInfo) {
    if (!fieldInfo) return 0;
    return Number(fieldInfo.non_empty_count || 0);
  }

  function buildCompareControlFieldCatalog(records) {
    const byField = Object.create(null);
    const orderedFields = [];
    const seen = new Set();

    function considerField(fieldName) {
      const key = String(fieldName || "").trim();
      if (!key || seen.has(key) || COMPARE_CONTROL_FIELD_SKIP.has(key)) return;
      seen.add(key);
      const valueCounts = Object.create(null);
      const numericValues = [];
      let nonEmpty = 0;
      let numericCount = 0;
      records.forEach(record => {
        const rawValue = previousRunsFieldValue(record, key);
        if (isEmptyRuleValue(rawValue)) return;
        const comparableKey = analysisComparableValue(rawValue);
        if (!Object.prototype.hasOwnProperty.call(valueCounts, comparableKey)) {
          valueCounts[comparableKey] = {
            key: comparableKey,
            label: analysisDisplayValue(rawValue, comparableKey),
            count: 0,
          };
        }
        valueCounts[comparableKey].count += 1;
        nonEmpty += 1;
        const numeric = maybeNumber(rawValue);
        if (numeric != null) {
          numericCount += 1;
          numericValues.push(numeric);
        }
      });
      const categories = Object.values(valueCounts).sort((left, right) => {
        if (right.count !== left.count) return right.count - left.count;
        return String(left.label).localeCompare(String(right.label), undefined, { numeric: true });
      });
      const distinctCount = categories.length;
      if (distinctCount < 2) return;
      const numeric = nonEmpty > 0 && numericCount === nonEmpty;
      const info = {
        field: key,
        label: compareControlFieldLabel(key),
        numeric,
        non_empty_count: nonEmpty,
        distinct_count: distinctCount,
        categories: numeric ? [] : categories.slice(0, 120),
        numeric_min: numericValues.length ? Math.min(...numericValues) : null,
        numeric_max: numericValues.length ? Math.max(...numericValues) : null,
      };
      byField[key] = info;
      orderedFields.push(info);
    }

    COMPARE_CONTROL_OUTCOME_PREFERRED.forEach(considerField);
    ANALYSIS_FIELD_PREFERRED.forEach(considerField);
    PREVIOUS_RUNS_DEFAULT_COLUMNS.forEach(considerField);
    previousRunsFieldOptions.forEach(considerField);
    orderedFields.sort((left, right) => {
      const sizeGap = compareControlFieldSortValue(right) - compareControlFieldSortValue(left);
      if (sizeGap !== 0) return sizeGap;
      return String(left.label || left.field).localeCompare(
        String(right.label || right.field),
        undefined,
        { numeric: true },
      );
    });
    const numericFields = orderedFields.filter(field => field.numeric);
    const categoricalFields = orderedFields.filter(field => !field.numeric);
    return {
      fields: orderedFields,
      by_field: byField,
      numeric_fields: numericFields,
      categorical_fields: categoricalFields,
    };
  }

  function chooseDefaultCompareOutcome(catalog) {
    const byField = (catalog && catalog.by_field) || Object.create(null);
    for (const fieldName of COMPARE_CONTROL_OUTCOME_PREFERRED) {
      const info = byField[fieldName];
      if (info && info.numeric) return fieldName;
    }
    const numericField = (catalog && catalog.numeric_fields || []).find(Boolean);
    if (numericField) return numericField.field;
    return COMPARE_CONTROL_DEFAULT_OUTCOME_FIELD;
  }

  function normalizeCompareControlStateForCatalog(rawState, catalog) {
    const state = normalizeCompareControlState(rawState);
    const byField = (catalog && catalog.by_field) || Object.create(null);
    const defaultOutcome = chooseDefaultCompareOutcome(catalog);
    if (!byField[state.outcome_field] || !byField[state.outcome_field].numeric) {
      state.outcome_field = defaultOutcome;
    }
    if (state.compare_field && !byField[state.compare_field]) {
      state.compare_field = "";
    }
    if (state.compare_field === state.outcome_field) {
      state.compare_field = "";
    }
    state.hold_constant_fields = state.hold_constant_fields.filter(fieldName => (
      byField[fieldName] &&
      fieldName !== state.outcome_field &&
      fieldName !== state.compare_field
    ));
    if (!byField[state.split_field] || state.split_field === state.outcome_field || state.split_field === state.compare_field) {
      state.split_field = "";
    }
    if (!state.compare_field) {
      state.view_mode = "discover";
      state.selected_groups = [];
    } else {
      state.view_mode = normalizeCompareControlViewMode(state.view_mode);
      const compareField = byField[state.compare_field];
      if (!compareField || compareField.numeric) {
        state.selected_groups = [];
      } else {
        const allowed = new Set(
          (compareField.categories || [])
            .map(entry => String(entry.key || "").trim())
            .filter(Boolean)
            .filter(value => value !== "__EMPTY__")
        );
        state.selected_groups = state.selected_groups.filter(value => allowed.has(value));
      }
    }
    return state;
  }

  function compareControlRecordsForState(records, state, catalog) {
    const baseRecords = Array.isArray(records) ? records : [];
    const activeState = state && typeof state === "object" ? state : compareControlDefaultState();
    if (!activeState.compare_field) return baseRecords;
    const byField = (catalog && catalog.by_field) || Object.create(null);
    const compareInfo = byField[activeState.compare_field];
    if (!compareInfo || compareInfo.numeric) return baseRecords;
    const selectedGroups = uniqueStringList(activeState.selected_groups)
      .filter(value => value && value !== "__EMPTY__");
    if (!selectedGroups.length) return baseRecords;
    const allowed = new Set(selectedGroups);
    return baseRecords.filter(record => (
      allowed.has(
        analysisComparableValue(
          previousRunsFieldValue(record, activeState.compare_field)
        )
      )
    ));
  }

  function compareControlPairs(records, outcomeField, compareField) {
    const pairs = [];
    records.forEach(record => {
      const outcome = maybeNumber(previousRunsFieldValue(record, outcomeField));
      const compare = maybeNumber(previousRunsFieldValue(record, compareField));
      if (outcome == null || compare == null) return;
      pairs.push({ x: compare, y: outcome, record });
    });
    return pairs;
  }

  function rankWithTies(values) {
    const indexed = values
      .map((value, index) => ({ value, index }))
      .sort((left, right) => left.value - right.value);
    const ranks = new Array(values.length);
    let idx = 0;
    while (idx < indexed.length) {
      let end = idx;
      while (end + 1 < indexed.length && indexed[end + 1].value === indexed[idx].value) {
        end += 1;
      }
      const rank = (idx + end + 2) / 2;
      for (let pos = idx; pos <= end; pos += 1) {
        ranks[indexed[pos].index] = rank;
      }
      idx = end + 1;
    }
    return ranks;
  }

  function pearsonCorrelation(xs, ys) {
    if (!Array.isArray(xs) || !Array.isArray(ys) || xs.length !== ys.length || xs.length < 2) {
      return null;
    }
    const meanX = mean(xs);
    const meanY = mean(ys);
    if (meanX == null || meanY == null) return null;
    let sumXY = 0;
    let sumXX = 0;
    let sumYY = 0;
    for (let idx = 0; idx < xs.length; idx += 1) {
      const dx = xs[idx] - meanX;
      const dy = ys[idx] - meanY;
      sumXY += dx * dy;
      sumXX += dx * dx;
      sumYY += dy * dy;
    }
    if (sumXX <= 0 || sumYY <= 0) return null;
    return sumXY / Math.sqrt(sumXX * sumYY);
  }

  function spearmanCorrelation(xs, ys) {
    if (!Array.isArray(xs) || !Array.isArray(ys) || xs.length !== ys.length || xs.length < 2) {
      return null;
    }
    const rankX = rankWithTies(xs);
    const rankY = rankWithTies(ys);
    return pearsonCorrelation(rankX, rankY);
  }

  function linearRegressionFromPairs(pairs) {
    if (!Array.isArray(pairs) || pairs.length < 2) {
      return {
        slope: null,
        intercept: null,
        r_squared: null,
        pearson: null,
      };
    }
    const xs = pairs.map(pair => pair.x);
    const ys = pairs.map(pair => pair.y);
    const meanX = mean(xs);
    const meanY = mean(ys);
    if (meanX == null || meanY == null) {
      return {
        slope: null,
        intercept: null,
        r_squared: null,
        pearson: null,
      };
    }
    let sumXX = 0;
    let sumXY = 0;
    for (let idx = 0; idx < pairs.length; idx += 1) {
      const dx = pairs[idx].x - meanX;
      sumXX += dx * dx;
      sumXY += dx * (pairs[idx].y - meanY);
    }
    if (sumXX <= 0) {
      return {
        slope: 0,
        intercept: meanY,
        r_squared: 0,
        pearson: 0,
      };
    }
    const slope = sumXY / sumXX;
    const intercept = meanY - (slope * meanX);
    const pearson = pearsonCorrelation(xs, ys);
    const rSquared = pearson == null ? null : pearson * pearson;
    return {
      slope,
      intercept,
      r_squared: rSquared,
      pearson,
    };
  }

  function equalCountBinsFromPairs(pairs, maxBins) {
    const sorted = Array.isArray(pairs)
      ? pairs
        .filter(pair => pair && Number.isFinite(pair.x) && Number.isFinite(pair.y))
        .sort((left, right) => left.x - right.x)
      : [];
    if (!sorted.length) return [];
    const targetBins = Math.max(1, Math.min(Number(maxBins) || 5, sorted.length));
    const binSize = Math.max(1, Math.ceil(sorted.length / targetBins));
    const bins = [];
    for (let start = 0; start < sorted.length; start += binSize) {
      const chunk = sorted.slice(start, start + binSize);
      const xs = chunk.map(item => item.x);
      const ys = chunk.map(item => item.y);
      bins.push({
        x_min: xs[0],
        x_max: xs[xs.length - 1],
        x_mean: mean(xs),
        y_mean: mean(ys),
        count: chunk.length,
      });
    }
    return bins;
  }

  function equalCountBinsFromValues(values, maxBins) {
    const sorted = Array.isArray(values)
      ? values
        .filter(value => Number.isFinite(value))
        .sort((left, right) => left - right)
      : [];
    if (!sorted.length) return [];
    const targetBins = Math.max(1, Math.min(Number(maxBins) || 4, sorted.length));
    const binSize = Math.max(1, Math.ceil(sorted.length / targetBins));
    const bins = [];
    for (let start = 0; start < sorted.length; start += binSize) {
      const chunk = sorted.slice(start, start + binSize);
      bins.push({
        min: chunk[0],
        max: chunk[chunk.length - 1],
        mean: mean(chunk),
        count: chunk.length,
      });
    }
    return bins;
  }

  function compareControlSecondaryMetricFields(records, outcomeField, compareField) {
    const totalRows = Array.isArray(records) ? records.length : 0;
    if (!totalRows) return [];
    const candidateOrder = [
      ...COMPARE_CONTROL_SECONDARY_METRIC_PREFERRED,
      ...previousRunsFieldOptions,
    ];
    const preferredSet = new Set(COMPARE_CONTROL_SECONDARY_METRIC_PREFERRED);
    const seen = new Set();
    const selected = [];
    for (const candidate of candidateOrder) {
      const fieldName = String(candidate || "").trim();
      if (!fieldName || seen.has(fieldName)) continue;
      seen.add(fieldName);
      if (fieldName === outcomeField || fieldName === compareField) continue;
      if (COMPARE_CONTROL_FIELD_SKIP.has(fieldName)) continue;
      if (!preferredSet.has(fieldName) && !COMPARE_CONTROL_SECONDARY_FIELD_PATTERN.test(fieldName)) {
        continue;
      }
      let numericCount = 0;
      let numericMin = null;
      let numericMax = null;
      records.forEach(record => {
        const numericValue = maybeNumber(previousRunsFieldValue(record, fieldName));
        if (numericValue == null) return;
        numericCount += 1;
        if (numericMin == null || numericValue < numericMin) numericMin = numericValue;
        if (numericMax == null || numericValue > numericMax) numericMax = numericValue;
      });
      if (numericCount < 2) continue;
      if (
        numericMin != null &&
        numericMax != null &&
        Math.abs(numericMax - numericMin) <= 1e-12
      ) {
        continue;
      }
      selected.push(fieldName);
      if (selected.length >= COMPARE_CONTROL_SECONDARY_MAX_FIELDS) break;
    }
    return selected;
  }

  function compareControlWeakCoverageWarnings(analysis) {
    if (!analysis || typeof analysis !== "object" || Array.isArray(analysis)) return [];
    const warnings = [];
    const candidateRows = Number(analysis.candidate_rows || 0);
    const usedRows = Number(analysis.used_rows || 0);
    if (usedRows <= 0) {
      warnings.push("No comparable rows remained after hold-constant controls.");
      return warnings;
    }
    if (candidateRows > 0) {
      const rowCoverage = usedRows / candidateRows;
      if (rowCoverage < COMPARE_CONTROL_WARNING_ROW_COVERAGE_MIN) {
        warnings.push(
          "Row coverage is low (" +
          usedRows +
          " / " +
          candidateRows +
          ", " +
          (rowCoverage * 100).toFixed(1) +
          "%)."
        );
      }
    }
    if (usedRows < COMPARE_CONTROL_WARNING_MIN_ROWS) {
      warnings.push("Only " + usedRows + " comparable rows are available.");
    }
    const totalStrata = Number(analysis.total_strata || 0);
    const usedStrata = Number(analysis.used_strata || 0);
    if (totalStrata > 0) {
      const strataCoverage = usedStrata / totalStrata;
      if (strataCoverage < COMPARE_CONTROL_WARNING_STRATA_COVERAGE_MIN) {
        warnings.push(
          "Comparable strata are limited (" +
          usedStrata +
          " / " +
          totalStrata +
          ", " +
          (strataCoverage * 100).toFixed(1) +
          "%)."
        );
      }
    }
    if (totalStrata > 0 && usedStrata < Math.min(totalStrata, COMPARE_CONTROL_WARNING_MIN_STRATA)) {
      warnings.push("Only " + usedStrata + " strata contribute to controlled estimates.");
    }
    return warnings;
  }

  function analyzeCompareControlCategoricalRaw(records, outcomeField, compareField) {
    const groupsByKey = Object.create(null);
    const secondaryFields = compareControlSecondaryMetricFields(records, outcomeField, compareField);
    let usedRows = 0;
    records.forEach(record => {
      const outcome = maybeNumber(previousRunsFieldValue(record, outcomeField));
      if (outcome == null) return;
      const rawCompareValue = previousRunsFieldValue(record, compareField);
      const groupKey = analysisComparableValue(rawCompareValue);
      if (groupKey === "__EMPTY__") return;
      if (!Object.prototype.hasOwnProperty.call(groupsByKey, groupKey)) {
        groupsByKey[groupKey] = {
          key: groupKey,
          label: analysisDisplayValue(rawCompareValue, groupKey),
          count: 0,
          outcome_sum: 0,
          secondary_sum: Object.create(null),
          secondary_count: Object.create(null),
        };
      }
      const group = groupsByKey[groupKey];
      group.count += 1;
      group.outcome_sum += outcome;
      secondaryFields.forEach(fieldName => {
        const secondaryValue = maybeNumber(previousRunsFieldValue(record, fieldName));
        if (secondaryValue == null) return;
        const sumValue = Number(group.secondary_sum[fieldName] || 0);
        const countValue = Number(group.secondary_count[fieldName] || 0);
        group.secondary_sum[fieldName] = sumValue + secondaryValue;
        group.secondary_count[fieldName] = countValue + 1;
      });
      usedRows += 1;
    });
    const groups = Object.values(groupsByKey)
      .map(group => ({
        key: group.key,
        label: group.label,
        count: group.count,
        outcome_mean: group.count > 0 ? group.outcome_sum / group.count : null,
        secondary_means: secondaryFields.reduce((acc, fieldName) => {
          const countValue = Number(group.secondary_count[fieldName] || 0);
          if (countValue > 0) {
            acc[fieldName] = Number(group.secondary_sum[fieldName] || 0) / countValue;
          }
          return acc;
        }, Object.create(null)),
      }))
      .sort((left, right) => {
        if (right.count !== left.count) return right.count - left.count;
        return String(left.label).localeCompare(String(right.label), undefined, { numeric: true });
      });
    return {
      type: "categorical",
      groups,
      used_rows: usedRows,
      candidate_rows: records.length,
      secondary_fields: secondaryFields,
    };
  }

  function analyzeCompareControlNumericRaw(records, outcomeField, compareField) {
    const pairs = compareControlPairs(records, outcomeField, compareField);
    const regression = linearRegressionFromPairs(pairs);
    const xs = pairs.map(pair => pair.x);
    const ys = pairs.map(pair => pair.y);
    const spearman = spearmanCorrelation(xs, ys);
    const bins = equalCountBinsFromPairs(pairs, 5);
    return {
      type: "numeric",
      used_rows: pairs.length,
      candidate_rows: records.length,
      slope: regression.slope,
      intercept: regression.intercept,
      r_squared: regression.r_squared,
      spearman,
      bins,
    };
  }

  function analyzeCompareControlCategoricalControlled(records, outcomeField, compareField, holdFields) {
    const hold = uniqueStringList(holdFields);
    if (!hold.length) {
      const raw = analyzeCompareControlCategoricalRaw(records, outcomeField, compareField);
      return {
        ...raw,
        used_strata: 0,
        total_strata: 0,
        hold_fields: hold,
      };
    }

    const strata = Object.create(null);
    records.forEach(record => {
      const outcome = maybeNumber(previousRunsFieldValue(record, outcomeField));
      if (outcome == null) return;
      const rawCompare = previousRunsFieldValue(record, compareField);
      const groupKey = analysisComparableValue(rawCompare);
      if (groupKey === "__EMPTY__") return;
      const stratumKey = hold
        .map(fieldName => analysisComparableValue(previousRunsFieldValue(record, fieldName)))
        .join("||");
      if (!Object.prototype.hasOwnProperty.call(strata, stratumKey)) {
        strata[stratumKey] = Object.create(null);
      }
      if (!Object.prototype.hasOwnProperty.call(strata[stratumKey], groupKey)) {
        strata[stratumKey][groupKey] = {
          key: groupKey,
          label: analysisDisplayValue(rawCompare, groupKey),
          count: 0,
          outcome_sum: 0,
        };
      }
      const group = strata[stratumKey][groupKey];
      group.count += 1;
      group.outcome_sum += outcome;
    });

    const weightedGroups = Object.create(null);
    let usedRows = 0;
    let usedStrata = 0;
    const totalStrata = Object.keys(strata).length;
    Object.keys(strata).forEach(stratumKey => {
      const groups = Object.values(strata[stratumKey]);
      if (groups.length < 2) return;
      const stratumWeight = groups.reduce((acc, group) => acc + Number(group.count || 0), 0);
      if (stratumWeight <= 0) return;
      usedStrata += 1;
      usedRows += stratumWeight;
      groups.forEach(group => {
        if (!Object.prototype.hasOwnProperty.call(weightedGroups, group.key)) {
          weightedGroups[group.key] = {
            key: group.key,
            label: group.label,
            weighted_sum: 0,
            weight: 0,
            count: 0,
            strata_count: 0,
          };
        }
        const meanOutcome = group.count > 0 ? group.outcome_sum / group.count : null;
        if (meanOutcome == null) return;
        // Use shared stratum weights so group means are compared on the same stratum mix.
        weightedGroups[group.key].weighted_sum += meanOutcome * stratumWeight;
        weightedGroups[group.key].weight += stratumWeight;
        weightedGroups[group.key].count += group.count;
        weightedGroups[group.key].strata_count += 1;
      });
    });
    const groups = Object.values(weightedGroups)
      .map(group => ({
        key: group.key,
        label: group.label,
        count: group.count,
        outcome_mean: group.weight > 0 ? group.weighted_sum / group.weight : null,
      }))
      .sort((left, right) => {
        if (right.count !== left.count) return right.count - left.count;
        return String(left.label).localeCompare(String(right.label), undefined, { numeric: true });
      });
    return {
      type: "categorical",
      groups,
      used_rows: usedRows,
      candidate_rows: records.length,
      used_strata: usedStrata,
      total_strata: totalStrata,
      hold_fields: hold,
    };
  }

  function analyzeCompareControlNumericControlled(records, outcomeField, compareField, holdFields) {
    const hold = uniqueStringList(holdFields);
    if (!hold.length) {
      const raw = analyzeCompareControlNumericRaw(records, outcomeField, compareField);
      return {
        ...raw,
        used_strata: 0,
        total_strata: 0,
        hold_fields: hold,
      };
    }

    const strata = Object.create(null);
    records.forEach(record => {
      const outcome = maybeNumber(previousRunsFieldValue(record, outcomeField));
      const compare = maybeNumber(previousRunsFieldValue(record, compareField));
      if (outcome == null || compare == null) return;
      const stratumKey = hold
        .map(fieldName => analysisComparableValue(previousRunsFieldValue(record, fieldName)))
        .join("||");
      if (!Object.prototype.hasOwnProperty.call(strata, stratumKey)) {
        strata[stratumKey] = [];
      }
      strata[stratumKey].push({ x: compare, y: outcome });
    });

    let usedStrata = 0;
    const centeredPairs = [];
    const totalStrata = Object.keys(strata).length;
    Object.keys(strata).forEach(stratumKey => {
      const rows = strata[stratumKey];
      if (!rows || rows.length < 2) return;
      const meanX = mean(rows.map(row => row.x));
      const meanY = mean(rows.map(row => row.y));
      if (meanX == null || meanY == null) return;
      const distinctX = new Set(rows.map(row => row.x)).size;
      if (distinctX < 2) return;
      usedStrata += 1;
      rows.forEach(row => {
        centeredPairs.push({
          x: row.x - meanX,
          y: row.y - meanY,
        });
      });
    });

    const regression = linearRegressionFromPairs(centeredPairs);
    const xs = centeredPairs.map(pair => pair.x);
    const ys = centeredPairs.map(pair => pair.y);
    const spearman = spearmanCorrelation(xs, ys);
    return {
      type: "numeric",
      used_rows: centeredPairs.length,
      candidate_rows: records.length,
      used_strata: usedStrata,
      total_strata: totalStrata,
      hold_fields: hold,
      slope: regression.slope,
      intercept: regression.intercept,
      r_squared: regression.r_squared,
      spearman,
      bins: [],
    };
  }

  function analyzeCompareControlDiscovery(records, outcomeField, catalog, discoveryPreferences) {
    const totalRows = Array.isArray(records) ? records.length : 0;
    const byField = (catalog && catalog.by_field) || Object.create(null);
    const preferences = normalizeCompareControlDiscoveryPreferences(discoveryPreferences);
    const excludedFields = new Set(
      preferences.exclude_fields.map(fieldName => String(fieldName || "").toLowerCase())
    );
    const preferredFields = new Set(
      preferences.prefer_fields.map(fieldName => String(fieldName || "").toLowerCase())
    );
    const demotePatterns = preferences.demote_patterns
      .map(pattern => String(pattern || "").toLowerCase().trim())
      .filter(Boolean);
    const scored = [];
    Object.keys(byField).forEach(fieldName => {
      if (fieldName === outcomeField) return;
      const fieldLower = String(fieldName || "").toLowerCase();
      if (excludedFields.has(fieldLower)) return;
      const fieldInfo = byField[fieldName];
      if (!fieldInfo) return;
      let strength = null;
      let summary = "";
      let coverageRatio = 0;
      if (fieldInfo.numeric) {
        const analysis = analyzeCompareControlNumericRaw(records, outcomeField, fieldName);
        coverageRatio = totalRows > 0 ? analysis.used_rows / totalRows : 0;
        const corrStrength = analysis.spearman == null ? 0 : Math.abs(analysis.spearman);
        const slopeStrength = analysis.slope == null ? 0 : Math.abs(analysis.slope);
        strength = corrStrength + Math.min(1, slopeStrength);
        summary =
          "Spearman " + fmtMaybe(analysis.spearman, 3) +
          ", R² " + fmtMaybe(analysis.r_squared, 3);
      } else {
        const analysis = analyzeCompareControlCategoricalRaw(records, outcomeField, fieldName);
        coverageRatio = totalRows > 0 ? analysis.used_rows / totalRows : 0;
        if (analysis.groups.length < 2) return;
        const means = analysis.groups
          .map(group => maybeNumber(group.outcome_mean))
          .filter(value => value != null);
        if (!means.length) return;
        const minMean = Math.min(...means);
        const maxMean = Math.max(...means);
        strength = Math.abs(maxMean - minMean) * 100;
        const topGroup = analysis.groups[0];
        summary = topGroup
          ? ("Top group: " + topGroup.label + " (" + fmtMaybe(topGroup.outcome_mean, 3) + ")")
          : "";
      }
      let finalScore = Number.isFinite(strength) ? strength * Math.max(0.2, coverageRatio) : 0;
      const scoreModifiers = [];
      if (preferredFields.has(fieldLower)) {
        finalScore *= COMPARE_CONTROL_DISCOVERY_PREFER_FIELD_BOOST;
        scoreModifiers.push("preferred");
      }
      if (demotePatterns.some(pattern => fieldLower.includes(pattern))) {
        finalScore *= COMPARE_CONTROL_DISCOVERY_DEMOTE_FACTOR;
        scoreModifiers.push("demoted");
      }
      if (scoreModifiers.length) {
        summary = summary + " | " + scoreModifiers.join("/");
      }
      scored.push({
        field: fieldName,
        field_label: fieldInfo.label,
        numeric: fieldInfo.numeric,
        coverage_ratio: coverageRatio,
        score: finalScore,
        summary,
      });
    });
    scored.sort((left, right) => right.score - left.score);
    return scored.slice(0, preferences.max_cards);
  }

  function compareControlSplitSegments(records, splitField, catalog) {
    const byField = (catalog && catalog.by_field) || Object.create(null);
    const splitInfo = byField[splitField];
    if (!splitInfo) return [];
    if (splitInfo.numeric) {
      const numericValues = records
        .map(record => maybeNumber(previousRunsFieldValue(record, splitField)))
        .filter(value => value != null);
      const bins = equalCountBinsFromValues(numericValues, 4);
      if (!bins.length) return [];
      const segments = bins.map((bin, idx) => ({
        key: "bin_" + idx,
        label: fmtMaybe(bin.min, 3) + " to " + fmtMaybe(bin.max, 3),
        records: records.filter(record => {
          const value = maybeNumber(previousRunsFieldValue(record, splitField));
          if (value == null) return false;
          if (idx === bins.length - 1) return value >= bin.min && value <= bin.max;
          return value >= bin.min && value < bin.max;
        }),
      }));
      const missing = records.filter(record => (
        maybeNumber(previousRunsFieldValue(record, splitField)) == null
      ));
      if (missing.length) {
        segments.push({
          key: "missing",
          label: "(missing)",
          records: missing,
        });
      }
      return segments.filter(segment => segment.records.length > 0).slice(0, 8);
    }
    const byGroup = Object.create(null);
    records.forEach(record => {
      const rawValue = previousRunsFieldValue(record, splitField);
      const key = analysisComparableValue(rawValue);
      const label = analysisDisplayValue(rawValue, key);
      if (!Object.prototype.hasOwnProperty.call(byGroup, key)) {
        byGroup[key] = {
          key,
          label,
          records: [],
        };
      }
      byGroup[key].records.push(record);
    });
    return Object.values(byGroup)
      .sort((left, right) => {
        if (right.records.length !== left.records.length) {
          return right.records.length - left.records.length;
        }
        return String(left.label).localeCompare(String(right.label), undefined, { numeric: true });
      })
      .slice(0, 8);
  }

  function compareControlSegmentSummary(records, state, catalog) {
    if (!Array.isArray(records) || !records.length || !state.compare_field) return "-";
    const compareInfo = catalog.by_field[state.compare_field];
    if (!compareInfo) return "-";
    if (compareInfo.numeric) {
      const numeric = state.view_mode === "controlled"
        ? analyzeCompareControlNumericControlled(
          records,
          state.outcome_field,
          state.compare_field,
          state.hold_constant_fields,
        )
        : analyzeCompareControlNumericRaw(records, state.outcome_field, state.compare_field);
      return (
        "slope " + fmtMaybe(numeric.slope, 4) +
        ", Spearman " + fmtMaybe(numeric.spearman, 3)
      );
    }
    const categorical = state.view_mode === "controlled"
      ? analyzeCompareControlCategoricalControlled(
        records,
        state.outcome_field,
        state.compare_field,
        state.hold_constant_fields,
      )
      : analyzeCompareControlCategoricalRaw(records, state.outcome_field, state.compare_field);
    if (!categorical.groups.length) return "-";
    const top = categorical.groups[0];
    return top.label + ": " + fmtMaybe(top.outcome_mean, 3);
  }

  function renderCompareControlPanel(context, config) {
    const cfg = config && typeof config === "object" ? config : Object.create(null);
    const setKey = cfg.set_key === "secondary" ? "secondary" : "primary";
    const panel = document.getElementById(
      String(cfg.panel_id || (setKey === "secondary" ? "compare-control-panel-secondary" : "compare-control-panel"))
    );
    const statusNode = document.getElementById(
      String(cfg.status_id || (setKey === "secondary" ? "compare-control-status-secondary" : "compare-control-status"))
    );
    const resultsNode = document.getElementById(
      String(cfg.results_id || (setKey === "secondary" ? "compare-control-results-secondary" : "compare-control-results"))
    );
    const viewModeNode = document.getElementById(
      String(cfg.view_mode_id || (setKey === "secondary" ? "compare-control-view-mode-secondary" : "compare-control-view-mode"))
    );
    const outcomeNode = document.getElementById(
      String(cfg.outcome_field_id || (setKey === "secondary" ? "compare-control-outcome-field-secondary" : "compare-control-outcome-field"))
    );
    const compareNode = document.getElementById(
      String(cfg.compare_field_id || (setKey === "secondary" ? "compare-control-compare-field-secondary" : "compare-control-compare-field"))
    );
    const splitNode = document.getElementById(
      String(cfg.split_field_id || (setKey === "secondary" ? "compare-control-split-field-secondary" : "compare-control-split-field"))
    );
    const holdNode = document.getElementById(
      String(cfg.hold_fields_id || (setKey === "secondary" ? "compare-control-hold-fields-secondary" : "compare-control-hold-fields"))
    );
    const groupNode = document.getElementById(
      String(cfg.group_selection_id || (setKey === "secondary" ? "compare-control-group-selection-secondary" : "compare-control-group-selection"))
    );
    const filterSubset = document.getElementById(
      String(cfg.filter_subset_id || (setKey === "secondary" ? "compare-control-filter-subset-secondary" : "compare-control-filter-subset"))
    );
    const clearSelection = document.getElementById(
      String(cfg.clear_selection_id || (setKey === "secondary" ? "compare-control-clear-selection-secondary" : "compare-control-clear-selection"))
    );
    if (
      !panel ||
      !statusNode ||
      !resultsNode ||
      !viewModeNode ||
      !outcomeNode ||
      !compareNode ||
      !splitNode ||
      !holdNode ||
      !groupNode ||
      !filterSubset ||
      !clearSelection
    ) {
      return;
    }

    const records = Array.isArray(context && context.records) ? context.records : [];
    const catalog = buildCompareControlFieldCatalog(records);
    const normalizedState = normalizeCompareControlStateForCatalog(
      compareControlStateForSet(setKey),
      catalog
    );
    setCompareControlStateForSet(setKey, normalizedState);
    const state = compareControlStateForSet(setKey);
    const scopedRecords = compareControlRecordsForState(records, state, catalog);

    viewModeNode.value = state.view_mode;
    outcomeNode.innerHTML = (catalog.numeric_fields || [])
      .map(field => (
        '<option value="' + esc(field.field) + '">' + esc(field.label) + "</option>"
      ))
      .join("");
    if (!outcomeNode.innerHTML) {
      outcomeNode.innerHTML = '<option value="">(no numeric outcome)</option>';
    }
    if (state.outcome_field && catalog.by_field[state.outcome_field]) {
      outcomeNode.value = state.outcome_field;
    }

    const compareOptions = [
      '<option value="">(discover best candidates)</option>',
      ...(catalog.fields || []).map(field => (
        '<option value="' + esc(field.field) + '">' +
        esc(field.label) +
        "</option>"
      )),
    ];
    compareNode.innerHTML = compareOptions.join("");
    compareNode.value = state.compare_field;

    const splitOptions = [
      '<option value="">(none)</option>',
      ...(catalog.fields || [])
        .filter(field => field.field !== state.compare_field && field.field !== state.outcome_field)
        .map(field => (
          '<option value="' + esc(field.field) + '">' +
          esc(field.label) +
          "</option>"
        )),
    ];
    splitNode.innerHTML = splitOptions.join("");
    splitNode.value = state.split_field;

    const holdCandidates = (catalog.fields || [])
      .filter(field => field.field !== state.compare_field && field.field !== state.outcome_field)
      .slice(0, 20);
    if (!holdCandidates.length) {
      holdNode.innerHTML = '<span class="compare-control-inline-note">No hold-constant fields available.</span>';
    } else {
      holdNode.innerHTML = holdCandidates
        .map(field => {
          const checked = state.hold_constant_fields.includes(field.field) ? " checked" : "";
          return (
            '<label class="compare-control-hold-item">' +
              '<input class="compare-control-hold-checkbox" type="checkbox" value="' + esc(field.field) + '"' + checked + ">" +
              esc(field.label) +
            "</label>"
          );
        })
        .join("");
    }

    if (!records.length) {
      statusNode.textContent = "No benchmark rows are available for Compare & Control.";
      resultsNode.innerHTML = '<p class="empty-note">Run benchmarks to populate Compare &amp; Control analysis rows.</p>';
      groupNode.innerHTML = "";
      filterSubset.disabled = true;
      clearSelection.disabled = true;
      return;
    }
    if (!catalog.numeric_fields.length) {
      statusNode.textContent = "No numeric outcome fields available in current rows.";
      resultsNode.innerHTML = '<p class="empty-note">Need at least one numeric metric to run Compare &amp; Control.</p>';
      groupNode.innerHTML = "";
      filterSubset.disabled = true;
      clearSelection.disabled = true;
      return;
    }

    const compareInfo = catalog.by_field[state.compare_field];
    const selectedGroups = uniqueStringList(state.selected_groups);
    const coverageBase = scopedRecords.length;
    let htmlParts = [];
    let statusText = "";
    let statusIsError = false;

    if (!state.compare_field || state.view_mode === "discover" || !compareInfo) {
      const discovery = analyzeCompareControlDiscovery(
        records,
        state.outcome_field,
        catalog,
        state.discovery_preferences
      );
      statusText =
        "Discovery view over " + records.length + " rows. Click a field card to compare.";
      if (!discovery.length) {
        htmlParts.push("<p>No candidate fields had enough variation for discovery scoring.</p>");
      } else {
        htmlParts.push('<div class="compare-control-discovery-list">');
        discovery.forEach(item => {
          htmlParts.push(
            '<button class="compare-control-discovery-card" type="button" data-compare-field="' + esc(item.field) + '">' +
              "<strong>" + esc(item.field_label) + "</strong> " +
              '<span class="score">score ' + esc(fmtMaybe(item.score, 3)) + "</span>" +
              "<br>" +
              '<span class="compare-control-inline-note">' +
                esc(item.summary + " | coverage " + (item.coverage_ratio * 100).toFixed(1) + "%") +
              "</span>" +
            "</button>"
          );
        });
        htmlParts.push("</div>");
      }
      groupNode.innerHTML = "";
      filterSubset.disabled = true;
      clearSelection.disabled = true;
    } else if (!scopedRecords.length) {
      groupNode.innerHTML = '<p class="compare-control-inline-note">No rows match the currently selected local groups.</p>';
      filterSubset.disabled = selectedGroups.length === 0;
      clearSelection.disabled = selectedGroups.length === 0;
      statusText = "No rows match the selected Compare & Control group subset.";
      htmlParts.push("<p>Adjust selected groups or clear them to continue analysis.</p>");
    } else if (compareInfo.numeric) {
      groupNode.innerHTML = '<p class="compare-control-inline-note">Group subset selection is available for categorical compare fields.</p>';
      filterSubset.disabled = true;
      clearSelection.disabled = true;
      const analysis = state.view_mode === "controlled"
        ? analyzeCompareControlNumericControlled(
          scopedRecords,
          state.outcome_field,
          state.compare_field,
          state.hold_constant_fields,
        )
        : analyzeCompareControlNumericRaw(scopedRecords, state.outcome_field, state.compare_field);
      const coverage = coverageBase > 0 ? (analysis.used_rows / coverageBase) * 100 : 0;
      statusText =
        (state.view_mode === "controlled" ? "Controlled" : "Raw") +
        " numeric compare on " +
        analysis.used_rows +
        " / " +
        coverageBase +
        " rows (" +
        coverage.toFixed(1) +
        "% coverage).";
      if (state.view_mode === "controlled") {
        statusText +=
          " Comparable strata: " +
          analysis.used_strata +
          " / " +
          analysis.total_strata +
          ".";
        const warnings = compareControlWeakCoverageWarnings(analysis);
        if (warnings.length) {
          htmlParts.push('<p class="compare-control-warning"><strong>Coverage warning:</strong></p><ul>');
          warnings.forEach(text => {
            htmlParts.push('<li class="compare-control-warning">' + esc(text) + "</li>");
          });
          htmlParts.push("</ul>");
        }
      }
      htmlParts.push("<p><strong>Slope:</strong> " + esc(fmtMaybe(analysis.slope, 5)) + "</p>");
      htmlParts.push("<p><strong>R²:</strong> " + esc(fmtMaybe(analysis.r_squared, 4)) + "</p>");
      htmlParts.push("<p><strong>Spearman:</strong> " + esc(fmtMaybe(analysis.spearman, 4)) + "</p>");
      if (analysis.bins && analysis.bins.length) {
        htmlParts.push("<p><strong>Equal-count bins:</strong></p><ul>");
        analysis.bins.forEach(bin => {
          htmlParts.push(
            "<li>" +
            esc(
              fmtMaybe(bin.x_min, 3) +
              " to " +
              fmtMaybe(bin.x_max, 3) +
              " (" +
              bin.count +
              " rows): outcome avg " +
              fmtMaybe(bin.y_mean, 4)
            ) +
            "</li>"
          );
        });
        htmlParts.push("</ul>");
      }
    } else {
      const groupOptions = compareInfo.categories || [];
      const sortedGroupOptions = [...groupOptions].sort((left, right) => (
        compareControlGroupDisplaySort(left, right, state.compare_field)
      ));
      groupNode.innerHTML = groupOptions.length
        ? (
          '<p class="compare-control-inline-note">Selected groups are local to Compare &amp; Control and do not change Previous Runs filters.</p>' +
          '<div class="compare-control-group-selection-list">' +
          sortedGroupOptions
            .map(group => {
              if (group.key === "__EMPTY__") return "";
              const checked = selectedGroups.includes(group.key) ? " checked" : "";
              return (
                '<label class="compare-control-group-option">' +
                  '<input class="compare-control-group-checkbox" type="checkbox" value="' + esc(group.key) + '"' + checked + ">" +
                  esc(group.label + " (" + group.count + ")") +
                "</label>"
              );
            })
            .join("") +
          "</div>"
        )
        : '<p class="compare-control-inline-note">No groups available for selection.</p>';
      filterSubset.disabled = selectedGroups.length === 0;
      clearSelection.disabled = selectedGroups.length === 0;
      const analysis = state.view_mode === "controlled"
        ? analyzeCompareControlCategoricalControlled(
          scopedRecords,
          state.outcome_field,
          state.compare_field,
          state.hold_constant_fields,
        )
        : analyzeCompareControlCategoricalRaw(scopedRecords, state.outcome_field, state.compare_field);
      const coverage = coverageBase > 0 ? (analysis.used_rows / coverageBase) * 100 : 0;
      statusText =
        (state.view_mode === "controlled" ? "Controlled" : "Raw") +
        " categorical compare on " +
        analysis.used_rows +
        " / " +
        coverageBase +
        " rows (" +
        coverage.toFixed(1) +
        "% coverage).";
      if (state.view_mode === "controlled") {
        statusText +=
          " Comparable strata: " +
          analysis.used_strata +
          " / " +
          analysis.total_strata +
          ".";
        const warnings = compareControlWeakCoverageWarnings(analysis);
        if (warnings.length) {
          htmlParts.push('<p class="compare-control-warning"><strong>Coverage warning:</strong></p><ul>');
          warnings.forEach(text => {
            htmlParts.push('<li class="compare-control-warning">' + esc(text) + "</li>");
          });
          htmlParts.push("</ul>");
        }
      }
      if (!analysis.groups.length) {
        htmlParts.push("<p>No comparable groups found with the current controls.</p>");
      } else {
        const secondaryFields = (analysis.secondary_fields || [])
          .filter(Boolean);
        const displayGroups = [...(analysis.groups || [])].sort((left, right) => (
          compareControlGroupDisplaySort(left, right, state.compare_field)
        ));
        htmlParts.push("<p><strong>Group outcome means:</strong></p>");
        htmlParts.push('<div class="compare-control-groups-table-wrap">');
        htmlParts.push('<table class="compare-control-groups-table"><thead><tr>');
        htmlParts.push("<th>Group</th>");
        htmlParts.push('<th class="num" data-metric-tooltip-key="task_count">Rows</th>');
        htmlParts.push(
          '<th class="num" data-metric-tooltip-key="' +
          esc(state.outcome_field) +
          '">Avg</th>'
        );
        secondaryFields.forEach(fieldName => {
          htmlParts.push(
            '<th data-metric-tooltip-key="' +
            esc(fieldName) +
            '">' +
            esc(compareControlFieldLabel(fieldName)) +
            "</th>"
          );
        });
        htmlParts.push("</tr></thead><tbody>");
        displayGroups.slice(0, 12).forEach(group => {
          htmlParts.push("<tr>");
          htmlParts.push("<td>" + esc(group.label) + "</td>");
          htmlParts.push('<td class="num">' + esc(compareControlTableNumber(group.count, 0)) + "</td>");
          htmlParts.push('<td class="num">' + esc(compareControlTableNumber(group.outcome_mean, 4)) + "</td>");
          secondaryFields.forEach(fieldName => {
            const value = maybeNumber(
              group &&
              group.secondary_means &&
              Object.prototype.hasOwnProperty.call(group.secondary_means, fieldName)
                ? group.secondary_means[fieldName]
                : null
            );
            htmlParts.push('<td class="num">' + esc(compareControlTableNumber(value, 3)) + "</td>");
          });
          htmlParts.push("</tr>");
        });
        htmlParts.push("</tbody></table></div>");
      }
    }

    if (state.split_field) {
      const segments = compareControlSplitSegments(scopedRecords, state.split_field, catalog);
      if (segments.length) {
        htmlParts.push('<div class="compare-control-split-list"><p><strong>Split by ' + esc(compareControlFieldLabel(state.split_field)) + ":</strong></p><ul>");
        segments.forEach(segment => {
          const summary = compareControlSegmentSummary(segment.records, state, catalog);
          htmlParts.push(
            "<li>" +
            esc(segment.label + " (" + segment.records.length + " rows): " + summary) +
            "</li>"
          );
        });
        htmlParts.push("</ul></div>");
      }
    }

    const setStatus = compareControlStatusForSet(setKey);
    if (setStatus.message) {
      const prefix = setStatus.is_error ? "Compare/Control: " : "";
      statusText = prefix + setStatus.message + (statusText ? " " + statusText : "");
      statusIsError = setStatus.is_error;
      clearCompareControlStatusForSet(setKey);
    }
    statusNode.textContent = statusText || (
      setKey === "secondary"
        ? "Set 2 ready."
        : "Compare & Control ready."
    );
    statusNode.classList.toggle("error", Boolean(statusIsError));
    resultsNode.innerHTML = htmlParts.join("");
  }

  function applyCompareControlSelectionSubsetForSet(setKey) {
    const key = setKey === "secondary" ? "secondary" : "primary";
    const state = normalizeCompareControlState(compareControlStateForSet(key));
    const compareField = String(state.compare_field || "").trim();
    const selectedGroups = uniqueStringList(state.selected_groups)
      .filter(value => value && value !== "__EMPTY__");
    if (!compareField) {
      return {
        applied: false,
        message: "Pick a categorical compare field first.",
      };
    }
    if (!selectedGroups.length) {
      return {
        applied: false,
        message: "Select one or more groups before applying a local subset.",
      };
    }
    state.selected_groups = selectedGroups;
    setCompareControlStateForSet(key, state);
    return {
      applied: true,
      message: "Using " + selectedGroups.length + " selected group(s) in Compare & Control only.",
    };
  }

  function applyCompareControlSelectionSubset() {
    return applyCompareControlSelectionSubsetForSet("primary");
  }

  function analysisComparableValue(value) {
    if (value == null) return "__EMPTY__";
    if (typeof value === "string") {
      const text = value.trim();
      return text ? text : "__EMPTY__";
    }
    if (typeof value === "boolean") return value ? "true" : "false";
    if (typeof value === "number") {
      if (!Number.isFinite(value)) return "__EMPTY__";
      return String(value);
    }
    return String(value);
  }

  function analysisDisplayValue(rawValue, comparableValue) {
    if (comparableValue === "__EMPTY__") return "(empty)";
    if (typeof rawValue === "boolean") return rawValue ? "true" : "false";
    if (typeof rawValue === "number") {
      if (!Number.isFinite(rawValue)) return "(empty)";
      return Number.isInteger(rawValue) ? String(rawValue) : rawValue.toFixed(4);
    }
    return String(rawValue);
  }

  function analysisFieldLabel(fieldName) {
    const meta = previousRunsColumnMeta(fieldName);
    if (!meta || !meta.label) return fieldName;
    return meta.label;
  }

  function previousRunsRecordsMatchingOtherFilters(excludedField) {
    const base = applyPreviousRunsQuickFilters(
      filteredBenchmarks(),
      { updateStatus: false },
    ).records;
    const filters = activePreviousRunsColumnFilters()
      .filter(filter => filter.field !== excludedField);
    if (!filters.length) return base;
    const grouped = groupPreviousRunsFiltersByField(filters);
    return base.filter(record => (
      recordMatchesPreviousRunsFilterGroups(
        record,
        grouped,
        previousRunsColumnFilterGlobalMode
      )
    ));
  }

  function previousRunsSuggestionValue(value) {
    if (value == null) return "";
    if (typeof value === "boolean") return value ? "true" : "false";
    if (typeof value === "number") {
      if (!Number.isFinite(value)) return "";
      return Number.isInteger(value) ? String(value) : String(value);
    }
    return String(value).trim();
  }

  function previousRunsSuggestionScore(typedLower, candidateLower) {
    if (!typedLower) return 500;
    if (!candidateLower) return -1;
    if (candidateLower === typedLower) return 2000;
    if (candidateLower.startsWith(typedLower)) {
      return 1500 - Math.min(300, candidateLower.length - typedLower.length);
    }
    const wordStart = candidateLower.indexOf(" " + typedLower);
    if (wordStart >= 0) {
      return 1300 - wordStart;
    }
    const includes = candidateLower.indexOf(typedLower);
    if (includes >= 0) {
      return 1100 - includes;
    }
    let needleIndex = 0;
    for (let idx = 0; idx < candidateLower.length && needleIndex < typedLower.length; idx += 1) {
      if (candidateLower[idx] === typedLower[needleIndex]) {
        needleIndex += 1;
      }
    }
    if (needleIndex === typedLower.length) {
      return 900;
    }
    return -1;
  }

  function previousRunsColumnSuggestionCandidates(fieldName, typedText) {
    const typedLower = normalizeRuleValue(typedText || "");
    const counts = new Map();
    previousRunsRecordsMatchingOtherFilters(fieldName).forEach(record => {
      const rawValue = previousRunsFieldValue(record, fieldName);
      const candidate = previousRunsSuggestionValue(rawValue);
      if (!candidate) return;
      counts.set(candidate, (counts.get(candidate) || 0) + 1);
    });

    const scored = [];
    counts.forEach((count, value) => {
      const lower = value.toLowerCase();
      const score = previousRunsSuggestionScore(typedLower, lower);
      if (score < 0) return;
      scored.push({
        value,
        count,
        score,
      });
    });

    scored.sort((left, right) => {
      if (right.score !== left.score) return right.score - left.score;
      if (right.count !== left.count) return right.count - left.count;
      if (left.value.length !== right.value.length) return left.value.length - right.value.length;
      return left.value.localeCompare(right.value);
    });
    return scored.slice(0, PREVIOUS_RUNS_FILTER_SUGGESTION_LIMIT);
  }

  function previousRunsPresetNames() {
    return Object.keys(previousRunsViewPresets).sort((left, right) => (
      String(left).localeCompare(String(right), undefined, { sensitivity: "base" })
    ));
  }

  function setPreviousRunsPresetStatus(message, isError) {
    const status = document.getElementById("previous-runs-preset-status");
    if (!status) return;
    status.textContent = String(message || "");
    status.classList.toggle("error", Boolean(isError));
  }

  function renderPreviousRunsPresetEditor() {
    const select = document.getElementById("previous-runs-preset-select");
    if (!select) return;
    const names = previousRunsPresetNames();
    const selected = sanitizePreviousRunsPresetName(previousRunsSelectedPreset);
    previousRunsSelectedPreset = names.includes(selected) ? selected : "";

    select.innerHTML = "";
    const emptyOption = document.createElement("option");
    emptyOption.value = "";
    emptyOption.textContent = "(none)";
    select.appendChild(emptyOption);
    names.forEach(name => {
      const option = document.createElement("option");
      option.value = name;
      option.textContent = name;
      select.appendChild(option);
    });
    select.value = previousRunsSelectedPreset;

    const loadBtn = document.getElementById("previous-runs-preset-load");
    if (loadBtn) loadBtn.disabled = !previousRunsSelectedPreset;
    const deleteBtn = document.getElementById("previous-runs-preset-delete");
    if (deleteBtn) deleteBtn.disabled = !previousRunsSelectedPreset;
  }

  function captureCurrentPreviousRunsPresetState() {
    ensurePreviousRunsColumns();
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
    });
    return sanitizePreviousRunsPresetState({
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
      column_widths: columnWidths,
      sort: {
        field: String(previousRunsSortField || "run_timestamp"),
        direction: previousRunsSortDirection === "asc" ? "asc" : "desc",
      },
    });
  }

  function applyPreviousRunsPresetByName(rawName) {
    const name = sanitizePreviousRunsPresetName(rawName);
    if (!name) {
      setPreviousRunsPresetStatus("Pick a preset first.", true);
      return false;
    }
    if (!Object.prototype.hasOwnProperty.call(previousRunsViewPresets, name)) {
      setPreviousRunsPresetStatus('Preset "' + name + '" was not found.', true);
      return false;
    }
    const preset = sanitizePreviousRunsPresetState(previousRunsViewPresets[name]);
    if (!preset) {
      setPreviousRunsPresetStatus('Preset "' + name + '" is invalid.', true);
      return false;
    }

    previousRunsSelectedPreset = name;
    previousRunsVisibleColumns = preset.visible_columns.slice();
    ensurePreviousRunsColumns();

    const availableSet = new Set(previousRunsAvailableColumnFields());
    const nextColumnFilters = Object.create(null);
    const nextColumnFilterModes = Object.create(null);
    Object.keys(preset.column_filters).forEach(fieldName => {
      if (!availableSet.has(fieldName)) return;
      const normalized = normalizePreviousRunsColumnFilterList(preset.column_filters[fieldName]);
      if (!normalized.length) return;
      nextColumnFilters[fieldName] = normalized;
      nextColumnFilterModes[fieldName] = normalizePreviousRunsColumnFilterMode(
        preset.column_filter_modes && preset.column_filter_modes[fieldName]
      );
    });
    previousRunsColumnFilters = nextColumnFilters;
    previousRunsColumnFilterModes = nextColumnFilterModes;
    previousRunsColumnFilterGlobalMode = normalizePreviousRunsColumnFilterGlobalMode(
      preset.column_filter_global_mode
    );

    previousRunsQuickFilters.exclude_ai_tests = Boolean(preset.quick_filters.exclude_ai_tests);
    previousRunsQuickFilters.official_full_golden_only = Boolean(
      preset.quick_filters.official_full_golden_only
    );
    previousRunsSortField = String(preset.sort.field || "run_timestamp");
    previousRunsSortDirection = preset.sort.direction === "asc" ? "asc" : "desc";
    ensurePreviousRunsColumns();

    previousRunsColumnWidths = sanitizeColumnWidthsMap(preset.column_widths);
    clearDashboardTableColumnWidths("previous-runs-table");
    Object.keys(previousRunsColumnWidths).forEach(fieldName => {
      setDashboardTableColumnWidth(
        "previous-runs-table",
        fieldName,
        previousRunsColumnWidths[fieldName]
      );
    });

    closePreviousRunsColumnFilterEditor();
    setupPreviousRunsGlobalFilterModeControl();
    setupPreviousRunsQuickFilters();
    renderPreviousRunsPresetEditor();
    renderAll();
    setPreviousRunsPresetStatus('Loaded preset "' + name + '".', false);
    return true;
  }

  function saveCurrentPreviousRunsViewPreset(rawName) {
    let name = sanitizePreviousRunsPresetName(rawName);
    if (!name && typeof window !== "undefined" && typeof window.prompt === "function") {
      name = sanitizePreviousRunsPresetName(
        window.prompt("Preset name for current Previous Runs view:", previousRunsSelectedPreset || "")
      );
    }
    if (!name) {
      setPreviousRunsPresetStatus("Preset save cancelled (name is required).", true);
      return false;
    }
    const names = previousRunsPresetNames();
    const exists = Object.prototype.hasOwnProperty.call(previousRunsViewPresets, name);
    if (!exists && names.length >= PREVIOUS_RUNS_PRESET_MAX_COUNT) {
      setPreviousRunsPresetStatus(
        "Preset limit reached (" + PREVIOUS_RUNS_PRESET_MAX_COUNT + "). Delete one first.",
        true
      );
      return false;
    }
    const snapshot = captureCurrentPreviousRunsPresetState();
    if (!snapshot) {
      setPreviousRunsPresetStatus("Could not capture current view.", true);
      return false;
    }
    previousRunsViewPresets[name] = snapshot;
    previousRunsSelectedPreset = name;
    renderPreviousRunsPresetEditor();
    persistDashboardUiState();
    setPreviousRunsPresetStatus(
      (exists ? "Updated" : "Saved") + ' preset "' + name + '".',
      false
    );
    return true;
  }

  function deletePreviousRunsPreset(rawName) {
    const name = sanitizePreviousRunsPresetName(rawName);
    if (!name || !Object.prototype.hasOwnProperty.call(previousRunsViewPresets, name)) {
      setPreviousRunsPresetStatus("Pick an existing preset to delete.", true);
      return false;
    }
    delete previousRunsViewPresets[name];
    if (previousRunsSelectedPreset === name) {
      previousRunsSelectedPreset = "";
    }
    renderPreviousRunsPresetEditor();
    persistDashboardUiState();
    setPreviousRunsPresetStatus('Deleted preset "' + name + '".', false);
    return true;
  }

  function syncPreviousRunsPopupVisibility() {
    const popup = document.getElementById("previous-runs-columns-popup");
    const toggleBtn = document.getElementById("previous-runs-columns-toggle");
    if (popup) {
      popup.hidden = !previousRunsColumnsPopupOpen;
    }
    if (toggleBtn) {
      toggleBtn.setAttribute("aria-expanded", previousRunsColumnsPopupOpen ? "true" : "false");
      toggleBtn.classList.toggle("open", previousRunsColumnsPopupOpen);
    }
  }

  function setPreviousRunsColumnsPopupOpen(nextOpen) {
    previousRunsColumnsPopupOpen = Boolean(nextOpen);
    syncPreviousRunsPopupVisibility();
  }

  function setupPreviousRunsColumnsControls() {
    const control = document.querySelector(".previous-runs-columns-control");
    const popup = document.getElementById("previous-runs-columns-popup");
    const toggleBtn = document.getElementById("previous-runs-columns-toggle");

    if (toggleBtn && !toggleBtn.dataset.bound) {
      toggleBtn.addEventListener("click", event => {
        event.preventDefault();
        event.stopPropagation();
        setPreviousRunsColumnsPopupOpen(!previousRunsColumnsPopupOpen);
      });
      toggleBtn.dataset.bound = "1";
    }

    if (popup && !popup.dataset.bound) {
      popup.addEventListener("click", event => {
        event.stopPropagation();
      });
      popup.dataset.bound = "1";
    }

    if (document.body && !document.body.dataset.previousRunsColumnsBound) {
      document.addEventListener("click", event => {
        if (!previousRunsColumnsPopupOpen) return;
        if (!(event.target instanceof Node)) return;
        if (control && control.contains(event.target)) return;
        setPreviousRunsColumnsPopupOpen(false);
      });
      document.addEventListener("keydown", event => {
        if (event.key !== "Escape") return;
        if (!previousRunsColumnsPopupOpen) return;
        setPreviousRunsColumnsPopupOpen(false);
      });
      document.body.dataset.previousRunsColumnsBound = "1";
    }

    const resetBtn = document.getElementById("previous-runs-column-reset");
    if (resetBtn && !resetBtn.dataset.bound) {
      resetBtn.addEventListener("click", () => {
        previousRunsVisibleColumns = PREVIOUS_RUNS_DEFAULT_COLUMNS
          .filter(fieldName => previousRunsAvailableColumnFields().includes(fieldName));
        ensurePreviousRunsColumns();
        previousRunsColumnWidths = Object.create(null);
        clearDashboardTableColumnWidths("previous-runs-table");
        renderPreviousRunsColumnEditor();
        renderPreviousRuns();
      });
      resetBtn.dataset.bound = "1";
    }
    setPreviousRunsColumnsPopupOpen(false);
  }

  function setupPreviousRunsPresetControls() {
    const presetSelect = document.getElementById("previous-runs-preset-select");
    if (presetSelect && !presetSelect.dataset.bound) {
      presetSelect.addEventListener("change", () => {
        previousRunsSelectedPreset = sanitizePreviousRunsPresetName(presetSelect.value);
        renderPreviousRunsPresetEditor();
        persistDashboardUiState();
      });
      presetSelect.dataset.bound = "1";
    }

    const presetLoadBtn = document.getElementById("previous-runs-preset-load");
    if (presetLoadBtn && !presetLoadBtn.dataset.bound) {
      presetLoadBtn.addEventListener("click", () => {
        const selectedName = sanitizePreviousRunsPresetName(
          presetSelect ? presetSelect.value : previousRunsSelectedPreset
        );
        applyPreviousRunsPresetByName(selectedName);
      });
      presetLoadBtn.dataset.bound = "1";
    }

    const presetSaveCurrentBtn = document.getElementById("previous-runs-preset-save-current");
    if (presetSaveCurrentBtn && !presetSaveCurrentBtn.dataset.bound) {
      presetSaveCurrentBtn.addEventListener("click", () => {
        const selectedName = sanitizePreviousRunsPresetName(
          presetSelect ? presetSelect.value : previousRunsSelectedPreset
        );
        saveCurrentPreviousRunsViewPreset(selectedName);
      });
      presetSaveCurrentBtn.dataset.bound = "1";
    }

    const presetDeleteBtn = document.getElementById("previous-runs-preset-delete");
    if (presetDeleteBtn && !presetDeleteBtn.dataset.bound) {
      presetDeleteBtn.addEventListener("click", () => {
        const selectedName = sanitizePreviousRunsPresetName(
          presetSelect ? presetSelect.value : previousRunsSelectedPreset
        );
        deletePreviousRunsPreset(selectedName);
      });
      presetDeleteBtn.dataset.bound = "1";
    }

    renderPreviousRunsPresetEditor();
  }

  function renderPreviousRunsColumnEditor() {
    ensurePreviousRunsColumns();
    const host = document.getElementById("previous-runs-columns-checklist");
    if (!host) return;

    host.innerHTML = "";
    const availableFields = previousRunsAvailableColumnFields();
    const availableSet = new Set(availableFields);
    const visibleSet = new Set(previousRunsVisibleColumns);
    const disabledFieldName = previousRunsVisibleColumns.length <= 1
      ? previousRunsVisibleColumns[0]
      : null;
    const checklistOrder = [...previousRunsVisibleColumns].filter(
      fieldName => availableSet.has(fieldName)
    );
    availableFields.forEach(fieldName => {
      if (!visibleSet.has(fieldName)) {
        checklistOrder.push(fieldName);
      }
    });
    checklistOrder.forEach(fieldName => {
      const meta = previousRunsColumnMeta(fieldName);
      const row = document.createElement("label");
      row.className = "previous-runs-columns-check-item";
      const checkbox = document.createElement("input");
      checkbox.type = "checkbox";
      checkbox.value = fieldName;
      checkbox.checked = visibleSet.has(fieldName);
      checkbox.disabled = fieldName === disabledFieldName;
      checkbox.addEventListener("change", () => {
        const checked = checkbox.checked;
        const currentVisible = new Set(previousRunsVisibleColumns);
        if (checked) {
          if (!currentVisible.has(fieldName)) {
            previousRunsVisibleColumns.push(fieldName);
          }
        } else {
          if (previousRunsVisibleColumns.length <= 1) {
            checkbox.checked = true;
            return;
          }
          previousRunsVisibleColumns = previousRunsVisibleColumns.filter(
            candidate => candidate !== fieldName
          );
        }
        ensurePreviousRunsColumns();
        renderPreviousRunsColumnEditor();
        renderPreviousRuns();
      });
      row.appendChild(checkbox);

      const labelText = document.createElement("span");
      labelText.textContent = meta.label || fieldName;
      setMetricTooltipTarget(labelText, fieldName, meta.title || meta.label || fieldName);
      if ((meta.label || fieldName) !== fieldName) {
        const key = document.createElement("code");
        key.textContent = " " + fieldName;
        setMetricTooltipTarget(key, fieldName, meta.title || fieldName);
        labelText.appendChild(key);
      }
      row.appendChild(labelText);
      host.appendChild(row);
    });
  }

  function reorderPreviousRunsColumns(fromField, toField) {
    const from = previousRunsVisibleColumns.indexOf(fromField);
    const to = previousRunsVisibleColumns.indexOf(toField);
    if (from < 0 || to < 0 || from === to) return false;
    const next = [...previousRunsVisibleColumns];
    const moved = next.splice(from, 1)[0];
    next.splice(to, 0, moved);
    previousRunsVisibleColumns = next;
    prunePreviousRunsColumnFilters();
    return true;
  }

  function collectBenchmarkFieldPaths() {
    const preferred = [
      "source_file_basename",
      "source_label",
      "source_file",
      "importer_name",
      "ai_model",
      "ai_effort",
      "ai_assistance_profile",
      "run_timestamp",
      "run_config_hash",
      "run_config_summary",
      "run_config.model",
      "run_config.reasoning_effort",
      "run_config.codex_model",
      "run_config.codex_reasoning_effort",
      "strict_accuracy",
      "macro_f1_excluding_other",
      "precision",
      "recall",
      "f1",
      "practical_f1",
      "gold_total",
      "gold_matched",
      "recipes",
      "all_token_use",
      "quality_per_million_tokens",
      "tokens_input",
      "tokens_cached_input",
      "tokens_output",
      "tokens_reasoning",
      "tokens_total",
      "all_method_record",
      "speed_suite_record",
      "artifact_dir",
    ];
    const discovered = new Set();
    (DATA.benchmark_records || []).forEach(record => {
      addFlattenedFieldPaths(record, "", discovered, 0);
    });
    discovered.add("source_file_basename");
    discovered.add("source_label");
    discovered.add("ai_model");
    discovered.add("ai_effort");
    discovered.add("ai_assistance_profile");
    discovered.add("artifact_dir_basename");
    discovered.add("all_method_record");
    discovered.add("speed_suite_record");
    PREVIOUS_RUNS_DEFAULT_COLUMNS.forEach(fieldName => discovered.add(fieldName));

    const ordered = [];
    const seen = new Set();
    preferred.forEach(fieldName => {
      if (discovered.has(fieldName) && !seen.has(fieldName)) {
        ordered.push(fieldName);
        seen.add(fieldName);
      }
    });
    Array.from(discovered)
      .sort((a, b) => a.localeCompare(b))
      .forEach(fieldName => {
        if (!seen.has(fieldName)) {
          ordered.push(fieldName);
          seen.add(fieldName);
        }
      });
    return ordered;
  }

  function benchmarkTrendFieldHasNumericValues(fieldName) {
    if (!fieldName) return false;
    const records = Array.isArray(DATA && DATA.benchmark_records)
      ? DATA.benchmark_records
      : [];
    for (let i = 0; i < records.length; i += 1) {
      const numeric = maybeNumber(previousRunsFieldValue(records[i], fieldName));
      if (numeric != null) return true;
    }
    return false;
  }

  function collectBenchmarkTrendFieldPaths() {
    const discovered = new Set();
    BENCHMARK_TREND_DEFAULT_FIELDS.forEach(fieldName => discovered.add(fieldName));
    PREVIOUS_RUNS_SCORE_FIELDS.forEach(fieldName => discovered.add(fieldName));
    previousRunsFieldOptions.forEach(fieldName => discovered.add(fieldName));
    discovered.add("all_token_use");
    discovered.add("quality_per_million_tokens");
    discovered.add("tokens_total");
    discovered.add("tokens_input");
    discovered.add("tokens_cached_input");
    discovered.add("tokens_output");
    discovered.add("tokens_reasoning");

    const defaultSet = new Set(BENCHMARK_TREND_DEFAULT_FIELDS);
    const numericFields = Array.from(discovered)
      .map(fieldName => String(fieldName || "").trim())
      .filter(Boolean)
      .filter(fieldName => !BENCHMARK_TREND_SKIP_FIELDS.has(fieldName))
      .filter(fieldName => defaultSet.has(fieldName) || benchmarkTrendFieldHasNumericValues(fieldName));

    const ordered = [];
    const seen = new Set();
    BENCHMARK_TREND_PREFERRED_FIELDS.forEach(fieldName => {
      if (!numericFields.includes(fieldName) || seen.has(fieldName)) return;
      seen.add(fieldName);
      ordered.push(fieldName);
    });
    numericFields
      .sort((left, right) => left.localeCompare(right))
      .forEach(fieldName => {
        if (seen.has(fieldName)) return;
        seen.add(fieldName);
        ordered.push(fieldName);
      });
    return ordered;
  }

  function benchmarkTrendFieldLabel(fieldName) {
    return analysisFieldLabel(fieldName);
  }

  function addFlattenedFieldPaths(value, prefix, output, depth) {
    if (depth > 4) {
      if (prefix) output.add(prefix);
      return;
    }
    if (value == null) {
      if (prefix) output.add(prefix);
      return;
    }
    if (Array.isArray(value)) {
      if (prefix) output.add(prefix);
      return;
    }
    if (typeof value === "object") {
      const keys = Object.keys(value);
      if (!keys.length) {
        if (prefix) output.add(prefix);
        return;
      }
      keys.forEach(key => {
        const nextPrefix = prefix ? prefix + "." + key : key;
        addFlattenedFieldPaths(value[key], nextPrefix, output, depth + 1);
      });
      return;
    }
    if (prefix) output.add(prefix);
  }

  function currentPreviousRunsFilterResult() {
    if (previousRunsFilterResultCache) return previousRunsFilterResultCache;
    previousRunsFilterResultCache = computePreviousRunsFilterResult();
    return previousRunsFilterResultCache;
  }

  function computePreviousRunsFilterResult() {
    const rawRecords = filteredBenchmarks();
    const quickFiltered = applyPreviousRunsQuickFilters(rawRecords);
    const allRecords = quickFiltered.records;
    const quickFilterLabels = activePreviousRunsQuickFilterLabels(quickFiltered.context.enabled);
    const quickFiltersText = quickFilterLabels.length ? quickFilterLabels.join("; ") : "none";
    if (!allRecords.length) {
      const activeExpression = activePreviousRunsColumnFilters()
        .map(filter => {
          const meta = previousRunsColumnMeta(filter.field);
          return meta.label + " " + formatPreviousRunsColumnFilterSummary(filter.field, filter);
        })
        .join("; ");
      updatePreviousRunsFilterStatus({
        total: rawRecords.length,
        matched: 0,
        expression: activeExpression || "(none)",
        quick_filters_text: quickFiltersText,
        column_filter_global_mode: normalizePreviousRunsColumnFilterGlobalMode(
          previousRunsColumnFilterGlobalMode
        ),
        error: null,
      });
      return {
        records: [],
        total: rawRecords.length,
        error: null,
      };
    }

    const compiled = compilePreviousRunsFilterPredicate();
    const matchedRecords = compiled.error
      ? allRecords
      : allRecords.filter(compiled.predicate);
    updatePreviousRunsFilterStatus({
      total: rawRecords.length,
      matched: matchedRecords.length,
      expression: compiled.expression,
      quick_filters_text: quickFiltersText,
      column_filter_global_mode: compiled.global_mode,
      error: compiled.error,
    });
    return {
      records: matchedRecords,
      total: rawRecords.length,
      error: compiled.error,
    };
  }

  function compilePreviousRunsFilterPredicate() {
    const filters = activePreviousRunsColumnFilters();
    const globalMode = normalizePreviousRunsColumnFilterGlobalMode(
      previousRunsColumnFilterGlobalMode
    );
    if (!filters.length) {
      return {
        predicate: () => true,
        expression: "(none)",
        global_mode: globalMode,
        error: null,
      };
    }

    for (const filter of filters) {
      if (filter.operator !== "regex") continue;
      try {
        new RegExp(String(filter.value || ""), "i");
      } catch (error) {
        return {
          predicate: () => true,
          expression: formatPreviousRunsColumnFilterSummary(filter.field, filter),
          global_mode: globalMode,
          error: "Invalid regex for " + filter.field + ".",
        };
      }
    }

    const groupedFilters = groupPreviousRunsFiltersByField(filters);
    const topJoinLabel = " " + String(PREVIOUS_RUNS_COLUMN_FILTER_MODE_LABEL[globalMode] || globalMode).toUpperCase() + " ";

    return {
      predicate: record => recordMatchesPreviousRunsFilterGroups(record, groupedFilters, globalMode),
      expression: groupedFilters
        .map(group => {
          const meta = previousRunsColumnMeta(group.field);
          const mode = normalizePreviousRunsColumnFilterMode(group.mode);
          const joinLabel = " " + String(PREVIOUS_RUNS_COLUMN_FILTER_MODE_LABEL[mode] || mode).toUpperCase() + " ";
          const clauseText = group.clauses
            .map(clause => formatPreviousRunsColumnFilterSummary(group.field, clause))
            .join(joinLabel);
          if (group.clauses.length > 1) {
            return meta.label + " (" + clauseText + ")";
          }
          return meta.label + " " + clauseText;
        })
        .join(topJoinLabel),
      global_mode: globalMode,
      error: null,
    };
  }

  function evaluatePreviousRunsFilterOperator(value, operator, expected) {
    const op = String(operator || "contains");
    const wanted = String(expected || "");

    if (op === "is_empty") return isEmptyRuleValue(value);
    if (op === "not_empty") return !isEmptyRuleValue(value);

    const actualText = normalizeRuleValue(value);
    const expectedText = normalizeRuleValue(wanted);
    if (op === "contains") return actualText.includes(expectedText);
    if (op === "not_contains") return !actualText.includes(expectedText);
    if (op === "starts_with") return actualText.startsWith(expectedText);
    if (op === "ends_with") return actualText.endsWith(expectedText);
    if (op === "regex") {
      try {
        const pattern = new RegExp(wanted, "i");
        return pattern.test(String(value == null ? "" : value));
      } catch (error) {
        return false;
      }
    }

    const leftNumber = maybeNumber(value);
    const rightNumber = maybeNumber(wanted);
    if (op === "gt") return leftNumber != null && rightNumber != null && leftNumber > rightNumber;
    if (op === "gte") return leftNumber != null && rightNumber != null && leftNumber >= rightNumber;
    if (op === "lt") return leftNumber != null && rightNumber != null && leftNumber < rightNumber;
    if (op === "lte") return leftNumber != null && rightNumber != null && leftNumber <= rightNumber;

    if (op === "eq" || op === "neq") {
      let equal = false;
      if (leftNumber != null && rightNumber != null) {
        equal = leftNumber === rightNumber;
      } else {
        equal = actualText === expectedText;
      }
      return op === "eq" ? equal : !equal;
    }
    return false;
  }

  function previousRunsFieldValue(record, fieldPath) {
    if (fieldPath === "source_file_basename") return basename(record.source_file || "");
    if (fieldPath === "source_label") return sourceLabelForRecord(record);
    if (fieldPath === "ai_model") return aiModelLabelForRecord(record);
    if (fieldPath === "ai_effort") return aiEffortLabelForRecord(record);
    if (fieldPath === "ai_assistance_profile") return aiAssistanceProfileLabelForRecord(record);
    if (fieldPath === "ai_model_effort") return aiModelEffortLabelForRecord(record);
    if (fieldPath === "all_token_use") {
      return discountedTokenTotalForRecord(record);
    }
    if (fieldPath === "conversion_seconds_per_recipe") {
      return previousRunsMetricPerRecipe(
        previousRunsFieldValue(record, "run_config.single_offline_split_cache.conversion_seconds"),
        record && record.recipes,
      );
    }
    if (fieldPath === "all_token_use_per_recipe") {
      return previousRunsMetricPerRecipe(
        previousRunsFieldValue(record, "all_token_use"),
        record && record.recipes,
      );
    }
    if (fieldPath === "quality_per_million_tokens") {
      return benchmarkQualityPerMillionTokensForRecord(record);
    }
    if (fieldPath === "artifact_dir_basename") return basename(record.artifact_dir || "");
    if (fieldPath === "all_method_record") return isAllMethodBenchmarkRecord(record);
    if (fieldPath === "speed_suite_record") return isSpeedBenchmarkRecord(record);
    if (!fieldPath) return null;

    const parts = fieldPath.split(".");
    let current = record;
    for (let idx = 0; idx < parts.length; idx += 1) {
      const key = parts[idx];
      if (current == null || typeof current !== "object" || !(key in current)) {
        return null;
      }
      current = current[key];
    }
    if (Array.isArray(current) || (current && typeof current === "object")) {
      try {
        return JSON.stringify(current);
      } catch (error) {
        return String(current);
      }
    }
    return current;
  }

  function maybeNumber(value) {
    if (value == null) return null;
    if (typeof value === "number" && Number.isFinite(value)) return value;
    if (typeof value === "boolean") return value ? 1 : 0;
    const text = String(value).trim();
    if (!text) return null;
    const parsed = Number(text);
    return Number.isFinite(parsed) ? parsed : null;
  }

  function normalizeRuleValue(value) {
    if (value == null) return "";
    if (typeof value === "boolean") return value ? "true" : "false";
    return String(value).toLowerCase().trim();
  }

  function isEmptyRuleValue(value) {
    if (value == null) return true;
    if (typeof value === "string") return value.trim() === "";
    if (Array.isArray(value)) return value.length === 0;
    return false;
  }

  function updatePreviousRunsFilterStatus(result) {
    const status = document.getElementById("previous-runs-filter-status");
    if (!status) return;
    const header = "Showing " + result.matched + " of " + result.total + " rows.";
    const quickFiltersPart = result.quick_filters_text
      ? " Quick filters: " + result.quick_filters_text + "."
      : "";
    const activeFilters = activePreviousRunsColumnFilters();
    const filtersPart = activeFilters.length
      ? " Active filters: " + result.expression + "."
      : " Active filters: none.";
    const globalMode = normalizePreviousRunsColumnFilterGlobalMode(
      result.column_filter_global_mode
    );
    const globalModePart = " Column combine: " + (
      globalMode === "or"
        ? "OR across columns."
        : "AND across columns."
    );
    if (result.error) {
      status.textContent = (
        header +
        quickFiltersPart +
        filtersPart +
        globalModePart +
        " Filter error: " +
        result.error +
        " (showing unfiltered rows)."
      );
      status.classList.add("filter-error");
      return;
    }
    status.textContent = header + quickFiltersPart + filtersPart + globalModePart;
    status.classList.remove("filter-error");
  }

  // ---- Render all sections ----
  function renderAll() {
    previousRunsFilterResultCache = null;
    renderPreviousRuns();
    renderBenchmarkTrendChart();
    renderCompareControlSection();
    renderLatestRuntime();
    renderPerLabel();
    renderBoundary();
    refreshMetricTooltipTargets();
    setupResizableDashboardTables();
  }

  function ensureResizableTableColgroup(table, columnCount) {
    if (!(table instanceof HTMLTableElement) || columnCount <= 0) return [];
    let colgroup = table.querySelector("colgroup");
    if (!colgroup) {
      colgroup = document.createElement("colgroup");
      table.insertBefore(colgroup, table.firstChild);
    }
    while (colgroup.children.length < columnCount) {
      colgroup.appendChild(document.createElement("col"));
    }
    while (colgroup.children.length > columnCount) {
      colgroup.removeChild(colgroup.lastChild);
    }
    return Array.from(colgroup.querySelectorAll("col"));
  }

  function setupResizableDashboardTable(table, options) {
    if (!(table instanceof HTMLTableElement)) return;
    const tableKey = String((options && options.tableKey) || table.id || "").trim();
    if (!tableKey) return;
    let cells = Array.from(table.querySelectorAll("thead tr:first-child > th"));
    if (!cells.length) {
      const fallbackRow = table.querySelector("tbody tr");
      if (fallbackRow) {
        cells = Array.from(fallbackRow.querySelectorAll(":scope > th, :scope > td"));
      }
    }
    if (!cells.length) return;
    const cols = ensureResizableTableColgroup(table, cells.length);
    if (!cols.length) return;
    table.classList.add("dashboard-resizable-table");
    cells.forEach((cell, index) => {
      if (!(cell instanceof HTMLElement)) return;
      const columnKey = "col_" + index;
      const col = cols[index];
      const persistedWidth = dashboardTableColumnWidth(tableKey, columnKey);
      if (persistedWidth != null) {
        col.style.width = persistedWidth + "px";
      }

      Array.from(cell.querySelectorAll(".dashboard-table-resize-handle")).forEach(handle => {
        handle.remove();
      });
      const resizeHandle = document.createElement("span");
      resizeHandle.className = "dashboard-table-resize-handle";
      resizeHandle.setAttribute("aria-hidden", "true");
      resizeHandle.draggable = false;
      resizeHandle.addEventListener("mousedown", event => {
        event.preventDefault();
        event.stopPropagation();
        const startX = event.clientX;
        const startWidth = col.getBoundingClientRect().width || cell.getBoundingClientRect().width;
        const minWidth = DASHBOARD_TABLE_COLUMN_MIN_WIDTH;
        const maxWidth = DASHBOARD_TABLE_COLUMN_MAX_WIDTH;
        document.body.classList.add("dashboard-table-resizing");

        const onMove = moveEvent => {
          const nextWidth = Math.max(
            minWidth,
            Math.min(maxWidth, startWidth + (moveEvent.clientX - startX))
          );
          col.style.width = nextWidth + "px";
          setDashboardTableColumnWidth(tableKey, columnKey, nextWidth);
        };

        const onUp = () => {
          document.body.classList.remove("dashboard-table-resizing");
          window.removeEventListener("mousemove", onMove);
          window.removeEventListener("mouseup", onUp);
          persistDashboardUiState();
        };

        window.addEventListener("mousemove", onMove);
        window.addEventListener("mouseup", onUp);
      });
      cell.appendChild(resizeHandle);
    });
  }

  function setupResizableDashboardTables() {
    // Keep Per-Label Breakdown content-sized and clear previously persisted drag widths.
    clearDashboardTableColumnWidths("per-label-table");
  }

  function latestPreferredBenchmarkRecord(records) {
    const sorted = [...records].sort((a, b) =>
      compareRunTimestampDesc(a.run_timestamp, b.run_timestamp)
    );
    const nonSpeed = sorted.filter(r => !isSpeedBenchmarkRecord(r));
    const preferred = nonSpeed.length > 0 ? nonSpeed : sorted;
    if (!preferred.length) return null;
    const latestTs = String(preferred[0].run_timestamp || "");
    const latestGroup = preferred.filter(
      record => String(record.run_timestamp || "") === latestTs
    );
    if (latestGroup.length <= 1) {
      return latestGroup[0];
    }
    let best = latestGroup[0];
    function score(record) {
      const model = aiModelForRecord(record);
      const effort = aiEffortForRecord(record);
      const pipeline = runConfigValue(record, ["llm_recipe_pipeline", "llm_pipeline"]);
      const pipelineText = String(pipeline || "").toLowerCase();
      const pipelineOn = pipelineText && pipelineText !== "off";
      return [
        model ? 2 : 0,
        effort ? 1 : 0,
        pipelineOn ? 1 : 0,
      ];
    }
    latestGroup.slice(1).forEach(candidate => {
      const bestScore = score(best);
      const nextScore = score(candidate);
      for (let i = 0; i < bestScore.length; i++) {
        if (nextScore[i] > bestScore[i]) {
          best = candidate;
          return;
        }
        if (nextScore[i] < bestScore[i]) {
          return;
        }
      }
    });
    return best;
  }

  function preferredRuntimeContextRecord(records) {
    const candidates = Array.isArray(records) ? records.filter(record => !!record) : [];
    if (!candidates.length) return null;
    let best = candidates[0];
    function score(record) {
      const model = aiModelForRecord(record);
      const effort = aiEffortForRecord(record);
      const pipeline = runConfigValue(record, ["llm_recipe_pipeline", "llm_pipeline"]);
      const pipelineText = String(pipeline || "").toLowerCase();
      const pipelineOn = pipelineText && pipelineText !== "off";
      return [
        model ? 2 : 0,
        effort ? 1 : 0,
        pipelineOn ? 1 : 0,
      ];
    }
    candidates.slice(1).forEach(candidate => {
      const bestScore = score(best);
      const nextScore = score(candidate);
      for (let i = 0; i < bestScore.length; i++) {
        if (nextScore[i] > bestScore[i]) {
          best = candidate;
          return;
        }
        if (nextScore[i] < bestScore[i]) {
          return;
        }
      }
      if (
        compareRunTimestampDesc(candidate.run_timestamp, best.run_timestamp) < 0
      ) {
        best = candidate;
      }
    });
    return best;
  }

  function latestRuntimeSummaryForRecords(records) {
    const sorted = [...(records || [])].sort((a, b) =>
      compareRunTimestampDesc(a.run_timestamp, b.run_timestamp)
    );
    const nonSpeed = sorted.filter(r => !isSpeedBenchmarkRecord(r));
    const preferredRecords = nonSpeed.length > 0 ? nonSpeed : sorted;
    const latestRunGroup = latestRunGroupRecords(preferredRecords, record => !!record);
    const latestRunRecords = latestRunGroup.records;
    if (!latestRunRecords.length) return null;

    const contextRecord = preferredRuntimeContextRecord(latestRunRecords) || latestRunRecords[0];
    if (!contextRecord) return null;
    const runGroupInfo = benchmarkRunGroupInfo(contextRecord);
    const pipelineMode = runConfigValue(contextRecord, ["llm_recipe_pipeline", "llm_pipeline"]);
    const tokenTotals = discountedTokenTotalForRecords(latestRunRecords);
    const quality = aggregateBenchmarkQuality(latestRunRecords);
    const qualityPerMillionTokens = qualityPerMillionTokensValue(
      quality.qualityScore,
      tokenTotals.discountedTokenTotal,
    );

    const codexRecords = latestRunRecords.filter(record => benchmarkVariantForRecord(record) === "codexfarm");
    const vanillaRecords = latestRunRecords.filter(record => benchmarkVariantForRecord(record) === "vanilla");
    let qualityDeltaVsVanilla = null;
    let qualityDeltaPerMillionExtraTokensVsVanilla = null;
    if (codexRecords.length > 0 && vanillaRecords.length > 0) {
      const codexQuality = aggregateBenchmarkQuality(codexRecords, quality.metricKey);
      const vanillaQuality = aggregateBenchmarkQuality(vanillaRecords, codexQuality.metricKey);
      const codexTokens = discountedTokenTotalForRecords(codexRecords).discountedTokenTotal;
      const vanillaTokens = discountedTokenTotalForRecords(vanillaRecords).discountedTokenTotal;
      if (
        codexQuality.qualityScore != null &&
        vanillaQuality.qualityScore != null
      ) {
        qualityDeltaVsVanilla = codexQuality.qualityScore - vanillaQuality.qualityScore;
      }
      const deltaTokens = (
        codexTokens != null && vanillaTokens != null
          ? codexTokens - vanillaTokens
          : null
      );
      if (
        qualityDeltaVsVanilla != null &&
        deltaTokens != null &&
        Number.isFinite(deltaTokens) &&
        deltaTokens > 0
      ) {
        qualityDeltaPerMillionExtraTokensVsVanilla =
          (qualityDeltaVsVanilla * QUALITY_PER_TOKEN_SCALE) / deltaTokens;
      }
    }
    const peerStats = runtimeQualityPeerStats(
      preferredRecords,
      runGroupInfo.runGroupKey,
      quality.metricKey,
    );

    return {
      runGroupLabel: String(latestRunGroup.runGroupLabel || contextRecord.run_timestamp || "").trim(),
      runGroupKey: String((runGroupInfo && runGroupInfo.runGroupKey) || "").trim(),
      runGroupRecordCount: latestRunRecords.length,
      model: aiModelForRecord(contextRecord),
      effort: aiEffortForRecord(contextRecord),
      pipelineMode,
      sourceLabel: sourceLabelForRecord(contextRecord),
      sourceTitle: sourceTitleForRecord(contextRecord),
      importerLabel: importerLabelForRecord(contextRecord),
      tokenUseValue: tokenTotals.discountedTokenTotal,
      tokenUseDisplay: formatTokenCountCompact(tokenTotals.discountedTokenTotal),
      qualityMetricKey: quality.metricKey,
      qualityScore: quality.qualityScore,
      qualityPerMillionTokens,
      qualityDeltaVsVanilla,
      qualityDeltaPerMillionExtraTokensVsVanilla,
      peerQualityStats: peerStats,
    };
  }

  function hasHighchartsStock() {
    return (
      typeof window !== "undefined" &&
      window.Highcharts &&
      typeof window.Highcharts.stockChart === "function"
    );
  }

  function hasHighchartsBasicChart() {
    return (
      typeof window !== "undefined" &&
      window.Highcharts &&
      typeof window.Highcharts.chart === "function"
    );
  }

  function destroyBenchmarkTrendChartHost(hostId) {
    const key = String(hostId || "").trim();
    if (!key) return;
    const existingChart = benchmarkTrendChartsByHostId[key];
    if (existingChart && typeof existingChart.destroy === "function") {
      try {
        existingChart.destroy();
      } catch (error) {
        // Ignore destroy failures from stale/incomplete chart instances.
      }
    }
    delete benchmarkTrendChartsByHostId[key];
  }

  function hasHighchartsAreaRange() {
    return (
      typeof window !== "undefined" &&
      window.Highcharts &&
      window.Highcharts.seriesTypes &&
      typeof window.Highcharts.seriesTypes.arearange === "function"
    );
  }

  function benchmarkVariantFromPathOrPipeline(record) {
    const path = benchmarkArtifactPath(record);
    if (path.includes("/codexfarm/") || path.endsWith("/codexfarm")) return "codexfarm";
    if (path.includes("/vanilla/") || path.endsWith("/vanilla")) return "vanilla";
    return null;
  }

  function aiAssistanceProfileForRecord(record) {
    const explicit = cleanConfigValue(record && record.ai_assistance_profile);
    if (explicit) {
      const explicitKey = String(explicit).toLowerCase().replace(/[-\s]+/g, "_");
      if (["deterministic", "line_role_only", "recipe_only", "full_stack", "other"].includes(explicitKey)) {
        return explicitKey;
      }
    }
    const pipelineOrPathVariant = benchmarkVariantFromPathOrPipeline(record);
    const path = benchmarkArtifactPath(record);
    const isOfficialPairedBenchmark =
      path.includes("/benchmark-vs-golden/") &&
      (
        path.includes("/single-offline-benchmark/") ||
        path.includes("/single-profile-benchmark/")
      );
    const recipePipeline = runConfigValue(record, ["llm_recipe_pipeline", "llm_pipeline"]);
    const lineRolePipeline = runConfigValue(record, ["line_role_pipeline"]);
    const recipeOn = recipePipeline && String(recipePipeline).toLowerCase() !== "off";
    const lineRoleOn = lineRolePipeline && String(lineRolePipeline).toLowerCase() !== "off";
    if (recipeOn && lineRoleOn) return "full_stack";
    if (
      isOfficialPairedBenchmark &&
      pipelineOrPathVariant === "codexfarm" &&
      recipeOn &&
      !lineRoleOn
    ) {
      return "full_stack";
    }
    if (recipeOn) return "recipe_only";
    if (lineRoleOn) return "line_role_only";
    if (
      isOfficialPairedBenchmark &&
      pipelineOrPathVariant === "vanilla" &&
      (!recipePipeline || String(recipePipeline).toLowerCase() === "off") &&
      !lineRoleOn
    ) {
      return "deterministic";
    }
    if (recipePipeline || lineRolePipeline) return "deterministic";
    if (isOfficialPairedBenchmark && pipelineOrPathVariant === "codexfarm") {
      return "full_stack";
    }
    if (isOfficialPairedBenchmark && pipelineOrPathVariant === "vanilla") {
      return "deterministic";
    }
    if (rawAiModelForRecord(record) || rawAiEffortForRecord(record)) return "full_stack";
    return "other";
  }

  function aiAssistanceProfileLabelForRecord(record) {
    const profile = aiAssistanceProfileForRecord(record);
    if (profile === "deterministic") return "AI off";
    if (profile === "line_role_only") return "Line-role only";
    if (profile === "recipe_only") return "Recipe only";
    if (profile === "full_stack") return "Full-stack AI";
    return "Unknown";
  }

  function benchmarkVariantForRecord(record) {
    const explicit = cleanConfigValue(record && record.benchmark_variant);
    if (explicit) {
      const explicitKey = String(explicit).toLowerCase().replace(/[-\s]+/g, "_");
      if (["vanilla", "codexfarm", "deterministic", "line_role_only", "recipe_only", "full_stack", "other"].includes(explicitKey)) {
        return explicitKey;
      }
    }
    const pipelineOrPathVariant = benchmarkVariantFromPathOrPipeline(record);
    const profile = aiAssistanceProfileForRecord(record);
    const path = benchmarkArtifactPath(record);
    const isOfficialPairedBenchmark =
      path.includes("/benchmark-vs-golden/") &&
      (
        path.includes("/single-offline-benchmark/") ||
        path.includes("/single-profile-benchmark/")
      );
    if (isOfficialPairedBenchmark && pipelineOrPathVariant === "vanilla" && profile === "deterministic") {
      return "vanilla";
    }
    if (isOfficialPairedBenchmark && pipelineOrPathVariant === "codexfarm" && profile === "full_stack") {
      return "codexfarm";
    }
    return profile;
  }

  function benchmarkRunGroupInfo(record) {
    const fallbackTimestamp = String((record && record.run_timestamp) || "").trim();
    const rawPathCandidates = [
      String((record && record.artifact_dir) || "").trim(),
      String((record && record.run_dir) || "").trim(),
      String((record && record.report_path) || "").trim(),
    ]
      .filter(value => value)
      .map(value => value.replace(/\\/g, "/"));
    let runToken = "";
    for (let p = 0; p < rawPathCandidates.length; p++) {
      const rawPath = rawPathCandidates[p];
      const parts = rawPath.split("/").filter(Boolean);
      for (let i = 0; i < parts.length; i++) {
        const segment = String(parts[i] || "").toLowerCase();
        if (segment !== "benchmark-vs-golden") continue;
        for (let j = i + 1; j < parts.length; j++) {
          const candidate = String(parts[j] || "");
          if (!isTimestampTokenText(candidate)) continue;
          runToken = candidate;
          break;
        }
        if (runToken) break;
      }
      if (runToken) break;
    }
    if (!runToken) {
      for (let p = 0; p < rawPathCandidates.length; p++) {
        const rawPath = rawPathCandidates[p];
        const parts = rawPath.split("/").filter(Boolean);
        for (let i = 0; i < parts.length; i++) {
          const candidate = String(parts[i] || "");
          if (!isTimestampTokenText(candidate)) continue;
          runToken = candidate;
          break;
        }
        if (runToken) break;
      }
    }
    const rawPath = rawPathCandidates[0] || "";
    const runGroupLabel = runToken || fallbackTimestamp || "-";
    const runGroupKey = runToken || fallbackTimestamp || rawPath || "-";
    const runGroupTimestampText = runToken || fallbackTimestamp || "";
    return { runGroupKey, runGroupLabel, runGroupTimestampText };
  }

  function benchmarkRunGroupXAxisTimestampMs(record, runGroup) {
    const candidates = [];
    const groupTimestampText = String((runGroup && runGroup.runGroupTimestampText) || "").trim();
    if (groupTimestampText) candidates.push(groupTimestampText);
    const recordTimestampText = String((record && record.run_timestamp) || "").trim();
    if (recordTimestampText) candidates.push(recordTimestampText);
    for (let i = 0; i < candidates.length; i++) {
      const ts = parseTs(candidates[i]);
      if (!ts) continue;
      return ts.getTime();
    }
    return null;
  }

  function benchmarkSeriesFromRecords(records, metricKey, variantKey) {
    return records
      .map(record => {
        if (!record) return null;
        if (variantKey && benchmarkVariantForRecord(record) !== variantKey) return null;
        const parsedValue = maybeNumber(previousRunsFieldValue(record, metricKey));
        if (parsedValue == null) return null;
        const runGroup = benchmarkRunGroupInfo(record);
        const xMs = benchmarkRunGroupXAxisTimestampMs(record, runGroup);
        if (xMs == null) return null;
        return {
          x: xMs,
          y: parsedValue,
          custom: {
            runGroupKey: runGroup.runGroupKey,
            runGroupLabel: runGroup.runGroupLabel,
            runTimestamp: String(record.run_timestamp || "").trim(),
            sourceLabel: sourceLabelForRecord(record),
            sourceTitle: sourceTitleForRecord(record),
            variant: benchmarkVariantForRecord(record),
          },
        };
      })
      .filter(point => point !== null)
      .sort((a, b) => a.x - b.x);
  }

  function trendSeriesPointForRunGroup(series, runGroupKey, hoveredX) {
    if (!series || !Array.isArray(series.points)) return null;
    let best = null;
    const target = Number(hoveredX || 0);
    series.points.forEach(point => {
      if (!point) return;
      const custom = (point.options && point.options.custom) || point.custom || {};
      if (String(custom.runGroupKey || "") !== runGroupKey) return;
      if (!best) {
        best = point;
        return;
      }
      const pointDelta = Math.abs(Number(point.x || 0) - target);
      const bestDelta = Math.abs(Number(best.x || 0) - target);
      if (pointDelta < bestDelta) {
        best = point;
      }
    });
    return best;
  }

  function rollingTrendWindowSize(count) {
    const n = Math.max(0, Number(count || 0));
    if (n <= 3) return n;
    if (n <= 5) return 3;
    if (n <= 9) return 5;
    return 7;
  }

  function medianFromSortedNumbers(values) {
    const usable = Array.isArray(values)
      ? values
        .map(value => Number(value))
        .filter(value => Number.isFinite(value))
        .sort((a, b) => a - b)
      : [];
    if (!usable.length) return null;
    const mid = Math.floor(usable.length / 2);
    if (usable.length % 2 === 1) return usable[mid];
    return (usable[mid - 1] + usable[mid]) / 2;
  }

  function aggregateTrendSeriesPoints(points) {
    const usable = Array.isArray(points)
      ? points
        .map(point => {
          const x = Number(point && point.x);
          const y = Number(point && point.y);
          if (!Number.isFinite(x) || !Number.isFinite(y)) return null;
          const custom = (point && point.custom) || {};
          const runGroupKey = String(custom.runGroupKey || "").trim();
          return { x, y, custom, runGroupKey };
        })
        .filter(point => point !== null)
      : [];
    if (!usable.length) return [];
    const groups = Object.create(null);
    usable.forEach(point => {
      const key = point.runGroupKey || ("x:" + String(point.x));
      if (!Object.prototype.hasOwnProperty.call(groups, key)) {
        groups[key] = [];
      }
      groups[key].push(point);
    });
    return Object.keys(groups)
      .map(key => {
        const group = groups[key];
        if (!Array.isArray(group) || !group.length) return null;
        const medianY = medianFromSortedNumbers(group.map(point => point.y));
        if (!Number.isFinite(medianY)) return null;
        const anchor = group[0];
        return {
          x: anchor.x,
          y: medianY,
          custom: {
            ...anchor.custom,
            aggregatedRunGroup: true,
            aggregatedPointCount: group.length,
          },
        };
      })
      .filter(point => point !== null)
      .sort((a, b) => a.x - b.x);
  }

  function buildRollingTrend(points) {
    const usable = aggregateTrendSeriesPoints(points);
    if (!usable.length) return null;

    const windowSize = rollingTrendWindowSize(usable.length);
    if (!windowSize) return null;
    const halfWindow = Math.floor(windowSize / 2);
    const trendPoints = usable.map((point, index) => {
      const start = Math.max(0, index - halfWindow);
      const end = Math.min(usable.length, start + windowSize);
      const adjustedStart = Math.max(0, end - windowSize);
      const windowPoints = usable.slice(adjustedStart, end);
      const meanY = windowPoints.reduce((sum, item) => sum + item.y, 0) / windowPoints.length;
      return {
        x: point.x,
        y: meanY,
        custom: point.custom,
      };
    });
    return { trendPoints, windowSize };
  }

  function trendSeriesIdPart(name, index) {
    const base = String(name || "series")
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, "-")
      .replace(/^-+|-+$/g, "");
    const safe = base || "series";
    return "trend-series-" + index + "-" + safe;
  }

  function withTrendOverlays(baseSeriesList) {
    const output = [];
    (baseSeriesList || []).forEach((baseSeries, index) => {
      if (!baseSeries) return;
      const baseId = trendSeriesIdPart(baseSeries.name, index);
      const baseWithId = {
        ...baseSeries,
        id: baseId,
      };
      output.push(baseWithId);

      const rollingTrend = buildRollingTrend(baseSeries.data);
      if (!rollingTrend) return;

      output.push({
        id: baseId + "-trendline",
        name: baseSeries.name + " rolling trend",
        type: "line",
        linkedTo: baseId,
        showInLegend: false,
        enableMouseTracking: false,
        color: baseSeries.color,
        dashStyle: "ShortDash",
        lineWidth: 1.75,
        marker: { enabled: false },
        zIndex: 2,
        custom: { isTrendOverlay: true },
        data: rollingTrend.trendPoints,
        turboThreshold: 0,
      });
    });
    return output;
  }

  function isTrendOverlaySeries(series) {
    const options = (series && series.options) || {};
    const custom = (options && options.custom) || {};
    return Boolean(custom.isTrendOverlay);
  }

  function benchmarkTrendShiftHexColor(baseColor, shift) {
    const match = String(baseColor || "").trim().match(/^#([0-9a-fA-F]{6})$/);
    if (!match) return String(baseColor || "");
    const raw = match[1];
    function next(start) {
      const parsed = Number.parseInt(raw.slice(start, start + 2), 16);
      if (!Number.isFinite(parsed)) return "00";
      const clamped = Math.max(0, Math.min(255, parsed + shift));
      return clamped.toString(16).padStart(2, "0");
    }
    return "#" + next(0) + next(2) + next(4);
  }

  function benchmarkTrendMetricColors(metricKey, metricIndex) {
    if (Object.prototype.hasOwnProperty.call(BENCHMARK_TREND_COLOR_OVERRIDES, metricKey)) {
      return BENCHMARK_TREND_COLOR_OVERRIDES[metricKey];
    }
    const base = BENCHMARK_TREND_BASE_COLORS[
      Math.abs(Number(metricIndex || 0)) % BENCHMARK_TREND_BASE_COLORS.length
    ];
    return {
      default: base,
      vanilla: benchmarkTrendShiftHexColor(base, 58),
      codexfarm: base,
      other: benchmarkTrendShiftHexColor(base, 20),
    };
  }

  function buildBenchmarkTrendSeries(records) {
    const metricKeys = normalizeBenchmarkTrendFieldList(
      benchmarkTrendSelectedFields,
      { allow_empty: Array.isArray(benchmarkTrendSelectedFields) },
    );
    if (!metricKeys.length) return [];
    const metricDefs = metricKeys.map((key, index) => ({
      key,
      colors: benchmarkTrendMetricColors(key, index),
    }));
    const variantOrder = ["vanilla", "codexfarm", "other"];
    const presentVariants = new Set(
      records.map(record => benchmarkVariantForRecord(record))
    );
    const hasPairedVariants =
      presentVariants.has("vanilla") || presentVariants.has("codexfarm");

    const baseSeries = [];
    if (!hasPairedVariants) {
      metricDefs.forEach(metric => {
        baseSeries.push({
          name: metric.key,
          type: "scatter",
          lineWidth: 0,
          marker: {
            enabled: true,
            radius: 3,
          },
          color: metric.colors.default,
          data: benchmarkSeriesFromRecords(records, metric.key),
          turboThreshold: 0,
        });
      });
      return withTrendOverlays(
        baseSeries.filter(series => Array.isArray(series.data) && series.data.length > 0)
      );
    }

    metricDefs.forEach(metric => {
      variantOrder.forEach(variant => {
        if (!presentVariants.has(variant)) return;
        const points = benchmarkSeriesFromRecords(records, metric.key, variant);
        if (!points.length) return;
        baseSeries.push({
          name: metric.key + " (" + variant + ")",
          type: "scatter",
          lineWidth: 0,
          marker: {
            enabled: true,
            radius: 3,
          },
          color: metric.colors[variant] || metric.colors.default,
          data: points,
          turboThreshold: 0,
        });
      });
    });
    return withTrendOverlays(baseSeries);
  }

  function compareControlChartSeriesColor(index) {
    const palette = BENCHMARK_TREND_BASE_COLORS;
    if (!Array.isArray(palette) || !palette.length) return "#355471";
    const idx = Math.abs(Number(index || 0)) % palette.length;
    return String(palette[idx] || "#355471");
  }

  function compareControlBarPointColor(index) {
    const palette = COMPARE_CONTROL_BAR_POINT_COLORS;
    if (!Array.isArray(palette) || !palette.length) return "rgba(143, 166, 186, 0.82)";
    const idx = Math.abs(Number(index || 0)) % palette.length;
    return String(palette[idx] || "rgba(143, 166, 186, 0.82)");
  }

  function compareControlStablePaletteIndex(compareField, groupKey) {
    const seed = (
      String(compareField || "").trim().toLowerCase() +
      "::" +
      String(groupKey || "").trim()
    );
    if (!seed) return 0;
    let hash = 2166136261;
    for (let i = 0; i < seed.length; i++) {
      hash ^= seed.charCodeAt(i);
      hash = Math.imul(hash, 16777619);
    }
    return hash >>> 0;
  }

  function compareControlScatterPointCustomForRecord(record) {
    if (!record || typeof record !== "object") {
      return {
        runTimestamp: "",
        sourceLabel: "",
        sourceTitle: "",
        variant: "",
        runGroupKey: "",
        runGroupLabel: "",
      };
    }
    const runGroup = benchmarkRunGroupInfo(record);
    return {
      runTimestamp: String(record.run_timestamp || "").trim(),
      sourceLabel: sourceLabelForRecord(record),
      sourceTitle: sourceTitleForRecord(record),
      variant: benchmarkVariantForRecord(record),
      runGroupKey: String((runGroup && runGroup.runGroupKey) || "").trim(),
      runGroupLabel: String((runGroup && runGroup.runGroupLabel) || "").trim(),
    };
  }

  function compareControlNumericControlledComparablePairs(
    records,
    outcomeField,
    compareField,
    holdFields,
  ) {
    const hold = uniqueStringList(holdFields);
    if (!hold.length) {
      return compareControlPairs(records, outcomeField, compareField);
    }
    const strata = Object.create(null);
    records.forEach(record => {
      const outcome = maybeNumber(previousRunsFieldValue(record, outcomeField));
      const compare = maybeNumber(previousRunsFieldValue(record, compareField));
      if (outcome == null || compare == null) return;
      const stratumKey = hold
        .map(fieldName => analysisComparableValue(previousRunsFieldValue(record, fieldName)))
        .join("||");
      if (!Object.prototype.hasOwnProperty.call(strata, stratumKey)) {
        strata[stratumKey] = [];
      }
      strata[stratumKey].push({
        x: compare,
        y: outcome,
        record,
      });
    });
    const comparablePairs = [];
    Object.keys(strata).forEach(stratumKey => {
      const rows = strata[stratumKey];
      if (!Array.isArray(rows) || rows.length < 2) return;
      const distinctX = new Set(rows.map(row => row.x)).size;
      if (distinctX < 2) return;
      rows.forEach(row => comparablePairs.push(row));
    });
    return comparablePairs;
  }

  function compareControlChartSegments(records, state, catalog) {
    if (!state.split_field) {
      return [
        {
          key: "__all_visible_rows__",
          label: "All visible rows",
          records,
        },
      ];
    }
    const splitSegments = compareControlSplitSegments(records, state.split_field, catalog);
    if (splitSegments.length) return splitSegments;
    return [
      {
        key: "__all_visible_rows__",
        label: "All visible rows",
        records,
      },
    ];
  }

  function compareControlChartModeSummary(state) {
    const normalizedState = normalizeCompareControlState(state);
    if (normalizedState.view_mode === "controlled") {
      if (normalizedState.split_field) {
        return "Controlled comparison, split by " + compareControlChartFieldLabel(normalizedState.split_field);
      }
      return "Controlled comparison";
    }
    if (normalizedState.split_field) {
      return "Raw comparison, split by " + compareControlChartFieldLabel(normalizedState.split_field);
    }
    return "Raw comparison";
  }

  function compareControlChartLegendEnabled(seriesList) {
    const series = Array.isArray(seriesList) ? seriesList : [];
    if (series.length > 1) return true;
    if (!series.length) return false;
    const onlyName = String((series[0] && series[0].name) || "").trim();
    return Boolean(onlyName && onlyName !== "All visible rows");
  }

  function buildCompareControlNumericScatterSeries(records, state, catalog) {
    const compareLabel = compareControlChartFieldLabel(state.compare_field);
    const outcomeLabel = compareControlChartFieldLabel(state.outcome_field);
    const series = [];
    const segments = compareControlChartSegments(records, state, catalog);
    segments.forEach((segment, index) => {
      const pairs = state.view_mode === "controlled"
        ? compareControlNumericControlledComparablePairs(
          segment.records,
          state.outcome_field,
          state.compare_field,
          state.hold_constant_fields,
        )
        : compareControlPairs(
          segment.records,
          state.outcome_field,
          state.compare_field,
        );
      if (!pairs.length) return;
      series.push({
        name: segment.label,
        type: "scatter",
        marker: {
          enabled: true,
          radius: 3,
        },
        color: compareControlChartSeriesColor(index),
        turboThreshold: 0,
        data: pairs.map(pair => ({
          x: pair.x,
          y: pair.y,
          custom: {
            compareLabel,
            outcomeLabel,
            compareValue: pair.x,
            outcomeValue: pair.y,
            splitLabel: segment.label,
            ...compareControlScatterPointCustomForRecord(pair.record),
          },
        })),
      });
    });
    return series;
  }

  function buildCompareControlCategoricalScatterSeries(records, state, catalog) {
    const compareLabel = compareControlChartFieldLabel(state.compare_field);
    const outcomeLabel = compareControlChartFieldLabel(state.outcome_field);
    const segments = compareControlChartSegments(records, state, catalog);
    const categoriesByKey = Object.create(null);
    const seriesPayloads = [];
    segments.forEach(segment => {
      const analysis = state.view_mode === "controlled"
        ? analyzeCompareControlCategoricalControlled(
          segment.records,
          state.outcome_field,
          state.compare_field,
          state.hold_constant_fields,
        )
        : analyzeCompareControlCategoricalRaw(
          segment.records,
          state.outcome_field,
          state.compare_field,
        );
      const points = (analysis.groups || [])
        .map(group => {
          const outcomeValue = maybeNumber(group.outcome_mean);
          if (outcomeValue == null) return null;
          const groupKey = String(group.key || "").trim();
          if (!groupKey) return null;
          const groupLabel = String(group.label || groupKey).trim() || groupKey;
          categoriesByKey[groupKey] = groupLabel;
          return {
            groupKey,
            groupLabel,
            count: Number(group.count || 0),
            outcomeValue,
          };
        })
        .filter(point => point !== null);
      if (!points.length) return;
      seriesPayloads.push({
        segment,
        points,
      });
    });
    const orderedGroupKeys = Object.keys(categoriesByKey).sort((left, right) => (
      String(categoriesByKey[left]).localeCompare(
        String(categoriesByKey[right]),
        undefined,
        { numeric: true }
      )
    ));
    if (!orderedGroupKeys.length || !seriesPayloads.length) {
      return {
        series: [],
        categories: [],
      };
    }
    const groupIndex = new Map(
      orderedGroupKeys.map((key, index) => [key, index])
    );
    const categories = orderedGroupKeys.map(key => categoriesByKey[key]);
    const series = seriesPayloads
      .map((entry, index) => ({
        name: entry.segment.label,
        type: "scatter",
        marker: {
          enabled: true,
          radius: 4,
        },
        color: compareControlChartSeriesColor(index),
        turboThreshold: 0,
        data: entry.points
          .map(point => {
            const pointIndex = groupIndex.get(point.groupKey);
            if (pointIndex == null) return null;
            return {
              x: pointIndex,
              y: point.outcomeValue,
              custom: {
                compareLabel,
                outcomeLabel,
                compareValue: point.groupLabel,
                outcomeValue: point.outcomeValue,
                groupLabel: point.groupLabel,
                groupCount: point.count,
                splitLabel: entry.segment.label,
              },
            };
          })
          .filter(point => point !== null),
      }))
      .filter(entry => Array.isArray(entry.data) && entry.data.length > 0);
    return {
      series,
      categories,
    };
  }

  function buildCompareControlCategoricalBarSeries(records, state, catalog) {
    const compareLabel = compareControlChartFieldLabel(state.compare_field);
    const outcomeLabel = compareControlChartFieldLabel(state.outcome_field);
    const segments = compareControlChartSegments(records, state, catalog);
    const categoriesByKey = Object.create(null);
    const seriesPayloads = [];
    segments.forEach(segment => {
      const analysis = state.view_mode === "controlled"
        ? analyzeCompareControlCategoricalControlled(
          segment.records,
          state.outcome_field,
          state.compare_field,
          state.hold_constant_fields,
        )
        : analyzeCompareControlCategoricalRaw(
          segment.records,
          state.outcome_field,
          state.compare_field,
        );
      const points = (analysis.groups || [])
        .map(group => {
          const outcomeValue = maybeNumber(group.outcome_mean);
          if (outcomeValue == null) return null;
          const groupKey = String(group.key || "").trim();
          if (!groupKey) return null;
          const groupLabel = String(group.label || groupKey).trim() || groupKey;
          categoriesByKey[groupKey] = groupLabel;
          return {
            groupKey,
            groupLabel,
            count: Number(group.count || 0),
            outcomeValue,
          };
        })
        .filter(point => point !== null);
      if (!points.length) return;
      seriesPayloads.push({
        segment,
        points,
      });
    });
    const orderedGroupKeys = Object.keys(categoriesByKey).sort((left, right) => (
      String(categoriesByKey[left]).localeCompare(
        String(categoriesByKey[right]),
        undefined,
        { numeric: true }
      )
    ));
    if (!orderedGroupKeys.length || !seriesPayloads.length) {
      return {
        series: [],
        categories: [],
      };
    }
    const groupColorByKey = Object.create(null);
    orderedGroupKeys.forEach(groupKey => {
      groupColorByKey[groupKey] = compareControlBarPointColor(
        compareControlStablePaletteIndex(state.compare_field, groupKey)
      );
    });
    const categories = orderedGroupKeys.map(key => categoriesByKey[key]);
    const series = seriesPayloads
      .map(entry => {
        const pointsByKey = Object.create(null);
        entry.points.forEach(point => {
          pointsByKey[point.groupKey] = point;
        });
        return {
          name: entry.segment.label,
          type: "column",
          turboThreshold: 0,
          data: orderedGroupKeys.map(groupKey => {
            const point = pointsByKey[groupKey];
            if (!point) return null;
            return {
              y: point.outcomeValue,
              color: groupColorByKey[groupKey],
              custom: {
                compareLabel,
                outcomeLabel,
                compareValue: point.groupLabel,
                outcomeValue: point.outcomeValue,
                groupLabel: point.groupLabel,
                groupCount: point.count,
                splitLabel: entry.segment.label,
              },
            };
          }),
        };
      })
      .filter(entry => (
        Array.isArray(entry.data) &&
        entry.data.some(point => point && typeof point === "object")
      ));
    return {
      series,
      categories,
    };
  }

  function buildCompareControlScatterChartDefinition(context) {
    const records = Array.isArray(context && context.records) ? context.records : [];
    const totalRows = Number(
      (context && context.total_rows) != null
        ? context.total_rows
        : records.length
    );
    const catalog = context && context.catalog && typeof context.catalog === "object"
      ? context.catalog
      : buildCompareControlFieldCatalog(records);
    const state = normalizeCompareControlState(
      (context && context.state) || compareControlState
    );
    const compareInfo = (context && context.compare_info) || catalog.by_field[state.compare_field];
    const compareLabel = compareControlChartFieldLabel(state.compare_field);
    const outcomeLabel = compareControlChartFieldLabel(state.outcome_field);

    if (!records.length) {
      const selectedGroups = uniqueStringList(state.selected_groups)
        .filter(value => value && value !== "__EMPTY__");
      const emptyReason = (
        totalRows > 0 &&
        selectedGroups.length > 0 &&
        compareInfo &&
        !compareInfo.numeric
      )
        ? "No rows match the selected Compare & Control group subset."
        : "No benchmark rows are available for Compare & Control.";
      return {
        chart_type: "scatter",
        chart_title: "Compare/Control Scatter",
        chart_subtitle: "",
        x_axis: { title: { text: "Compare field" } },
        y_axis: { title: { text: "Outcome field" } },
        series: [],
        empty_reason: emptyReason,
        total_rows: totalRows,
      };
    }
    if (!state.compare_field) {
      return {
        chart_type: "scatter",
        chart_title: "Compare/Control Scatter",
        chart_subtitle: "",
        x_axis: { title: { text: "Compare field" } },
        y_axis: { title: { text: "Outcome field" } },
        series: [],
        empty_reason: "Pick a Compare by field to generate the dynamic chart.",
        total_rows: totalRows,
      };
    }
    if (state.view_mode === "discover") {
      return {
        chart_type: "scatter",
        chart_title: "Compare/Control Scatter",
        chart_subtitle: "",
        x_axis: { title: { text: compareLabel } },
        y_axis: { title: { text: outcomeLabel } },
        series: [],
        empty_reason: "Switch View to raw or controlled to plot the selected compare field.",
        total_rows: totalRows,
      };
    }
    if (!compareInfo) {
      return {
        chart_type: "scatter",
        chart_title: "Compare/Control Scatter",
        chart_subtitle: "",
        x_axis: { title: { text: compareLabel } },
        y_axis: { title: { text: outcomeLabel } },
        series: [],
        empty_reason: "Selected compare field is not available in current Compare & Control rows.",
        total_rows: totalRows,
      };
    }

    if (compareInfo.numeric) {
      const series = buildCompareControlNumericScatterSeries(records, state, catalog);
      return {
        chart_type: "scatter",
        chart_title: outcomeLabel + " vs " + compareLabel,
        chart_subtitle: compareControlChartModeSummary(state),
        x_axis: {
          title: { text: compareLabel },
        },
        y_axis: {
          title: { text: outcomeLabel },
        },
        series,
        empty_reason: (
          state.view_mode === "controlled"
            ? "No comparable numeric rows remained after hold-constant controls."
            : "No numeric rows had both compare and outcome values."
        ),
        total_rows: totalRows,
      };
    }

    const categorical = buildCompareControlCategoricalScatterSeries(records, state, catalog);
    return {
      chart_type: "scatter",
      chart_title: "Average " + outcomeLabel + " by " + compareLabel,
      chart_subtitle: compareControlChartModeSummary(state),
      x_axis: {
        title: { text: compareLabel + " groups" },
        categories: categorical.categories,
      },
      y_axis: {
        title: { text: outcomeLabel },
      },
      series: categorical.series,
      empty_reason: (
        state.view_mode === "controlled"
          ? "No comparable categorical groups remained after hold-constant controls."
          : "No categorical groups had enough numeric outcome values."
      ),
      total_rows: totalRows,
    };
  }

  function buildCompareControlBarChartDefinition(context) {
    const records = Array.isArray(context && context.records) ? context.records : [];
    const totalRows = Number(
      (context && context.total_rows) != null
        ? context.total_rows
        : records.length
    );
    const catalog = context && context.catalog && typeof context.catalog === "object"
      ? context.catalog
      : buildCompareControlFieldCatalog(records);
    const state = normalizeCompareControlState(
      (context && context.state) || compareControlState
    );
    const compareInfo = (context && context.compare_info) || catalog.by_field[state.compare_field];
    const compareLabel = compareControlChartFieldLabel(state.compare_field);
    const outcomeLabel = compareControlChartFieldLabel(state.outcome_field);

    if (!records.length) {
      const selectedGroups = uniqueStringList(state.selected_groups)
        .filter(value => value && value !== "__EMPTY__");
      const emptyReason = (
        totalRows > 0 &&
        selectedGroups.length > 0 &&
        compareInfo &&
        !compareInfo.numeric
      )
        ? "No rows match the selected Compare & Control group subset."
        : "No benchmark rows are available for Compare & Control.";
      return {
        chart_type: "bar",
        chart_title: "Compare/Control Bar",
        chart_subtitle: "",
        x_axis: { title: { text: "Compare field groups" } },
        y_axis: { title: { text: "Outcome field" } },
        series: [],
        empty_reason: emptyReason,
        total_rows: totalRows,
      };
    }
    if (!state.compare_field) {
      return {
        chart_type: "bar",
        chart_title: "Compare/Control Bar",
        chart_subtitle: "",
        x_axis: { title: { text: "Compare field groups" } },
        y_axis: { title: { text: "Outcome field" } },
        series: [],
        empty_reason: "Pick a Compare by field to generate the dynamic chart.",
        total_rows: totalRows,
      };
    }
    if (state.view_mode === "discover") {
      return {
        chart_type: "bar",
        chart_title: "Compare/Control Bar",
        chart_subtitle: "",
        x_axis: { title: { text: compareLabel + " groups" } },
        y_axis: { title: { text: outcomeLabel } },
        series: [],
        empty_reason: "Switch View to raw or controlled to plot the selected compare field.",
        total_rows: totalRows,
      };
    }
    if (!compareInfo) {
      return {
        chart_type: "bar",
        chart_title: "Compare/Control Bar",
        chart_subtitle: "",
        x_axis: { title: { text: compareLabel + " groups" } },
        y_axis: { title: { text: outcomeLabel } },
        series: [],
        empty_reason: "Selected compare field is not available in current Compare & Control rows.",
        total_rows: totalRows,
      };
    }
    if (compareInfo.numeric) {
      return buildCompareControlScatterChartDefinition(context);
    }

    const categorical = buildCompareControlCategoricalBarSeries(records, state, catalog);
    return {
      chart_type: "bar",
      chart_title: "Average " + outcomeLabel + " by " + compareLabel,
      chart_subtitle: compareControlChartModeSummary(state),
      x_axis: {
        title: { text: compareLabel + " groups" },
        categories: categorical.categories,
      },
      y_axis: {
        title: { text: outcomeLabel },
      },
      series: categorical.series,
      empty_reason: (
        state.view_mode === "controlled"
          ? "No comparable categorical groups remained after hold-constant controls."
          : "No categorical groups had enough numeric outcome values."
      ),
      total_rows: totalRows,
    };
  }

  const COMPARE_CONTROL_CHART_BUILDERS = {
    bar: buildCompareControlBarChartDefinition,
    scatter: buildCompareControlScatterChartDefinition,
  };

  function compareControlAutoChartType(sourceState, context) {
    const state = sourceState && typeof sourceState === "object"
      ? sourceState
      : compareControlDefaultState();
    if (!state.compare_field) return "scatter";
    if (state.view_mode === "discover") return "scatter";
    const catalog = context && context.catalog && typeof context.catalog === "object"
      ? context.catalog
      : null;
    const compareInfo = (
      (context && context.compare_info) ||
      (catalog && catalog.by_field && catalog.by_field[state.compare_field]) ||
      null
    );
    if (compareInfo && compareInfo.numeric === false) return "bar";
    return "scatter";
  }

  function buildCompareControlChartDefinition(context) {
    const sourceState = normalizeCompareControlState(
      (context && context.state) || compareControlState
    );
    const chartType = compareControlAutoChartType(sourceState, context);
    const builder = (
      COMPARE_CONTROL_CHART_BUILDERS[chartType] ||
      COMPARE_CONTROL_CHART_BUILDERS[COMPARE_CONTROL_DEFAULT_CHART_TYPE]
    );
    const built = typeof builder === "function"
      ? builder({
        ...(context || Object.create(null)),
        state: {
          ...sourceState,
          chart_type: chartType,
        },
      })
      : null;
    const records = Array.isArray(context && context.records) ? context.records : [];
    return {
      chart_type: chartType,
      chart_title: String((built && built.chart_title) || "Compare/Control Dynamic Chart"),
      chart_subtitle: String((built && built.chart_subtitle) || "").trim(),
      x_axis: built && built.x_axis && typeof built.x_axis === "object"
        ? built.x_axis
        : Object.create(null),
      y_axis: built && built.y_axis && typeof built.y_axis === "object"
        ? built.y_axis
        : Object.create(null),
      series: built && Array.isArray(built.series) ? built.series : [],
      empty_reason: String((built && built.empty_reason) || "").trim(),
      total_rows: Number((built && built.total_rows) || records.length || 0),
    };
  }

  function renderCompareControlChartHost(config) {
    const hostId = String((config && config.hostId) || "").trim();
    if (!hostId) return;
    const chartHost = document.getElementById(hostId);
    if (!chartHost) return;
    const fallback = document.getElementById(String((config && config.fallbackId) || ""));
    const chartDefinition = config && config.chartDefinition && typeof config.chartDefinition === "object"
      ? config.chartDefinition
      : Object.create(null);
    const series = Array.isArray(chartDefinition.series) ? chartDefinition.series : [];
    const pointCount = series.reduce(
      (total, item) => total + (
        Array.isArray(item && item.data)
          ? item.data.filter(point => point != null).length
          : 0
      ),
      0,
    );
    const totalRows = Number(chartDefinition.total_rows || 0);
    const chartTitle = String(chartDefinition.chart_title || "Compare/Control Dynamic Chart");
    const chartSubtitle = String(chartDefinition.chart_subtitle || "").trim();
    const emptyReason = String(chartDefinition.empty_reason || "").trim();
    const chartType = normalizeCompareControlChartType(chartDefinition.chart_type);
    const highchartsChartType = chartType === "bar" ? "column" : "scatter";

    if (pointCount === 0) {
      destroyBenchmarkTrendChartHost(hostId);
      chartHost.innerHTML = "";
      if (fallback) {
        fallback.hidden = false;
        fallback.textContent = emptyReason || (
          totalRows > 0
            ? "No chart points are available for the current compare/control selection."
            : "No benchmark rows are available for Compare & Control."
        );
      }
      return;
    }

    if (!hasHighchartsBasicChart()) {
      destroyBenchmarkTrendChartHost(hostId);
      chartHost.innerHTML = "";
      if (fallback) {
        fallback.hidden = false;
        fallback.textContent =
          "Highcharts did not load, so the compare/control chart is unavailable.";
      }
      return;
    }

    if (fallback) {
      fallback.hidden = true;
      fallback.textContent = "";
    }

    const measuredHostWidth = Math.floor(
      Number(chartHost.clientWidth || 0) ||
      Number(
        typeof chartHost.getBoundingClientRect === "function"
          ? chartHost.getBoundingClientRect().width
          : 0
      )
    );
    const chartWidth = (
      Number.isFinite(measuredHostWidth) && measuredHostWidth > 0
    ) ? measuredHostWidth : null;
    const chartConfig = {
      type: highchartsChartType,
      height: 800,
    };
    if (chartWidth != null) {
      chartConfig.width = chartWidth;
    }

    const xAxisConfig = chartDefinition.x_axis && typeof chartDefinition.x_axis === "object"
      ? { ...chartDefinition.x_axis }
      : Object.create(null);
    if (!xAxisConfig.title || typeof xAxisConfig.title !== "object") {
      xAxisConfig.title = { text: "Compare field" };
    }
    const rawYAxis = chartDefinition.y_axis;
    const yAxisConfigs = Array.isArray(rawYAxis)
      ? rawYAxis
          .map(item => (item && typeof item === "object" ? { ...item } : Object.create(null)))
      : [
        rawYAxis && typeof rawYAxis === "object"
          ? { ...rawYAxis }
          : Object.create(null),
      ];
    const normalizedYAxisConfigs = yAxisConfigs.map((axis, axisIdx) => {
      const next = axis && typeof axis === "object" ? { ...axis } : Object.create(null);
      if (!next.title || typeof next.title !== "object") {
        next.title = { text: axisIdx === 0 ? "Outcome field" : "Outcome field (set 2)" };
      }
      next.title = {
        ...next.title,
        style: {
          color: "#4f5d68",
          fontSize: "1rem",
          fontWeight: "600",
          ...(next.title && typeof next.title.style === "object" ? next.title.style : {}),
        },
      };
      if (!Number.isFinite(Number(next.title.margin))) {
        next.title.margin = 18;
      }
      if (chartType === "bar") {
        next.gridLineColor = "#eef1f4";
        next.gridLineWidth = 1;
      }
      return next;
    });

    const chartOptions = {
      chart: chartConfig,
      credits: { enabled: false },
      title: {
        text: chartTitle,
        align: "left",
        style: chartType === "bar"
          ? {
            color: "#4f5d68",
            fontSize: "1.45rem",
            fontWeight: "600",
          }
          : undefined,
      },
      legend: { enabled: compareControlChartLegendEnabled(series) },
      xAxis: xAxisConfig,
      yAxis: normalizedYAxisConfigs.length === 1
        ? normalizedYAxisConfigs[0]
        : normalizedYAxisConfigs,
      tooltip: {
        shared: false,
        useHTML: true,
        formatter: function() {
          const point =
            this.point ||
            (Array.isArray(this.points) && this.points.length ? this.points[0].point : null);
          if (!point) return false;
          const custom = (point.options && point.options.custom) || point.custom || {};
          const seriesName = String(
            (point.series && point.series.name) || "series"
          ).trim();
          const compareLabel = String(custom.compareLabel || "Compare").trim();
          const outcomeLabel = String(custom.outcomeLabel || "Outcome").trim();
          const compareValueRaw = custom.compareValue != null
            ? custom.compareValue
            : (
              point.category != null
                ? point.category
                : (Number.isFinite(Number(point.x)) ? Number(point.x) : "")
            );
          const outcomeValueRaw = custom.outcomeValue != null
            ? custom.outcomeValue
            : (Number.isFinite(Number(point.y)) ? Number(point.y) : "");
          const outcomeNumber = maybeNumber(outcomeValueRaw);
          const outcomeText = outcomeNumber == null
            ? String(outcomeValueRaw == null ? "-" : outcomeValueRaw)
            : fmtMaybe(outcomeNumber, 4);
          let html = (
            '<span style="font-size: 0.85rem"><b>' +
            esc(seriesName) +
            "</b></span><br/>"
          );
          html += (
            "<span><b>" + esc(compareLabel) + ":</b> " +
            esc(String(compareValueRaw == null ? "-" : compareValueRaw)) +
            "</span><br/>"
          );
          html += (
            "<span><b>" + esc(outcomeLabel) + ":</b> " +
            esc(String(outcomeText)) +
            "</span><br/>"
          );
          if (custom.groupCount != null) {
            html += "<span><b>Rows:</b> " + esc(String(custom.groupCount)) + "</span><br/>";
          }
          if (custom.sourceLabel) {
            html += "<span><b>Book:</b> " + esc(String(custom.sourceLabel)) + "</span><br/>";
          }
          if (custom.variant) {
            html += "<span><b>Variant:</b> " + esc(String(custom.variant)) + "</span><br/>";
          }
          if (custom.runTimestamp) {
            html += "<span><b>Eval row:</b> " + esc(String(custom.runTimestamp)) + "</span><br/>";
          }
          return html;
        },
      },
      plotOptions: {
        column: {
          borderWidth: 1,
          borderColor: "rgba(108, 120, 131, 0.24)",
          borderRadius: 4,
          pointPadding: 0.2,
          groupPadding: 0.28,
          states: {
            hover: {
              brightness: 0.02,
            },
          },
        },
        scatter: {
          marker: {
            symbol: "circle",
          },
        },
      },
      series,
    };
    if (chartSubtitle) {
      chartOptions.subtitle = {
        text: chartSubtitle,
        align: "left",
        style: chartType === "bar"
          ? {
            color: "#73808b",
            fontSize: "0.9rem",
            fontWeight: "500",
          }
          : undefined,
      };
    }

    destroyBenchmarkTrendChartHost(hostId);
    chartHost.innerHTML = "";
    const nextChart = window.Highcharts.chart(hostId, chartOptions);
    if (nextChart && typeof nextChart.destroy === "function") {
      benchmarkTrendChartsByHostId[hostId] = nextChart;
    }
  }

  function compareControlChartPlaceholder(totalRows, emptyReason) {
    return {
      chart_type: "scatter",
      chart_title: "Compare/Control Scatter",
      chart_subtitle: "",
      x_axis: { title: { text: "Compare field" } },
      y_axis: { title: { text: "Outcome field" } },
      series: [],
      empty_reason: String(emptyReason || ""),
      total_rows: Number(totalRows || 0),
    };
  }

  function compareControlChartPointCount(definition) {
    const chartDefinition = definition && typeof definition === "object"
      ? definition
      : Object.create(null);
    const series = Array.isArray(chartDefinition.series) ? chartDefinition.series : [];
    return series.reduce((total, item) => {
      const data = Array.isArray(item && item.data) ? item.data : [];
      return total + data.filter(point => point != null).length;
    }, 0);
  }

  function remapCompareControlSeriesToCategories(seriesList, sourceCategories, targetCategories) {
    const source = Array.isArray(sourceCategories) ? sourceCategories : [];
    const target = Array.isArray(targetCategories) ? targetCategories : [];
    if (!source.length || !target.length) {
      return Array.isArray(seriesList) ? seriesList : [];
    }
    const targetIndexByCategory = new Map();
    target.forEach((label, idx) => {
      const key = String(label || "");
      if (!targetIndexByCategory.has(key)) {
        targetIndexByCategory.set(key, idx);
      }
    });
    return (Array.isArray(seriesList) ? seriesList : []).map(series => {
      const nextSeries = series && typeof series === "object"
        ? { ...series }
        : Object.create(null);
      const sourceData = Array.isArray(nextSeries.data) ? nextSeries.data : [];
      const mapped = new Array(target.length).fill(null);
      source.forEach((category, sourceIdx) => {
        const targetIdx = targetIndexByCategory.get(String(category || ""));
        if (targetIdx == null) return;
        mapped[targetIdx] = sourceIdx < sourceData.length ? sourceData[sourceIdx] : null;
      });
      nextSeries.data = mapped;
      return nextSeries;
    });
  }

  function compareControlChartDefinitionForSet(records, totalRows, setKey) {
    const key = setKey === "secondary" ? "secondary" : "primary";
    const rows = Array.isArray(records) ? records : [];
    const total = Number(totalRows || rows.length || 0);
    const catalog = buildCompareControlFieldCatalog(rows);
    const normalizedState = normalizeCompareControlStateForCatalog(
      compareControlStateForSet(key),
      catalog
    );
    setCompareControlStateForSet(key, normalizedState);
    const state = compareControlStateForSet(key);
    const compareInfo = catalog.by_field[state.compare_field];
    if (
      !compareControlChartActivatedForSet(key) &&
      shouldAutoActivateCompareControlChart(state, compareInfo)
    ) {
      activateCompareControlChartForSet(key);
    }
    if (!compareControlChartActivatedForSet(key)) {
      return compareControlChartPlaceholder(
        total,
        "Use Compare & Control selections above to generate this chart."
      );
    }
    const scopedRows = compareControlRecordsForState(rows, state, catalog);
    return buildCompareControlChartDefinition({
      records: scopedRows,
      total_rows: total,
      state,
      catalog,
      compare_info: compareInfo,
    });
  }

  function buildCombinedCompareControlChartDefinition(primaryDefinition, secondaryDefinition) {
    const primary = primaryDefinition && typeof primaryDefinition === "object"
      ? primaryDefinition
      : Object.create(null);
    const secondary = secondaryDefinition && typeof secondaryDefinition === "object"
      ? secondaryDefinition
      : Object.create(null);
    const primaryPoints = compareControlChartPointCount(primary);
    const secondaryPoints = compareControlChartPointCount(secondary);
    const totalRows = Math.max(
      Number(primary.total_rows || 0),
      Number(secondary.total_rows || 0),
    );
    if (!primaryPoints || !secondaryPoints) {
      return compareControlChartPlaceholder(
        totalRows,
        "Both sets need chart points before combined mode can render."
      );
    }

    const primaryCategories = Array.isArray(primary.x_axis && primary.x_axis.categories)
      ? primary.x_axis.categories.map(value => String(value || ""))
      : [];
    const secondaryCategories = Array.isArray(secondary.x_axis && secondary.x_axis.categories)
      ? secondary.x_axis.categories.map(value => String(value || ""))
      : [];
    const primaryHasCategories = primaryCategories.length > 0;
    const secondaryHasCategories = secondaryCategories.length > 0;
    if (primaryHasCategories !== secondaryHasCategories) {
      return compareControlChartPlaceholder(
        totalRows,
        "Combined mode is not available when one set is categorical and the other is numeric."
      );
    }

    let mergedCategories = [];
    if (primaryHasCategories && secondaryHasCategories) {
      const mergedSet = new Set([...primaryCategories, ...secondaryCategories]);
      mergedCategories = Array.from(mergedSet);
    }

    const primarySeries = (Array.isArray(primary.series) ? primary.series : []).map(series => ({
      ...(series && typeof series === "object" ? series : Object.create(null)),
      name: "Set 1 - " + String((series && series.name) || "series"),
    }));
    const secondarySeries = (Array.isArray(secondary.series) ? secondary.series : []).map(series => ({
      ...(series && typeof series === "object" ? series : Object.create(null)),
      name: "Set 2 - " + String((series && series.name) || "series"),
      yAxis: normalizeCompareControlCombinedAxisMode(compareControlCombinedAxisMode) === "dual" ? 1 : 0,
    }));

    const remappedPrimarySeries = mergedCategories.length
      ? remapCompareControlSeriesToCategories(primarySeries, primaryCategories, mergedCategories)
      : primarySeries;
    const remappedSecondarySeries = mergedCategories.length
      ? remapCompareControlSeriesToCategories(secondarySeries, secondaryCategories, mergedCategories)
      : secondarySeries;
    const combinedSeries = [...remappedPrimarySeries, ...remappedSecondarySeries];

    const combinedChartType = (
      String(primary.chart_type || "") === "bar" &&
      String(secondary.chart_type || "") === "bar"
    )
      ? "bar"
      : "scatter";

    const xAxisBase = (
      primary.x_axis && typeof primary.x_axis === "object"
        ? { ...primary.x_axis }
        : Object.create(null)
    );
    if (mergedCategories.length) {
      xAxisBase.categories = mergedCategories;
      if (!xAxisBase.title || typeof xAxisBase.title !== "object") {
        xAxisBase.title = { text: "Compare groups (merged)" };
      }
    }
    const primaryYAxis = (
      primary.y_axis && typeof primary.y_axis === "object"
        ? { ...primary.y_axis }
        : { title: { text: "Outcome (set 1)" } }
    );
    if (!primaryYAxis.title || typeof primaryYAxis.title !== "object") {
      primaryYAxis.title = { text: "Outcome (set 1)" };
    }

    const axisMode = normalizeCompareControlCombinedAxisMode(compareControlCombinedAxisMode);
    let yAxis;
    if (axisMode === "dual") {
      const secondaryYAxis = (
        secondary.y_axis && typeof secondary.y_axis === "object"
          ? { ...secondary.y_axis }
          : { title: { text: "Outcome (set 2)" } }
      );
      if (!secondaryYAxis.title || typeof secondaryYAxis.title !== "object") {
        secondaryYAxis.title = { text: "Outcome (set 2)" };
      }
      secondaryYAxis.opposite = true;
      yAxis = [primaryYAxis, secondaryYAxis];
    } else {
      yAxis = primaryYAxis;
    }

    return {
      chart_type: combinedChartType,
      chart_title: "Compare/Control Combined Chart",
      chart_subtitle:
        axisMode === "dual"
          ? "Set 1 (left axis) + Set 2 (right axis)"
          : "Set 1 + Set 2 on a shared Y axis",
      x_axis: xAxisBase,
      y_axis: yAxis,
      series: combinedSeries,
      empty_reason: "",
      total_rows: totalRows,
    };
  }

  function clearCompareControlChartHost(hostId, fallbackId, reason) {
    renderCompareControlChartHost({
      hostId,
      fallbackId,
      chartDefinition: compareControlChartPlaceholder(0, reason || ""),
    });
  }

  function renderCompareControlDynamicChartForSet(records, totalRows, config) {
    const cfg = config && typeof config === "object" ? config : Object.create(null);
    const setKey = cfg.set_key === "secondary" ? "secondary" : "primary";
    const chartDefinition = compareControlChartDefinitionForSet(records, totalRows, setKey);
    renderCompareControlChartHost({
      hostId: String(cfg.host_id || ""),
      fallbackId: String(cfg.fallback_id || ""),
      chartDefinition,
    });
    return chartDefinition;
  }

  function renderCompareControlDynamicChart(records, totalRows) {
    return renderCompareControlDynamicChartForSet(records, totalRows, {
      set_key: "primary",
      host_id: "compare-control-trend-chart",
      fallback_id: "compare-control-trend-fallback",
    });
  }

  function compareControlSourceRecords() {
    return filteredBenchmarks();
  }

  function renderCompareControlSection() {
    const records = compareControlSourceRecords();
    syncCompareControlLayoutChrome();
    renderCompareControlPanel(
      { records },
      {
        set_key: "primary",
      }
    );
    if (compareControlSecondSetEnabled) {
      renderCompareControlPanel(
        { records },
        {
          set_key: "secondary",
        }
      );
    } else {
      const secondaryStatus = document.getElementById("compare-control-status-secondary");
      const secondaryResults = document.getElementById("compare-control-results-secondary");
      const secondaryGroups = document.getElementById("compare-control-group-selection-secondary");
      if (secondaryStatus) {
        secondaryStatus.textContent = "";
        secondaryStatus.classList.remove("error");
      }
      if (secondaryResults) secondaryResults.innerHTML = "";
      if (secondaryGroups) secondaryGroups.innerHTML = "";
    }

    const primaryChartDefinition = compareControlChartDefinitionForSet(
      records,
      records.length,
      "primary"
    );
    const layout = compareControlSecondSetEnabled
      ? normalizeCompareControlChartLayout(compareControlChartLayout)
      : COMPARE_CONTROL_DEFAULT_CHART_LAYOUT;

    if (!compareControlSecondSetEnabled) {
      renderCompareControlChartHost({
        hostId: "compare-control-trend-chart",
        fallbackId: "compare-control-trend-fallback",
        chartDefinition: primaryChartDefinition,
      });
      clearCompareControlChartHost(
        "compare-control-trend-chart-secondary",
        "compare-control-trend-fallback-secondary",
        ""
      );
      clearCompareControlChartHost(
        "compare-control-trend-chart-combined",
        "compare-control-trend-fallback-combined",
        ""
      );
      return;
    }

    const secondaryChartDefinition = compareControlChartDefinitionForSet(
      records,
      records.length,
      "secondary"
    );

    if (layout === "combined") {
      const combined = buildCombinedCompareControlChartDefinition(
        primaryChartDefinition,
        secondaryChartDefinition
      );
      clearCompareControlChartHost(
        "compare-control-trend-chart",
        "compare-control-trend-fallback",
        ""
      );
      clearCompareControlChartHost(
        "compare-control-trend-chart-secondary",
        "compare-control-trend-fallback-secondary",
        ""
      );
      renderCompareControlChartHost({
        hostId: "compare-control-trend-chart-combined",
        fallbackId: "compare-control-trend-fallback-combined",
        chartDefinition: combined,
      });
      return;
    }

    clearCompareControlChartHost(
      "compare-control-trend-chart-combined",
      "compare-control-trend-fallback-combined",
      ""
    );
    renderCompareControlChartHost({
      hostId: "compare-control-trend-chart",
      fallbackId: "compare-control-trend-fallback",
      chartDefinition: primaryChartDefinition,
    });
    renderCompareControlChartHost({
      hostId: "compare-control-trend-chart-secondary",
      fallbackId: "compare-control-trend-fallback-secondary",
      chartDefinition: secondaryChartDefinition,
    });
  }

  function renderBenchmarkTrendChartHost(config) {
    const hostId = String((config && config.hostId) || "").trim();
    if (!hostId) return;
    const chartHost = document.getElementById(hostId);
    if (!chartHost) return;
    const fallback = document.getElementById(String((config && config.fallbackId) || ""));
    const records = Array.isArray(config && config.records) ? config.records : [];
    const trendSeries = Array.isArray(config && config.trendSeries) ? config.trendSeries : [];
    const timelineMin = config && config.timelineMin != null ? config.timelineMin : null;
    const timelineMax = config && config.timelineMax != null ? config.timelineMax : null;
    const pointCount = trendSeries.reduce(
      (total, series) => total + (series.data ? series.data.length : 0),
      0,
    );
    const totalRows = Number((config && config.totalRows) || 0);
    const chartTitle = String((config && config.chartTitle) || "Explicit Benchmark Score Trends");
    const emptyReason = String((config && config.emptyReason) || "").trim();

    if (pointCount === 0) {
      destroyBenchmarkTrendChartHost(hostId);
      chartHost.innerHTML = "";
      if (fallback) {
        fallback.hidden = false;
        if (emptyReason) {
          fallback.textContent = emptyReason;
        } else if (totalRows > 0 && records.length === 0) {
          fallback.textContent = "No benchmark rows match the current Previous Runs filters.";
        } else {
          fallback.textContent = "No benchmark score points available yet.";
        }
      }
      return;
    }

    if (!hasHighchartsStock()) {
      destroyBenchmarkTrendChartHost(hostId);
      chartHost.innerHTML = "";
      if (fallback) {
        fallback.hidden = false;
        fallback.textContent =
          "Highcharts did not load, so the interactive trend chart is unavailable.";
      }
      return;
    }

    if (fallback) {
      fallback.hidden = true;
      fallback.textContent = "";
    }

    const measuredHostWidth = Math.floor(
      Number(chartHost.clientWidth || 0) ||
      Number(
        typeof chartHost.getBoundingClientRect === "function"
          ? chartHost.getBoundingClientRect().width
          : 0
      )
    );
    const chartWidth = (
      Number.isFinite(measuredHostWidth) && measuredHostWidth > 0
    ) ? measuredHostWidth : null;
    const chartConfig = {
      height: 800,
    };
    if (chartWidth != null) {
      chartConfig.width = chartWidth;
    }

    const xAxisConfig = {
      type: "datetime",
    };
    if (timelineMin != null) xAxisConfig.min = timelineMin;
    if (timelineMax != null) xAxisConfig.max = timelineMax;

    destroyBenchmarkTrendChartHost(hostId);
    chartHost.innerHTML = "";
    const nextChart = window.Highcharts.stockChart(hostId, {
      chart: chartConfig,
      credits: { enabled: false },
      title: { text: chartTitle, align: "left" },
      legend: { enabled: true },
      rangeSelector: {
        // Start on full history so default chart span matches long-run table context.
        buttons: [
          { type: "month", count: 1, text: "1m" },
          { type: "month", count: 3, text: "3m" },
          { type: "month", count: 6, text: "6m" },
          { type: "ytd", text: "YTD" },
          { type: "year", count: 1, text: "1y" },
          { type: "all", text: "All" },
        ],
        selected: 5,
        inputEnabled: false,
      },
      navigator: {
        enabled: false,
      },
      scrollbar: {
        enabled: false,
      },
      xAxis: xAxisConfig,
      yAxis: [
        {
          title: { text: "Score (0-1)" },
          min: 0,
          max: 1,
        },
      ],
      tooltip: {
        shared: false,
        useHTML: true,
        formatter: function() {
          const hoveredPoint =
            this.point ||
            (Array.isArray(this.points) && this.points.length ? this.points[0].point : null);
          if (!hoveredPoint) return false;
          const hoveredCustom =
            (hoveredPoint.options && hoveredPoint.options.custom) || hoveredPoint.custom || {};
          const runGroupKey = String(hoveredCustom.runGroupKey || "").trim();
          if (!runGroupKey) return false;
          const hoveredSeriesName = String(
            (hoveredPoint.series && hoveredPoint.series.name) || ""
          ).trim();
          const hoveredColor = String(
            hoveredPoint.color ||
            (hoveredPoint.series && hoveredPoint.series.color) ||
            "#2f2f2f"
          );
          const hoveredScore = Number(hoveredPoint.y);
          const hoveredSourceLabel = String(hoveredCustom.sourceLabel || "").trim();
          const hoveredSourceTitle = String(hoveredCustom.sourceTitle || "").trim();
          const hoveredVariant = String(hoveredCustom.variant || "").trim();
          const hoveredRunTimestamp = String(hoveredCustom.runTimestamp || "").trim();

          const hoveredX = Number(hoveredPoint.x || 0);
          const chart = hoveredPoint.series && hoveredPoint.series.chart;
          if (!chart) return false;

          const rows = [];
          chart.series.forEach(series => {
            if (!series || series.visible === false || isTrendOverlaySeries(series)) return;
            const match = trendSeriesPointForRunGroup(series, runGroupKey, hoveredX);
            if (!match) return;
            const score = Number(match.y);
            if (!Number.isFinite(score)) return;
            rows.push({
              name: String(series.name || ""),
              color: String(series.color || "#2f2f2f"),
              score,
            });
          });
          if (!rows.length) return false;
          rows.sort((a, b) => a.name.localeCompare(b.name, undefined, { numeric: true }));

          const label = String(hoveredCustom.runGroupLabel || "").trim();
          const header = label && label !== "-"
            ? label
            : window.Highcharts.dateFormat("%A, %b %e, %Y, %I:%M:%S %p", hoveredX);
          let html = '<span style="font-size: 0.85rem"><b>' + esc(header) + "</b></span><br/>";
          if (Number.isFinite(hoveredScore)) {
            html +=
              '<span style="color:' + hoveredColor + '">&#9679;</span> ' +
              esc(hoveredSeriesName || "score") +
              ': <b>' +
              hoveredScore.toFixed(4) +
              "</b><br/>";
          }
          if (hoveredSourceLabel) {
            html +=
              '<span><b>Book:</b> <span title="' +
              esc(hoveredSourceTitle || hoveredSourceLabel) +
              '">' +
              esc(hoveredSourceLabel) +
              "</span></span><br/>";
          }
          if (hoveredVariant) {
            html += '<span><b>Variant:</b> ' + esc(hoveredVariant) + "</span><br/>";
          }
          if (hoveredRunTimestamp) {
            html += '<span><b>Eval row:</b> ' + esc(hoveredRunTimestamp) + "</span><br/>";
          }
          return html;
        },
      },
      series: trendSeries,
    });
    if (nextChart && typeof nextChart.destroy === "function") {
      benchmarkTrendChartsByHostId[hostId] = nextChart;
    }
  }

  function renderBenchmarkTrendChart() {
    const filterResult = currentPreviousRunsFilterResult();
    const records = filterResult.records;
    const sorted = [...records].sort((a, b) =>
      compareRunTimestampAsc(a.run_timestamp, b.run_timestamp)
    );
    const selectedTrendFields = setBenchmarkTrendSelectedFields(
      benchmarkTrendSelectedFields,
      {
        allow_empty: Array.isArray(benchmarkTrendSelectedFields),
        available_fields: benchmarkTrendFieldOptions,
      },
    );
    const allRunTimestamps = sorted
      .map(record => {
        const ts = parseTs(record.run_timestamp);
        return ts ? ts.getTime() : null;
      })
      .filter(value => value != null)
      .sort((a, b) => a - b);
    const timelineMin = allRunTimestamps.length ? allRunTimestamps[0] : null;
    const timelineMax = allRunTimestamps.length ? allRunTimestamps[allRunTimestamps.length - 1] : null;
    const trendSeries = selectedTrendFields.length
      ? buildBenchmarkTrendSeries(sorted)
      : [];
    const emptyReason = selectedTrendFields.length
      ? ""
      : "No trend fields selected. Pick one or more fields above.";

    renderBenchmarkTrendChartHost({
      hostId: "benchmark-trend-chart",
      fallbackId: "benchmark-trend-fallback",
      records: sorted,
      totalRows: filterResult.total,
      trendSeries,
      timelineMin,
      timelineMax,
      chartTitle: "Explicit Benchmark Score Trends",
      emptyReason,
    });

  }

  function requestBenchmarkTrendResizeRender() {
    if (benchmarkTrendResizeRafId != null) return;
    const hasAnimationFrame = (
      typeof window !== "undefined" &&
      typeof window.requestAnimationFrame === "function"
    );
    if (hasAnimationFrame) {
      benchmarkTrendResizeRafId = window.requestAnimationFrame(() => {
        benchmarkTrendResizeRafId = null;
        renderBenchmarkTrendChart();
        renderCompareControlSection();
      });
      return;
    }
    benchmarkTrendResizeRafId = 1;
    setTimeout(() => {
      benchmarkTrendResizeRafId = null;
      renderBenchmarkTrendChart();
      renderCompareControlSection();
    }, 80);
  }

  function handleDashboardWindowResize() {
    if (typeof window === "undefined") return;
    const nextWidth = Math.max(0, Math.floor(Number(window.innerWidth || 0)));
    if (nextWidth <= 0 || nextWidth === lastKnownViewportWidth) {
      return;
    }
    lastKnownViewportWidth = nextWidth;
    requestBenchmarkTrendResizeRender();
  }

  function setupDashboardResizeHandlers() {
    if (dashboardResizeHandlersBound) return;
    if (
      typeof window === "undefined" ||
      typeof window.addEventListener !== "function"
    ) {
      return;
    }
    dashboardResizeHandlersBound = true;
    lastKnownViewportWidth = Math.max(
      0,
      Math.floor(Number(window.innerWidth || 0))
    );
    window.addEventListener("resize", handleDashboardWindowResize, { passive: true });
  }

  function setAllTableCollapsedState(collapsed) {
    Object.keys(TABLE_COLLAPSE_DEFAULT_ROWS).forEach(tableId => {
      tableCollapsedState[tableId] = collapsed;
    });
  }

  function setupGlobalCollapseControls() {
    const showAllBtn = document.getElementById("show-all-tables");
    const collapseAllBtn = document.getElementById("collapse-all-tables");
    if (!showAllBtn || !collapseAllBtn) return;

    if (!showAllBtn.dataset.bound) {
      showAllBtn.addEventListener("click", () => {
        setAllTableCollapsedState(false);
        renderAll();
      });
      showAllBtn.dataset.bound = "1";
    }

    if (!collapseAllBtn.dataset.bound) {
      collapseAllBtn.addEventListener("click", () => {
        setAllTableCollapsedState(true);
        renderAll();
      });
      collapseAllBtn.dataset.bound = "1";
    }
  }

  function renderRowsWithCollapse(options) {
    const table = document.getElementById(options.tableId);
    if (!table) return;
    const tbody = table.querySelector("tbody");
    if (!tbody) return;
    tbody.innerHTML = "";

    const rows = options.rows || [];
    const defaultVisible = options.defaultVisible || 10;
    const canCollapse = rows.length > defaultVisible;

    if (canCollapse && typeof tableCollapsedState[options.tableId] !== "boolean") {
      tableCollapsedState[options.tableId] = true;
    }

    const collapsed = canCollapse ? tableCollapsedState[options.tableId] : false;
    const visibleRows = collapsed ? rows.slice(0, defaultVisible) : rows;
    visibleRows.forEach(row => {
      const tr = options.renderRow(row);
      if (tr) tbody.appendChild(tr);
    });

    renderTableCollapseControl({
      tableId: options.tableId,
      canCollapse,
      collapsed,
      totalRows: rows.length,
      defaultVisible,
      label: options.label || "rows",
      rerender: options.rerender,
    });
  }

  function renderTableCollapseControl(options) {
    const table = document.getElementById(options.tableId);
    if (!table || !table.parentNode) return;
    const controlId = "collapse-control-" + options.tableId;
    let control = document.getElementById(controlId);
    if (!control) {
      control = document.createElement("div");
      control.id = controlId;
      control.className = "table-collapse-controls";
      control.innerHTML =
        '<button type="button" class="table-collapse-toggle"></button>' +
        '<span class="table-collapse-status"></span>';
      table.parentNode.insertBefore(control, table);
    }

    if (!options.canCollapse) {
      control.style.display = "none";
      return;
    }

    control.style.display = "";
    const button = control.querySelector("button");
    const status = control.querySelector(".table-collapse-status");
    button.textContent = options.collapsed
      ? "Show all " + options.totalRows
      : "Show fewer";
    status.textContent = options.collapsed
      ? "Showing first " + Math.min(options.defaultVisible, options.totalRows) + " of " + options.totalRows + " " + options.label
      : "Showing all " + options.totalRows + " " + options.label;
    button.onclick = function () {
      tableCollapsedState[options.tableId] = !options.collapsed;
      options.rerender();
    };
  }

  // ---- Stats helpers ----
  function mean(values) {
    if (!values.length) return null;
    return values.reduce((acc, v) => acc + v, 0) / values.length;
  }

  function median(values) {
    if (!values.length) return null;
    const ordered = [...values].sort((a, b) => a - b);
    const mid = Math.floor(ordered.length / 2);
    if (ordered.length % 2 === 1) return ordered[mid];
    return (ordered[mid - 1] + ordered[mid]) / 2;
  }

  function percentile(values, pct) {
    if (!values.length) return null;
    const ordered = [...values].sort((a, b) => a - b);
    const rank = (Math.max(0, Math.min(100, pct)) / 100) * (ordered.length - 1);
    const lower = Math.floor(rank);
    const upper = Math.ceil(rank);
    if (lower === upper) return ordered[lower];
    const weight = rank - lower;
    return ordered[lower] * (1 - weight) + ordered[upper] * weight;
  }

  function fmtMaybe(value, digits) {
    if (value == null || Number.isNaN(value)) return "-";
    return Number(value).toFixed(digits);
  }

  function compareControlTableNumber(value, smallDigits) {
    const numeric = maybeNumber(value);
    if (numeric == null) return "-";
    if (Math.abs(numeric) > 5) {
      return Math.round(numeric).toLocaleString("en-US");
    }
    return fmtMaybe(numeric, smallDigits);
  }

  function latestTimestampLabel(records) {
    let latest = null;
    records.forEach(record => {
      const ts = parseTs(record.run_timestamp);
      if (!ts) return;
      if (latest == null || ts > latest) latest = ts;
    });
    if (!latest) return "-";
    const yr = latest.getFullYear();
    const mo = String(latest.getMonth() + 1).padStart(2, "0");
    const dy = String(latest.getDate()).padStart(2, "0");
    const hh = String(latest.getHours()).padStart(2, "0");
    const mm = String(latest.getMinutes()).padStart(2, "0");
    return yr + "-" + mo + "-" + dy + " " + hh + ":" + mm;
  }

  function renderKpis() {
    const host = document.getElementById("kpi-cards");
    if (!host) return;
    const stage = filteredStage();
    const benchmarks = filteredBenchmarks();
    const perRecipeValues = stage
      .map(r => r.per_recipe_seconds)
      .filter(v => v != null && Number.isFinite(v));
    const strictValues = benchmarks
      .map(r => r.strict_accuracy)
      .filter(v => v != null && Number.isFinite(v));
    const macroValues = benchmarks
      .map(r => r.macro_f1_excluding_other)
      .filter(v => v != null && Number.isFinite(v));
    const medianPerRecipe = median(perRecipeValues);
    const strictMean = mean(strictValues);
    const macroMean = mean(macroValues);
    const latestLabel = latestTimestampLabel(stage.concat(benchmarks));

    const cards = [
      {
        label: "Stage rows",
        value: String(stage.length),
        detail: stage.length ? "filtered rows" : "no visible rows",
      },
      {
        label: "Median sec/recipe",
        value: fmtMaybe(medianPerRecipe, 3),
        detail: perRecipeValues.length + " runs with timing",
      },
      {
        label: "Mean strict_accuracy",
        value: strictMean == null ? "-" : (strictMean * 100).toFixed(1) + "%",
        detail: "macro_f1_excluding_other " + (macroMean == null ? "-" : (macroMean * 100).toFixed(1) + "%"),
      },
      {
        label: "Latest run",
        value: latestLabel,
        detail: benchmarks.length + " benchmark rows",
      },
    ];
    host.innerHTML = cards.map(card =>
      '<article class="kpi-card">' +
        '<span class="kpi-label">' + esc(card.label) + '</span>' +
        '<span class="kpi-value">' + esc(card.value) + '</span>' +
        '<span class="kpi-detail">' + esc(card.detail) + '</span>' +
      '</article>'
    ).join("");
  }

  // ---- SVG line chart helper ----
  function svgLineChart(seriesList, opts) {
    const w = opts.width || 700;
    const h = opts.height || 160;
    const pad = { top: 20, right: 20, bottom: 32, left: 58 };
    const iw = w - pad.left - pad.right;
    const ih = h - pad.top - pad.bottom;

    const usableSeries = (seriesList || []).map(s => ({
      name: s.name || "",
      color: s.color || "#0d6efd",
      points: (s.points || []).filter(p => p && p.x && p.y != null),
    })).filter(s => s.points.length > 0);
    if (!usableSeries.length) return '<p class="empty-note">No data points for chart.</p>';

    const allPoints = usableSeries.flatMap(s => s.points);
    const xs = allPoints.map(p => p.x.getTime());
    const ys = allPoints.map(p => p.y);
    const xMin = Math.min(...xs);
    const xMax = Math.max(...xs);
    let yMin = opts.yMin != null ? opts.yMin : Math.min(...ys);
    let yMax = opts.yMax != null ? opts.yMax : Math.max(...ys);
    if (opts.includeZero) {
      yMin = Math.min(0, yMin);
    }
    if (yMax === yMin) {
      yMax = yMin + 1;
    }
    const yPad = (yMax - yMin) * 0.08;
    if (!opts.yMax) yMax += yPad;
    if (!opts.yMin) yMin = Math.max(0, yMin - yPad);

    function sx(v) { return pad.left + (xMax === xMin ? iw / 2 : (v - xMin) / (xMax - xMin) * iw); }
    function sy(v) { return pad.top + ih - (yMax === yMin ? ih / 2 : (v - yMin) / (yMax - yMin) * ih); }

    let svg = '<svg width="' + w + '" height="' + h + '" xmlns="http://www.w3.org/2000/svg">';

    const yTickFormatter = opts.yTickFormatter || (v => v.toFixed(2));
    const yTicks = opts.yTicks || 4;
    for (let i = 0; i <= yTicks; i++) {
      const v = yMin + (yMax - yMin) * i / yTicks;
      const y = sy(v);
      svg += '<line x1="' + pad.left + '" y1="' + y + '" x2="' + (w - pad.right) + '" y2="' + y + '" stroke="#e9ecef" stroke-width="1"/>';
      svg += '<text x="' + (pad.left - 5) + '" y="' + (y + 4) + '" text-anchor="end" font-size="10" fill="#6c757d">' + esc(yTickFormatter(v)) + '</text>';
    }

    if (opts.yLabel) {
      svg += '<text x="12" y="' + (pad.top + ih / 2) + '" text-anchor="middle" font-size="11" fill="#6c757d" transform="rotate(-90, 12, ' + (pad.top + ih / 2) + ')">' + esc(opts.yLabel) + '</text>';
    }

    svg += '<line x1="' + pad.left + '" y1="' + (h - pad.bottom) + '" x2="' + (w - pad.right) + '" y2="' + (h - pad.bottom) + '" stroke="#d6dee8" stroke-width="1"/>';
    const midTs = xMin + ((xMax - xMin) / 2);
    const xTickValues = [xMin, midTs, xMax];
    xTickValues.forEach(ts => {
      const x = sx(ts);
      const d = new Date(ts);
      const label = String(d.getFullYear()) + "-" + String(d.getMonth() + 1).padStart(2, "0") + "-" + String(d.getDate()).padStart(2, "0");
      svg += '<text x="' + x + '" y="' + (h - pad.bottom + 14) + '" text-anchor="middle" font-size="10" fill="#6c757d">' + label + '</text>';
    });

    usableSeries.forEach(series => {
      const ordered = [...series.points].sort((a, b) => a.x - b.x);
      const linePoints = ordered.map(p => sx(p.x.getTime()) + "," + sy(p.y)).join(" ");
      svg += '<polyline fill="none" stroke="' + series.color + '" stroke-width="2.25" points="' + linePoints + '"/>';
      ordered.forEach(point => {
        const cx = sx(point.x.getTime());
        const cy = sy(point.y);
        svg += '<circle cx="' + cx + '" cy="' + cy + '" r="3.1" fill="' + series.color + '">';
        svg += '<title>' + esc(point.label || "") + '</title></circle>';
      });
    });

    svg += '</svg>';
    return svg;
  }

  // ---- Throughput section ----
  function renderThroughput() {
    const records = filteredStage();
    const section = document.getElementById("throughput-section");
    if (records.length === 0) {
      section.innerHTML = '<h2>Stage / Import Throughput</h2><p class="empty-note">No stage/import records found. Run <code>cookimport perf-report</code> to generate performance history.</p>';
      return;
    }

    const scaleNote = document.getElementById("throughput-scale-note");
    if (scaleNote) {
      scaleNote.textContent = THROUGHPUT_SCALE_NOTES[throughputScaleMode] || THROUGHPUT_SCALE_NOTES.clamp95;
    }

    const chartDiv = document.getElementById("throughput-chart");
    const rawPoints = records
      .filter(r => r.per_recipe_seconds != null && r.run_timestamp)
      .map(r => ({
        x: parseTs(r.run_timestamp) || new Date(),
        rawY: r.per_recipe_seconds,
        label: r.file_name + ": " + r.per_recipe_seconds.toFixed(3) + " sec/recipe"
      }))
      .filter(p => p.x)
      .sort((a, b) => a.x - b.x);

    const rawValues = rawPoints.map(point => point.rawY);
    const clamp95 = percentile(rawValues, 95);
    const chartPoints = rawPoints.map(point => {
      let y = point.rawY;
      if (throughputScaleMode === "clamp95" && clamp95 != null) {
        y = Math.min(point.rawY, clamp95);
      } else if (throughputScaleMode === "log") {
        y = Math.log10(point.rawY + 1);
      }
      return {
        x: point.x,
        y,
        label: point.label,
      };
    });
    chartDiv.innerHTML = svgLineChart(
      [
        {
          name: "sec/recipe",
          color: "#1f5ea8",
          points: chartPoints,
        },
      ],
      {
        width: Math.min(920, Math.max(400, chartPoints.length * 30)),
        height: 170,
        yLabel: throughputScaleMode === "log" ? "log10(sec/recipe + 1)" : "sec / recipe",
        includeZero: throughputScaleMode !== "log",
      }
    );

    const recentRuns = [...records]
      .sort((a, b) => compareRunTimestampDesc(a.run_timestamp, b.run_timestamp));
    renderRowsWithCollapse({
      tableId: "recent-runs",
      rows: recentRuns,
      defaultVisible: TABLE_COLLAPSE_DEFAULT_ROWS["recent-runs"],
      label: "runs",
      rerender: renderThroughput,
      renderRow: r => {
        const tr = document.createElement("tr");
        tr.innerHTML =
          '<td>' + esc(r.run_timestamp || "") + '</td>' +
          '<td>' + esc(r.file_name) + '</td>' +
          '<td>' + esc(importerLabelForRecord(r)) + '</td>' +
          '<td class="num">' + (r.total_seconds != null ? r.total_seconds.toFixed(2) : "-") + '</td>' +
          '<td class="num">' + (r.recipes != null ? r.recipes : "-") + '</td>' +
          '<td class="num">' + (r.per_recipe_seconds != null ? r.per_recipe_seconds.toFixed(3) : "-") + '</td>' +
          extractorCells(r) +
          runConfigCell(r) +
          '<td><a href="' + esc(r.artifact_dir || "") + '">' + esc(shortPath(r.artifact_dir)) + '</a></td>';
        return tr;
      },
    });

    const fileSelect = document.getElementById("file-trend-select");
    const fileNames = Array.from(new Set(records.map(r => r.file_name).filter(Boolean)))
      .sort((a, b) => a.localeCompare(b));

    if (!fileNames.includes(selectedFileTrend)) {
      selectedFileTrend = fileNames[0] || "";
    }

    const nextOptions = fileNames.map(name =>
      '<option value="' + esc(name) + '"' + (name === selectedFileTrend ? " selected" : "") + '>' + esc(name) + "</option>"
    ).join("");
    if (fileSelect.innerHTML !== nextOptions) {
      fileSelect.innerHTML = nextOptions;
    }

    if (!fileSelect.dataset.bound) {
      fileSelect.addEventListener("change", () => {
        selectedFileTrend = fileSelect.value;
        renderThroughput();
      });
      fileSelect.dataset.bound = "1";
    }

    const fileRecords = records
      .filter(r => r.file_name === selectedFileTrend)
      .sort((a, b) => compareRunTimestampAsc(a.run_timestamp, b.run_timestamp));

    const filePoints = fileRecords
      .filter(r => r.total_seconds != null && r.run_timestamp)
      .map(r => ({
        x: parseTs(r.run_timestamp) || new Date(),
        y: r.total_seconds,
        label: (r.run_timestamp || "") + " " + selectedFileTrend + " total=" + r.total_seconds.toFixed(3) + "s"
      }))
      .sort((a, b) => a.x - b.x);

    const fileChart = document.getElementById("file-trend-chart");
    fileChart.innerHTML = svgLineChart(
      [
        {
          name: "total seconds",
          color: "#127a52",
          points: filePoints,
        },
      ],
      {
        width: Math.min(920, Math.max(400, filePoints.length * 48)),
        height: 165,
        yLabel: "total sec",
        includeZero: true,
      }
    );

    const fileRows = [...fileRecords]
      .sort((a, b) => compareRunTimestampDesc(a.run_timestamp, b.run_timestamp));
    renderRowsWithCollapse({
      tableId: "file-trend-table",
      rows: fileRows,
      defaultVisible: TABLE_COLLAPSE_DEFAULT_ROWS["file-trend-table"],
      label: "runs",
      rerender: renderThroughput,
      renderRow: r => {
        const tr = document.createElement("tr");
        tr.innerHTML =
          '<td>' + esc(r.run_timestamp || "") + '</td>' +
          '<td class="num">' + (r.total_seconds != null ? r.total_seconds.toFixed(2) : "-") + '</td>' +
          '<td class="num">' + (r.per_recipe_seconds != null ? r.per_recipe_seconds.toFixed(3) : "-") + '</td>' +
          '<td class="num">' + (r.recipes != null ? r.recipes : "-") + '</td>' +
          '<td>' + esc(importerLabelForRecord(r)) + '</td>' +
          extractorCells(r) +
          runConfigCell(r) +
          '<td><a href="' + esc(r.artifact_dir || "") + '">' + esc(shortPath(r.artifact_dir)) + '</a></td>';
        return tr;
      },
    });
  }

  // ---- Benchmark section ----
  function renderBenchmarks() {
    const records = filteredBenchmarks();
    const section = document.getElementById("benchmark-section");
    if (records.length === 0) {
      section.innerHTML = '<h2>Benchmark Evaluations</h2><p class="empty-note">No benchmark evaluation records found. Run an eval workflow to generate eval_report.json files.</p>';
      return;
    }

    const legend = document.getElementById("benchmark-legend");
    if (legend) {
      legend.innerHTML = (
        '<span class="chart-legend-item"><span class="chart-legend-dot" style="background:#127a52"></span>macro_f1_excluding_other</span>' +
        '<span class="chart-legend-item"><span class="chart-legend-dot" style="background:#1f5ea8"></span>strict_accuracy</span>'
      );
    }

    const chartDiv = document.getElementById("benchmark-chart");
    const macroPoints = records
      .filter(r => r.macro_f1_excluding_other != null && r.run_timestamp)
      .map(r => ({
        x: parseTs(r.run_timestamp) || new Date(),
        y: r.macro_f1_excluding_other,
        label: (r.run_timestamp || "") + " macro_f1_excluding_other=" + (r.macro_f1_excluding_other != null ? r.macro_f1_excluding_other.toFixed(4) : "?")
      }))
      .sort((a, b) => a.x - b.x);

    const strictPoints = records
      .filter(r => r.strict_accuracy != null && r.run_timestamp)
      .map(r => ({
        x: parseTs(r.run_timestamp) || new Date(),
        y: r.strict_accuracy,
        label: (r.run_timestamp || "") + " strict_accuracy=" + (r.strict_accuracy != null ? r.strict_accuracy.toFixed(4) : "?")
      }))
      .sort((a, b) => a.x - b.x);

    chartDiv.innerHTML = svgLineChart(
      [
        { name: "macro_f1_excluding_other", color: "#127a52", points: macroPoints },
        { name: "strict_accuracy", color: "#1f5ea8", points: strictPoints },
      ],
      {
        width: Math.min(920, Math.max(400, Math.max(macroPoints.length, strictPoints.length) * 38)),
        height: 182,
        yLabel: "score",
        yMin: 0,
        yMax: 1,
      }
    );

    const sorted = [...records].sort((a, b) => compareRunTimestampDesc(a.run_timestamp, b.run_timestamp));
    renderRowsWithCollapse({
      tableId: "benchmark-table",
      rows: sorted,
      defaultVisible: TABLE_COLLAPSE_DEFAULT_ROWS["benchmark-table"],
      label: "benchmarks",
      rerender: renderBenchmarks,
      renderRow: r => {
        const sourceLabel = sourceLabelForRecord(r);
        const sourceTitle = sourceTitleForRecord(r);
        const configSummary = runConfigSummary(r);
        const configRaw = r.run_config ? JSON.stringify(r.run_config) : "";
        const processedReportLink = r.processed_report_path
          ? ' <a href="' + esc(r.processed_report_path) + '" title="' + esc(r.processed_report_path) + '">report</a>'
          : "";
        const mismatchTag = r.granularity_mismatch_likely
          ? ' <span class="mismatch-tag" title="Strict IoU is low while practical overlap is high.">mismatch</span>'
          : "";
        const tr = document.createElement("tr");
        tr.innerHTML =
          '<td>' + esc(r.run_timestamp || "") + '</td>' +
          '<td class="num">' + fmt4(r.strict_accuracy) + '</td>' +
          '<td class="num">' + fmt4(r.macro_f1_excluding_other) + mismatchTag + '</td>' +
          '<td class="num">' + (r.gold_total != null ? r.gold_total : "-") + '</td>' +
          '<td class="num">' + (r.gold_matched != null ? r.gold_matched : "-") + '</td>' +
          '<td class="num">' + (r.recipes != null ? r.recipes : "-") + '</td>' +
          '<td title="' + esc(sourceTitle) + '">' + esc(sourceLabel || "-") + '</td>' +
          '<td>' + esc(importerLabelForRecord(r)) + '</td>' +
          '<td title="' + esc(configRaw) + '">' + esc(configSummary || "-") + '</td>' +
          '<td><a href="' + esc(r.artifact_dir || "") + '">' + esc(shortPath(r.artifact_dir)) + '</a>' + processedReportLink + '</td>';
        return tr;
      },
    });
  }

  function renderPreviousRunsTableColumns(table, columns) {
    const previousRunsTableKey = "previous-runs-table";
    const colgroup = table.querySelector("colgroup");
    const headerRow = table.querySelector("thead tr.previous-runs-header-row");
    const filterRow = table.querySelector("thead tr.previous-runs-active-filters-row");
    const spacerRow = table.querySelector("thead tr.previous-runs-filter-spacer-row");
    if (!colgroup || !headerRow || !filterRow || !spacerRow) return;

    colgroup.innerHTML = "";
    headerRow.innerHTML = "";
    filterRow.innerHTML = "";
    spacerRow.innerHTML = "";
    columns.forEach(fieldName => {
      const meta = previousRunsColumnMeta(fieldName);
      const filterClauses = previousRunsColumnFilterClauses(fieldName);
      const hasActiveFilters = filterClauses.length > 0;
      const isEditorOpen = previousRunsOpenFilterField === fieldName;
      const draftState = currentPreviousRunsColumnFilterDraft(fieldName);
      const col = document.createElement("col");
      col.dataset.columnKey = fieldName;
      const width = normalizeDashboardColumnWidth(previousRunsColumnWidths[fieldName]);
      const persistedWidth = width != null
        ? width
        : dashboardTableColumnWidth(previousRunsTableKey, fieldName);
      if (persistedWidth != null) {
        previousRunsColumnWidths[fieldName] = persistedWidth;
        setDashboardTableColumnWidth(previousRunsTableKey, fieldName, persistedWidth);
        col.style.width = persistedWidth + "px";
      }
      colgroup.appendChild(col);

      const th = document.createElement("th");
      th.dataset.columnKey = fieldName;
      const isSorted = previousRunsSortField === fieldName;
      const sortIndicator = isSorted
        ? (previousRunsSortDirection === "asc" ? " ▲" : " ▼")
        : "";

      const titleWrap = document.createElement("span");
      titleWrap.className = "previous-runs-header-title";
      const titleText = document.createElement("span");
      titleText.textContent = (meta.label || fieldName) + sortIndicator;
      titleWrap.appendChild(titleText);
      th.appendChild(titleWrap);
      setMetricTooltipTarget(th, fieldName, meta.title || fieldName);
      th.setAttribute(
        "aria-label",
        (meta.label || fieldName) + ". Click to sort A to Z / Z to A."
      );
      th.classList.add("previous-runs-draggable");
      th.draggable = true;
      if (meta.numeric) {
        th.classList.add("num");
      }
      th.addEventListener("click", event => {
        if (
          event.target instanceof HTMLElement
          && event.target.classList.contains("previous-runs-resize-handle")
        ) {
          return;
        }
        if (previousRunsSortField === fieldName) {
          previousRunsSortDirection = previousRunsSortDirection === "asc" ? "desc" : "asc";
        } else {
          previousRunsSortField = fieldName;
          previousRunsSortDirection = fieldName === "run_timestamp" ? "desc" : "asc";
        }
        renderPreviousRuns();
      });
      th.addEventListener("dragstart", event => {
        previousRunsDraggedColumn = fieldName;
        th.classList.add("previous-runs-drag-source");
        if (event.dataTransfer) {
          event.dataTransfer.effectAllowed = "move";
          event.dataTransfer.setData("text/plain", fieldName);
        }
      });
      th.addEventListener("dragover", event => {
        if (!previousRunsDraggedColumn || previousRunsDraggedColumn === fieldName) return;
        event.preventDefault();
        if (event.dataTransfer) {
          event.dataTransfer.dropEffect = "move";
        }
        th.classList.add("previous-runs-drag-target");
      });
      th.addEventListener("dragleave", () => {
        th.classList.remove("previous-runs-drag-target");
      });
      th.addEventListener("drop", event => {
        event.preventDefault();
        th.classList.remove("previous-runs-drag-target");
        const sourceField = previousRunsDraggedColumn || (
          event.dataTransfer ? event.dataTransfer.getData("text/plain") : ""
        );
        if (!sourceField || sourceField === fieldName) return;
        if (reorderPreviousRunsColumns(sourceField, fieldName)) {
          renderPreviousRunsColumnEditor();
          renderPreviousRuns();
        }
      });
      th.addEventListener("dragend", () => {
        previousRunsDraggedColumn = null;
        headerRow.querySelectorAll("th").forEach(candidate => {
          candidate.classList.remove("previous-runs-drag-source");
          candidate.classList.remove("previous-runs-drag-target");
        });
      });

      const resizeHandle = document.createElement("span");
      resizeHandle.className = "previous-runs-resize-handle";
      resizeHandle.setAttribute("aria-hidden", "true");
      resizeHandle.draggable = false;
      resizeHandle.addEventListener("mousedown", event => {
        event.preventDefault();
        event.stopPropagation();
        const startX = event.clientX;
        const startWidth = th.getBoundingClientRect().width;
        const minWidth = DASHBOARD_TABLE_COLUMN_MIN_WIDTH;
        const maxWidth = DASHBOARD_TABLE_COLUMN_MAX_WIDTH;
        document.body.classList.add("previous-runs-resizing");

        const onMove = moveEvent => {
          const nextWidth = Math.max(
            minWidth,
            Math.min(maxWidth, startWidth + (moveEvent.clientX - startX))
          );
          previousRunsColumnWidths[fieldName] = nextWidth;
          setDashboardTableColumnWidth(previousRunsTableKey, fieldName, nextWidth);
          th.style.width = nextWidth + "px";
          col.style.width = nextWidth + "px";
        };

        const onUp = () => {
          document.body.classList.remove("previous-runs-resizing");
          window.removeEventListener("mousemove", onMove);
          window.removeEventListener("mouseup", onUp);
          persistDashboardUiState();
        };

        window.addEventListener("mousemove", onMove);
        window.addEventListener("mouseup", onUp);
      });
      th.appendChild(resizeHandle);
      headerRow.appendChild(th);

      const filterTh = document.createElement("th");
      filterTh.dataset.columnKey = fieldName;
      const filterWrap = document.createElement("div");
      filterWrap.className = "previous-runs-column-filter";

      const summaryWrap = document.createElement("div");
      summaryWrap.className = "previous-runs-column-filter-summary-wrap";
      const summary = document.createElement("div");
      summary.className = "previous-runs-column-filter-summary";
      if (hasActiveFilters) {
        summary.classList.add("filter-active");
        const mode = previousRunsColumnFilterMode(fieldName);
        const joinLabel = String(PREVIOUS_RUNS_COLUMN_FILTER_MODE_LABEL[mode] || mode).toUpperCase();
        filterClauses.forEach((clause, clauseIndex) => {
          const summaryItem = document.createElement("div");
          summaryItem.className = "previous-runs-column-filter-summary-item";
          const summaryEditBtn = document.createElement("button");
          summaryEditBtn.type = "button";
          summaryEditBtn.className = "previous-runs-column-filter-summary-edit";
          const prefix = clauseIndex > 0 ? joinLabel + " " : "";
          summaryEditBtn.textContent = prefix + formatPreviousRunsColumnFilterSummary(fieldName, clause);
          summaryEditBtn.setAttribute("aria-label", "Edit filter " + String(clauseIndex + 1));
          summaryEditBtn.addEventListener("click", event => {
            event.preventDefault();
            event.stopPropagation();
            openPreviousRunsColumnFilterEditor(
              fieldName,
              {
                operator: clause.operator,
                value: clause.value,
                edit_index: clauseIndex,
              },
            );
            renderPreviousRuns();
          });
          summaryItem.appendChild(summaryEditBtn);
          const summaryRemoveBtn = document.createElement("button");
          summaryRemoveBtn.type = "button";
          summaryRemoveBtn.className = "previous-runs-column-filter-summary-remove";
          setPreviousRunsIcon(summaryRemoveBtn, "close");
          summaryRemoveBtn.setAttribute("aria-label", "Remove filter " + String(clauseIndex + 1));
          summaryRemoveBtn.addEventListener("click", event => {
            event.preventDefault();
            event.stopPropagation();
            removePreviousRunsColumnFilterAt(fieldName, clauseIndex);
            renderAll();
          });
          summaryItem.appendChild(summaryRemoveBtn);
          summary.appendChild(summaryItem);
        });
      } else {
        summary.textContent = "No filter";
      }
      summaryWrap.appendChild(summary);

      const toggleBtn = document.createElement("button");
      toggleBtn.type = "button";
      toggleBtn.className = "previous-runs-column-filter-toggle";
      if (hasActiveFilters) {
        toggleBtn.classList.add("filter-active");
      }
      setPreviousRunsIcon(toggleBtn, isEditorOpen ? "minus" : "plus");
      toggleBtn.title = isEditorOpen ? "Close filter editor" : "Open filter editor";
      toggleBtn.setAttribute("aria-label", (meta.label || fieldName) + " filter editor");
      toggleBtn.setAttribute("aria-expanded", isEditorOpen ? "true" : "false");
      toggleBtn.addEventListener("click", event => {
        event.preventDefault();
        event.stopPropagation();
        if (previousRunsOpenFilterField === fieldName) {
          closePreviousRunsColumnFilterEditor();
        } else {
          openPreviousRunsColumnFilterEditor(fieldName);
        }
        renderPreviousRuns();
      });
      summaryWrap.appendChild(toggleBtn);
      filterWrap.appendChild(summaryWrap);

      if (isEditorOpen) {
        const popover = document.createElement("div");
        popover.className = "previous-runs-column-filter-popover";
        const columnMode = previousRunsColumnFilterMode(fieldName);
        const editClauseIndex = Number.isInteger(draftState.edit_index)
          ? draftState.edit_index
          : null;

        const popoverTitle = document.createElement("div");
        popoverTitle.className = "previous-runs-column-filter-popover-title";
        popoverTitle.textContent = (meta.label || fieldName)
          + (draftState.editing ? " filter (edit)" : " filter");
        popover.appendChild(popoverTitle);

        const modeWrap = document.createElement("div");
        modeWrap.className = "previous-runs-column-filter-mode";
        const modeLabel = document.createElement("span");
        modeLabel.className = "previous-runs-column-filter-mode-label";
        modeLabel.textContent = "Stack mode";
        modeWrap.appendChild(modeLabel);
        const modeButtons = document.createElement("div");
        modeButtons.className = "previous-runs-column-filter-mode-buttons";
        PREVIOUS_RUNS_COLUMN_FILTER_MODES.forEach(([modeValue, modeLabelText]) => {
          const modeBtn = document.createElement("button");
          modeBtn.type = "button";
          modeBtn.className = "previous-runs-column-filter-mode-btn";
          modeBtn.textContent = modeLabelText;
          if (modeValue === columnMode) {
            modeBtn.classList.add("active");
          }
          modeBtn.disabled = !hasActiveFilters;
          modeBtn.addEventListener("click", () => {
            if (!hasActiveFilters) return;
            setPreviousRunsColumnFilterMode(fieldName, modeValue);
            renderAll();
          });
          modeButtons.appendChild(modeBtn);
        });
        modeWrap.appendChild(modeButtons);
        popover.appendChild(modeWrap);

        const activeList = document.createElement("div");
        activeList.className = "previous-runs-column-filter-active-list";
        if (hasActiveFilters) {
          filterClauses.forEach((clause, clauseIndex) => {
            const row = document.createElement("div");
            row.className = "previous-runs-column-filter-active-item";
            const text = document.createElement("span");
            text.textContent = formatPreviousRunsColumnFilterSummary(fieldName, clause);
            row.appendChild(text);
            const removeBtn = document.createElement("button");
            removeBtn.type = "button";
            removeBtn.className = "previous-runs-column-filter-active-remove";
            setPreviousRunsIcon(removeBtn, "close");
            removeBtn.setAttribute("aria-label", "Remove filter " + String(clauseIndex + 1));
            removeBtn.addEventListener("click", () => {
              removePreviousRunsColumnFilterAt(fieldName, clauseIndex);
              renderAll();
            });
            row.appendChild(removeBtn);
            activeList.appendChild(row);
          });
        } else {
          const empty = document.createElement("div");
          empty.className = "previous-runs-column-filter-active-empty";
          empty.textContent = "No active filters yet.";
          activeList.appendChild(empty);
        }
        popover.appendChild(activeList);

        const controls = document.createElement("div");
        controls.className = "previous-runs-column-filter-popover-controls";

        const operatorSelect = document.createElement("select");
        operatorSelect.setAttribute("aria-label", (meta.label || fieldName) + " filter operator");
        PREVIOUS_RUNS_COLUMN_FILTER_OPERATORS.forEach(([operatorValue, operatorLabel]) => {
          const option = document.createElement("option");
          option.value = operatorValue;
          option.textContent = operatorLabel;
          if (operatorValue === draftState.operator) {
            option.selected = true;
          }
          operatorSelect.appendChild(option);
        });
        controls.appendChild(operatorSelect);

        const valueInput = document.createElement("input");
        valueInput.type = "text";
        valueInput.value = draftState.value;
        valueInput.placeholder = meta.numeric ? "number" : "value";
        valueInput.setAttribute("aria-label", (meta.label || fieldName) + " filter value");
        valueInput.disabled = PREVIOUS_RUNS_UNARY_FILTER_OPERATORS.has(draftState.operator);
        controls.appendChild(valueInput);

        popover.appendChild(controls);

        const suggestionWrap = document.createElement("div");
        suggestionWrap.className = "previous-runs-column-filter-suggestions";
        const suggestionTitle = document.createElement("div");
        suggestionTitle.className = "previous-runs-column-filter-suggestions-title";
        suggestionWrap.appendChild(suggestionTitle);
        const suggestionList = document.createElement("div");
        suggestionList.className = "previous-runs-column-filter-suggestions-list";
        suggestionWrap.appendChild(suggestionList);
        popover.appendChild(suggestionWrap);

        function syncDraft(operatorValue, valueText) {
          const nextOperator = PREVIOUS_RUNS_COLUMN_FILTER_OPERATOR_MAP[operatorValue]
            ? String(operatorValue)
            : "contains";
          const unary = PREVIOUS_RUNS_UNARY_FILTER_OPERATORS.has(nextOperator);
          const nextValue = unary ? "" : String(valueText || "");
          if (!previousRunsOpenFilterDraft || previousRunsOpenFilterField !== fieldName) {
            previousRunsOpenFilterDraft = {
              operator: nextOperator,
              value: nextValue,
            };
            return;
          }
          previousRunsOpenFilterDraft.operator = nextOperator;
          previousRunsOpenFilterDraft.value = nextValue;
        }

        function renderSuggestionList() {
          const operatorValue = String(operatorSelect.value || "contains");
          const unary = PREVIOUS_RUNS_UNARY_FILTER_OPERATORS.has(operatorValue);
          if (unary || meta.numeric) {
            suggestionWrap.hidden = true;
            valueInput.dataset.topSuggestion = "";
            suggestionList.innerHTML = "";
            return;
          }

          const typedText = String(valueInput.value || "");
          const candidates = previousRunsColumnSuggestionCandidates(fieldName, typedText);
          const topCandidate = candidates.length ? candidates[0].value : "";
          valueInput.dataset.topSuggestion = topCandidate;
          suggestionWrap.hidden = false;
          suggestionList.innerHTML = "";
          if (!candidates.length) {
            suggestionTitle.textContent = "No matching suggestions.";
            return;
          }

          suggestionTitle.textContent = topCandidate
            ? "Tab completes top match."
            : "Suggestions";

          candidates.forEach((candidate, candidateIndex) => {
            const button = document.createElement("button");
            button.type = "button";
            button.className = "previous-runs-column-filter-suggestion";
            if (candidateIndex === 0) {
              button.classList.add("best");
            }
            button.textContent = candidate.value;
            button.title = candidate.value + " (" + candidate.count + " rows)";
            button.addEventListener("click", () => {
              valueInput.value = candidate.value;
              syncDraft(operatorSelect.value || "contains", valueInput.value || "");
              renderSuggestionList();
              valueInput.focus();
            });
            suggestionList.appendChild(button);
          });
        }

        function applyFilterAndClose() {
          if (editClauseIndex != null) {
            updatePreviousRunsColumnFilterAt(
              fieldName,
              editClauseIndex,
              operatorSelect.value || "contains",
              valueInput.value || "",
            );
          } else {
            addPreviousRunsColumnFilter(fieldName, operatorSelect.value || "contains", valueInput.value || "");
          }
          closePreviousRunsColumnFilterEditor();
          renderAll();
        }

        operatorSelect.addEventListener("change", () => {
          const nextOperator = String(operatorSelect.value || "contains");
          const unary = PREVIOUS_RUNS_UNARY_FILTER_OPERATORS.has(nextOperator);
          if (unary) {
            valueInput.value = "";
          }
          syncDraft(nextOperator, valueInput.value || "");
          valueInput.disabled = unary;
          renderSuggestionList();
        });

        valueInput.addEventListener("input", () => {
          syncDraft(operatorSelect.value || "contains", valueInput.value || "");
          renderSuggestionList();
        });
        valueInput.addEventListener("keydown", event => {
          if (event.key === "Tab" && !event.shiftKey) {
            const suggested = String(valueInput.dataset.topSuggestion || "");
            const current = String(valueInput.value || "");
            if (
              suggested &&
              normalizeRuleValue(suggested) !== normalizeRuleValue(current)
            ) {
              event.preventDefault();
              valueInput.value = suggested;
              syncDraft(operatorSelect.value || "contains", valueInput.value || "");
              renderSuggestionList();
              return;
            }
          }
          if (event.key !== "Enter") return;
          event.preventDefault();
          applyFilterAndClose();
        });

        const actions = document.createElement("div");
        actions.className = "previous-runs-column-filter-popover-actions";

        const saveBtn = document.createElement("button");
        saveBtn.type = "button";
        saveBtn.className = "previous-runs-column-filter-save";
        saveBtn.textContent = "Save";
        saveBtn.addEventListener("click", applyFilterAndClose);
        actions.appendChild(saveBtn);

        const clearBtn = document.createElement("button");
        clearBtn.type = "button";
        clearBtn.className = "previous-runs-column-filter-clear";
        clearBtn.textContent = "Clear";
        clearBtn.disabled = !hasActiveFilters;
        clearBtn.addEventListener("click", () => {
          clearPreviousRunsColumnFilter(fieldName);
          closePreviousRunsColumnFilterEditor();
          renderAll();
        });
        actions.appendChild(clearBtn);

        const closeBtn = document.createElement("button");
        closeBtn.type = "button";
        closeBtn.className = "previous-runs-column-filter-close";
        closeBtn.textContent = "Close";
        closeBtn.addEventListener("click", () => {
          closePreviousRunsColumnFilterEditor();
          renderPreviousRuns();
        });
        actions.appendChild(closeBtn);

        popover.appendChild(actions);
        renderSuggestionList();
        filterWrap.appendChild(popover);
      }

      filterTh.appendChild(filterWrap);
      filterRow.appendChild(filterTh);

      const spacerTh = document.createElement("th");
      spacerTh.dataset.columnKey = fieldName;
      spacerRow.appendChild(spacerTh);
    });

    const headerHeight = headerRow.getBoundingClientRect().height;
    const filterHeight = filterRow.getBoundingClientRect().height;
    const spacerHeight = spacerRow.getBoundingClientRect().height;
    if (headerHeight > 0) {
      table.style.setProperty("--previous-runs-header-row-height", headerHeight + "px");
    }
    if (filterHeight > 0) {
      table.style.setProperty("--previous-runs-filter-row-height", filterHeight + "px");
    }
    if (spacerHeight > 0) {
      table.style.setProperty("--previous-runs-spacer-row-height", spacerHeight + "px");
    }
  }

  function previousRunsRowFieldValue(row, fieldName) {
    if (fieldName === "run_timestamp") return row.run_timestamp || "";
    if (row.type === "all_method") {
      if (fieldName === "source_label") return row.source || "-";
      if (fieldName === "source_file_basename") return row.source || "-";
      if (fieldName === "importer_name") return row.importer_name || "-";
      if (fieldName === "ai_model") return row.ai_model || "-";
      if (fieldName === "ai_effort") return row.ai_effort || "-";
      if (fieldName === "ai_assistance_profile") return row.ai_assistance_profile || "-";
      if (fieldName === "ai_model_effort") return row.ai_model_effort || "-";
      if (fieldName === "all_token_use") {
        return discountedTokenTotalForRecord(row);
      }
      if (fieldName === "quality_per_million_tokens") {
        return benchmarkQualityPerMillionTokensForRecord(row);
      }
      if (fieldName === "artifact_dir") return row.href || "";
      if (Object.prototype.hasOwnProperty.call(row, fieldName)) {
        return row[fieldName];
      }
      return null;
    }

    const record = row.record;
    if (!record) return null;
    if (fieldName === "source_label") return sourceLabelForRecord(record);
    if (fieldName === "importer_name") return importerLabelForRecord(record);
    if (fieldName === "ai_model") return aiModelLabelForRecord(record);
    if (fieldName === "ai_effort") return aiEffortLabelForRecord(record);
    if (fieldName === "ai_assistance_profile") return aiAssistanceProfileLabelForRecord(record);
    if (fieldName === "ai_model_effort") return aiModelEffortLabelForRecord(record);
    if (fieldName === "all_token_use") {
      return discountedTokenTotalForRecord(record);
    }
    if (fieldName === "quality_per_million_tokens") {
      return benchmarkQualityPerMillionTokensForRecord(record);
    }
    if (fieldName === "artifact_dir") return record.artifact_dir || "";
    return previousRunsFieldValue(record, fieldName);
  }

  function previousRunsDiscountedTokenTotal(tokensInput, tokensCachedInput, tokensOutput, tokensTotal) {
    const input = maybeNumber(tokensInput);
    const cached = maybeNumber(tokensCachedInput);
    const output = maybeNumber(tokensOutput);
    const rawTotal = maybeNumber(tokensTotal);
    if (input == null && cached == null && output == null) {
      return rawTotal;
    }

    let effectiveInput = input != null ? input : 0;
    if (cached != null) {
      if (input != null) {
        effectiveInput = Math.max(0, input - cached) + (cached * 0.1);
      } else {
        effectiveInput = cached * 0.1;
      }
    }
    const effectiveOutput = output != null ? output : 0;
    return effectiveInput + effectiveOutput;
  }

  function discountedTokenTotalForRecord(record) {
    return previousRunsDiscountedTokenTotal(
      maybeNumber(record && record.tokens_input),
      maybeNumber(record && record.tokens_cached_input),
      maybeNumber(record && record.tokens_output),
      maybeNumber(record && record.tokens_total),
    );
  }

  function previousRunsMetricPerRecipe(metricValue, recipesValue) {
    const metric = maybeNumber(metricValue);
    const recipes = maybeNumber(recipesValue);
    if (metric == null || recipes == null || !Number.isFinite(recipes) || recipes <= 0) {
      return null;
    }
    return metric / recipes;
  }

  function discountedTokenTotalForRecords(records) {
    let total = 0;
    let hasTokenUse = false;
    (records || []).forEach(record => {
      const discounted = discountedTokenTotalForRecord(record);
      if (discounted == null || !Number.isFinite(discounted)) return;
      total += discounted;
      hasTokenUse = true;
    });
    return {
      discountedTokenTotal: hasTokenUse ? total : null,
      hasTokenUse,
    };
  }

  function benchmarkQualityMetricValue(record, preferredMetricKey) {
    const preferred = String(preferredMetricKey || "").trim();
    if (preferred) {
      const preferredValue = maybeNumber(record && record[preferred]);
      if (preferredValue != null) {
        return { metricKey: preferred, value: preferredValue };
      }
    }
    for (let i = 0; i < BENCHMARK_QUALITY_METRIC_KEYS.length; i++) {
      const metricKey = BENCHMARK_QUALITY_METRIC_KEYS[i];
      const value = maybeNumber(record && record[metricKey]);
      if (value != null) {
        return { metricKey, value };
      }
    }
    return { metricKey: preferred || null, value: null };
  }

  function benchmarkQualityMetricForRecords(records, preferredMetricKey) {
    const preferred = String(preferredMetricKey || "").trim();
    if (preferred) return preferred;
    for (let i = 0; i < BENCHMARK_QUALITY_METRIC_KEYS.length; i++) {
      const metricKey = BENCHMARK_QUALITY_METRIC_KEYS[i];
      const hasMetric = (records || []).some(record => maybeNumber(record && record[metricKey]) != null);
      if (hasMetric) return metricKey;
    }
    return null;
  }

  function aggregateBenchmarkQuality(records, preferredMetricKey) {
    const metricKey = benchmarkQualityMetricForRecords(records, preferredMetricKey);
    if (!metricKey) {
      return {
        metricKey: null,
        qualityScore: null,
        qualityCount: 0,
      };
    }

    const qualityValues = [];
    let weightedNumerator = 0;
    let weightedDenominator = 0;
    (records || []).forEach(record => {
      const value = maybeNumber(record && record[metricKey]);
      if (value == null) return;
      qualityValues.push(value);
      const weight = maybeNumber(record && record.gold_total);
      if (weight == null || !Number.isFinite(weight) || weight <= 0) return;
      weightedNumerator += value * weight;
      weightedDenominator += weight;
    });

    if (!qualityValues.length) {
      return {
        metricKey,
        qualityScore: null,
        qualityCount: 0,
      };
    }

    return {
      metricKey,
      qualityScore: weightedDenominator > 0 ? (weightedNumerator / weightedDenominator) : mean(qualityValues),
      qualityCount: qualityValues.length,
    };
  }

  function qualityPerMillionTokensValue(qualityScore, tokenTotal) {
    const quality = maybeNumber(qualityScore);
    const tokens = maybeNumber(tokenTotal);
    if (quality == null || tokens == null || !Number.isFinite(tokens) || tokens <= 0) {
      return null;
    }
    return (quality * QUALITY_PER_TOKEN_SCALE) / tokens;
  }

  function benchmarkQualityPerMillionTokensForRecord(record) {
    const quality = benchmarkQualityMetricValue(record);
    if (!quality.metricKey || quality.value == null) return null;
    return qualityPerMillionTokensValue(
      quality.value,
      discountedTokenTotalForRecord(record),
    );
  }

  function formatSigned4(value) {
    const number = maybeNumber(value);
    if (number == null) return "-";
    if (Math.abs(number) <= 1e-12) return "0.0000";
    return (number > 0 ? "+" : "") + number.toFixed(4);
  }

  function runtimeQualityPeerStats(records, currentRunGroupKey, preferredMetricKey) {
    const key = String(currentRunGroupKey || "").trim();
    if (!key) return null;
    const groupsByKey = Object.create(null);
    (records || []).forEach(record => {
      if (!record) return;
      const info = benchmarkRunGroupInfo(record);
      const runGroupKey = String((info && info.runGroupKey) || "").trim();
      if (!runGroupKey) return;
      if (!groupsByKey[runGroupKey]) groupsByKey[runGroupKey] = [];
      groupsByKey[runGroupKey].push(record);
    });

    const ranked = Object.keys(groupsByKey)
      .map(runGroupKey => {
        const runGroupRecords = groupsByKey[runGroupKey];
        const quality = aggregateBenchmarkQuality(runGroupRecords, preferredMetricKey);
        const tokens = discountedTokenTotalForRecords(runGroupRecords);
        const qualityPerMillionTokens = qualityPerMillionTokensValue(
          quality.qualityScore,
          tokens.discountedTokenTotal,
        );
        if (qualityPerMillionTokens == null || !Number.isFinite(qualityPerMillionTokens)) return null;
        return {
          runGroupKey,
          qualityPerMillionTokens,
        };
      })
      .filter(item => item != null)
      .sort((left, right) => {
        if (right.qualityPerMillionTokens !== left.qualityPerMillionTokens) {
          return right.qualityPerMillionTokens - left.qualityPerMillionTokens;
        }
        return String(left.runGroupKey || "").localeCompare(String(right.runGroupKey || ""));
      });

    if (!ranked.length) return null;
    const currentIndex = ranked.findIndex(item => item.runGroupKey === key);
    if (currentIndex < 0) return null;
    const values = ranked
      .map(item => item.qualityPerMillionTokens)
      .sort((left, right) => left - right);
    const mid = Math.floor(values.length / 2);
    const median = values.length % 2 === 1
      ? values[mid]
      : (values[mid - 1] + values[mid]) / 2;
    const current = ranked[currentIndex];
    return {
      rank: currentIndex + 1,
      total: ranked.length,
      currentValue: current.qualityPerMillionTokens,
      medianValue: median,
      ratioToMedian: median > 0 ? (current.qualityPerMillionTokens / median) : null,
    };
  }

  function runtimeQualityPeerSummaryText(stats) {
    if (!stats) return "-";
    const rank = Math.max(1, Math.round(Number(stats.rank || 0)));
    const total = Math.max(1, Math.round(Number(stats.total || 0)));
    const ratio = maybeNumber(stats.ratioToMedian);
    const ratioText = ratio != null ? (ratio.toFixed(2) + "x median") : "median n/a";
    return "rank " + rank + "/" + total + " (" + ratioText + ")";
  }

  function previousRunsTokenPartsForRow(row) {
    if (row.type === "all_method") {
      return {
        total: previousRunsDiscountedTokenTotal(
          maybeNumber(row.tokens_input),
          maybeNumber(row.tokens_cached_input),
          maybeNumber(row.tokens_output),
          maybeNumber(row.tokens_total),
        ),
        input: maybeNumber(row.tokens_input),
        cached_input: maybeNumber(row.tokens_cached_input),
        output: maybeNumber(row.tokens_output),
        raw_total: maybeNumber(row.tokens_total),
      };
    }
    const record = row.record || null;
    return {
      total: previousRunsDiscountedTokenTotal(
        maybeNumber(record && record.tokens_input),
        maybeNumber(record && record.tokens_cached_input),
        maybeNumber(record && record.tokens_output),
        maybeNumber(record && record.tokens_total),
      ),
      input: maybeNumber(record && record.tokens_input),
      cached_input: maybeNumber(record && record.tokens_cached_input),
      output: maybeNumber(record && record.tokens_output),
      raw_total: maybeNumber(record && record.tokens_total),
    };
  }

  function formatTokenCount(value) {
    if (value == null || !Number.isFinite(value)) return "-";
    const rounded = Math.round(value);
    if (Math.abs(value - rounded) < 1e-9) {
      return rounded.toLocaleString("en-US");
    }
    return value.toLocaleString("en-US", {
      minimumFractionDigits: 1,
      maximumFractionDigits: 1,
    });
  }

  function formatTokenCountCompact(value) {
    if (value == null || !Number.isFinite(value)) return "-";
    const absValue = Math.abs(value);
    const sign = value < 0 ? "-" : "";
    if (absValue >= 1000000) {
      const millionsText = Number((absValue / 1000000).toFixed(2)).toString();
      return sign + millionsText + "m";
    }
    if (absValue >= 1000) {
      const thousands = Math.floor(absValue / 1000);
      return sign + String(thousands) + "k";
    }
    return formatTokenCount(value);
  }

  function previousRunsAllTokenUseDisplay(row) {
    const parts = previousRunsTokenPartsForRow(row);
    if (parts.total == null && parts.input == null && parts.output == null) {
      return "-";
    }
    return (
      formatTokenCountCompact(parts.total) +
      " total | " +
      formatTokenCountCompact(parts.input) +
      " in | " +
      formatTokenCountCompact(parts.output) +
      " out"
    );
  }

  function previousRunsAllTokenUseTitle(row) {
    const parts = previousRunsTokenPartsForRow(row);
    if (
      parts.total == null &&
      parts.input == null &&
      parts.cached_input == null &&
      parts.output == null
    ) {
      return "";
    }
    return (
      "discounted_total=" +
      formatTokenCount(parts.total) +
      " (cached input at 0.1x), raw_total=" +
      formatTokenCount(parts.raw_total) +
      ", input=" +
      formatTokenCount(parts.input) +
      ", cached_input=" +
      formatTokenCount(parts.cached_input) +
      ", output=" +
      formatTokenCount(parts.output)
    );
  }

  function previousRunsQualityPerMillionTokensTitle(row) {
    const qualityPerMillionTokens = previousRunsRowFieldValue(row, "quality_per_million_tokens");
    const parts = previousRunsTokenPartsForRow(row);
    const source = row.type === "all_method" ? row : row.record;
    const quality = benchmarkQualityMetricValue(source || null);
    if (
      qualityPerMillionTokens == null &&
      quality.value == null &&
      parts.total == null
    ) {
      return "";
    }
    return (
      "metric=" +
      String(quality.metricKey || "-") +
      ", quality=" +
      fmt4(quality.value) +
      ", discounted_total=" +
      formatTokenCount(parts.total) +
      ", quality_per_1M_tokens=" +
      fmt4(qualityPerMillionTokens)
    );
  }

  function previousRunsDisplayValue(fieldName, value) {
    if (value == null || value === "") return "-";
    if (fieldName === "run_timestamp") return String(value);
    if (PREVIOUS_RUNS_SCORE_FIELDS.has(fieldName)) return fmt4(value);
    if (typeof value === "boolean") return value ? "true" : "false";
    if (typeof value === "number") {
      if (!Number.isFinite(value)) return "-";
      return Number.isInteger(value) ? String(value) : Number(value).toFixed(4);
    }
    return String(value);
  }

  function previousRunsCellTitle(row, fieldName) {
    if (fieldName === "run_timestamp") {
      return row.href || "";
    }
    if (fieldName === "all_token_use") {
      return previousRunsAllTokenUseTitle(row);
    }
    if (fieldName === "quality_per_million_tokens") {
      return previousRunsQualityPerMillionTokensTitle(row);
    }
    if (row.type === "single" && fieldName === "source_label" && row.record) {
      return sourceTitleForRecord(row.record);
    }
    const value = previousRunsRowFieldValue(row, fieldName);
    if (value == null) return "";
    return typeof value === "string" ? value : String(value);
  }

  function previousRunsValueIsNumeric(fieldName, value) {
    if (previousRunsColumnMeta(fieldName).numeric) return true;
    if (PREVIOUS_RUNS_SCORE_FIELDS.has(fieldName)) return true;
    return typeof value === "number" && Number.isFinite(value);
  }

  function comparePreviousRunsFieldValues(fieldName, left, right) {
    if (fieldName === "run_timestamp") {
      return compareRunTimestampAsc(left, right);
    }

    const leftEmpty = left == null || left === "";
    const rightEmpty = right == null || right === "";
    if (leftEmpty && rightEmpty) return 0;
    if (leftEmpty) return 1;
    if (rightEmpty) return -1;

    const leftNumber = maybeNumber(left);
    const rightNumber = maybeNumber(right);
    if (leftNumber != null && rightNumber != null) {
      if (leftNumber < rightNumber) return -1;
      if (leftNumber > rightNumber) return 1;
      return 0;
    }

    const leftText = String(left).toLowerCase();
    const rightText = String(right).toLowerCase();
    return leftText.localeCompare(rightText, undefined, { numeric: true });
  }

  function comparePreviousRunsRows(leftRow, rightRow) {
    const fieldName = String(previousRunsSortField || "run_timestamp");
    const direction = previousRunsSortDirection === "asc" ? 1 : -1;
    const leftValue = previousRunsRowFieldValue(leftRow, fieldName);
    const rightValue = previousRunsRowFieldValue(rightRow, fieldName);
    const primary = comparePreviousRunsFieldValues(fieldName, leftValue, rightValue);
    if (primary !== 0) return primary * direction;

    const tieBreak = compareRunTimestampDesc(leftRow.run_timestamp, rightRow.run_timestamp);
    if (tieBreak !== 0) return tieBreak;
    const leftHref = String(leftRow.href || "");
    const rightHref = String(rightRow.href || "");
    return leftHref.localeCompare(rightHref);
  }

  function renderPreviousRunsCell(row, fieldName) {
    const td = document.createElement("td");
    if (fieldName === "run_timestamp") {
      const ts = row.run_timestamp || "";
      const href = row.href || "";
      if (href) {
        const link = document.createElement("a");
        link.href = href;
        link.title = href;
        link.textContent = ts || "-";
        td.appendChild(link);
      } else {
        td.textContent = ts || "-";
      }
      return td;
    }
    if (fieldName === "all_token_use") {
      const value = previousRunsRowFieldValue(row, fieldName);
      if (previousRunsValueIsNumeric(fieldName, value)) {
        td.classList.add("num");
      }
      td.textContent = previousRunsAllTokenUseDisplay(row);
      const title = previousRunsAllTokenUseTitle(row);
      if (title) {
        td.title = title;
      }
      return td;
    }

    const value = previousRunsRowFieldValue(row, fieldName);
    if (previousRunsValueIsNumeric(fieldName, value)) {
      td.classList.add("num");
    }
    td.textContent = previousRunsDisplayValue(fieldName, value);
    const title = previousRunsCellTitle(row, fieldName);
    if (title) {
      td.title = title;
    }
    return td;
  }

  // ---- Previous runs section ----
  function renderPreviousRuns() {
    const filterResult = currentPreviousRunsFilterResult();
    const records = filterResult.records;
    const section = document.getElementById("previous-runs-section");
    const table = document.getElementById("previous-runs-table");
    if (!section || !table) return;
    const tbody = table.querySelector("tbody");
    if (!tbody) return;
    ensurePreviousRunsColumns();
    setupPreviousRunsGlobalFilterModeControl();
    const visibleColumns = [...previousRunsVisibleColumns];
    renderPreviousRunsTableColumns(table, visibleColumns);
    renderPreviousRunsColumnEditor();

    if (records.length === 0) {
      const emptyMessage = filterResult.total === 0
        ? "No benchmark evaluation records found. Run an eval workflow to generate eval_report.json files."
        : "No benchmark rows match the current Previous Runs filters.";
      const colspan = Math.max(1, visibleColumns.length);
      tbody.innerHTML = '<tr><td colspan="' + colspan + '" class="empty-note-cell">' + esc(emptyMessage) + "</td></tr>";
      persistDashboardUiState();
      return;
    }

    const ALL_METHOD_SEGMENT = "all-method-benchmark";
    const ALL_METHOD_CONFIG_PREFIX = "config_";

    function normalizePathParts(pathValue) {
      if (pathValue == null) return { prefix: "", parts: [] };
      const raw = String(pathValue).trim().replace(/\\/g, "/");
      if (!raw) return { prefix: "", parts: [] };
      const prefix = raw.startsWith("/") ? "/" : "";
      const parts = raw.split("/").filter(p => p && p !== ".");
      return { prefix, parts };
    }

    function isTimestampToken(token) {
      const text = String(token || "").trim();
      if (!text) return false;
      return /^\d{4}-\d{2}-\d{2}[T_]\d{2}[.:]\d{2}[.:]\d{2}(?:_.+)?$/.test(text);
    }

    function nearestRunTimestamp(parts, beforeIndex) {
      if (!Array.isArray(parts) || beforeIndex <= 0) return null;
      for (let i = beforeIndex - 1; i >= 0; i--) {
        const candidate = parts[i];
        if (isTimestampToken(candidate)) return String(candidate);
      }
      return null;
    }

    function allMethodRunInfo(record) {
      const artifactDir = record ? record.artifact_dir : null;
      const info = normalizePathParts(artifactDir);
      if (info.parts.length < 3) return null;
      const lower = info.parts.map(p => String(p).toLowerCase());
      for (let idx = 0; idx < lower.length; idx++) {
        if (lower[idx] !== ALL_METHOD_SEGMENT) continue;
        if (idx + 2 >= info.parts.length) continue;
        const sourceSlug = info.parts[idx + 1];
        const configDir = info.parts[idx + 2];
        if (!String(configDir).startsWith(ALL_METHOD_CONFIG_PREFIX)) continue;
        const runDirTimestamp = nearestRunTimestamp(info.parts, idx);
        const fallbackTimestamp = String((record && record.run_timestamp) || "").trim();
        const runRootDir = info.prefix + info.parts.slice(0, idx + 1).join("/");
        const groupDir = info.prefix + info.parts.slice(0, idx + 2).join("/");
        return {
          runKey: runRootDir || groupDir,
          groupKey: groupDir,
          runDirTimestamp: runDirTimestamp || fallbackTimestamp || null,
          configDir: String(configDir),
          sourceSlug: String(sourceSlug),
        };
      }
      return null;
    }

    function slugToken(value) {
      const token = String(value || "")
        .trim()
        .replace(/[^a-zA-Z0-9._-]+/g, "_")
        .replace(/^[._-]+|[._-]+$/g, "");
      return token || "unknown";
    }

    function metric(value) {
      const parsed = Number(value);
      return Number.isFinite(parsed) ? parsed : 0;
    }

    function aggregateConfigKey(record, configDir) {
      const hash = String(record.run_config_hash || "").trim().toLowerCase();
      if (hash) return "hash:" + hash;
      return "name:" + String(configDir || "");
    }

    function bestRecord(recordsForGroup) {
      if (!recordsForGroup.length) return null;
      let best = recordsForGroup[0];
      recordsForGroup.slice(1).forEach(next => {
        const bestKey = [
          metric(best.macro_f1_excluding_other),
          metric(best.strict_accuracy),
          metric(best.f1),
          metric(best.practical_f1),
        ];
        const nextKey = [
          metric(next.macro_f1_excluding_other),
          metric(next.strict_accuracy),
          metric(next.f1),
          metric(next.practical_f1),
        ];
        for (let i = 0; i < bestKey.length; i++) {
          if (nextKey[i] > bestKey[i]) { best = next; return; }
          if (nextKey[i] < bestKey[i]) return;
        }
      });
      return best;
    }

    function mostCommonValue(counts) {
      let best = null;
      let bestCount = -1;
      Object.keys(counts).forEach(key => {
        const count = counts[key] || 0;
        if (count > bestCount) {
          best = key;
          bestCount = count;
        }
      });
      return best;
    }

    function summarizeAllMethodSource(counts) {
      const labels = Object.keys(counts);
      if (!labels.length) return "all-method benchmark run";
      labels.sort((a, b) => {
        const countA = counts[a] || 0;
        const countB = counts[b] || 0;
        if (countB !== countA) return countB - countA;
        return String(a).localeCompare(String(b));
      });
      if (labels.length === 1) {
        return "all-method: " + labels[0];
      }
      return "all-method: " + labels[0] + " + " + (labels.length - 1) + " more";
    }

    const singleRows = [];
    const allMethodRuns = Object.create(null);

    records.forEach(r => {
      const info = allMethodRunInfo(r);
      if (!info) {
        singleRows.push({ type: "single", record: r });
        return;
      }
      let run = allMethodRuns[info.runKey];
      if (!run) {
        run = {
          runKey: info.runKey,
          runDirTimestamp: info.runDirTimestamp,
          groups: Object.create(null),
        };
        allMethodRuns[info.runKey] = run;
      }
      if (!run.runDirTimestamp && info.runDirTimestamp) {
        run.runDirTimestamp = info.runDirTimestamp;
      }
      let group = run.groups[info.groupKey];
      if (!group) {
        group = { groupKey: info.groupKey, records: [] };
        run.groups[info.groupKey] = group;
      }
      group.records.push({ record: r, configDir: info.configDir });
    });

    function summarizeAllMethodRun(run) {
      const groups = Object.keys(run.groups).map(k => run.groups[k]);
      if (!groups.length) return null;

      const state = Object.create(null);
      const winsByConfig = Object.create(null);
      const sourceCounts = Object.create(null);
      const aiModelCounts = Object.create(null);
      const aiEffortCounts = Object.create(null);
      const aiProfileCounts = Object.create(null);

      groups.forEach(group => {
        const groupRecords = group.records.map(entry => entry.record);
        const winner = bestRecord(groupRecords);
        const winnerInfo = winner ? allMethodRunInfo(winner) : null;
        const winnerKey = (winner && winnerInfo)
          ? aggregateConfigKey(winner, winnerInfo.configDir)
          : null;
        if (winnerKey) {
          winsByConfig[winnerKey] = (winsByConfig[winnerKey] || 0) + 1;
        }

        group.records.forEach(entry => {
          const r = entry.record;
          const configDir = entry.configDir;
          const configKey = aggregateConfigKey(r, configDir);
          let agg = state[configKey];
          if (!agg) {
            agg = {
              configKey,
              configName: configDir,
              groupKeys: new Set(),
              importerCounts: Object.create(null),
              strictAccuracyValues: [],
              macroF1Values: [],
              goldTotalSum: 0,
              goldTotalN: 0,
                goldMatchedSum: 0,
                goldMatchedN: 0,
                recipesSum: 0,
                recipesN: 0,
                tokensInputSum: 0,
                tokensInputN: 0,
                tokensCachedInputSum: 0,
                tokensCachedInputN: 0,
                tokensOutputSum: 0,
                tokensOutputN: 0,
                tokensTotalSum: 0,
                tokensTotalN: 0,
                wins: 0,
              };
              state[configKey] = agg;
            }

          agg.groupKeys.add(group.groupKey);
          const importer = importerLabelForRecord(r);
          agg.importerCounts[importer] = (agg.importerCounts[importer] || 0) + 1;
          const sourceLabel = sourceLabelForRecord(r);
          if (sourceLabel && sourceLabel !== "-") {
            sourceCounts[sourceLabel] = (sourceCounts[sourceLabel] || 0) + 1;
          }
          const aiModel = aiModelLabelForRecord(r);
          if (aiModel && aiModel !== "-") {
            aiModelCounts[aiModel] = (aiModelCounts[aiModel] || 0) + 1;
          }
          const aiEffort = aiEffortLabelForRecord(r);
          if (aiEffort && aiEffort !== "-") {
            aiEffortCounts[aiEffort] = (aiEffortCounts[aiEffort] || 0) + 1;
          }
          const aiProfile = aiAssistanceProfileLabelForRecord(r);
          if (aiProfile && aiProfile !== "-") {
            aiProfileCounts[aiProfile] = (aiProfileCounts[aiProfile] || 0) + 1;
          }
          if (r.strict_accuracy != null) agg.strictAccuracyValues.push(Number(r.strict_accuracy));
          if (r.macro_f1_excluding_other != null) agg.macroF1Values.push(Number(r.macro_f1_excluding_other));
          if (r.gold_total != null) { agg.goldTotalSum += Number(r.gold_total); agg.goldTotalN += 1; }
          if (r.gold_matched != null) { agg.goldMatchedSum += Number(r.gold_matched); agg.goldMatchedN += 1; }
          if (r.recipes != null) { agg.recipesSum += Number(r.recipes); agg.recipesN += 1; }
          if (r.tokens_input != null) { agg.tokensInputSum += Number(r.tokens_input); agg.tokensInputN += 1; }
          if (r.tokens_cached_input != null) { agg.tokensCachedInputSum += Number(r.tokens_cached_input); agg.tokensCachedInputN += 1; }
          if (r.tokens_output != null) { agg.tokensOutputSum += Number(r.tokens_output); agg.tokensOutputN += 1; }
          if (r.tokens_total != null) { agg.tokensTotalSum += Number(r.tokens_total); agg.tokensTotalN += 1; }
        });
      });

      Object.keys(winsByConfig).forEach(key => {
        if (state[key]) state[key].wins = winsByConfig[key];
      });

      const aggregates = Object.keys(state).map(key => {
        const agg = state[key];
        const importer = mostCommonValue(agg.importerCounts) || "-";
        return {
          configKey: agg.configKey,
          configName: agg.configName,
          books: agg.groupKeys.size,
          wins: agg.wins || 0,
          strict_accuracy_mean: mean(agg.strictAccuracyValues),
          macro_f1_excluding_other_mean: mean(agg.macroF1Values),
          gold_total: agg.goldTotalN ? agg.goldTotalSum : null,
          gold_matched: agg.goldMatchedN ? agg.goldMatchedSum : null,
          recipes: agg.recipesN ? agg.recipesSum : null,
          tokens_input: agg.tokensInputN ? agg.tokensInputSum : null,
          tokens_cached_input: agg.tokensCachedInputN ? agg.tokensCachedInputSum : null,
          tokens_output: agg.tokensOutputN ? agg.tokensOutputSum : null,
          tokens_total: agg.tokensTotalN ? agg.tokensTotalSum : null,
          importer_name: importer,
        };
      });

      aggregates.sort((a, b) => {
        const aKey = [
          a.books,
          metric(a.macro_f1_excluding_other_mean),
          metric(a.strict_accuracy_mean),
          a.wins,
        ];
        const bKey = [
          b.books,
          metric(b.macro_f1_excluding_other_mean),
          metric(b.strict_accuracy_mean),
          b.wins,
        ];
        for (let i = 0; i < aKey.length; i++) {
          if (bKey[i] !== aKey[i]) return bKey[i] - aKey[i];
        }
        return String(a.configName || "").localeCompare(String(b.configName || ""));
      });

      const best = aggregates.length ? aggregates[0] : null;
      const ts = run.runDirTimestamp || "";
      const fileName = "all-method-benchmark-run__" + slugToken(ts) + ".html";
      const href = "all-method-benchmark/" + fileName;
      const sourceSummary = summarizeAllMethodSource(sourceCounts);
      const aiModel = mostCommonValue(aiModelCounts) || "-";
      const aiEffort = mostCommonValue(aiEffortCounts) || "-";
      const aiAssistanceProfile = mostCommonValue(aiProfileCounts) || "-";

      return {
        type: "all_method",
        run_timestamp: ts,
        href,
        strict_accuracy: best ? best.strict_accuracy_mean : null,
        macro_f1_excluding_other: best ? best.macro_f1_excluding_other_mean : null,
        gold_total: best ? best.gold_total : null,
        gold_matched: best ? best.gold_matched : null,
        recipes: best ? best.recipes : null,
        tokens_input: best ? best.tokens_input : null,
        tokens_cached_input: best ? best.tokens_cached_input : null,
        tokens_output: best ? best.tokens_output : null,
        tokens_total: best ? best.tokens_total : null,
        source: sourceSummary,
        importer_name: best ? best.importer_name : "-",
        ai_model: aiModel,
        ai_effort: aiEffort,
        ai_assistance_profile: aiAssistanceProfile,
      };
    }

    const bundledRows = Object.keys(allMethodRuns)
      .map(key => summarizeAllMethodRun(allMethodRuns[key]))
      .filter(Boolean);
    const rows = bundledRows.concat(singleRows.map(item => ({
      type: "single",
      run_timestamp: item.record.run_timestamp || "",
      href: item.record.artifact_dir || "",
      record: item.record,
    })));

    rows.sort((a, b) => comparePreviousRunsRows(a, b));
    tbody.innerHTML = "";
    rows.forEach(row => {
      const tr = document.createElement("tr");
      visibleColumns.forEach(fieldName => {
        tr.appendChild(renderPreviousRunsCell(row, fieldName));
      });
      tbody.appendChild(tr);
    });
    persistDashboardUiState();
  }

  // ---- Per-label section ----
  function aggregatePerLabelRows(records) {
    const byLabel = Object.create(null);
    (records || []).forEach(record => {
      const labels = Array.isArray(record && record.per_label) ? record.per_label : [];
      labels.forEach(lbl => {
        const label = String(lbl.label || "").trim();
        if (!label) return;
        if (!byLabel[label]) {
          byLabel[label] = {
            label,
            gold_total: 0,
            pred_total: 0,
            tp_from_recall: 0,
            tp_from_precision: 0,
            has_gold: false,
            has_pred: false,
          };
        }
        const agg = byLabel[label];
        const goldTotal = lbl.gold_total != null ? Number(lbl.gold_total) : null;
        const predTotal = lbl.pred_total != null ? Number(lbl.pred_total) : null;
        const recall = lbl.recall != null ? Number(lbl.recall) : null;
        const precision = lbl.precision != null ? Number(lbl.precision) : null;

        if (goldTotal != null && Number.isFinite(goldTotal)) {
          agg.gold_total += goldTotal;
          agg.has_gold = true;
          if (recall != null && Number.isFinite(recall)) {
            agg.tp_from_recall += recall * goldTotal;
          }
        }
        if (predTotal != null && Number.isFinite(predTotal)) {
          agg.pred_total += predTotal;
          agg.has_pred = true;
          if (precision != null && Number.isFinite(precision)) {
            agg.tp_from_precision += precision * predTotal;
          }
        }
      });
    });

    return Object.values(byLabel)
      .map(agg => {
        const goldTotal = agg.has_gold ? agg.gold_total : null;
        const predTotal = agg.has_pred ? agg.pred_total : null;
        let tp = null;
        if (agg.has_gold && agg.has_pred) {
          tp = (agg.tp_from_recall + agg.tp_from_precision) / 2;
        } else if (agg.has_gold) {
          tp = agg.tp_from_recall;
        } else if (agg.has_pred) {
          tp = agg.tp_from_precision;
        }
        let precision = null;
        if (predTotal != null) {
          precision = predTotal > 0 && tp != null ? (tp / predTotal) : 0;
        }
        let recall = null;
        if (goldTotal != null) {
          recall = goldTotal > 0 && tp != null ? (tp / goldTotal) : 0;
        }
        return {
          label: agg.label,
          precision,
          recall,
          gold_total: goldTotal,
          pred_total: predTotal,
        };
      })
      .sort((a, b) => String(a.label).localeCompare(String(b.label)));
  }

  function perLabelRowsByLabel(rows) {
    const mapping = Object.create(null);
    (rows || []).forEach(row => {
      const label = String((row && row.label) || "").trim();
      if (!label) return;
      mapping[label] = row;
    });
    return mapping;
  }

  function perLabelComparisonModeLabel(mode) {
    return mode === "point_value" ? "Point Value" : "Delta";
  }

  function perLabelComparisonHeaderTitle(mode, scope, metric, variant) {
    const metricLabel = metric === "recall" ? "recall" : "precision";
    const variantLabel = variant === "vanilla" ? "vanilla" : "codexfarm";
    if (mode === "point_value") {
      if (scope === "run") {
        return "Latest-run " + variantLabel + " " + metricLabel + " for this label.";
      }
      return "Rolling " + variantLabel + " " + metricLabel + " over N runs for this label.";
    }
    if (scope === "run") {
      return "Latest-run codexfarm " + metricLabel + " minus latest-run " + variantLabel + " " + metricLabel + " for this label.";
    }
    return "Latest-run codexfarm " + metricLabel + " minus rolling " + variantLabel + " " + metricLabel + " over N runs for this label.";
  }

  function perLabelComparisonCell(value, baseline) {
    const normalizeComparisonNumber = function(candidate) {
      if (candidate == null) return null;
      if (typeof candidate === "string" && candidate.trim() === "") return null;
      return maybeNumber(candidate);
    };
    const valueNum = normalizeComparisonNumber(value);
    const baselineNum = normalizeComparisonNumber(baseline);
    if (valueNum == null || baselineNum == null) {
      return '<td class="num" style="text-align:left">-</td>';
    }
    const rawDelta = baselineNum - valueNum;
    const delta = Math.abs(rawDelta) <= 1e-12 ? 0 : rawDelta;
    let cellClass = "num";
    if (delta > 0) {
      cellClass += " delta-better";
    } else if (delta < 0) {
      cellClass += " delta-worse";
    }
    if (normalizePerLabelComparisonMode(perLabelComparisonMode) === "point_value") {
      return '<td class="' + cellClass + '" style="text-align:left">' + fmt4(valueNum) + "</td>";
    }
    const absText = Math.abs(delta).toFixed(4);
    let signedText = "";
    if (delta < 0) {
      signedText = "-" + absText;
    } else if (delta > 0) {
      signedText = "+" + absText;
    } else {
      // Reserve sign width for 0.0000 without showing a plus symbol.
      signedText = "&nbsp;" + absText;
    }
    return '<td class="' + cellClass + '" style="text-align:left">' + signedText + "</td>";
  }

  function syncPerLabelRollingWindowUi() {
    const value = normalizePerLabelRollingWindowSize(perLabelRollingWindowSize);
    perLabelRollingWindowSize = value;
    const input = document.getElementById("per-label-rolling-window-size");
    if (input) {
      input.value = String(value);
    }
    document.querySelectorAll(".per-label-rolling-window-value").forEach(node => {
      node.textContent = String(value);
    });
  }

  function syncPerLabelComparisonModeUi() {
    const mode = normalizePerLabelComparisonMode(perLabelComparisonMode);
    perLabelComparisonMode = mode;
    const checkbox = document.getElementById("per-label-comparison-point-value");
    if (checkbox) {
      checkbox.checked = mode === "point_value";
    }
    const modeLabel = perLabelComparisonModeLabel(mode);
    document.querySelectorAll(".per-label-comparison-mode-value").forEach(node => {
      node.textContent = modeLabel;
    });
    document.querySelectorAll(".per-label-comparison-header").forEach(node => {
      const scope = String(node.getAttribute("data-per-label-comparison-scope") || "").trim().toLowerCase();
      const metric = String(node.getAttribute("data-per-label-comparison-metric") || "").trim().toLowerCase();
      const variant = String(node.getAttribute("data-per-label-comparison-variant") || "").trim().toLowerCase();
      if (!scope || !metric || !variant) return;
      node.title = perLabelComparisonHeaderTitle(mode, scope, metric, variant);
    });
  }

  function perLabelRunGroups(records) {
    const groupsByKey = Object.create(null);
    (records || []).forEach(record => {
      if (!record || !Array.isArray(record.per_label) || !record.per_label.length) return;
      const info = benchmarkRunGroupInfo(record);
      const runGroupKey = String((info && info.runGroupKey) || "").trim();
      if (!runGroupKey) return;
      let group = groupsByKey[runGroupKey];
      if (!group) {
        group = {
          runGroupKey,
          runGroupLabel: String((info && info.runGroupLabel) || record.run_timestamp || "-").trim() || "-",
          runGroupTimestampText: String((info && info.runGroupTimestampText) || record.run_timestamp || "").trim(),
          records: [],
        };
        groupsByKey[runGroupKey] = group;
      }
      group.records.push(record);
      const candidateTimestampText = String(
        (info && info.runGroupTimestampText) || record.run_timestamp || ""
      ).trim();
      if (
        candidateTimestampText &&
        (
          !group.runGroupTimestampText ||
          compareRunTimestampDesc(candidateTimestampText, group.runGroupTimestampText) < 0
        )
      ) {
        group.runGroupTimestampText = candidateTimestampText;
      }
    });
    return Object.keys(groupsByKey)
      .map(key => groupsByKey[key])
      .sort((left, right) => {
        const leftTimestamp = String(left.runGroupTimestampText || "").trim();
        const rightTimestamp = String(right.runGroupTimestampText || "").trim();
        const timestampCompare = compareRunTimestampDesc(leftTimestamp, rightTimestamp);
        if (timestampCompare !== 0) return timestampCompare;
        const labelCompare = String(left.runGroupLabel || "").localeCompare(String(right.runGroupLabel || ""));
        if (labelCompare !== 0) return labelCompare;
        return String(left.runGroupKey || "").localeCompare(String(right.runGroupKey || ""));
      });
  }

  function syncPerLabelRunGroupUi(runGroups) {
    const select = document.getElementById("per-label-run-group-select");
    if (!select) return;
    const groups = Array.isArray(runGroups) ? runGroups : [];
    const normalizedSelected = normalizePerLabelRunGroupKey(perLabelRunGroupKey);
    const availableKeys = new Set(
      groups.map(group => String((group && group.runGroupKey) || "").trim()).filter(Boolean)
    );
    let persistedSelectedKey = normalizedSelected;
    if (
      groups.length > 0 &&
      persistedSelectedKey !== PER_LABEL_RUN_GROUP_DEFAULT_KEY &&
      !availableKeys.has(persistedSelectedKey)
    ) {
      persistedSelectedKey = PER_LABEL_RUN_GROUP_DEFAULT_KEY;
    }
    perLabelRunGroupKey = persistedSelectedKey;
    const selectedKey = groups.length > 0 ? persistedSelectedKey : PER_LABEL_RUN_GROUP_DEFAULT_KEY;

    select.innerHTML = "";
    const defaultOption = document.createElement("option");
    defaultOption.value = PER_LABEL_RUN_GROUP_DEFAULT_KEY;
    defaultOption.textContent = "Default - most recent";
    select.appendChild(defaultOption);
    groups.forEach(group => {
      const key = String((group && group.runGroupKey) || "").trim();
      const label = String((group && group.runGroupLabel) || "").trim();
      if (!key || !label) return;
      const option = document.createElement("option");
      option.value = key;
      option.textContent = label;
      select.appendChild(option);
    });
    select.value = selectedKey;
    select.disabled = groups.length === 0;
  }

  function setupPerLabelControls() {
    syncPerLabelRunGroupUi([]);
    syncPerLabelRollingWindowUi();
    syncPerLabelComparisonModeUi();
    const runGroupSelect = document.getElementById("per-label-run-group-select");
    if (runGroupSelect && runGroupSelect.dataset.bound !== "1") {
      runGroupSelect.addEventListener("change", () => {
        const nextKey = normalizePerLabelRunGroupKey(runGroupSelect.value);
        if (nextKey === perLabelRunGroupKey) {
          return;
        }
        perLabelRunGroupKey = nextKey;
        persistDashboardUiState();
        renderPerLabel();
      });
      runGroupSelect.dataset.bound = "1";
    }
    const input = document.getElementById("per-label-rolling-window-size");
    if (input && input.dataset.bound !== "1") {
      input.addEventListener("change", () => {
        const nextValue = normalizePerLabelRollingWindowSize(input.value);
        if (nextValue === perLabelRollingWindowSize) {
          syncPerLabelRollingWindowUi();
          return;
        }
        perLabelRollingWindowSize = nextValue;
        syncPerLabelRollingWindowUi();
        persistDashboardUiState();
        renderPerLabel();
      });
      input.dataset.bound = "1";
    }
    const checkbox = document.getElementById("per-label-comparison-point-value");
    if (checkbox && checkbox.dataset.bound !== "1") {
      checkbox.addEventListener("change", () => {
        const nextMode = checkbox.checked ? "point_value" : "delta";
        if (nextMode === perLabelComparisonMode) {
          syncPerLabelComparisonModeUi();
          return;
        }
        perLabelComparisonMode = nextMode;
        syncPerLabelComparisonModeUi();
        persistDashboardUiState();
        renderPerLabel();
      });
      checkbox.dataset.bound = "1";
    }
  }

  function mapBenchmarkVariantForPerLabel(record, fallbackFullStackAsCodexfarm) {
    const variant = benchmarkVariantForRecord(record);
    if (!fallbackFullStackAsCodexfarm) return variant;
    return variant === "full_stack" ? "codexfarm" : variant;
  }

  function rollingPerLabelByVariant(records, variant, windowSize, perLabelVariantMapper) {
    const byRunTimestamp = Object.create(null);
    const normalizeVariant = typeof perLabelVariantMapper === "function"
      ? perLabelVariantMapper
      : function(item) {
          return benchmarkVariantForRecord(item);
        };
    (records || []).forEach(record => {
      if (!record) return;
      if (normalizeVariant(record) !== variant) return;
      const ts = String(record.run_timestamp || "").trim();
      if (!ts) return;
      if (!Array.isArray(record.per_label) || !record.per_label.length) return;
      if (!byRunTimestamp[ts]) byRunTimestamp[ts] = [];
      byRunTimestamp[ts].push(record);
    });

    const recentRunTimestamps = Object.keys(byRunTimestamp)
      .sort(compareRunTimestampDesc)
      .slice(0, windowSize);
    const valuesByLabel = Object.create(null);
    recentRunTimestamps.forEach(ts => {
      const runRows = aggregatePerLabelRows(byRunTimestamp[ts]);
      runRows.forEach(row => {
        const label = row.label;
        if (!valuesByLabel[label]) {
          valuesByLabel[label] = {
            precision_values: [],
            recall_values: [],
          };
        }
        if (row.precision != null && Number.isFinite(row.precision)) {
          valuesByLabel[label].precision_values.push(Number(row.precision));
        }
        if (row.recall != null && Number.isFinite(row.recall)) {
          valuesByLabel[label].recall_values.push(Number(row.recall));
        }
      });
    });

    const out = Object.create(null);
    Object.keys(valuesByLabel).forEach(label => {
      const entry = valuesByLabel[label];
      out[label] = {
        precision: entry.precision_values.length ? mean(entry.precision_values) : null,
        recall: entry.recall_values.length ? mean(entry.recall_values) : null,
      };
    });
    return out;
  }

  function latestRunGroupRecords(records, hasData) {
    const latestRecord = (records || []).find(record => record && hasData(record));
    if (!latestRecord) {
      return {
        runGroupLabel: "",
        records: [],
      };
    }
    const latestRunGroup = benchmarkRunGroupInfo(latestRecord);
    const latestRunGroupKey = String((latestRunGroup && latestRunGroup.runGroupKey) || "").trim();
    const latestRunGroupLabel = String(
      (latestRunGroup && latestRunGroup.runGroupLabel) || latestRecord.run_timestamp || ""
    ).trim();
    const latestRunRecords = (records || []).filter(record => {
      if (!record || !hasData(record)) return false;
      const recordRunGroup = benchmarkRunGroupInfo(record);
      return String((recordRunGroup && recordRunGroup.runGroupKey) || "").trim() === latestRunGroupKey;
    });
    return {
      runGroupLabel: latestRunGroupLabel,
      records: latestRunRecords,
    };
  }

  function renderPerLabel() {
    const records = filteredBenchmarks();
    const section = document.getElementById("per-label-section");
    if (!section) return;
    const title = section.querySelector("h2");
    const tbody = document.querySelector("#per-label-table tbody");
    if (!tbody) return;
    syncPerLabelRollingWindowUi();
    syncPerLabelComparisonModeUi();
    if (records.length === 0) {
      syncPerLabelRunGroupUi([]);
      if (title) title.textContent = "Per-Label Breakdown";
      tbody.innerHTML = '<tr><td class="empty-note-cell" colspan="11">No benchmark records with per-label data.</td></tr>';
      return;
    }
    const sorted = [...records].sort((a, b) => compareRunTimestampDesc(a.run_timestamp, b.run_timestamp));
    const nonSpeed = sorted.filter(r =>
      !isSpeedBenchmarkRecord(r)
    );
    const preferredRecords = nonSpeed.length > 0 ? nonSpeed : sorted;
    const latestAllMethodRecords = preferredRecords.filter(r =>
      isAllMethodBenchmarkRecord(r) &&
      r.per_label &&
      r.per_label.length > 0
    );
    const candidateRecords = latestAllMethodRecords.length > 0
      ? latestAllMethodRecords
      : preferredRecords.filter(r => r.per_label && r.per_label.length > 0);
    const runGroups = perLabelRunGroups(candidateRecords);
    const latestRunGroup = latestRunGroupRecords(
      candidateRecords,
      record => Array.isArray(record.per_label) && record.per_label.length > 0,
    );
    let didResetRunGroupSelection = false;
    const selectedRunGroupKey = normalizePerLabelRunGroupKey(perLabelRunGroupKey);
    let selectedRunGroup = null;
    if (selectedRunGroupKey !== PER_LABEL_RUN_GROUP_DEFAULT_KEY) {
      selectedRunGroup = runGroups.find(group =>
        String((group && group.runGroupKey) || "").trim() === selectedRunGroupKey
      ) || null;
      if (!selectedRunGroup && runGroups.length > 0) {
        perLabelRunGroupKey = PER_LABEL_RUN_GROUP_DEFAULT_KEY;
        didResetRunGroupSelection = true;
      }
    }
    const activeRunGroup = selectedRunGroup || latestRunGroup;
    syncPerLabelRunGroupUi(runGroups);
    const latestRunRecords = activeRunGroup.records;
    const latestRunLabel = activeRunGroup.runGroupLabel;
    if (!latestRunRecords.length) {
      if (title) title.textContent = "Per-Label Breakdown";
      tbody.innerHTML = '<tr><td class="empty-note-cell" colspan="9">No per-label metrics available in benchmark records.</td></tr>';
      return;
    }
    if (didResetRunGroupSelection) {
      persistDashboardUiState();
    }
    if (title) {
      title.textContent =
        "Per-Label Breakdown (" + (latestRunLabel || "latest") + ", " + latestRunRecords.length + " evals)";
    }
    tbody.innerHTML = "";
    const rollingWindowSize = normalizePerLabelRollingWindowSize(perLabelRollingWindowSize);
    const hasOfficialVariants = latestRunRecords.some(record => {
      const variant = benchmarkVariantForRecord(record);
      return variant === "codexfarm" || variant === "vanilla";
    });
    const mapVariant = record => mapBenchmarkVariantForPerLabel(
      record,
      !hasOfficialVariants
    );
    const runCodexFarmRows = aggregatePerLabelRows(
      latestRunRecords.filter(record => mapVariant(record) === "codexfarm")
    );
    const runVanillaRows = aggregatePerLabelRows(
      latestRunRecords.filter(record => benchmarkVariantForRecord(record) === "vanilla")
    );
    const latestRows = aggregatePerLabelRows(latestRunRecords);
    const runCodexFarmByLabel = perLabelRowsByLabel(runCodexFarmRows);
    const runVanillaByLabel = perLabelRowsByLabel(runVanillaRows);
    const rollingCodexFarmByLabel = rollingPerLabelByVariant(
      candidateRecords,
      "codexfarm",
      rollingWindowSize,
      mapVariant,
    );

    latestRows.forEach(lbl => {
      const runCodexFarm = runCodexFarmByLabel[lbl.label] || {};
      const runVanilla = runVanillaByLabel[lbl.label] || {};
      const rollingCodexFarm = rollingCodexFarmByLabel[lbl.label] || {};
      const baselinePrecision = runCodexFarm.precision;
      const baselineRecall = runCodexFarm.recall;
      const tr = document.createElement("tr");
      tr.innerHTML =
        '<td>' + esc(lbl.label) + '</td>' +
        '<td class="num" style="text-align:left">' + (lbl.gold_total != null ? Math.round(lbl.gold_total) : "-") + '</td>' +
        '<td class="num" style="text-align:left">' + (lbl.pred_total != null ? Math.round(lbl.pred_total) : "-") + '</td>' +
        '<td class="num" style="text-align:left">' + fmt4(runCodexFarm.precision) + '</td>' +
        '<td class="num" style="text-align:left">' + fmt4(runCodexFarm.recall) + '</td>' +
        perLabelComparisonCell(runVanilla.precision, baselinePrecision) +
        perLabelComparisonCell(runVanilla.recall, baselineRecall) +
        perLabelComparisonCell(rollingCodexFarm.precision, baselinePrecision) +
        perLabelComparisonCell(rollingCodexFarm.recall, baselineRecall);
      tbody.appendChild(tr);
    });
  }

  // ---- Boundary section ----
  function renderBoundary() {
    const records = filteredBenchmarks();
    const section = document.getElementById("boundary-section");
    if (!section) return;
    if (records.length === 0) {
      section.innerHTML = '<h2>Boundary Classification</h2><p class="empty-note">No benchmark records.</p>';
      return;
    }
    const sorted = [...records].sort((a, b) => compareRunTimestampDesc(a.run_timestamp, b.run_timestamp));
    const nonSpeed = sorted.filter(r =>
      !isSpeedBenchmarkRecord(r)
    );
    const preferredRecords = nonSpeed.length > 0 ? nonSpeed : sorted;
    const hasBoundaryMetrics = function(record) {
      return (
        record.boundary_correct != null ||
        record.boundary_over != null ||
        record.boundary_under != null ||
        record.boundary_partial != null
      );
    };
    const latestAllMethodRecords = preferredRecords.filter(r =>
      isAllMethodBenchmarkRecord(r) &&
      hasBoundaryMetrics(r)
    );
    const candidateRecords = latestAllMethodRecords.length > 0
      ? latestAllMethodRecords
      : preferredRecords.filter(hasBoundaryMetrics);
    const latestRunGroup = latestRunGroupRecords(candidateRecords, hasBoundaryMetrics);
    const latestRunRecords = latestRunGroup.records;
    const latestRunLabel = latestRunGroup.runGroupLabel;
    if (!latestRunRecords.length) {
      section.innerHTML = '<h2>Boundary Classification</h2><p class="empty-note">No boundary data available in benchmark records.</p>';
      return;
    }
    section.querySelector("h2").textContent =
      "Boundary Classification (" + esc(latestRunLabel || "latest") + ", " + latestRunRecords.length + " evals)";
    const div = document.getElementById("boundary-summary");
    const boundary = {
      correct: 0,
      over: 0,
      under: 0,
      partial: 0,
      has_correct: false,
      has_over: false,
      has_under: false,
      has_partial: false,
    };
    const coverage = {
      gold_total: 0,
      gold_matched: 0,
      pred_total: 0,
      has_gold_total: false,
      has_gold_matched: false,
      has_pred_total: false,
    };
    latestRunRecords.forEach(record => {
      const correct = maybeNumber(record.boundary_correct);
      const over = maybeNumber(record.boundary_over);
      const under = maybeNumber(record.boundary_under);
      const partial = maybeNumber(record.boundary_partial);
      const goldTotal = maybeNumber(record.gold_total);
      const goldMatched = maybeNumber(record.gold_matched);
      const predTotal = maybeNumber(record.pred_total);

      if (correct != null) {
        boundary.correct += correct;
        boundary.has_correct = true;
      }
      if (over != null) {
        boundary.over += over;
        boundary.has_over = true;
      }
      if (under != null) {
        boundary.under += under;
        boundary.has_under = true;
      }
      if (partial != null) {
        boundary.partial += partial;
        boundary.has_partial = true;
      }
      if (goldTotal != null) {
        coverage.gold_total += goldTotal;
        coverage.has_gold_total = true;
      }
      if (goldMatched != null) {
        coverage.gold_matched += goldMatched;
        coverage.has_gold_matched = true;
      }
      if (predTotal != null) {
        coverage.pred_total += predTotal;
        coverage.has_pred_total = true;
      }
    });

    const valueOrNull = function(value, hasValue) {
      return hasValue ? Math.round(value) : null;
    };
    const boundaryCorrect = valueOrNull(boundary.correct, boundary.has_correct);
    const boundaryOver = valueOrNull(boundary.over, boundary.has_over);
    const boundaryUnder = valueOrNull(boundary.under, boundary.has_under);
    const boundaryPartial = valueOrNull(boundary.partial, boundary.has_partial);
    const classifiedMatchedTotal = (boundaryCorrect || 0) + (boundaryOver || 0) + (boundaryUnder || 0) + (boundaryPartial || 0);
    const goldTotal = coverage.has_gold_total ? Math.max(0, Math.round(coverage.gold_total)) : null;
    const matchedGold = coverage.has_gold_matched ? Math.max(0, Math.round(coverage.gold_matched)) : null;
    const matchedButUnclassified = (
      matchedGold != null
        ? Math.max(0, matchedGold - classifiedMatchedTotal)
        : null
    );
    const unmatchedGold = (
      goldTotal != null
        ? Math.max(
          0,
          goldTotal - (matchedGold != null ? matchedGold : classifiedMatchedTotal)
        )
        : null
    );
    const pctGold = function(v) {
      return goldTotal != null && goldTotal > 0 ? ((v || 0) / goldTotal * 100).toFixed(1) + "%" : "-";
    };

    const contextParts = [];
    if (coverage.has_gold_total && coverage.has_gold_matched && coverage.gold_total > 0) {
      const recallPct = (coverage.gold_matched / coverage.gold_total * 100).toFixed(1);
      contextParts.push(
        "Coverage: " + Math.round(coverage.gold_matched) + "/" + Math.round(coverage.gold_total) + " matched gold spans (" + recallPct + "%)."
      );
    }
    if (
      coverage.has_pred_total &&
      coverage.has_gold_matched &&
      coverage.pred_total > 0 &&
      Math.round(coverage.pred_total) !== Math.round(coverage.gold_total || -1)
    ) {
      const precisionPct = (coverage.gold_matched / coverage.pred_total * 100).toFixed(1);
      contextParts.push(
        "Matched predictions: " + Math.round(coverage.gold_matched) + "/" + Math.round(coverage.pred_total) + " (" + precisionPct + "%)."
      );
    }
    const contextHtml = contextParts.length
      ? '<p class="section-note">' + esc(contextParts.join(" ")) + '</p>'
      : "";

    div.innerHTML =
      contextHtml +
      '<table id="boundary-table"><thead><tr><th>Category</th><th>Count</th><th>% of gold</th></tr></thead><tbody>' +
      '<tr><td data-metric-tooltip-key="boundary_correct" title="Prediction span matches gold boundaries exactly.">Correct</td><td class="num">' + (boundaryCorrect != null ? boundaryCorrect : "-") + '</td><td class="num">' + pctGold(boundaryCorrect) + '</td></tr>' +
      '<tr><td data-metric-tooltip-key="boundary_over" title="Prediction fully contains the gold span (too wide).">Over-segmented</td><td class="num">' + (boundaryOver != null ? boundaryOver : "-") + '</td><td class="num">' + pctGold(boundaryOver) + '</td></tr>' +
      '<tr><td data-metric-tooltip-key="boundary_under" title="Prediction is fully inside the gold span (too narrow).">Under-segmented</td><td class="num">' + (boundaryUnder != null ? boundaryUnder : "-") + '</td><td class="num">' + pctGold(boundaryUnder) + '</td></tr>' +
      '<tr><td data-metric-tooltip-key="boundary_partial" title="Prediction overlaps but boundaries are misaligned.">Partial</td><td class="num">' + (boundaryPartial != null ? boundaryPartial : "-") + '</td><td class="num">' + pctGold(boundaryPartial) + '</td></tr>' +
      (
        matchedButUnclassified != null
          ? '<tr><td data-metric-tooltip-key="boundary_unclassified" title="Gold spans counted as matched overall but not assigned to a boundary bucket.">Matched (boundary unclassified)</td><td class="num">' + matchedButUnclassified + '</td><td class="num">' + pctGold(matchedButUnclassified) + '</td></tr>'
          : ""
      ) +
      '<tr><td data-metric-tooltip-key="gold_unmatched" title="Gold spans not matched by prediction.">Unmatched gold spans</td><td class="num">' + (unmatchedGold != null ? unmatchedGold : "-") + '</td><td class="num">' + pctGold(unmatchedGold) + '</td></tr>' +
      '</tbody></table>';
  }

  // ---- Runtime section ----
  function renderLatestRuntime() {
    const section = document.getElementById("runtime-section");
    if (!section) return;
    const summary = document.getElementById("runtime-summary");
    if (!summary) return;

    const records = filteredBenchmarks();
    if (records.length === 0) {
      section.querySelector("h2").textContent = "Benchmark Runtime";
      summary.innerHTML = '<p class="empty-note">No benchmark records.</p>';
      return;
    }

    const runtimeSummary = latestRuntimeSummaryForRecords(records);
    if (!runtimeSummary) {
      section.querySelector("h2").textContent = "Benchmark Runtime";
      summary.innerHTML = '<p class="empty-note">No benchmark runtime metadata available.</p>';
      return;
    }

    const pipelineMode = runtimeSummary.pipelineMode;
    const model = runtimeSummary.model;
    const effort = runtimeSummary.effort;
    const totalTokenUse = runtimeSummary.tokenUseDisplay;
    const pipelineOff = pipelineMode && String(pipelineMode).toLowerCase() === "off";
    const qualityMetricKey = String(runtimeSummary.qualityMetricKey || "").trim();
    const qualityPerMillionTokens = runtimeSummary.qualityPerMillionTokens;
    const qualityPerMillionTokensDisplay = fmt4(qualityPerMillionTokens);
    const qualityDeltaVsVanillaDisplay = formatSigned4(runtimeSummary.qualityDeltaVsVanilla);
    const qualityDeltaPerMillionExtraTokensVsVanillaDisplay = formatSigned4(
      runtimeSummary.qualityDeltaPerMillionExtraTokensVsVanilla,
    );
    const qualityPeerSummary = runtimeQualityPeerSummaryText(runtimeSummary.peerQualityStats);

    const sourceLabel = runtimeSummary.sourceLabel;
    const sourceTitle = runtimeSummary.sourceTitle;
    const runGroupLabel = runtimeSummary.runGroupLabel || "latest";
    const runGroupRecordCount = Math.max(0, Math.round(Number(runtimeSummary.runGroupRecordCount || 0)));

    section.querySelector("h2").textContent =
      "Benchmark Runtime (" + esc(runGroupLabel) + ", " + runGroupRecordCount + " evals)";
    summary.innerHTML =
      '<table id="runtime-table"><tbody>' +
      '<tr><td data-metric-tooltip-key="ai_model">Model</td><td>' + esc(model || (pipelineOff ? "off" : "-")) + '</td></tr>' +
      '<tr><td data-metric-tooltip-key="ai_effort">Thinking Effort</td><td>' + esc(effort || (pipelineOff ? "n/a (pipeline off)" : "-")) + '</td></tr>' +
      '<tr><td data-metric-tooltip-key="run_config.llm_recipe_pipeline">Pipeline</td><td>' + esc(pipelineMode || "-") + '</td></tr>' +
      '<tr><td data-metric-tooltip-key="all_token_use">Token use</td><td>' + esc(totalTokenUse) + '</td></tr>' +
      '<tr><td data-metric-tooltip-key="' + esc(qualityMetricKey || "strict_accuracy") + '">Quality metric</td><td>' + esc(qualityMetricKey || "-") + '</td></tr>' +
      '<tr><td data-metric-tooltip-key="quality_per_million_tokens">Quality / 1M tokens</td><td>' + esc(qualityPerMillionTokensDisplay) + '</td></tr>' +
      '<tr><td data-metric-tooltip-key="strict_accuracy">Delta quality vs vanilla</td><td>' + esc(qualityDeltaVsVanillaDisplay) + '</td></tr>' +
      '<tr><td data-metric-tooltip-key="quality_per_million_tokens">Delta quality / 1M extra tokens vs vanilla</td><td>' + esc(qualityDeltaPerMillionExtraTokensVsVanillaDisplay) + '</td></tr>' +
      '<tr><td data-metric-tooltip-key="quality_per_million_tokens">Quality/tokens vs peers</td><td>' + esc(qualityPeerSummary) + '</td></tr>' +
      '<tr><td data-metric-tooltip-key="source_label">Source</td><td title="' + esc(sourceTitle) + '">' + esc(sourceLabel || "-") + '</td></tr>' +
      '<tr><td data-metric-tooltip-key="importer_name">Importer</td><td>' + esc(runtimeSummary.importerLabel || "-") + '</td></tr>' +
      '</tbody></table>';
  }

  // ---- Utils ----
  function esc(s) {
    if (s == null) return "";
    return String(s).replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;").replace(/"/g,"&quot;");
  }
  function fmt4(v) { return v != null ? v.toFixed(4) : "-"; }
  function normalizePathParts(pathValue) {
    if (pathValue == null) return { prefix: "", parts: [] };
    const raw = String(pathValue).trim().replace(/\\/g, "/");
    if (!raw) return { prefix: "", parts: [] };
    const prefix = raw.startsWith("/") ? "/" : "";
    const parts = raw.split("/").filter(p => p && p !== ".");
    return { prefix, parts };
  }
  function isUsefulSourceToken(token) {
    const text = String(token || "").trim();
    if (!text) return false;
    const lower = text.toLowerCase();
    if (lower === "eval" || lower === "eval_output" || lower === "prediction-run") return false;
    if (lower.startsWith("config_") || lower.startsWith("repeat_")) return false;
    return true;
  }
  function sourceSlugFromArtifactPath(pathValue) {
    const info = normalizePathParts(pathValue);
    if (!info.parts.length) return null;
    const lower = info.parts.map(p => String(p).toLowerCase());

    const markerNext = ["all-method-benchmark", "single-profile-benchmark", "scenario_runs", "source_runs"];
    for (let i = 0; i < lower.length; i++) {
      if (!markerNext.includes(lower[i])) continue;
      const candidate = info.parts[i + 1];
      if (isUsefulSourceToken(candidate)) return String(candidate);
    }

    for (let i = 0; i < lower.length; i++) {
      if (!["candidate", "promoted", "challenger", "baseline", "control"].includes(lower[i])) {
        continue;
      }
      const candidate = info.parts[i + 1];
      if (isUsefulSourceToken(candidate)) return String(candidate);
    }

    for (let i = 0; i < lower.length; i++) {
      if (lower[i] !== "eval") continue;
      const candidate = info.parts[i + 1];
      if (isUsefulSourceToken(candidate)) return String(candidate);
    }
    return null;
  }
  function sourceTitleForRecord(record) {
    const sourceFile = String((record && record.source_file) || "").trim();
    if (sourceFile) return sourceFile;
    const artifactDir = String((record && record.artifact_dir) || "").trim();
    if (artifactDir) return artifactDir;
    const slug = sourceSlugFromArtifactPath(artifactDir);
    return slug || "";
  }
  function importerLabelForRecord(record) {
    const explicit = String((record && record.importer_name) || "").trim();
    if (explicit) return explicit;
    const source = String((record && record.source_file) || "");
    let suffix = "";
    if (source) {
      const name = basename(source).toLowerCase();
      const dot = name.lastIndexOf(".");
      if (dot > 0) suffix = name.slice(dot);
    }
    if (suffix === ".epub") return "epub";
    if (suffix === ".pdf") return "pdf";
    if (suffix === ".doc" || suffix === ".docx" || suffix === ".txt" || suffix === ".md" || suffix === ".rtf") return "text";
    if (suffix === ".html" || suffix === ".htm") return "web";
    const cfg = (record && record.run_config) || {};
    if (cfg.epub_extractor != null || cfg.epub_extractor_requested != null || cfg.epub_extractor_effective != null) {
      return "epub";
    }
    return "-";
  }
  function sourceLabelForRecord(record) {
    const sourceFileLabel = basename((record && record.source_file) || "");
    if (sourceFileLabel) return sourceFileLabel;
    const slug = sourceSlugFromArtifactPath(record ? record.artifact_dir : null);
    if (slug) return slug;
    const artifactTail = basename((record && record.artifact_dir) || "");
    return artifactTail || "-";
  }
  function cleanConfigValue(value) {
    if (value == null) return null;
    const text = String(value).trim();
    if (!text) return null;
    const lower = text.toLowerCase();
    if (
      lower === "none" ||
      lower === "null" ||
      lower === "n/a" ||
      lower === "<default>" ||
      lower === "default" ||
      lower === "(default)"
    ) {
      return null;
    }
    return text;
  }
  function runConfigSummaryMap(summary) {
    const mapping = Object.create(null);
    const text = String(summary || "").trim();
    if (!text) return mapping;
    text.split("|").forEach(chunk => {
      const part = String(chunk || "").trim();
      if (!part) return;
      const idx = part.indexOf("=");
      if (idx <= 0) return;
      const key = part.slice(0, idx).trim();
      const value = part.slice(idx + 1).trim();
      if (!key || !value) return;
      mapping[key] = value;
    });
    return mapping;
  }
  function runConfigValue(record, keys) {
    const cfg = (record && record.run_config) || {};
    for (let i = 0; i < keys.length; i++) {
      const key = String(keys[i] || "");
      if (!key) continue;
      if (!Object.prototype.hasOwnProperty.call(cfg, key)) continue;
      const direct = cleanConfigValue(cfg[key]);
      if (direct != null) return direct;
    }
    const summaryFields = runConfigSummaryMap(runConfigSummary(record));
    for (let i = 0; i < keys.length; i++) {
      const key = String(keys[i] || "");
      if (!key) continue;
      const fromSummary = cleanConfigValue(summaryFields[key]);
      if (fromSummary != null) return fromSummary;
    }
    return null;
  }
  function rawAiModelForRecord(record) {
    return runConfigValue(record, [
      "codex_farm_model",
      "codex_model",
      "provider_model",
      "model",
    ]);
  }
  function rawAiEffortForRecord(record) {
    return runConfigValue(record, [
      "codex_farm_reasoning_effort",
      "codex_farm_thinking_effort",
      "codex_reasoning_effort",
      "model_reasoning_effort",
      "thinking_effort",
      "reasoning_effort",
    ]);
  }
  function aiModelForRecord(record) {
    if (aiAssistanceProfileForRecord(record) === "deterministic") return null;
    return rawAiModelForRecord(record);
  }
  function codexRuntimeErrorForRecord(record) {
    if (aiAssistanceProfileForRecord(record) === "deterministic") return null;
    return runConfigValue(record, [
      "codex_farm_runtime_error",
      "codex_farm_fatal_error",
      "codex_farm_error",
      "fatal_error",
    ]);
  }
  function aiEffortForRecord(record) {
    if (aiAssistanceProfileForRecord(record) === "deterministic") return null;
    return rawAiEffortForRecord(record);
  }
  function aiModelEffortLabelForRecord(record) {
    const model = aiModelForRecord(record);
    const effort = aiEffortForRecord(record);
    if (model && effort) return model + " (" + effort + ")";
    if (model) return model;
    if (effort) return "effort=" + effort;
    const pipeline = runConfigValue(record, ["llm_recipe_pipeline", "llm_pipeline"]);
    if (pipeline) {
      const pipelineText = String(pipeline).toLowerCase();
      if (pipelineText === "off") return "off";
      return "-";
    }
    return "-";
  }
  function aiModelLabelForRecord(record) {
    const runtimeError = codexRuntimeErrorForRecord(record);
    if (runtimeError) return "System error";
    const model = aiModelForRecord(record);
    if (model) return model;
    if (aiAssistanceProfileForRecord(record) === "deterministic") return "off";
    return "-";
  }
  function aiEffortLabelForRecord(record) {
    const effort = aiEffortForRecord(record);
    if (effort) return effort;
    return aiAssistanceProfileLabelForRecord(record);
  }
  function basename(path) {
    if (!path) return "";
    const parts = path.replace(/\\/g, "/").split("/");
    return parts[parts.length - 1] || path;
  }
  function epubExtractorRequested(record) {
    if (record.epub_extractor_requested) return String(record.epub_extractor_requested);
    const importer = String(record.importer_name || "").toLowerCase();
    if (importer && importer !== "epub") return null;
    const cfg = record.run_config || {};
    return cfg.epub_extractor_requested || cfg.epub_extractor || null;
  }
  function epubExtractorEffective(record) {
    if (record.epub_extractor_effective) return String(record.epub_extractor_effective);
    const importer = String(record.importer_name || "").toLowerCase();
    if (importer && importer !== "epub") return null;
    const cfg = record.run_config || {};
    return cfg.epub_extractor_effective || cfg.epub_extractor || null;
  }
  function extractorCells(record) {
    return (
      '<td>' + esc(epubExtractorRequested(record) || "-") + '</td>' +
      '<td>' + esc(epubExtractorEffective(record) || "-") + '</td>'
    );
  }
  function runConfigSummary(record) {
    if (record.run_config_summary) {
      return record.run_config_summary;
    }
    const cfg = record.run_config || {};
    const parts = [];
    if (cfg.epub_extractor != null) parts.push("epub_extractor=" + cfg.epub_extractor);
    if (cfg.epub_extractor_requested != null) parts.push("epub_extractor_requested=" + cfg.epub_extractor_requested);
    if (cfg.epub_extractor_effective != null) parts.push("epub_extractor_effective=" + cfg.epub_extractor_effective);
    if (cfg.ocr_device != null) parts.push("ocr_device=" + cfg.ocr_device);
    if (cfg.ocr_batch_size != null) parts.push("ocr_batch_size=" + cfg.ocr_batch_size);
    if (cfg.effective_workers != null) parts.push("effective_workers=" + cfg.effective_workers);
    else if (cfg.workers != null) parts.push("workers=" + cfg.workers);
    if (cfg.llm_recipe_pipeline != null) parts.push("llm_recipe_pipeline=" + cfg.llm_recipe_pipeline);
    if (cfg.codex_farm_model != null) parts.push("codex_farm_model=" + cfg.codex_farm_model);
    if (cfg.codex_farm_reasoning_effort != null) parts.push("codex_farm_reasoning_effort=" + cfg.codex_farm_reasoning_effort);
    if (cfg.codex_model != null) parts.push("codex_model=" + cfg.codex_model);
    if (cfg.model_reasoning_effort != null) parts.push("model_reasoning_effort=" + cfg.model_reasoning_effort);
    return parts.join(" | ");
  }
  function runConfigCell(record) {
    const summary = runConfigSummary(record);
    const warning = record.run_config_warning || "";
    const hash = record.run_config_hash || "";
    let title = warning;
    if (record.run_config) {
      title = JSON.stringify(record.run_config);
    } else if (summary) {
      title = summary;
    }
    if (hash) {
      title = (title ? title + "\n" : "") + "hash=" + hash;
    }
    if (summary) {
      const shortHash = hash ? " [" + hash.slice(0, 10) + "]" : "";
      return '<td title="' + esc(title) + '">' + esc(summary + shortHash) + '</td>';
    }
    if (warning) {
      return '<td class="warn-note" title="' + esc(title) + '">' + esc("[warn] " + warning) + '</td>';
    }
    return '<td>-</td>';
  }
  function shortPath(p) {
    if (!p) return "";
    const parts = p.replace(/\\/g, "/").split("/");
    return parts.slice(-3).join("/");
  }
})();
