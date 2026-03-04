---
summary: "Codebase-grounded ExecPlan for adding a Compare & Control analysis workspace to the stats dashboard while preserving Isolate/table filter contracts."
read_when:
  - "When implementing Compare & Control analysis in the Previous Runs dashboard area."
  - "When changing Isolate For X, table filter sync, or Previous Runs UI-state/preset schema."
---

# Add Compare & Control beside Isolate For X in Previous Runs

This ExecPlan is a living document. The sections `Progress`, `Surprises & Discoveries`, `Decision Log`, and `Outcomes & Retrospective` must be kept up to date as work proceeds.

Maintain this document in accordance with `docs/PLANS.md` from the repository root.

This plan builds on already-shipped isolate/filter work in:
- `docs/plans/2026-03-03_19.56.30-isolate-table-filter-unification.md`
- `docs/plans/2026-03-03_20.33.20-isolate-numeric-boolean-logic.md`

## Purpose / Big Picture

After this change, the dashboard will support two distinct workflows in `Previous Runs`:

1. `Isolate For X` keeps doing row slicing via existing table-filter semantics.
2. New `Compare & Control` helps answer "what seems to move quality/cost/runtime?" using deterministic browser-side analysis of the currently visible benchmark rows.

The user-visible win is that they can start from discovery (candidate drivers), drill into one comparison field, optionally hold other fields constant, and then push selected groups back into the existing table-filter path using `Filter to subset`. This avoids building a second filter engine and keeps table/trend/preset behavior coherent.

The implementation proof is a generated `cookimport stats-dashboard` page where:
- a `Compare & Control` panel appears in `Previous Runs`,
- selecting fields updates results live without re-running Python,
- `Filter to subset` writes into existing column filters,
- page reload and preset save/load preserve compare/control state.

Scope guard: this is dashboard analytics/UI work only. It must not enable codex-farm or any LLM data-import path.

## Progress

- [x] (2026-03-03_21.47.05) Read `docs/PLANS.md`, `docs/08-analytics/08-analytics_readme.md`, `docs/08-analytics/dashboard_readme.md`, and Isolate system report.
- [x] (2026-03-03_21.47.05) Traced current isolate/table filter contracts in `cookimport/analytics/dashboard_render.py` and dashboard tests in `tests/analytics/test_stats_dashboard.py`.
- [x] (2026-03-03_21.47.05) Rebased this OG plan from generic draft text to concrete repo seams, commands, and state contracts.
- [x] (2026-03-03_22.00.24) Added compare/control panel markup, CSS, and JS state plumbing in `cookimport/analytics/dashboard_render.py`.
- [x] (2026-03-03_22.00.24) Implemented raw compare analysis (categorical + numeric) and `Filter to subset` handoff into existing table filters.
- [x] (2026-03-03_22.00.24) Implemented controlled analysis with hold-constant strata and coverage reporting.
- [x] (2026-03-03_22.00.24) Added discovery defaults, optional split-by field, and UI-state/preset persistence for compare/control state.
- [x] (2026-03-03_22.00.24) Updated analytics docs and extended dashboard tests; ran `. .venv/bin/activate && pytest tests/analytics/test_stats_dashboard.py -q` and `. .venv/bin/activate && cookimport stats-dashboard`.

## Surprises & Discoveries

- Observation: Isolate is already unified with table filters and global cross-column `AND/OR`.
  Evidence: `applyIsolateRulesToTableFilters(...)`, `recordMatchesPreviousRunsFilterGroups(...)`, and `column_filter_global_mode` state are already active in `cookimport/analytics/dashboard_render.py`.

- Observation: Dashboard frontend logic is emitted from a Python string constant, not a separate source tree.
  Evidence: renderer writes `_JS` to `assets/dashboard.js` from `cookimport/analytics/dashboard_render.py`; there is no standalone frontend module to patch.

