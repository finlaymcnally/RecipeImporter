---
summary: "ExecPlan and implementation log for per-run run settings selection, editing, and runConfig persistence."
read_when:
  - When changing interactive Import or benchmark run-settings selection/editor behavior
  - When updating runConfig hash/summary persistence into reports, CSV history, or dashboard data
---

# Add per-run Run Settings selector + toggle editor, with runConfig persistence

This ExecPlan is a living document. The sections `Progress`, `Surprises & Discoveries`, `Decision Log`, and `Outcomes & Retrospective` must be kept up to date as work proceeds.

This repository includes `PLANS.md` at the repository root. This ExecPlan must be maintained in accordance with `PLANS.md` (same path).

## Purpose / Big Picture

Right now, “settings” are global defaults, but import/benchmark runs need a *per-run* configuration layer so you can rapidly experiment (toggle features, swap extractors, change worker strategies, etc.) without corrupting your global defaults and without losing traceability.

After this change, when you use the interactive CLI and choose **Import** or **Benchmark**, you will always go through a **Run Settings** chooser:

1) Run with global defaults  
2) Run with last run’s settings (with a compact summary shown in the menu)  
3) Change run settings (opens a TUI “toggle table” editor with ↑/↓ to move rows, ←/→ to change values, and Save/Cancel)

Every run will write a *structured* `runConfig` snapshot (plus a stable hash and human-readable summary) into:
- the per-file conversion report JSON (`*.excel_import_report.json`)
- the cross-run history CSV (`performance_history.csv`) at least as `run_config_hash` and `run_config_summary`
- benchmark/eval artifacts used by the dashboard, so the dashboard can display and group results by config

Critically, the system must be designed so that adding a new pipeline knob later requires changing *one canonical place*, and the UI + reporting automatically pick it up.

## Progress

- [x] (2026-02-16) Repo reconnaissance: identified settings/report/analytics wiring and benchmark append paths.
- [x] (2026-02-16) Defined canonical `RunSettings` model (typed + UI metadata) with stable `run_config_hash` + `run_config_summary`.
- [x] (2026-02-16) Implemented per-operation last-run settings persistence (`import` vs `benchmark`) with schema-evolution-safe loading and atomic writes.
- [x] (2026-02-16) Wired “Run Settings mode” picker into interactive Import and Benchmark upload flows (global / last / edit).
- [x] (2026-02-16) Implemented prompt_toolkit toggle-table editor driven by canonical settings metadata.
- [x] (2026-02-16) Ensured runConfig propagation for single-file stage, split-merge stage, prediction-run generation, benchmark CSV append paths, and dashboard ingestion.
- [x] (2026-02-16) Updated analytics CSV + dashboard schema/collector/renderer to surface run-config hash/summary consistently.
- [x] (2026-02-16) Added tests for run-settings model/store and updated report/dashboard/interactive benchmark tests.
- [x] (2026-02-16) Updated CLI, Label Studio, analytics, conventions, and understandings docs for new behavior and extension rules.

## Surprises & Discoveries

- Observation: Adding `run_config_hash`/`run_config_summary` required touching three independent analytics surfaces (CSV writer, collector schema, renderer) to keep the CSV-first contract intact.
  Evidence: `cookimport/analytics/perf_report.py`, `cookimport/analytics/dashboard_collect.py`, `cookimport/analytics/dashboard_schema.py`, `cookimport/analytics/dashboard_render.py`.

- Observation: Benchmark rows need manifest enrichment in both eval root and `prediction-run/` to reliably attach run config metadata and recipe counts.
  Evidence: `cookimport/analytics/dashboard_collect.py` manifest candidate probes and `cookimport/labelstudio/ingest.py` manifest fields.

- Observation: Backward compatibility for last-run settings benefits from accepting both wrapped payloads (`{"run_settings": {...}}`) and legacy flat payloads.
  Evidence: `cookimport/config/last_run_store.py` load path + `tests/test_run_settings.py::test_last_run_store_round_trip_and_corrupt_recovery`.

## Decision Log

- Decision: Use a single canonical typed settings model (`RunSettings`) as the source of truth for (1) UI rows, (2) per-run report `runConfig`, and (3) history/dashboard metadata.
  Rationale: This makes “add a new toggle” a single edit and automatically keeps UI + reporting in sync.
  Date/Author: 2026-02-16 / assistant

