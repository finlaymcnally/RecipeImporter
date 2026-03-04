# Build a Compare & Control workspace in the benchmark dashboard

This ExecPlan is a living document. The sections `Progress`, `Surprises & Discoveries`, `Decision Log`, and `Outcomes & Retrospective` must be kept up to date as work proceeds.

This document must be maintained in accordance with `PLANS.md` at the repository root. The draft below was authored against the uploaded reference copy of that file and is intended to be checked into the repo as a standalone ExecPlan.

## Purpose / Big Picture

After this change, someone opening the benchmark dashboard can do three user-visible things that are awkward or impossible today. First, they can land on a discovery view that answers “what seems to affect quality?” instead of starting from a rule builder. Second, they can pick one field such as `ai_model` or `all_token_use`, hold other fields constant, and see a deterministic raw-versus-controlled comparison. Third, they can turn a discovered comparison back into the existing subset workflow by clicking `Filter to subset`, which reuses the current rule-based filter engine instead of replacing it.

The working proof is the generated dashboard from `cookimport stats-dashboard`. In the `Previous Runs` area, the old `Isolate For X` label is replaced by `Slice`, a new `Compare & Control` panel appears above it, the panel updates live in the browser without rerunning Python, and saved presets keep both the old slice state and the new compare/control state.

## Progress

- [x] (2026-03-04 02:12Z) Reviewed the uploaded architecture summary, the Isolate report, and the ExecPlan requirements and reduced the feature from “mini BI tool” to three concrete deliverables: discovery, compare/control, and filter handoff.
- [x] (2026-03-04 02:12Z) Chosen the product split for v1: keep the current rule-based isolate engine as `Slice`, add a new primary `Compare & Control` workspace, and keep the dashboard deterministic with no in-dashboard LLM dependency.
- [ ] Add a small analytics helper module that infers field roles, chooses the default outcome metric, and serializes bootstrap metadata for the browser.
- [ ] Rename the current `Isolate For X` surface to `Slice` while preserving existing filter semantics and preset compatibility.
- [ ] Add browser-side `Compare & Control` state, controls, and raw single-variable analysis for categorical and numeric fields.
- [ ] Add `Hold constant` support, raw-versus-controlled views, comparable-coverage warnings, and categorical `Filter to subset` / `Compare selected groups` actions.
- [ ] Add default discovery cards, optional `Split by` interactions, persistence in local UI state and view presets, tests, docs, and manual acceptance evidence.

## Surprises & Discoveries

- Observation: the dashboard is a static artifact, not a server-backed app, so interactive analysis must run in the browser against embedded data rather than through a Python API call.
  Evidence: the architecture summary says `cookimport stats-dashboard` emits `index.html` plus local assets and inline JSON fallback for `file://` usage.

- Observation: the current Isolate feature already shares the table-filter engine and persists with dashboard state, so replacing it wholesale would risk breaking saved views and create two conflicting filter systems.
  Evidence: the Isolate report says isolate rules are translated directly into table column filters, use the same operator evaluator, and persist with UI state and view presets.

- Observation: the user’s actual need is not “narrow the rows” but “tease apart what matters when many variables change at once,” so `Hold constant` must be a first-class control rather than a hidden advanced option.
  Evidence: user clarification during planning explicitly centered on confounding and fair comparison, not on a stronger filtering UI.

## Decision Log

- Decision: keep the existing isolate/filter engine but rename the user-facing surface to `Slice`.
  Rationale: the current engine already solves subset selection and filter consistency well. The confusion is product framing, not the core rule evaluator.
  Date/Author: 2026-03-04 / OpenAI GPT-5.2 Pro

- Decision: add a new primary analysis surface named `Compare & Control`.
  Rationale: this wording matches the actual job of the feature: compare one field and hold other fields constant when needed. It is more precise than `Isolate For X` and less vague than `Explore`.
  Date/Author: 2026-03-04 / OpenAI GPT-5.2 Pro

