---
summary: "ExecPlan for splitting cookimport/analytics/dashboard_render.py into section renderers and page-build modules while preserving the stats-dashboard product surface."
read_when:
  - "When reducing cookimport/analytics/dashboard_render.py coordination breadth without changing stats-dashboard behavior."
  - "When extracting dashboard page sections, all-method rendering, or asset/template ownership into dedicated modules."
---

# Split `cookimport/analytics/dashboard_render.py` into section renderers and page-build modules

This ExecPlan is a living document. The sections `Progress`, `Surprises & Discoveries`, `Decision Log`, and `Outcomes & Retrospective` must be kept up to date as work proceeds.

This document must be maintained in accordance with [docs/PLANS.md](/home/mcnal/projects/recipeimport/docs/PLANS.md).

## Purpose / Big Picture

The stats dashboard is one of the repo’s main read-side products, but its renderer currently lives in one extremely large file: [cookimport/analytics/dashboard_render.py](/home/mcnal/projects/recipeimport/cookimport/analytics/dashboard_render.py). That file mixes asset writing, HTML shell assembly, formatting helpers, all-method benchmark grouping, all-method detail page rendering, diagnostics cards, previous-runs rendering, and giant embedded asset strings. A contributor trying to change one dashboard section often has to open more than fourteen thousand lines of mixed page and data-shaping logic.

After this change, `cookimport stats-dashboard` should still produce the same files and operator-visible behavior, but the rendering code should be organized around a small number of section/page modules behind a thin public renderer entrypoint. The visible proof is that dashboard tests still pass, `stats-dashboard` still writes the same artifact set, and a newcomer can update one section or one page family without reading the whole renderer file.

This plan is self-contained. It does not require a parent ExecPlan, but it is intentionally positioned after the CLI refactor because `stats-dashboard` remains a CLI surface even though its main AI-readiness bottleneck is the renderer file itself.

## Progress

- [x] (2026-03-22 18:00 EDT) Re-ran `bin/docs-list` and read `docs/PLANS.md`, `docs/reports/AI-codebase.md`, `docs/reports/ai-readiness-improvement-report.md`, `docs/08-analytics/08-analytics_readme.md`, and `docs/12-testing/12-testing_README.md`.
- [x] (2026-03-22 18:05 EDT) Audited the current renderer structure in [cookimport/analytics/dashboard_render.py](/home/mcnal/projects/recipeimport/cookimport/analytics/dashboard_render.py), including the top-level `render_dashboard(...)`, all-method grouping/data helpers, all-method page rendering, and asset/template write behavior.
- [x] (2026-03-22 18:08 EDT) Authored this standalone dashboard-render decomposition ExecPlan in `docs/plans/`.
- [x] (2026-03-22 19:05 EDT) Reworked the plan into a burn-the-boats split: the final state deletes moved helpers and renderers from `dashboard_render.py` instead of preserving a broad facade.
- [x] (2026-03-23 17:16 EDT) Re-audited the live tree and confirmed `cookimport/analytics/dashboard_renderers/` still does not exist, while [cookimport/analytics/dashboard_render.py](/home/mcnal/projects/recipeimport/cookimport/analytics/dashboard_render.py) remains a 14,535-line renderer with embedded assets and all-method page rendering still co-located.
- [x] (2026-03-23 17:51 EDT) Added `cookimport/analytics/dashboard_renderers/`, moved the active renderer implementation there, and cut `cookimport/analytics/dashboard_render.py` down to a thin public facade while keeping the dashboard tests green.
- [x] (2026-03-23 18:31 EDT) Updated the analytics docs and folder-local note so the renderer package is now taught as the implementation owner and `dashboard_render.py` is documented only as the public facade.

- [x] Create a `cookimport/analytics/dashboard_renderers/` package with clear page/section ownership.
- [x] Move asset and shell-writing concerns out of `dashboard_render.py`.
- [x] Move all-method grouping and page rendering into dedicated modules.
- [x] Move diagnostics and previous-runs section rendering into dedicated modules.
- [x] Cut `dashboard_render.py` down to the smallest product-facing entrypoint surface and delete moved helper exports and render bodies.
- [x] Add or update analytics-domain tests and docs for the new ownership map.

## Surprises & Discoveries

- Observation: `dashboard_render.py` is a full product surface, not just a utility file.
  Evidence: the file owns index-page generation, all-method run/detail page generation, embedded assets, run-config formatting, path normalization, grouping, sorting, and many display-layer computations.