- Decision: Implement the toggle-table editor using `prompt_toolkit` (already an indirect dependency via Questionary), instead of adding a new TUI framework.
  Rationale: Minimizes new dependencies while still supporting full-screen UI + key bindings (↑/↓/←/→).
  Date/Author: 2026-02-16 / assistant

- Decision: Store “last run settings” separately from global defaults (don’t mutate global settings when running experiments).
  Rationale: Preserves the conceptual split the user wants: global defaults vs per-run overrides/snapshots.
  Date/Author: 2026-02-16 / assistant

- Decision: Record both `run_config_hash` (for grouping/filtering) and `run_config_summary` (for human scanning) in CSV rows, while keeping the full structured config in JSON reports/manifests.
  Rationale: CSV stays small and stable; JSON retains full fidelity for debugging and dashboard details.
  Date/Author: 2026-02-16 / assistant

- Decision: Keep run-settings metadata for optional/derived fields (`effective_workers`, mapping/overrides paths) in the canonical `RunSettings` model, but hide them from direct UI editing.
  Rationale: This keeps one serialized source of truth for report/analytics traceability while keeping the interactive editor focused on user-tunable knobs.
  Date/Author: 2026-02-16 / assistant

- Decision: Interactive benchmark eval-only mode should explicitly bypass run-settings selection and persistence.
  Rationale: Eval-only re-scoring does not run the extraction pipeline, so saving benchmark run settings from this path would be misleading.
  Date/Author: 2026-02-16 / assistant

## Outcomes & Retrospective

- Outcome: The project now has a canonical per-run settings stack (`RunSettings`, chooser, toggle editor, last-run store) used by interactive Import and benchmark upload without mutating global defaults.
- Outcome: Run settings traceability is end-to-end: conversion reports, benchmark manifests, `performance_history.csv`, and dashboard records now all carry hash + summary metadata.
- Outcome: Regression coverage now includes run-settings hashing/schema evolution, last-run persistence/recovery, report field presence, benchmark interactive routing, and dashboard ingestion/rendering of hash/summary.
- Remaining gap: `pytest -q` still reports unrelated fixture/path failures in importer tests (`tests/test_paprika_importer.py`, `tests/test_recipesage_importer.py`) in this environment; changed-area targeted suites pass.

## Context and Orientation

This project is a Python 3.12 CLI-first pipeline. It uses Typer for command wiring, Rich for console output, and Questionary for interactive prompts. EPUB/PDF ingestion uses a block-based pipeline; outputs include per-file conversion reports and a cross-run performance history CSV. The stats dashboard reads those artifacts and benchmark eval reports to render HTML/JS.

Relevant areas you will need to inspect in the repository (verify paths/filenames in the working tree; the list below reflects documented structure, but the repo is source of truth):

1. Interactive CLI wiring and global settings:
   - `cookimport/cli.py` (interactive mode callback, main menu, settings menu, import flow, benchmark flow)
   - the persistent global settings file `cookimport.json` (location and load/save functions live in code; find them)
2. Staging and report writing:
   - `cookimport/cli_worker.py` (stage worker orchestration)
   - `cookimport/staging/writer.py` (`write_report(...)` and where report fields are shaped)
   - `cookimport/core/models.py` (the `ConversionReport` schema, including any existing `runConfig` fields)
3. Analytics and history:
   - `cookimport/analytics/perf_report.py` (append/expand columns in `performance_history.csv`)
   - `cookimport/analytics/dashboard_collect.py` and `cookimport/analytics/dashboard_schema.py` (dashboard ingestion and runConfig surfaces)
4. Benchmark/pred-run generation:
   - `cookimport/labelstudio/ingest.py` (prediction run artifact generation)
   - `cookimport/bench/*` (offline bench runs, knob system, and where configs are recorded)

Definitions used in this plan:

- “Global settings”: persistent defaults saved in `cookimport.json` and edited via the interactive Settings menu. These define the default behavior when you don’t override anything for a run.
- “Run settings”: a snapshot of pipeline knobs used for one specific import/benchmark run. These may begin as a copy of global settings, but can be edited for that run without changing global defaults.
- “runConfig”: the serialized representation of run settings stored into reports/history/bench artifacts for traceability.
- “Toggle-table editor”: a full-screen terminal UI where each setting is a row; ↑/↓ changes the selected row, ←/→ changes the value, and Save writes the resulting RunSettings.