- Decision: keep the dashboard deterministic and do not add an in-dashboard LLM flow in this feature.
  Rationale: the user said LLM-driven analysis will happen in Codex CLI, and deterministic browser-side summaries are easier to trust, test, and maintain.
  Date/Author: 2026-03-04 / OpenAI GPT-5.2 Pro

- Decision: default the outcome metric to the best available quality field, but allow manual selection of any numeric metric.
  Rationale: quality is the main question most of the time, but the dashboard still needs to support token, runtime, and cost analysis without a second feature.
  Date/Author: 2026-03-04 / OpenAI GPT-5.2 Pro

- Decision: implement `Hold constant` using exact strata and weighted aggregation rather than opaque model-based adjustment.
  Rationale: exact strata are easy to explain to a novice, work in a static dashboard, and visibly expose comparable coverage. This is not full causal inference; it is an honest “compare like with like” method.
  Date/Author: 2026-03-04 / OpenAI GPT-5.2 Pro

- Decision: support at most one optional `Split by` field in v1.
  Rationale: this satisfies the “grab two variables and see how they interact” requirement without exploding the UI into a blank-canvas dashboard.
  Date/Author: 2026-03-04 / OpenAI GPT-5.2 Pro

- Decision: do not build pinboards, arbitrary dashboard composition, or numeric brushing/range filtering in this ExecPlan.
  Rationale: those are valuable, but they are a separate “mini BI tool” layer. This plan is deliberately scoped to discovery, fair comparison, and handoff into existing filters.
  Date/Author: 2026-03-04 / OpenAI GPT-5.2 Pro

## Outcomes & Retrospective

Initial planning outcome: the work is now framed as one coherent dashboard feature instead of four overlapping ones. The deliverable is a deterministic browser-side analysis workspace with three jobs: discover candidate drivers, compare one field against an outcome, and hold other fields constant when needed. No code has landed yet. The biggest implementation risk is the browser-side analytics logic inside a static HTML dashboard; Milestone 1 intentionally starts with a narrow raw-analysis shell before controlled analysis is added.

## Context and Orientation

The relevant repository surface is the analytics dashboard. The architecture summary says `cookimport stats-dashboard` writes a static dashboard to `data/.history/dashboard` by default, and the current Isolate feature lives in `cookimport/analytics/dashboard_render.py`. That file is the most important starting point because it already owns the previous-runs UI, current filter state, and Isolate behavior. Also update `docs/08-analytics/08-analytics_readme.md` so a future contributor can understand the new surface without needing this plan, and update `cookimport/analytics/CONVENTIONS.md` if that file contains subsystem rules for dashboard state or rendering.

This plan uses the following plain-language terms throughout. A “visible row” is a benchmark-history row that remains after the dashboard’s ordinary quick filters, date filters, and table filters. A “slice” is a narrower subset of those visible rows created by the existing rule-based filter UI; `Slice` is the renamed user-facing label for the current Isolate feature. An “outcome” is the numeric result being explained, usually quality. A “compare field” is the one column being tested as a possible driver, such as `ai_model` or `all_token_use`. “Hold constant” means only comparing rows that match on selected fields; implementation uses exact strata, which are groups of rows with identical values for those hold-constant fields. A “split field” is one optional second field that breaks the compare view into separate panels or series. A “discovery card” is a ranked summary that says a field looks interesting and lets the user jump directly into a prefilled compare view.

This dashboard is static HTML. There is no live Python process once the file is generated. That means any interaction the user performs after opening `index.html` must run in browser-side JavaScript against the embedded run-history data and the existing client-side filter state. Do not add a web server requirement, a JavaScript bundler, or a new front-end framework for this feature. Reuse the same asset approach already used by the dashboard today.

## Milestones

### Milestone 1: Rename Isolate to Slice and add a usable Compare & Control shell

At the end of this milestone, the dashboard still supports everything the old Isolate panel did, but the user-visible label is `Slice` and there is a new `Compare & Control` panel above it. The new panel has an outcome selector, a compare-field selector, and a results area that supports raw analysis only. Choosing a categorical field shows grouped outcome summaries. Choosing a numeric field shows a relationship summary with a simple trend view and regression statistics. The proof is manual: generate the dashboard, open it, choose `ai_model` and then `all_token_use`, and watch the results area update immediately.