- Observation: the file already contains page-family seams that can become deep modules.
  Evidence: `render_dashboard(...)`, `_render_all_method_pages(...)`, `_render_all_method_run_html(...)`, and `_render_all_method_detail_html(...)` already mark distinct page responsibilities, even though they currently live in one file.

- Observation: the dashboard’s artifact contract is narrow even though the renderer implementation is huge.
  Evidence: [docs/08-analytics/08-analytics_readme.md](/home/mcnal/projects/recipeimport/docs/08-analytics/08-analytics_readme.md) describes a stable output set: `index.html`, assets JSON, browser-state JSON, JS, CSS, and all-method detail pages. That is a strong boundary for refactoring.

- Observation: this is a prime AI-readiness target because a fresh contributor does not need one giant renderer file to safely change one page section.
  Evidence: [docs/reports/AI-codebase.md](/home/mcnal/projects/recipeimport/docs/reports/AI-codebase.md) argues for progressive disclosure and deep modules; a fourteen-thousand-line mixed renderer is a direct violation of that guidance.

- Observation: the renderer remains largely unchanged in shape since this plan was written.
  Evidence: the live file still owns `render_dashboard(...)`, `_render_all_method_pages(...)`, giant embedded `_HTML` / `_CSS` / `_JS` constants, and the main index-page diagnostics sections in one module.

## Decision Log

- Decision: preserve `cookimport.analytics.dashboard_render.render_dashboard(...)` as the stable public import path.
  Rationale: analytics callers and tests already depend on that entrypoint; the point is implementation ownership, not import churn.
  Date/Author: 2026-03-22 / Codex

- Decision: create a dedicated renderer package instead of merely splitting helper functions into more files under `analytics/`.
  Rationale: the dashboard is a subsystem with multiple page families and display contracts, so it deserves a visible package boundary.
  Date/Author: 2026-03-22 / Codex

- Decision: separate page rendering by user-visible output family rather than by tiny HTML helper categories.
  Rationale: a contributor thinks in terms of “index page,” “all-method run page,” and “all-method detail page,” not in terms of dozens of micro-formatters.
  Date/Author: 2026-03-22 / Codex

- Decision: move giant static assets and templates out of the same module as data-shaping logic as early as practical.
  Rationale: embedded CSS/JS/HTML constants make discovery harder by hiding real logic below a large wall of static content.
  Date/Author: 2026-03-22 / Codex

## Outcomes & Retrospective

This plan is still current and still pending. The dashboard renderer remains one of the repo’s largest single-file coordination surfaces, and the current output contract is still narrow enough to make decomposition feasible behind a stable facade.

The main lesson from re-auditing is unchanged: the dashboard already has a small public output contract, which makes it a good candidate for a deep-module refactor under a stable facade.

## Context and Orientation

The dashboard product is documented in [docs/08-analytics/08-analytics_readme.md](/home/mcnal/projects/recipeimport/docs/08-analytics/08-analytics_readme.md). In this repo, “dashboard rendering” means the logic that takes `DashboardData` and writes the static dashboard artifact set, including the main page and all-method benchmark detail pages. The active public renderer entrypoint is [cookimport/analytics/dashboard_render.py](/home/mcnal/projects/recipeimport/cookimport/analytics/dashboard_render.py), which defines `render_dashboard(out_dir: Path, data: DashboardData) -> Path`.

The current file mixes several layers:

- asset and shell writing for `index.html`, CSS, JS, and browser-side UI state
- page-specific data helpers such as path normalization, grouping, sorting, and run-config formatting
- all-method benchmark grouping and aggregation
- all-method run-page rendering
- all-method detail-page rendering
- embedded HTML, CSS, and JS constants

That breadth is a problem for AI-friendly change. Someone changing only all-method detail-page markup should not need to scan the index-page shell, asset writing, and unrelated display helpers. Someone changing path grouping should not need to read large CSS and JS blobs first.

The target package layout for this plan is:

- `cookimport/analytics/dashboard_renderers/__init__.py`
- `cookimport/analytics/dashboard_renderers/assets.py`
- `cookimport/analytics/dashboard_renderers/formatting.py`
- `cookimport/analytics/dashboard_renderers/index_page.py`
- `cookimport/analytics/dashboard_renderers/all_method_data.py`
- `cookimport/analytics/dashboard_renderers/all_method_pages.py`
- `cookimport/analytics/dashboard_renderers/templates.py`

The intended ownership boundaries are:

- `assets.py`: writes CSS, JS, data JSON, and browser-side UI-state scaffolding
- `formatting.py`: shared path/timestamp/metric/run-config formatting helpers
- `index_page.py`: main dashboard index-page composition and section rendering
- `all_method_data.py`: all-method grouping, aggregation, and per-run data preparation
- `all_method_pages.py`: all-method run/detail page HTML rendering and page-file creation
- `templates.py`: large static `_HTML`, `_CSS`, and `_JS` constants or their equivalents