## Plan of Work

### Milestone 1: Canonical RunSettings model + serialization (foundation)

At the end of this milestone, you can build a `RunSettings` object, serialize it deterministically, compute a stable hash, and generate a concise summary string. You will also be able to load an older serialized config safely even if the schema has added fields.

Work:

1. Create a new module for the canonical per-run settings model. Suggested path:
   - `cookimport/config/run_settings.py` (or `cookimport/core/run_settings.py` if config folder doesn’t exist)
2. Define `RunSettings` as a Pydantic v2 model. It should include every knob that affects pipeline behavior and should be displayed in the run-settings editor, including (at minimum, based on current documented settings):
   - worker and split controls: `workers`, `pdf_split_workers`, `epub_split_workers`, `pdf_pages_per_job`, `epub_spine_items_per_job`
   - extraction knobs: `epub_extractor` (enum: `unstructured|legacy`)
   - OCR knobs: `ocr_device` (enum: `auto|cpu|cuda|mps`), `ocr_batch_size` (int)
   - warmup: `warm_models` (bool)
   - any other “run-level knobs” currently included in report `runConfig` (mapping, overrides paths, etc.)
3. For each field, add UI metadata in `Field(..., json_schema_extra={...})` that the editor can use, such as:
   - `ui_group` (string): e.g. “Workers”, “EPUB”, “PDF”, “OCR”, “Advanced”
   - `ui_label` (string): human readable label for row
   - optional: `ui_order` (int) for stable ordering
   - for int fields: `ui_step`, and ensure bounds exist via Pydantic constraints (`ge`, `le`)
4. Add methods on `RunSettings`:
   - `def to_run_config_dict(self) -> dict[str, object]`: returns JSON-serializable dict with stable keys.
   - `def summary(self) -> str`: returns something like:
     `epub_extractor=legacy | ocr_device=auto | ocr_batch_size=1 | workers=7 | pdf_split_workers=7 | ...`
     Keep it compact and stable. Consider showing only fields that differ from defaults *only if* you also provide a “full summary” for debugging.
   - `def stable_hash(self) -> str`: compute hash from canonical JSON (sorted keys, no whitespace). Use SHA-256 and shorten to e.g. 10–12 chars for display, but keep the full hash available if needed.
5. Implement “schema evolution” behavior:
   - Loading a dict with missing fields should fill defaults.
   - Loading a dict with unknown fields should not crash; it should warn once and ignore unknown keys.
   - This is important because “last run settings” might be from an older version.

Proof/acceptance for milestone 1:

- In a REPL or a small unit test, create a `RunSettings()`, call `summary()` and `stable_hash()`, and ensure the hash is stable across runs.
- Validate that `RunSettings.model_validate({...})` succeeds even if the input dict is missing newer fields.

### Milestone 2: Last-run settings store (per operation)

At the end of this milestone, the interactive CLI can load “last import run settings” and “last benchmark run settings” without scanning the entire output directory, and it can save new last-run settings after successful runs.

Work:

1. Add a small persistence module, suggested:
   - `cookimport/config/last_run_store.py`
2. Store files under the chosen output root’s history directory, for example:
   - `<output_dir>/.history/last_run_settings_import.json`
   - `<output_dir>/.history/last_run_settings_benchmark.json`
   Rationale: keeps per-run state near the run history and out of the global defaults file.
3. Implement:
   - `load_last_run_settings(kind: Literal["import","benchmark"], output_dir: Path) -> RunSettings | None`
   - `save_last_run_settings(kind: ..., output_dir: Path, settings: RunSettings) -> None`
4. Make write behavior safe:
   - write to a temp file then atomic rename (avoid partial/corrupt files on crash)
   - if JSON is corrupt, treat as missing and log a warning

Proof/acceptance:

- Create settings, save, load, compare equality.
- Corrupt the file manually and confirm load returns None + warning.

### Milestone 3: “Run Settings mode” picker wired into interactive Import and Benchmark flows

At the end of this milestone, the interactive CLI has the “1) global / 2) last / 3) change” chooser for Import and Benchmark. “Change” may temporarily use a simple per-setting prompt editor (not the full toggle-table yet). This milestone is intentionally a functional stepping stone.