### Milestone 2: Add Hold Constant, raw-versus-controlled views, and filter handoff

At the end of this milestone, the feature does what the user originally meant by “isolate”: it can compare a field while holding other fields constant. The panel shows `Raw` and `Controlled` views, comparable-coverage warnings, and group-level actions for categorical compare fields. Choosing two groups under a categorical compare field shows a head-to-head delta card. Clicking `Filter to subset` converts those selections into the existing slice/filter state rather than inventing a second filtering system. The proof is a synthetic fixture that demonstrates a Simpson’s-paradox-style reversal: the raw comparison points one way, the controlled comparison points the other way, and a regression test locks in the expected interpretation.

### Milestone 3: Add discovery defaults, one-field interactions, persistence, and docs

At the end of this milestone, the dashboard opens into a sensible default instead of a blank state. With no compare field selected, it shows ranked discovery cards answering “what affects quality?” Clicking a card opens the compare view with that field selected. The optional `Split by` control allows the user to see a second field’s interaction with the first without leaving the panel. The new state persists in local UI state and saved view presets. The proof is manual and automated: discovery cards appear on initial load, split views update with one extra field, presets survive reload, and the analytics docs describe the behavior in plain language.

## Plan of Work

### Add a Python helper for field catalog and defaults

Create a new module at `cookimport/analytics/dashboard_compare_control.py`. This module is not responsible for HTML. Its job is to inspect the benchmark-history rows that are already loaded during dashboard generation and produce a field catalog plus bootstrap defaults for the browser.

The field catalog must classify every column into a value kind and a semantic role. “Value kind” is just `numeric`, `categorical`, or `ignored`. “Semantic role” is a higher-level hint such as `quality`, `tokens`, `runtime`, `cost`, `factor`, `identifier`, `timestamp`, or `ignored`. Use simple, repository-local heuristics rather than outside dependencies. A field should be treated as numeric only when most non-empty values parse as numbers. A field should be treated as an identifier or timestamp and excluded from discovery by default when the name strongly suggests it or when the field is nearly unique per row and looks like a run label, path, slug, or date-like value.

This module must also choose the default outcome field. Reuse any existing primary-quality concept already present in the dashboard if one exists. Otherwise, choose the first available quality-like numeric field from a small explicit priority list, then fall back to the first numeric field tagged as `quality`, and finally fall back to `None` with a visible empty-state message in the UI.

Keep this helper pure and testable. It should accept rows as mappings and return JSON-serializable metadata. The browser should not need to rediscover column types from scratch.

### Update dashboard_render.py to expose the new state and UI surface

Edit `cookimport/analytics/dashboard_render.py` to serialize the field catalog and a new compare/control bootstrap state into the dashboard’s embedded JSON. Add a new UI section named `Compare & Control` above the renamed `Slice` section in the `Previous Runs` area.

The initial compare/control state must include `outcomeField`, `compareField`, `holdConstantFields`, `splitField`, `viewMode`, and `selectedGroups`. `viewMode` starts as `discover` when no compare field is chosen, becomes `raw` when a compare field is selected and no controls are active, and can be toggled to `controlled` when at least one hold-constant field is set. `selectedGroups` is only meaningful for categorical compare fields and is capped at two values for the head-to-head card.

Do not remove the old isolate state keys yet. Keep their internal names for compatibility if that is what the existing renderer already uses. Only change the visible label from `Isolate For X` to `Slice`, update helper text to explain that Slice is for narrowing rows, and leave the existing evaluator and preset format intact.

### Implement browser-side compare/control calculations using the already-visible rows

Extend the dashboard’s existing browser-side script, or the generated JS asset it already uses, with pure functions that recompute the compare/control results from the currently visible rows. The compare panel must always operate on the same visible rows the table currently shows before slice reduction, so the user sees one consistent candidate pool.

