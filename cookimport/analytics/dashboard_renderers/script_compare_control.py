from __future__ import annotations

_JS_COMPARE_CONTROL = """\
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

    const codexRecords = latestRunRecords.filter(record => benchmarkVariantForRecord(record) === "codex-exec");
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
    if (path.includes("/codex-exec/") || path.endsWith("/codex-exec")) return "codex-exec";
    if (path.includes("/vanilla/") || path.endsWith("/vanilla")) return "vanilla";
    return null;
  }

  function aiAssistanceProfileForRecord(record) {
    const explicit = cleanConfigValue(record && record.ai_assistance_profile);
    if (explicit) {
      const explicitKey = String(explicit).toLowerCase().replace(/[-\\s]+/g, "_");
      if (["deterministic", "line_role_only", "recipe_only", "full_stack", "other"].includes(explicitKey)) {
        return explicitKey;
      }
    }
    const pipelineOrPathVariant = benchmarkVariantFromPathOrPipeline(record);
    const path = benchmarkArtifactPath(record);
    const isOfficialPairedBenchmark =
      path.includes("/benchmark-vs-golden/") &&
      (
        path.includes("/single-book-benchmark/") ||
        path.includes("/single-profile-benchmark/")
      );
    const recipePipeline = runConfigValue(record, ["llm_recipe_pipeline", "llm_pipeline"]);
    const lineRolePipeline = runConfigValue(record, ["line_role_pipeline"]);
    const recipeOn = recipePipeline && String(recipePipeline).toLowerCase() !== "off";
    const lineRoleOn = lineRolePipeline && String(lineRolePipeline).toLowerCase() !== "off";
    if (recipeOn && lineRoleOn) return "full_stack";
    if (
      isOfficialPairedBenchmark &&
      pipelineOrPathVariant === "codex-exec" &&
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
    if (isOfficialPairedBenchmark && pipelineOrPathVariant === "codex-exec") {
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
      const explicitKey = String(explicit).toLowerCase().replace(/[-\\s]+/g, "_");
      if (["vanilla", "codex-exec", "deterministic", "line_role_only", "recipe_only", "full_stack", "other"].includes(explicitKey)) {
        return explicitKey;
      }
    }
    const pipelineOrPathVariant = benchmarkVariantFromPathOrPipeline(record);
    const profile = aiAssistanceProfileForRecord(record);
    const path = benchmarkArtifactPath(record);
    const isOfficialPairedBenchmark =
      path.includes("/benchmark-vs-golden/") &&
      (
        path.includes("/single-book-benchmark/") ||
        path.includes("/single-profile-benchmark/")
      );
    if (isOfficialPairedBenchmark && pipelineOrPathVariant === "vanilla" && profile === "deterministic") {
      return "vanilla";
    }
    if (isOfficialPairedBenchmark && pipelineOrPathVariant === "codex-exec" && profile === "full_stack") {
      return "codex-exec";
    }
    return profile;
  }

  function benchmarkTrendVariantForRecord(record) {
    const rawVariant = benchmarkVariantForRecord(record);
    if (rawVariant === "vanilla") return "vanilla";
    if (rawVariant === "codex-exec") return "codex-exec";
    if (rawVariant === "deterministic") return "vanilla";
    if (
      rawVariant === "line_role_only" ||
      rawVariant === "recipe_only" ||
      rawVariant === "full_stack"
    ) {
      return "codex-exec";
    }

    const path = benchmarkArtifactPath(record).toLowerCase();
    if (/(^|[\\/_-])codex(?:farm)?([\\/_-]|$)/.test(path)) return "codex-exec";
    if (
      path.includes("baseline-off") ||
      /(^|[\\/_-])vanilla([\\/_-]|$)/.test(path) ||
      /(^|[\\/_-])det(?:erministic)?([\\/_-]|$)/.test(path)
    ) {
      return "vanilla";
    }

    const recipePipeline = runConfigValue(record, ["llm_recipe_pipeline", "llm_pipeline"]);
    const lineRolePipeline = runConfigValue(record, ["line_role_pipeline"]);
    const knowledgePipeline = runConfigValue(record, ["llm_knowledge_pipeline"]);
    const hasEnabledPipeline = [
      recipePipeline,
      lineRolePipeline,
      knowledgePipeline,
    ].some(value => value && String(value).toLowerCase() !== "off");
    if (hasEnabledPipeline) return "codex-exec";
    if (rawAiModelForRecord(record) || rawAiEffortForRecord(record)) return "codex-exec";
    return "vanilla";
  }

  function benchmarkRunGroupInfo(record) {
    const fallbackTimestamp = String((record && record.run_timestamp) || "").trim();
    const rawPathCandidates = [
      String((record && record.artifact_dir) || "").trim(),
      String((record && record.run_dir) || "").trim(),
      String((record && record.report_path) || "").trim(),
    ]
      .filter(value => value)
      .map(value => value.replace(/\\\\/g, "/"));
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
        const trendVariant = benchmarkTrendVariantForRecord(record);
        if (variantKey && trendVariant !== variantKey) return null;
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
            variant: trendVariant,
            rawVariant: benchmarkVariantForRecord(record),
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
      const end = Math.min(usable.length, index + halfWindow + 1);
      const windowPoints = usable.slice(start, end);
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
      codex-exec: base,
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
    const variantPriority = ["vanilla", "codex-exec"];
    const presentVariants = new Set(
      records.map(record => benchmarkTrendVariantForRecord(record))
    );
    const hasPairedVariants =
      presentVariants.has("vanilla") || presentVariants.has("codex-exec");

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

    const variantOrder = [
      ...variantPriority.filter(variant => presentVariants.has(variant)),
      ...Array.from(presentVariants).filter(variant => !variantPriority.includes(variant)),
    ];
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
          color: metric.colors[variant] || metric.colors.other || metric.colors.default,
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
"""