Work:

1. In `cookimport/cli.py`, find the interactive Import flow handler (the function that currently prompts file selection, applies extractor env var, then calls `stage(...)`).
2. Before starting the import, prompt for run settings mode:
   - Choice A: “Run with global settings”
   - Choice B: “Run with last import settings: <summary>” (disable or replace with “(none found)” if missing)
   - Choice C: “Change run settings…”
3. Implement a helper function in a new UI module, suggested:
   - `cookimport/cli_ui/run_settings_flow.py`
   providing:
   - `choose_run_settings(kind, global_settings, output_dir) -> RunSettings`
4. For now (this milestone only), implement “Change run settings” as a sequence of Questionary prompts, one per field, to de-risk correctness before building the full-screen editor.
   - This can be quick: for enums use select; for bool use confirm; for int use text + validation.
5. When the final `RunSettings` is chosen, print a clear banner before starting work:
   - “Run settings: <full summary>”
6. After a successful import run, call `save_last_run_settings("import", ...)`.
7. Repeat the same insertion for the interactive Benchmark flow *only for branches that generate fresh predictions / run the pipeline*. For eval-only re-score flows, run settings do not affect results; instead:
   - show a short message “Eval-only mode: no pipeline run settings applied.”
   - do not overwrite “last benchmark run settings” unless a prediction run was generated.

Proof/acceptance:

- Run `cookimport` → Import → confirm you see the 3-option run settings picker.
- Pick “Change run settings”, change one value (e.g., EPUB extractor), run import, and see the run proceed.
- Re-run Import and confirm the “last settings” option appears with the correct summary.

### Milestone 4: Toggle-table editor (final UX)

At the end of this milestone, “Change run settings” opens a full-screen toggle-table editor with the key bindings the user described.

Work:

1. Add a new module, suggested:
   - `cookimport/cli_ui/toggle_editor.py`
2. Implement:
   - `edit_run_settings(*, title: str, initial: RunSettings) -> RunSettings | None`
   returning None on cancel, or the edited settings on save.
3. Use `prompt_toolkit` directly (do not fight Questionary’s higher-level abstractions). The editor should be driven entirely by `RunSettings.model_fields` and each field’s UI metadata.

Editor behavior contract:

- Layout:
  - Header: title + one-line help (“↑/↓ move, ←/→ change, Enter edit, S save, Q cancel”)
  - Body: rows (group headings + fields)
  - Footer: currently selected row description (from metadata) and current value
- Navigation:
  - Up/Down selects rows (skip group headings; they are non-interactive)
  - Left/Right changes value:
    - Enum: cycle through allowed values
    - Bool: toggle true/false
    - Int: decrement/increment by `ui_step` (default 1). Support Shift+Left/Right (or Ctrl+Left/Right) for bigger step (e.g., 5 or 10).
  - Enter:
    - For ints, open a small prompt to type an exact value, validate bounds, then update.
    - For strings/paths (if any), open a prompt to type/paste.
  - Save:
    - Press `s` or `S` to save and return the edited `RunSettings`.
  - Cancel:
    - Press `q`, `Q`, or `Esc` to cancel and return None.
- Deterministic ordering:
  - Sort by `ui_group` then `ui_order` then field name.
- Safety:
  - Always validate the final settings with Pydantic before returning; if invalid, show an error message in-editor and do not exit.

4. Replace the milestone-3 “sequential prompts editor” with this toggle editor.
5. Ensure this is used for both Import and Benchmark run settings editing.

Proof/acceptance:

- In interactive mode, choose Import → Change run settings → the full-screen editor opens.
- Use arrow keys to change at least:
  - `epub_extractor` (enum cycling)
  - `warm_models` (bool toggle)
  - `workers` (int inc/dec)
- Save and confirm the import uses the chosen settings.

### Milestone 5: Ensure runConfig is recorded everywhere the dashboard/bench cares about

At the end of this milestone, run settings appear in:
- conversion report JSON (`runConfig`, `runConfigHash`, `runConfigSummary`)
- performance_history.csv rows for stage/import and benchmark/eval
- any benchmark artifacts that the stats dashboard reads (especially prediction-run manifests)

Work:

1. Find where conversion reports are built (likely in staging/writer or reporting code). Ensure:
   - the report schema has fields:
     - `runConfig` (structured dict)
     - `runConfigHash` (string)
     - `runConfigSummary` (string)
   - both single-file and split-merge report paths populate them identically.
2. Update the stage/import path so it always constructs a `RunSettings` (even in non-interactive mode) from the effective CLI option values. This prevents reports from having missing runConfig when runs are executed without interactive mode.
   - If it is too invasive to change function signatures, implement a helper:
     - `build_run_settings_from_stage_args(...) -> RunSettings`
3. Update perf CSV append logic so these columns exist and are populated:
   - `run_config_hash`
   - `run_config_summary`
   Optionally also add:
   - `run_config_epub_extractor`, `run_config_ocr_device`, etc.
   but prefer not to explode columns unless the dashboard needs them. The stable approach is hash+summary in CSV, full config in JSON.
4. Ensure benchmark eval rows include a run_config reference. Preferred approach:
   - Eval rows should include the run_config_hash/summary of the *prediction run* they evaluated.
   - If eval-only, it should still carry the prediction run’s stored config so the dashboard can group by it.
5. Update the dashboard collector (if needed) to:
   - ingest these columns for stage rows
   - ingest run_config from benchmark eval artifacts
   - include run_config in the emitted dashboard data JSON so the UI can display it.

Proof/acceptance:

- Run one import interactively with a non-default setting.
- Confirm `<run_root>/<slug>.excel_import_report.json` contains runConfig fields.
- Confirm a new row exists in `data/output/.history/performance_history.csv` with run_config_hash and run_config_summary.
- Generate dashboard and confirm the run’s config is visible in the dashboard UI or in the dashboard JSON artifact.

### Milestone 6: Guardrails (tests + “how to add a new setting”)

At the end of this milestone, it should be hard to accidentally add a new knob without it showing up in UI + reporting.

Work:

1. Add unit tests, suggested:
   - `tests/test_run_settings.py`
     - verifies `RunSettings.summary()` and `.stable_hash()` stability
     - verifies schema evolution: unknown keys ignored, missing keys defaulted
     - verifies every field has required UI metadata keys (`ui_group`, `ui_label`, `ui_order` or default)
2. Add an integration-ish test for report population:
   - either: a small “fake report build” unit test that calls the report builder with a RunSettings and asserts fields are written
   - or: run a minimal stage path on a tiny fixture and assert the produced report contains runConfig (if there are already fixture-based stage tests)
3. Add a short developer doc section:
   - where: `docs/02-cli/...` or a new `docs/` note
   - content:
     - “To add a new toggle: add a field to RunSettings with UI metadata; ensure pipeline reads it; tests will fail if metadata missing.”

Proof/acceptance:

- Run `pytest -q` and ensure all tests pass.
- Intentionally remove UI metadata from one field and confirm the new test fails (then revert).

## Concrete Steps

These steps are written so a novice can run them in order while implementing. Adjust commands to the repo’s actual tooling once you confirm it.

1. From repo root, locate current interactive settings + report wiring:

    rg -n "cookimport.json" cookimport
    rg -n "runConfig" cookimport
    rg -n "write_report" cookimport
    rg -n "performance_history.csv" cookimport
    rg -n "stats-dashboard" cookimport

2. Run tests to establish baseline:

    pytest -q

3. Implement milestone 1, then re-run targeted tests:

    pytest -q tests/test_run_settings.py

4. After wiring interactive flows, do a manual interactive run:

    cookimport
    (choose Import → Change run settings → adjust epub_extractor → Save → run one file)

5. Generate dashboard to confirm surfacing:

    cookimport stats-dashboard
    (open output_dir/.history/dashboard/index.html)

## Validation and Acceptance

This work is accepted when the following behaviors are demonstrably true:

1. Interactive run settings flow:
   - Running `cookimport` and selecting Import shows a 3-option run settings mode picker.
   - Selecting “Run with last import settings …” uses the last settings and prints the exact summary before starting.
   - Selecting “Change run settings…” opens a full-screen toggle-table editor.
   - Arrow keys work as described: ↑/↓ moves rows; ←/→ changes values; Save commits and starts the run; Cancel returns without changing anything.