- Observation: Primary regression coverage for dashboard UI contracts is concentrated in one analytics test file.
  Evidence: `tests/analytics/test_stats_dashboard.py` contains current isolate/quick-filter/JS contract assertions; there is no existing `tests/analytics/test_dashboard_render.py`.

- Observation: Previous Runs state already has dual persistence (localStorage plus optional program-side JSON sync in `--serve` mode).
  Evidence: `buildDashboardUiStatePayload(...)` / `applyDashboardUiStatePayload(...)` and `assets/dashboard_ui_state.json` sync flow.

- Observation: Compare/control analysis should run on already-visible rows, not pre-filter rows.
  Evidence: wiring `renderCompareControlPanel(...)` from `computePreviousRunsFilterResult()` with `matchedRecords` keeps table, trend, isolate, and compare contexts aligned.

- Observation: `Filter to subset` can remain deterministic by writing only through existing table filter helpers.
  Evidence: `syncCompareControlSelectionToTableFilters()` now uses `setPreviousRunsColumnFilterClauses(...)` + `setPreviousRunsColumnFilterMode(...)` and marks `previousRunsFilterControlSource = "table"`.

## Decision Log

- Decision: Keep user-facing `Isolate For X` label unchanged in this plan.
  Rationale: current docs/tests/UI all anchor that wording; rename churn is orthogonal to compare/control behavior and can be a later pass.
  Date/Author: 2026-03-03 / assistant

- Decision: Add compare/control as a sibling panel, not as a replacement for isolate.
  Rationale: isolate already solves deterministic subset filtering; compare/control solves attribution and confounding questions.
  Date/Author: 2026-03-03 / assistant

- Decision: Compute compare/control in browser JS using already collected benchmark rows.
  Rationale: dashboard is static HTML; no runtime API layer exists after generation.
  Date/Author: 2026-03-03 / assistant

- Decision: Persist compare/control state inside existing `previous_runs` UI-state/preset payloads.
  Rationale: this keeps restore behavior consistent with filters/sort/columns and avoids adding a second persistence channel.
  Date/Author: 2026-03-03 / assistant

- Decision: Keep compare/control math lightweight and browser-native (ranked discovery, regression/correlation, exact-strata centering) without adding dependencies.
  Rationale: the dashboard remains static and deterministic while still providing actionable directional analysis and coverage diagnostics.
  Date/Author: 2026-03-03 / assistant

## Outcomes & Retrospective

Current outcome: compare/control shipped in `Previous Runs` as a sibling panel to isolate, with discovery/raw/controlled modes, split-by summaries, and deterministic filter handoff into existing table filters.

Validation outcome: dashboard contracts remained intact (`Isolate For X`, quick filters, trend chart integration, preset/state flow), docs were updated, and `pytest tests/analytics/test_stats_dashboard.py -q` passed after the implementation.

## Context and Orientation

`cookimport stats-dashboard` is a static-site generator. `cookimport/analytics/dashboard_collect.py` produces `DashboardData`, then `cookimport/analytics/dashboard_render.py` emits:
- `index.html`
- `assets/dashboard.js` (from `_JS`)
- `assets/style.css` (from `_CSS`)
- `assets/dashboard_data.json`
- `assets/dashboard_ui_state.json`

All compare/control UI logic in this plan belongs in `cookimport/analytics/dashboard_render.py` inside the emitted JS/CSS/HTML templates.

Current filter and state seams to reuse:
- `computePreviousRunsFilterResult()` / `currentPreviousRunsFilterResult()`: central source of filtered benchmark rows and status text.
- `applyIsolateRulesToTableFilters(...)`: existing isolate -> table filter bridge.
- `activePreviousRunsColumnFilters()`, `compilePreviousRunsFilterPredicate()`, `recordMatchesPreviousRunsFilterGroups(...)`: existing table filter evaluator path.
- `buildDashboardUiStatePayload()` / `applyDashboardUiStatePayload(...)` / preset sanitizers: where compare/control state must be persisted and restored.
- `renderIsolateInsightsPanel(...)`: existing analytics panel pattern in Previous Runs.