For a categorical compare field in raw mode, compute one group summary per distinct value. Each summary must include row count and the mean outcome. If fields tagged as tokens, runtime, or cost exist, also include one secondary metric per role so the user can spot tradeoffs. Sort the primary table by mean outcome descending. Also compute a simple “group explained R²” number by assigning every row its group mean and measuring how much outcome variation those group means explain. This number is only a comparison aid; do not imply causal certainty.

For a numeric compare field in raw mode, compute a linear regression slope and R² on the compare field against the chosen outcome, plus Spearman rank correlation, plus a binned trend. The binned trend should use equal-count bins so sparse tails do not dominate the visual. Use simple tables or lightweight inline SVG if the dashboard already uses that style. Do not block the feature on a new charting dependency.

### Implement controlled comparisons with exact strata

Add `Hold constant` as a multi-select control listing eligible factor fields. Exact strata means grouping rows by the exact combined values of those hold-constant fields and only comparing rows within the same stratum. This is intentionally simple and auditable.

For a categorical compare field in controlled mode, compute per-stratum means by compare group, then aggregate those stratum means using the stratum row count as weight. For overall ranking, only use strata where at least two compare groups are present. For a head-to-head comparison of two selected groups, only use strata where both groups are present. Always display comparable coverage: rows used versus visible rows, and strata used versus total strata. If coverage is poor, show a warning badge rather than hiding the result.

For a numeric compare field in controlled mode, create eligible strata that contain at least two distinct compare values. Inside each eligible stratum, subtract the stratum mean from both the compare value and the outcome. Then run the linear regression and rank correlation on those centered values. Present the result as a controlled slope and controlled R², again with comparable coverage. In plain language in the UI, explain that controlled mode removes between-stratum differences so the user sees the within-like-with-like relationship instead of the across-all-rows relationship.

This controlled analysis is the heart of the feature. Keep the formulas simple, named, and documented in comments so a novice can reason about them.

### Add group actions and handoff back into Slice

For categorical compare fields, let the user select up to two groups from the summary table or cards. With one selected group, show a `Filter to subset` action. With two selected groups, show both `Filter to subset` and `Compare selected groups`.

`Filter to subset` must not invent a second filter pathway. It must populate the existing slice/table-filter state using the same rule semantics the current Isolate implementation already uses. One selected group becomes one equality clause. Two selected groups become two equality clauses combined with global OR. Preserve any unrelated existing table filters.

`Compare selected groups` does not open a second page. It reveals a head-to-head delta card inside the same panel, showing the outcome difference and the secondary tradeoff metrics in both raw and controlled form when available.

For v1, numeric compare fields do not need click-and-drag range selection. Numeric range filtering stays in the existing Slice/table filter surface.

### Add discovery defaults and Split by without turning this into a blank-canvas dashboard

When `compareField` is empty, the panel should show ranked discovery cards using the current visible rows and the chosen outcome. Each card should identify one field, say why it looks interesting, and display a compact strength indicator plus coverage. Use simple scoring: categorical fields can use the group-explained R² described above; numeric fields can use the larger of linear R² and squared Spearman correlation, with a label that says which relationship was used. Exclude identifiers, timestamps, and fields with too few usable rows or too little variation.

Clicking a discovery card must populate the compare state and switch the panel into compare mode. This gives the user a guided “I do not know what matters yet” path without asking them to choose from every field immediately.

Add one optional `Split by` field. Restrict v1 to one field only. If the split field is categorical, show separate grouped series or panels. If the split field is numeric, convert it into four equal-count bins plus `Missing` and treat those bins as categories. This is enough to support “grab two variables and see how they interact” without becoming a general-purpose dashboard builder.

### Persist state, document the behavior, and keep the old contract safe

Persist the new compare/control state in the same local UI state and view-preset systems the dashboard already uses. Old presets that contain only isolate/table state must still load. New presets must store both the old slice state and the new compare/control state. Add a default-state migration path so missing compare/control keys are filled in safely on load.