2. Recording and traceability:
   - Every import run writes `runConfig`, `runConfigHash`, and `runConfigSummary` into each per-file report JSON for that run.
   - `performance_history.csv` appends rows that include `run_config_hash` and `run_config_summary`.
   - Benchmark/eval artifacts that appear in the dashboard include the prediction run’s config metadata so you can compare benchmark results across different pipeline configs.

3. Extensibility guarantee:
   - Adding a new field to `RunSettings` with UI metadata automatically makes it appear in the toggle-table editor (no extra UI wiring).
   - Tests fail if the developer adds a new setting field but forgets required UI metadata.

## Idempotence and Recovery

- The run settings editor should not mutate global defaults unless explicitly invoked in the global Settings menu. Per-run edits should be applied only to the in-memory RunSettings for that run.
- “Last run settings” files are safe to overwrite; writes should be atomic (temp + rename). If the file becomes corrupt, loading should degrade gracefully (warn and treat as missing).
- Adding new fields to RunSettings must not break older stored last-run configs; missing fields default, unknown keys ignored.

## Artifacts and Notes

Example `runConfig` payload shape to aim for in reports:

    {
      "epub_extractor": "legacy",
      "ocr_device": "auto",
      "ocr_batch_size": 1,
      "workers": 7,
      "pdf_split_workers": 7,
      "epub_split_workers": 7,
      "pdf_pages_per_job": 50,
      "epub_spine_items_per_job": 10,
      "warm_models": false
    }

Example summary string:

    epub_extractor=legacy | ocr_device=auto | ocr_batch_size=1 | workers=7 | pdf_split_workers=7 | epub_split_workers=7

Keep the summary stable and avoid including ephemeral paths unless those paths materially change outcomes (mapping/overrides might be included but can be abbreviated).

Validation evidence captured during implementation:

    . .venv/bin/activate && pytest -q tests/test_run_settings.py tests/test_cli_output_structure.py tests/test_labelstudio_benchmark_helpers.py tests/test_labelstudio_ingest_parallel.py tests/test_stats_dashboard.py
    # 77 passed

    . .venv/bin/activate && pytest -q tests/test_bench.py tests/test_benchmark_csv_backfill_cli.py tests/test_performance_features.py tests/test_c3imp_interactive_menu.py
    # 36 passed

Known unrelated full-suite failures in current environment:

    . .venv/bin/activate && pytest -q
    # failures in tests/test_paprika_importer.py and tests/test_recipesage_importer.py due to missing docs/template/examples fixtures

## Interfaces and Dependencies

Dependencies:

- Use existing installed dependencies:
  - Pydantic v2 for typed settings and validation.
  - prompt_toolkit (already present via Questionary) for the full-screen toggle editor.
  - Typer + Questionary for menu selects and overall interactive flow.

Required interfaces to exist at end of plan:

In `cookimport/config/run_settings.py`, define:

    class RunSettings(BaseModel):
        ...
        def summary(self) -> str: ...
        def stable_hash(self) -> str: ...
        def to_run_config_dict(self) -> dict[str, object]: ...

In `cookimport/config/last_run_store.py`, define:

    def load_last_run_settings(kind: Literal["import","benchmark"], output_dir: Path) -> RunSettings | None: ...
    def save_last_run_settings(kind: Literal["import","benchmark"], output_dir: Path, settings: RunSettings) -> None: ...

In `cookimport/cli_ui/toggle_editor.py`, define:

    def edit_run_settings(*, title: str, initial: RunSettings) -> RunSettings | None: ...

In `cookimport/cli_ui/run_settings_flow.py`, define:

    def choose_run_settings(*, kind: Literal["import","benchmark"], global_defaults: RunSettings, output_dir: Path) -> RunSettings | None: ...

In report writing code (where ConversionReport is built), ensure fields exist and are always populated:

    report.runConfig: dict[str, object]
    report.runConfigHash: str
    report.runConfigSummary: str

At the analytics layer that appends to `performance_history.csv`, ensure columns exist and are populated:

    run_config_hash
    run_config_summary

Plan revision note (2026-02-16): Initial version authored to introduce a canonical RunSettings model, a prompt_toolkit toggle editor, and end-to-end runConfig persistence into reports/CSV/dashboard.
Plan revision note (2026-02-16_12.09.36): Marked all milestones complete, added implementation discoveries/evidence, and documented shipped outcomes plus known unrelated full-suite failures so the plan now reflects deployed behavior.
