from __future__ import annotations

_JS_TABLES = """\

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
      const raw = String(pathValue).trim().replace(/\\\\/g, "/");
      if (!raw) return { prefix: "", parts: [] };
      const prefix = raw.startsWith("/") ? "/" : "";
      const parts = raw.split("/").filter(p => p && p !== ".");
      return { prefix, parts };
    }

    function isTimestampToken(token) {
      const text = String(token || "").trim();
      if (!text) return false;
      return /^\\d{4}-\\d{2}-\\d{2}[T_]\\d{2}[.:]\\d{2}[.:]\\d{2}(?:_.+)?$/.test(text);
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
    const raw = String(pathValue).trim().replace(/\\\\/g, "/");
    if (!raw) return { prefix: "", parts: [] };
    const prefix = raw.startsWith("/") ? "/" : "";
    const parts = raw.split("/").filter(p => p && p !== ".");
    return { prefix, parts };
  }
  function isUsefulSourceToken(token) {
    const text = String(token || "").trim();
    if (!text) return false;
    const lower = text.toLowerCase();
    if (lower === "eval" || lower === "eval_output") return false;
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
    const parts = path.replace(/\\\\/g, "/").split("/");
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
    if (cfg.workers != null) parts.push("workers=" + cfg.workers);
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
      title = (title ? title + "\\n" : "") + "hash=" + hash;
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
    const parts = p.replace(/\\\\/g, "/").split("/");
    return parts.slice(-3).join("/");
  }
})();
"""
