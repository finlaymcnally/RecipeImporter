---
summary: "ExecPlan refresh for multi-backend EPUB auto-selection, focused on finishing report/analytics visibility and a dedicated race command on top of shipped extractor infrastructure."
read_when:
  - "When extending EPUB auto-selection (`--epub-extractor auto`) or race diagnostics"
  - "When wiring EPUB extractor decision metadata into reports, perf CSV, or dashboard views"
---

# Multi-backend EPUB auto-selection: finish race visibility and tooling

This ExecPlan is a living document. The sections `Progress`, `Surprises & Discoveries`, `Decision Log`, and `Outcomes & Retrospective` must be kept up to date as work proceeds.

This plan must be maintained in accordance with `docs/PLANS.md`.

## Purpose / Big Picture

The original `06` goal was to run multiple EPUB extraction backends, choose the best one deterministically, and make that decision easy to inspect later. Since this draft was first written, most backend and auto-selection infrastructure has already shipped (`legacy`, `unstructured`, `markdown`, `markitdown`, plus deterministic `auto` resolution before workers run). The remaining gap is not extraction capability; the gap is visibility and ergonomics.

After this refreshed plan is implemented, a user can run EPUB imports with `--epub-extractor auto` and get the backend decision captured directly in the conversion report, visible in history/dashboard surfaces, and available through a dedicated one-file race command under the existing `cookimport epub ...` debug namespace. This avoids manual archaeology in raw artifacts while preserving today’s deterministic behavior.

## Progress

- [x] (2026-02-20_10.35.00) Reviewed current code paths and completed ExecPlans (`03`, `04`, `05`, `07`, `08`) to establish what is already shipped vs. still missing from this plan’s intent.
- [x] (2026-02-20_10.46.00) Confirmed that `auto` extractor selection is already deterministic and resolved before worker fan-out (`cookimport/parsing/epub_auto_select.py`, `cookimport/cli.py`, `cookimport/labelstudio/ingest.py`).
- [x] (2026-02-20_10.53.00) Confirmed split-job safety behavior: workers receive concrete effective extractors, not unresolved `auto`, and split planning respects extractor capabilities.
- [x] (2026-02-20_14.12.00) Added first-class report schema fields for EPUB auto-selection/race metadata and selected-score summary (`epubAutoSelection`, `epubAutoSelectedScore`).
- [x] (2026-02-20_14.24.00) Propagated auto-selection metadata through stage worker/split-merge report paths and benchmark prediction processed report/manifest paths.
- [x] (2026-02-20_14.30.00) Added `cookimport epub race` command under `cookimport/epubdebug/cli.py` with deterministic candidate scoring and `epub_race_report.json`.
- [x] (2026-02-20_14.37.00) Added explicit extractor visibility fields to perf CSV + dashboard schema/collector/renderer (including dashboard extractor filter).
- [x] (2026-02-20_14.49.00) Added targeted tests/docs/conventions/understandings updates and validated with local venv test run.

## Surprises & Discoveries

- Observation: The old `06` draft is no longer the right baseline because the core extractor architecture was implemented later under adjacent plans.
  Evidence: `docs/plans/08-HolisticHardening.md` and current code already include `markdown` backend, deterministic `auto`, and benchmark wiring.

- Observation: Auto-selection details are currently persisted as a raw artifact (`epub_extractor_auto.json`) but not as first-class report fields.
  Evidence: `cookimport/parsing/epub_auto_select.py:write_auto_extractor_artifact` writes JSON under `raw/epub/...`; `cookimport/core/models.py:ConversionReport` has no dedicated auto-selection field.

- Observation: Existing analytics can infer extractor choice from `runConfig`, but there is no explicit, normalized field for auto-selected score or candidate outcome.
  Evidence: Added additive CSV columns (`epub_extractor_requested`, `epub_extractor_effective`, `epub_auto_selected_score`) and stage dashboard fields in `cookimport/analytics/*` to remove inference-only behavior.

- Observation: Non-EPUB stage rows still carry generic run config keys; extractor-specific dashboard columns should not be populated from those values.
  Evidence: Collector now gates extractor field projection by EPUB-like rows (importer/file) so text/pdf rows do not show misleading extractor labels.

## Decision Log

- Decision: Keep the current deterministic sampling-based auto-selection design as the default race mechanism for v1 of this plan refresh.
  Rationale: It is already deployed, split-safe, benchmark-safe, and fast. Replacing it with full N-backend full-book conversion would be more expensive and riskier without clear user benefit for this solo workflow.
  Date/Author: 2026-02-20 / Codex