Primary regression harness:
- `tests/analytics/test_stats_dashboard.py`

Docs that must be updated with behavior changes:
- `docs/08-analytics/dashboard_readme.md`
- `docs/08-analytics/08-analytics_readme.md`

## Milestones

### Milestone 1: Compare & Control shell and state plumbing

Add a `Compare & Control` panel in the `Previous Runs` section (sibling to existing Isolate panel) with controls for:
- outcome metric,
- compare field,
- hold-constant fields (initially empty),
- optional split field,
- view mode (`discover`, `raw`, `controlled`),
- selected categorical groups.

Wire state into existing dashboard UI persistence (`previous_runs`) with safe defaults when keys are missing.

Acceptance for Milestone 1: panel renders, controls are interactive, state survives reload/preset save-load, no isolate/filter regressions.

### Milestone 2: Raw compare analysis and filter handoff

Implement raw-mode analysis on currently visible benchmark rows (same pool feeding Previous Runs table after active filters).

Categorical compare field:
- grouped row count,
- grouped outcome mean,
- optional secondary means for token/runtime/cost fields when available.

Numeric compare field:
- slope + linear R-squared,
- Spearman rank correlation,
- equal-count binned summary for trend readability.

Add `Filter to subset` action that translates selected categorical groups into existing table clauses via current filter helpers; do not create a parallel filtering path.

Acceptance for Milestone 2: selecting fields updates analysis live and `Filter to subset` modifies table filters using current semantics.

### Milestone 3: Controlled analysis with exact strata

Add hold-constant behavior using exact strata (rows with identical hold-field values). For controlled output:
- categorical compare: weighted within-strata group means, comparable-coverage stats,
- numeric compare: within-strata centered regression/correlation, comparable-coverage stats.

Show coverage explicitly (used rows / candidate rows and used strata / total strata), with warning text when coverage is weak.

Acceptance for Milestone 3: controlled metrics differ from raw when confounding exists and coverage messaging is visible.

### Milestone 4: Discovery defaults, split-by, docs/tests

When no compare field is selected, render ranked discovery cards (deterministic strength score + coverage) from visible rows. Clicking a card pre-fills compare controls and enters compare mode.

Add one optional `Split by` field:
- categorical split => segmented summaries,
- numeric split => equal-count bins plus missing bucket.

Finish by updating analytics docs and extending `tests/analytics/test_stats_dashboard.py` with new markup/JS/state contract assertions.

Acceptance for Milestone 4: no blank initial state, split view works, docs reflect behavior, tests pass.

## Plan of Work

Start by adding compare/control state definitions and control rendering near existing Previous Runs/isolate setup functions in `_JS`. Keep naming/style consistent with current helpers (`normalize*`, `setup*`, `render*`).

Next, add a field-catalog helper for compare controls. Reuse existing benchmark field-value access (`previousRunsFieldValue`) and numeric detection patterns already present for isolate/table filters, instead of introducing external dependencies.

Then implement analysis functions in small pure helpers (raw categorical, raw numeric, controlled categorical, controlled numeric) and one panel renderer that consumes their outputs. Integrate this renderer into `computePreviousRunsFilterResult()` so compare/control and table status use the same filtered context.

After analysis, add `Filter to subset` wiring that appends/sets table clauses through current column-filter helpers (`addPreviousRunsColumnFilter`, `setPreviousRunsColumnFilterClauses`, global mode setters) and marks control source as table to preserve current ownership rules.

Finally, add persistence migration logic for `previous_runs.compare_control`, update docs, and extend analytics tests for markup IDs, JS function presence, state payload keys, and compatibility with older state payloads that lack compare keys.

## Concrete Steps

Run from repository root.

1. Prepare Python environment for tests.

    . .venv/bin/activate
    pip install -e '.[dev]'

2. Implement panel/state/analysis in `cookimport/analytics/dashboard_render.py`.

3. Extend dashboard tests in `tests/analytics/test_stats_dashboard.py`.