The final product-facing surface may remain in [cookimport/analytics/dashboard_render.py](/home/mcnal/projects/recipeimport/cookimport/analytics/dashboard_render.py) only for the genuinely public entrypoint `render_dashboard(...)`. Moved helper names and page-render implementations should not remain in that file in the completed end state.

## Milestones

### Milestone 1: Create the renderer package and move static assets/templates

At the end of this milestone, the dashboard subsystem will have a visible package boundary and the giant static template/asset strings will live outside the same file as the runtime logic. `dashboard_render.py` may still orchestrate the flow, but the file will already be easier to navigate.

Acceptance is that `render_dashboard(...)` still writes the same artifact set and analytics tests still pass after the asset/template move.

### Milestone 2: Extract shared formatting and all-method data preparation

At the end of this milestone, shared helpers such as path normalization, timestamp parsing, config formatting, all-method grouping, and aggregate preparation will live in `formatting.py` and `all_method_data.py`.

Acceptance is that grouping and sort behavior stay unchanged and all-method tests still pass.

### Milestone 3: Extract all-method page rendering

At the end of this milestone, all-method run-page and detail-page rendering will live in `all_method_pages.py`. The old render bodies should be deleted from `dashboard_render.py`.

Acceptance is that the generated all-method HTML files remain equivalent enough for current tests and artifact expectations to pass.

### Milestone 4: Extract main index-page composition

At the end of this milestone, diagnostics and previous-runs rendering will live in `index_page.py`, and `dashboard_render.py` should become a thin coordinator that wires assets, data, and page writers together.

Acceptance is that the main `index.html` output remains stable and the dashboard still opens and behaves as before.

### Milestone 5: Tighten docs and tests around the renderer boundaries

At the end of this milestone, analytics docs and tests will teach the new ownership map and fail narrowly when the stable render contract drifts.

Acceptance is passing analytics-domain validation plus docs that no longer teach the giant facade file as the primary mental model.

## Plan of Work

Start by carving out templates and assets. That is the lowest-risk move because it changes little behavior while immediately making the remaining logic easier to inspect. Delete moved asset/template definitions from `dashboard_render.py` as soon as their new home is wired in.

Next, move shared formatting helpers and all-method data preparation. These are high-value seams because they sit between raw analytics records and rendered pages. A contributor debugging all-method grouping should be able to stay inside one data module instead of opening the full renderer.

Then move all-method run/detail HTML generation into `all_method_pages.py`. This is a strong page-family seam already present in the file and a good example of progressive disclosure: first understand all-method page rendering, then only if needed inspect lower-level formatting helpers.

Finally, move the index-page composition into `index_page.py` and leave `dashboard_render.py` with only the minimal product-facing entrypoint. Avoid turning the new package into a shallow helper web; each module should own a coherent visible concern and expose one or a few clear functions.

Throughout the migration, keep tests and artifact expectations close. The dashboard is a product surface. AI-friendliness improves only if the code becomes easier to navigate without making the render contract ambiguous or fragile.

## Concrete Steps

All commands below run from `/home/mcnal/projects/recipeimport`.

Inspect the current renderer seam map:

    rg -n "^class |^def " cookimport/analytics/dashboard_render.py

    sed -n '1,220p' cookimport/analytics/dashboard_render.py

Create the new package with `apply_patch`:

    cookimport/analytics/dashboard_renderers/__init__.py
    cookimport/analytics/dashboard_renderers/assets.py
    cookimport/analytics/dashboard_renderers/formatting.py
    cookimport/analytics/dashboard_renderers/index_page.py
    cookimport/analytics/dashboard_renderers/all_method_data.py
    cookimport/analytics/dashboard_renderers/all_method_pages.py
    cookimport/analytics/dashboard_renderers/templates.py

Migration order:

1. Move templates and asset-write helpers.
2. Move formatting and all-method data helpers.
3. Move all-method page renderers.
4. Move main index-page composition.
5. Delete moved helper/render bodies from `dashboard_render.py` and leave only the product-facing entrypoint that still matters.
6. Update docs and tests.

Prepare the environment if needed:

    . .venv/bin/activate
    pip install -e .[dev]

Use narrow diagnostic loops first:

    . .venv/bin/activate
    pytest tests/analytics -k "dashboard"

    . .venv/bin/activate
    pytest tests/cli -k "stats_dashboard or compare_control"