- Decision: Add report/analytics visibility by promoting existing auto-selection artifact data, rather than creating an entirely separate second scoring pipeline.
  Rationale: Reusing the shipped selection payload keeps behavior consistent and minimizes new moving parts.
  Date/Author: 2026-02-20 / Codex

- Decision: Implement a dedicated race entrypoint as `cookimport epub race` (within existing EPUB debug CLI), not as a new top-level command.
  Rationale: EPUB debugging already lives under `cookimport epub ...`; keeping this command there preserves CLI discoverability and avoids command-surface sprawl.
  Date/Author: 2026-02-20 / Codex

- Decision: Centralize selected-score extraction in `selected_auto_score(...)` and reuse it in stage/prediction/report/analytics wiring.
  Rationale: Prevents drift where each layer computes selected candidate score differently.
  Date/Author: 2026-02-20 / Codex

## Outcomes & Retrospective

Implemented the remaining `06` scope end-to-end:

- Stage and processed report JSON now emit first-class `epubAutoSelection` + `epubAutoSelectedScore` for auto runs.
- Split EPUB merges preserve auto metadata in merged reports.
- Prediction-run manifests now include auto metadata, and benchmark CSV appenders can carry `epub_auto_selected_score`.
- `cookimport epub race` now provides one-command deterministic candidate comparison + `epub_race_report.json`.
- Perf CSV/dashboard now expose explicit EPUB extractor requested/effective/auto-score fields (with extractor filtering in dashboard UI).

Validation evidence:

- `pytest -q tests/test_epub_auto_select.py tests/test_cli_output_structure.py tests/test_epub_debug_cli.py tests/test_performance_features.py tests/test_stats_dashboard.py`
- Result: `53 passed` (warnings only) in local `.venv`.

Residual limitations:

- `epub_extractor=markitdown` can be passed to `epub race --candidates`, but because auto scoring samples spine ranges, markitdown candidate runs are expected to fail and are reported as failed candidates (by design for now).

## Context and Orientation

Relevant current modules and contracts:

- `cookimport/plugins/epub.py`: extractor execution (`legacy`, `unstructured`, `markdown`, `markitdown`) and per-run `epubBackend` reporting.
- `cookimport/parsing/epub_extractors.py`: explicit extractor implementations and diagnostics metadata.
- `cookimport/parsing/extraction_quality.py`: deterministic score model (`score_blocks`) used by auto-selection.
- `cookimport/parsing/epub_auto_select.py`: deterministic candidate sampling and effective extractor resolution with artifact payload.
- `cookimport/cli.py`: stage orchestration, per-file auto resolution, split planning, worker dispatch, split merge.
- `cookimport/cli_worker.py`: single-file and split-job report writing path.
- `cookimport/labelstudio/ingest.py`: benchmark prediction generation path, including `auto` resolution and scoped EPUB env behavior.
- `cookimport/core/models.py`: `ConversionReport` schema.
- `cookimport/analytics/perf_report.py`: performance CSV schema and row append logic.
- `cookimport/analytics/dashboard_schema.py`, `cookimport/analytics/dashboard_collect.py`, `cookimport/analytics/dashboard_render.py`: dashboard data contract and rendering.
- `cookimport/epubdebug/cli.py`: existing EPUB debug command group where new race command should live.

Definitions used in this plan:

- Auto-selection artifact: JSON payload produced by `select_epub_extractor_auto(...)`, including candidates, sample indices, and selected backend rationale.
- Effective extractor: concrete backend actually used by conversion (`legacy`, `unstructured`, `markdown`, `markitdown`), after resolving requested value.
- Race command: a one-file developer command that runs the same deterministic auto-selection logic and writes a focused comparison artifact.

## Plan of Work

### Milestone 1: Report contract for auto-selection metadata

Add explicit report fields so backend choice is visible without reading raw artifacts.

Work:

1) Extend `ConversionReport` in `cookimport/core/models.py` with optional EPUB auto-selection fields. Keep these additive and backward-compatible.
- `epub_auto_selection` (alias `epubAutoSelection`): structured payload containing selected extractor, sample indices, candidates, and selection reason.
- `epub_auto_selected_score` (alias `epubAutoSelectedScore`): float score for selected candidate when available.