4. Update docs:
   - `docs/08-analytics/dashboard_readme.md`
   - `docs/08-analytics/08-analytics_readme.md`

5. Run targeted dashboard tests.

    . .venv/bin/activate && pytest tests/analytics/test_stats_dashboard.py -q

6. Regenerate dashboard and run manual UI check.

    . .venv/bin/activate && cookimport stats-dashboard

   If `cookimport` entrypoint is unavailable:

    . .venv/bin/activate && python -m cookimport.cli stats-dashboard

7. Optional local static serving for browser checks.

    python -m http.server 8010 -d data/.history/dashboard

## Validation and Acceptance

Acceptance is behavioral and regression-safe.

- `Previous Runs` shows both `Compare & Control` and `Isolate For X`.
- Compare controls react immediately on field changes without re-running CLI commands.
- Raw categorical and numeric summaries appear with non-empty benchmark history.
- Controlled mode shows coverage stats and does not silently report values when strata are incomparable.
- `Filter to subset` updates existing table filter UI/results; no duplicate filter engine appears.
- Existing isolate interactions (`Add rule`, `Clear all`, AND/OR combine, numeric operators) still work.
- Saved presets and reload restore compare/control state alongside existing Previous Runs state.
- `pytest tests/analytics/test_stats_dashboard.py -q` passes.

## Idempotence and Recovery

Edits are additive and safe to rerun. `cookimport stats-dashboard` rewrites generated artifacts deterministically.

If UI state causes confusing local behavior during testing, clear local storage key `cookimport.stats_dashboard.ui_state.v1` and reload. In `--serve` mode, also clear/replace `data/.history/dashboard/assets/dashboard_ui_state.json` and regenerate.

If compare/control panel logic is mid-implementation and unstable, guard rendering behind a temporary feature boolean in `_JS` while keeping existing isolate/table/trend behavior untouched.

## Artifacts and Notes

Expected persisted shape under `previous_runs` (new key):

    {
      "compare_control": {
        "outcome_field": "strict_accuracy",
        "compare_field": "",
        "hold_constant_fields": [],
        "split_field": "",
        "view_mode": "discover",
        "selected_groups": []
      }
    }

Expected UX text examples:
- `Controlled view uses 148 of 231 rows across 12 of 19 comparable strata.`
- `Filter to subset wrote 2 clauses into Previous Runs table filters.`

Synthetic fixture recommendation for manual sanity checks (or future pure-math tests):
- include one confounded dataset where raw and controlled conclusions diverge.

## Interfaces and Dependencies

No new runtime dependencies.

Add stable helper names inside dashboard JS (emitted from `dashboard_render.py`) so future contributors can find seams quickly:

    function normalizeCompareControlState(rawState) { ... }
    function buildCompareControlFieldCatalog(records) { ... }
    function chooseDefaultCompareOutcome(catalog) { ... }
    function analyzeCompareControlCategoricalRaw(records, outcomeField, compareField) { ... }
    function analyzeCompareControlNumericRaw(records, outcomeField, compareField) { ... }
    function analyzeCompareControlCategoricalControlled(records, outcomeField, compareField, holdFields) { ... }
    function analyzeCompareControlNumericControlled(records, outcomeField, compareField, holdFields) { ... }
    function renderCompareControlPanel(context) { ... }
    function syncCompareControlSelectionToTableFilters(selection) { ... }

Persist these fields through existing UI-state/preset sanitizer paths:
- `sanitizePreviousRunsPresetState(...)`
- `applyDashboardUiStatePayload(...)`
- `buildDashboardUiStatePayload(...)`

Plan revision note (2026-03-03_21.47.05 EST): replaced generic draft assumptions with codebase-grounded implementation details for this repository (real files, real state/filter contracts, and repo-specific validation commands).
Plan revision note (2026-03-03_22.00.24 EST): marked all milestones complete after implementing compare/control panel + analysis + state/preset plumbing, updated analytics docs/tests, and recorded validation command outcomes.