Update `docs/08-analytics/08-analytics_readme.md` to explain the purpose and behavior in plain language. Also update `cookimport/analytics/CONVENTIONS.md` if it exists and currently documents dashboard invariants. Record that `Slice` is the row-narrowing tool, `Compare & Control` is the explanation tool, and browser-side analysis must remain deterministic and server-free.

## Concrete Steps

Run all commands from the repository root.

Start by adding the new helper module and its unit tests.

    $ python -m pytest tests/analytics/test_dashboard_compare_control.py
    ...
    4 passed in 0.20s

Then wire the new field catalog and the renamed `Slice` label into the dashboard renderer, adding a fixture-based render test so the generated HTML contains the new panel and serialized state.

    $ python -m pytest tests/analytics/test_dashboard_render.py -k "compare_control or slice"
    ...
    3 passed in 0.35s

After that, implement browser-side raw analysis and rerun both analytics test files.

    $ python -m pytest tests/analytics/test_dashboard_compare_control.py tests/analytics/test_dashboard_render.py
    ...
    7 passed in 0.48s

When controlled mode and discovery mode are added, include a synthetic Simpson’s-paradox fixture and rerun the same tests plus any broader analytics suite already present in the repo.

    $ python -m pytest tests/analytics
    ...
    12 passed in 0.91s

Rebuild the real dashboard artifact.

    $ cookimport stats-dashboard

Expect output that mentions the dashboard output directory, normally `data/.history/dashboard/index.html`. If the shell entrypoint is unavailable in the local environment, use the module form instead.

    $ python -m cookimport.cli stats-dashboard

Open the generated dashboard in a browser. Because the dashboard is designed to work from static files, opening `data/.history/dashboard/index.html` directly is acceptable. When browser security settings make local storage or asset loading flaky, serve the folder locally instead.

    $ python -m http.server 8010 -d data/.history/dashboard

Then visit `http://127.0.0.1:8010/index.html`.

## Validation and Acceptance

Acceptance is behavioral.

A human should be able to generate the dashboard and observe a `Compare & Control` panel above a `Slice` panel in the `Previous Runs` area. The old `Isolate For X` wording should not be present in the visible UI.

With no compare field chosen, the panel should show discovery cards for the current visible rows, defaulting to the best available quality metric. Clicking a card should populate `Compare by` and replace the discovery cards with a compare view.

Choosing a categorical field such as `ai_model` should show grouped outcome summaries, sample counts, and secondary token/runtime/cost summaries when those metrics exist. Selecting one group should enable `Filter to subset`. Selecting two groups should reveal a head-to-head delta card.

Choosing a numeric field such as `all_token_use` should show a relationship summary with a trend view, linear R², and rank correlation. Adding `ai_model` to `Hold constant` should change the displayed controlled relationship when the dataset contains meaningful between-model differences. The UI must show how many rows were comparable enough to use.

On the synthetic Simpson’s-paradox fixture, the raw categorical comparison must point in the opposite direction from the controlled comparison. This is the automated proof that the feature really addresses confounding instead of merely restyling filters.

Reloading the page and re-opening a saved preset should restore the compare/control state as well as the existing slice/table state. Older presets created before this feature existed must still load with sensible defaults.

## Idempotence and Recovery

This work is additive and safe to repeat. Regenerating the dashboard should overwrite the static artifact in place without mutating benchmark history. Re-running tests should be side-effect free.

If rendering fails midway through development, delete only the generated dashboard directory and regenerate it. Do not hand-edit generated HTML under `data/.history/dashboard`; always regenerate from Python.

If a preset migration bug appears, keep backward compatibility by preserving the old isolate keys and adding defaults for the new compare/control keys. As a local recovery path during development, clear the dashboard’s local storage or remove the newly added preset keys rather than changing the historical benchmark CSV.

If the compare/control UI becomes unstable during implementation, keep the `Slice` rename and existing filter engine working first, then hide the unfinished panel behind a clearly named feature flag or temporary guard in the renderer until the browser-side calculations are correct. Do not partially repurpose the old isolate UI into a broken hybrid.

## Artifacts and Notes