2) Normalize payload shape before writing:
- Keep field names stable and JSON-serializable.
- Preserve candidate order and status (`ok`/`failed`) exactly as evaluated.

3) Ensure non-auto runs remain clean:
- Fields should be omitted or `None` when extractor request is not `auto`.

Acceptance:
- A stage report generated with `--epub-extractor auto` contains `epubAutoSelection` and `epubAutoSelectedScore`.
- A stage report generated with `--epub-extractor legacy` does not contain misleading auto fields.

### Milestone 2: Propagate metadata through stage + benchmark flows

Ensure report metadata survives both direct writes and split merges.

Work:

1) In `cookimport/cli.py`, keep a per-file map of auto-selection artifacts during pre-worker resolution.

2) Pass per-file artifact data into worker/merge write paths:
- `stage_one_file(...)` in `cookimport/cli_worker.py`
- `stage_epub_job(...)` in `cookimport/cli_worker.py`
- `_merge_split_jobs(...)` path in `cookimport/cli.py`

3) In `cookimport/labelstudio/ingest.py`, attach the same metadata into prediction-run report/manifests so benchmark paths keep parity with stage paths.

4) Preserve existing invariants:
- Do not re-resolve `auto` inside workers.
- Do not mutate global env state outside scoped context managers.

Acceptance:
- Single-file auto stage report includes full auto payload.
- Split EPUB auto stage run writes one merged report with the same selected extractor and payload shape.
- Prediction-run artifacts include requested/effective extractor plus auto-selection metadata when applicable.

### Milestone 3: Add `cookimport epub race` developer command

Expose a fast, explicit way to inspect backend candidate scoring without running full stage.

Work:

1) Add a new subcommand in `cookimport/epubdebug/cli.py`:
- `cookimport epub race PATH --out OUTDIR [--candidates unstructured,markdown,legacy] [--json] [--force]`

2) Command behavior:
- Resolve candidates with `select_epub_extractor_auto(...)`.
- Print a compact summary table (candidate, status, average score, selected marker).
- Write `epub_race_report.json` to `OUTDIR` (or equivalent stable name).

3) Keep implementation aligned with stage behavior:
- Reuse deterministic sampling logic and scorer from `epub_auto_select.py`.
- Do not introduce a second, different selection algorithm.

Acceptance:
- Running the command on an EPUB writes a deterministic race report artifact.
- Console output clearly identifies selected backend and candidate score summary.

### Milestone 4: Analytics visibility and dashboard support

Add explicit fields so historical analysis does not require parsing nested run config blobs manually.

Work:

1) Extend CSV row schema in `cookimport/analytics/perf_report.py` with additive columns:
- `epub_extractor_requested`
- `epub_extractor_effective`
- `epub_auto_selected_score`

2) Populate new columns from report/run_config data with safe fallback:
- prefer explicit report fields, fallback to run config keys when possible.

3) Extend dashboard schema and collector:
- add corresponding fields to stage records in `cookimport/analytics/dashboard_schema.py`.
- parse from CSV in `cookimport/analytics/dashboard_collect.py`.

4) Extend dashboard rendering:
- expose effective extractor and selected auto score in stage table and filters in `cookimport/analytics/dashboard_render.py`.

Acceptance:
- `performance_history.csv` includes new EPUB extractor visibility fields for stage rows.
- `stats-dashboard` displays effective extractor and selected score when present.

### Milestone 5: Tests and docs

Add guardrails and document the final contract.

Work:

1) Tests:
- Extend CLI output tests (`tests/test_cli_output_structure.py`) to assert `epubAutoSelection` fields on auto runs.
- Add/extend split-path tests to ensure merged reports keep auto-selection metadata.
- Add command tests for `cookimport epub race` in `tests/test_epub_debug_cli.py`.
- Add perf/dashboard tests for new CSV and schema fields.

2) Docs:
- Update `docs/03-ingestion/03-ingestion_readme.md` with explicit report field contract.
- Update `docs/08-analytics/08-analytics_readme.md` and `docs/08-analytics/dashboard_readme.md` with new CSV/dashboard fields.
- Update `docs/understandings/IMPORTANT-UNDERSTANDING-epub-extractor-types.md` with race command usage.

3) Finalize this plan:
- Mark progress items complete.
- Record test command outcomes and residual limitations in `Outcomes & Retrospective`.

Acceptance:
- Targeted tests pass in local venv.
- Docs reflect the shipped report + analytics contracts.

## Concrete Steps

