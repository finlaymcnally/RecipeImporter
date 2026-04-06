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
    if (!path.includes("/single-book-benchmark/")) return false;
    const variant = benchmarkVariantForRecord(record);
    const profile = aiAssistanceProfileForRecord(record);
    return (
      (variant === "vanilla" && profile === "deterministic") ||
      (variant === "codex-exec" && profile === "full_stack")
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
      labels.push("official single-book vanilla/codex-exec runs only");
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
    const xAxisToggleWrap = document.getElementById(String(cfg.x_axis_toggle_wrap_id || ""));
    const xAxisDateButton = document.getElementById(String(cfg.x_axis_date_id || ""));
    const xAxisPerRunButton = document.getElementById(String(cfg.x_axis_per_run_id || ""));
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
    [xAxisDateButton, xAxisPerRunButton].forEach(button => {
      if (!(button instanceof HTMLButtonElement) || button.dataset.bound) return;
      button.addEventListener("click", () => {
        const mode = normalizeCompareControlXAxisMode(
          button.getAttribute("data-x-axis-mode")
        );
        const state = compareControlStateForSet(setKey);
        activateCompareControlChartForSet(setKey);
        state.x_axis_mode = mode;
        setCompareControlStateForSet(setKey, state);
        rerenderCompareControl();
      });
      button.dataset.bound = "1";
    });
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
      x_axis_toggle_wrap_id: "compare-control-x-axis-toggle-wrap",
      x_axis_date_id: "compare-control-x-axis-date",
      x_axis_per_run_id: "compare-control-x-axis-per-run",
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
      x_axis_toggle_wrap_id: "compare-control-x-axis-toggle-wrap-secondary",
      x_axis_date_id: "compare-control-x-axis-date-secondary",
      x_axis_per_run_id: "compare-control-x-axis-per-run-secondary",
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

    [
      ["compare-control-x-axis-date-combined", "date"],
      ["compare-control-x-axis-per-run-combined", "per_run"],
    ].forEach(([id, mode]) => {
      const button = document.getElementById(id);
      if (!(button instanceof HTMLButtonElement) || button.dataset.bound) return;
      button.addEventListener("click", () => {
        const normalizedMode = normalizeCompareControlXAxisMode(mode);
        const primaryState = compareControlStateForSet("primary");
        const secondaryState = compareControlStateForSet("secondary");
        activateCompareControlChartForSet("primary");
        activateCompareControlChartForSet("secondary");
        primaryState.x_axis_mode = normalizedMode;
        secondaryState.x_axis_mode = normalizedMode;
        setCompareControlStateForSet("primary", primaryState);
        setCompareControlStateForSet("secondary", secondaryState);
        renderCompareControlSection();
        persistDashboardUiState();
      });
      button.dataset.bound = "1";
    });

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

  function compareControlNumericValue(record, fieldName) {
    const key = String(fieldName || "").trim();
    const rawValue = previousRunsFieldValue(record, key);
    if (key === "run_timestamp") {
      const parsed = parseTs(rawValue);
      return parsed ? parsed.getTime() : null;
    }
    return maybeNumber(rawValue);
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
        const numeric = compareControlNumericValue(record, key);
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
        time_like: key === "run_timestamp" && numeric,
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
      const outcome = compareControlNumericValue(record, outcomeField);
      const compare = compareControlNumericValue(record, compareField);
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
        previousRunsFieldValue(record, "run_config.single_book_split_cache.conversion_seconds"),
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
    renderAllMethodSummary();
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