Use a small synthetic fixture to prove the controlled logic. Keep it in `tests/fixtures/analytics/compare_control_simpson.csv` or the equivalent fixture format already used by analytics tests.

    run_id,ai_model,dataset,quality,all_token_use,benchmark_total_seconds
    r1,A,easy,0.92,120000,40
    r2,A,easy,0.91,125000,42
    r3,A,hard,0.71,210000,70
    r4,A,hard,0.72,215000,69
    r5,B,easy,0.88,90000,34
    r6,B,easy,0.87,95000,36
    r7,B,hard,0.68,180000,62
    r8,B,hard,0.67,175000,61

In this toy example, model A is better than model B within both datasets, but a skewed real fixture should also be added where one model appears worse in the raw aggregate because it was used more often on harder tasks. The test should assert that raw and controlled conclusions diverge in that fixture.

The serialized compare/control state should look roughly like this in the generated HTML JSON bootstrap.

    {
      "outcomeField": "strict_accuracy",
      "compareField": "",
      "holdConstantFields": [],
      "splitField": "",
      "viewMode": "discover",
      "selectedGroups": []
    }

A controlled categorical coverage message should read like plain English, for example:

    Controlled view uses 148 of 231 visible rows across 12 of 19 comparable strata.

A controlled numeric explanation line should say, in plain language, that the number reflects the relationship after removing average differences between the hold-constant groups.

## Interfaces and Dependencies

Do not add new runtime dependencies for this feature. Reuse the existing Python stack and the existing browser-side asset approach used by the dashboard. Do not add npm, a bundler, a server dependency, or an LLM call.

In `cookimport/analytics/dashboard_compare_control.py`, define these stable Python interfaces:

    @dataclass(frozen=True)
    class DashboardFieldInfo:
        key: str
        label: str
        value_kind: Literal["numeric", "categorical", "ignored"]
        semantic_role: Literal["quality", "tokens", "runtime", "cost", "factor", "identifier", "timestamp", "ignored"]
        distinct_count: int
        missing_count: int
        usable_for_outcome: bool
        usable_for_compare: bool
        usable_for_hold_constant: bool

    def infer_dashboard_field_catalog(rows: Sequence[Mapping[str, Any]]) -> list[DashboardFieldInfo]:
        ...

    def choose_default_outcome(field_catalog: Sequence[DashboardFieldInfo]) -> str | None:
        ...

    def serialize_compare_control_bootstrap(
        rows: Sequence[Mapping[str, Any]],
        field_catalog: Sequence[DashboardFieldInfo],
    ) -> dict[str, Any]:
        ...

In the browser-side script emitted from `cookimport/analytics/dashboard_render.py`, implement functions with these stable names so later contributors can find them easily:

    function getCompareControlVisibleRows(allRows, dashboardState) { ... }
    function computeDiscoveryCards(rows, fieldCatalog, outcomeField) { ... }
    function analyzeCategoricalRaw(rows, compareField, outcomeField, metricRoles) { ... }
    function analyzeCategoricalControlled(rows, compareField, outcomeField, holdConstantFields, metricRoles) { ... }
    function analyzeNumericRaw(rows, compareField, outcomeField) { ... }
    function analyzeNumericControlled(rows, compareField, outcomeField, holdConstantFields) { ... }
    function renderCompareControlPanel(state, analysis) { ... }
    function syncCompareSelectionToSlice(state, selectedGroups) { ... }

Keep `syncCompareSelectionToSlice` as the only place where compare/control writes back into the existing filter engine. That preserves one source of truth for actual row narrowing.

When updating tests, add at least one pure-Python test file for the field catalog and one dashboard-render fixture test file that asserts the new labels and serialized state. If the repo already has an analytics fixture pattern, follow it rather than inventing a second one.

Plan revision note: initial draft created on 2026-03-04 after clarifying that the real feature is discovery plus fair comparison, not a more elaborate filter builder. This revision intentionally scopes out blank-canvas dashboard composition and in-dashboard LLM actions so the first implementation can ship as a coherent, observable improvement.