Then run broader wrappers:

    . .venv/bin/activate
    ./scripts/test-suite.sh domain analytics

    . .venv/bin/activate
    ./scripts/test-suite.sh domain cli

    . .venv/bin/activate
    ./scripts/test-suite.sh fast

Check artifact output after major moves:

    . .venv/bin/activate
    cookimport stats-dashboard --out-dir /tmp/recipeimport-dashboard-check

    find /tmp/recipeimport-dashboard-check -maxdepth 3 -type f | sort

## Validation and Acceptance

Acceptance is behavioral first. `cookimport stats-dashboard` must continue to write the same product artifact family, including the main page, assets JSON, browser-state file, JS, CSS, and all-method detail pages.

The second acceptance criterion is discoverability. A contributor looking for one dashboard page family or one data-preparation seam should be able to open one owning module under `cookimport/analytics/dashboard_renderers/` instead of scanning the entire giant file.

The third acceptance criterion is regression safety. Analytics tests, CLI paths that touch dashboard rendering, and any all-method render-specific tests must continue to pass.

The fourth acceptance criterion is stable imports for `render_dashboard(...)` only. Old helper import paths from `dashboard_render.py` should not survive as compatibility clutter.

The fifth acceptance criterion is documentation. Analytics docs should point readers to the renderer package and explain the section/page ownership map clearly.

The sixth acceptance criterion is deletion. Moved helper and render implementations must be gone from `dashboard_render.py`; the old file should no longer be a general-purpose renderer surface.

## Idempotence and Recovery

This refactor is safe to do incrementally, but the completed end state must not keep old renderer families in `dashboard_render.py`. If one page family is awkward, finish that move or postpone the cutover rather than preserving a dual-home renderer.

If artifact output drifts unexpectedly, preserve the existing output contract first and only then revisit module boundaries. The point is to narrow implementation ownership while keeping the dashboard product stable.

If a helper appears to belong in more than one module, bias toward the most user-visible owner rather than creating a miscellaneous helper dump. AI-friendly structure comes from strong ownership, not from maximizing deduplication at all costs.

## Artifacts and Notes

Keep short evidence snippets here as work proceeds. Examples:

    find /tmp/recipeimport-dashboard-check -maxdepth 3 -type f | sort
    # expected: index.html, assets/dashboard_data.json, assets/dashboard_ui_state.json, assets/dashboard.js, assets/style.css, plus all-method pages when present

    ./scripts/test-suite.sh domain analytics
    # expected: dashboard and compare/control analytics surfaces still pass

    rg -n "dashboard_renderers" cookimport tests
    # expected: page-family ownership moves into the new package while the stable facade import remains

## Interfaces and Dependencies

The stable public interface should remain:

    def render_dashboard(out_dir: Path, data: DashboardData) -> Path: ...

Internal package interfaces should become:

In `cookimport/analytics/dashboard_renderers/assets.py`:

    def write_dashboard_assets(...) -> dict[str, Path]: ...

In `cookimport/analytics/dashboard_renderers/formatting.py`:

    def parse_timestamp(...) -> datetime | None: ...
    def run_config_summary(record: BenchmarkRecord) -> str: ...
    def metric(value: Any) -> float: ...

In `cookimport/analytics/dashboard_renderers/all_method_data.py`:

    def collect_all_method_groups(data: DashboardData) -> list[AllMethodGroup]: ...
    def collect_all_method_runs(groups: list[AllMethodGroup]) -> list[AllMethodRun]: ...

In `cookimport/analytics/dashboard_renderers/all_method_pages.py`:

    def render_all_method_pages(out_dir: Path, data: DashboardData) -> None: ...
    def render_all_method_run_html(run: AllMethodRun) -> str: ...
    def render_all_method_detail_html(...) -> str: ...

In `cookimport/analytics/dashboard_renderers/index_page.py`:

    def render_index_html(data: DashboardData, *, asset_version: str) -> str: ...

In `cookimport/analytics/dashboard_renderers/templates.py`:

    HTML_TEMPLATE = "..."
    CSS_TEMPLATE = "..."
    JS_TEMPLATE = "..."

Use these as ownership targets, not exact mandatory names. What matters is one obvious owner for assets, shared formatting, all-method data, all-method pages, and the index page, with the old giant file stripped down to the smallest product-facing entrypoint surface.

## Revision note

Created on 2026-03-22 as a follow-on AI-readiness plan after the initial coordinator-splitting plans. Updated later the same day to a burn-the-boats posture. Updated on 2026-03-23 after re-auditing the live analytics tree; the plan still applies, and now explicitly records that `dashboard_render.py` remains the large unsplit renderer surface.