Run from repository root:

1) Environment:

    source .venv/bin/activate
    pip install -e .[dev]

2) Targeted tests:

    pytest -q tests/test_epub_auto_select.py tests/test_cli_output_structure.py tests/test_epub_debug_cli.py tests/test_performance_features.py tests/test_stats_dashboard.py

3) Manual stage check:

    cookimport stage data/input/<book>.epub --epub-extractor auto --workers 1 --epub-split-workers 2

Inspect:
- `<run_root>/<book_slug>.excel_import_report.json` for `epubAutoSelection`.
- `<run_root>/raw/epub/<source_hash>/epub_extractor_auto.json` for parity with report payload.

4) Manual race command check:

    cookimport epub race data/input/<book>.epub --out /tmp/epub-race --force

Inspect:
- `/tmp/epub-race/epub_race_report.json`
- console summary for selected backend and candidate scores.

5) Analytics check:

    cookimport perf-report --run-dir <run_root> --out-dir data/output --write-csv
    cookimport stats-dashboard --output-root data/output --golden-root data/golden --out-dir data/output/.history/dashboard

Inspect:
- `data/output/.history/performance_history.csv` includes new EPUB extractor columns.
- dashboard stage table/filter exposes effective extractor and selected score.

## Validation and Acceptance

This plan is complete when all of the following are true:

1) Report visibility:
- Auto stage runs include first-class auto-selection metadata in report JSON.
- Non-auto runs do not populate auto-only fields.

2) Split parity:
- Split EPUB runs preserve the same selected backend and auto metadata in merged report outputs.

3) Debug ergonomics:
- `cookimport epub race` provides one-command candidate comparison and artifact output.

4) Analytics visibility:
- History CSV and dashboard include explicit requested/effective extractor fields and selected score when available.

5) Regression safety:
- Targeted tests covering auto selection, report shape, race command, and analytics fields pass.

## Idempotence and Recovery

- All changes are additive to report/dashboard contracts; old report files remain readable because new fields are optional.
- Stage and benchmark runs remain timestamped and idempotent at run-root level.
- If any new analytics column causes issues, fallback is to leave the field blank (not crash ingestion/report collection).
- Race command is read-only on input EPUB and writes only to explicit output path.

## Artifacts and Notes

Expected report fragment for auto runs (shape-level example):

    {
      "runConfig": {
        "epub_extractor": "auto",
        "epub_extractor_requested": "auto",
        "epub_extractor_effective": "markdown"
      },
      "epubBackend": "markdown",
      "epubAutoSelectedScore": 0.81,
      "epubAutoSelection": {
        "requested_extractor": "auto",
        "effective_extractor": "markdown",
        "sample_indices": [0, 1, 6, 11, 12],
        "selected_reason": "highest_average_score_then_candidate_order",
        "candidates": [
          {"backend": "unstructured", "status": "ok", "average_score": 0.74},
          {"backend": "markdown", "status": "ok", "average_score": 0.81},
          {"backend": "legacy", "status": "failed", "error": "..."}
        ]
      }
    }

Notes:
- Keep the report payload aligned with the raw auto artifact structure to reduce drift and debugging confusion.
- `markitdown` stays a concrete opt-in extractor and is not part of default auto candidate set unless explicitly changed.

## Interfaces and Dependencies

Expected interfaces after implementation:

- `cookimport/core/models.py`:
  - `ConversionReport.epub_auto_selection: dict[str, Any] | None` (alias `epubAutoSelection`)
  - `ConversionReport.epub_auto_selected_score: float | None` (alias `epubAutoSelectedScore`)

- `cookimport/epubdebug/cli.py`:
  - new command `epub race` that reuses `select_epub_extractor_auto(...)`

- `cookimport/analytics/perf_report.py`:
  - new CSV fields for requested/effective extractor and selected auto score

- `cookimport/analytics/dashboard_schema.py`:
  - stage record fields mirroring the same extractor/score values

No new third-party dependencies are required for this refresh.

Plan revision note (2026-02-20_11.08.55): Replaced the outdated pre-implementation draft with a current-state ExecPlan that treats multi-backend extraction and deterministic auto-selection as already shipped, and narrows remaining work to report/analytics visibility plus a dedicated EPUB race command.

Plan revision note (2026-02-20_14.49.00): Completed implementation of report/manifest metadata propagation, `epub race`, and analytics/dashboard visibility; updated tests/docs and recorded validation outcomes.
