---
summary: "ExecPlan and implementation record for unifying stage/benchmark semantics with shared run manifests, clearer CLI wording, and parity safeguards."
read_when:
  - When changing run-manifest schema or writers across stage/labelstudio/bench flows
  - When changing labelstudio-benchmark upload/offline behavior or freeform eval wiring
  - When debugging stage-vs-benchmark parity or analytics history-root/timestamp resolution
---

# Unify Stage vs Benchmark Semantics

This ExecPlan is a living document. The sections `Progress`, `Surprises & Discoveries`, `Decision Log`, and `Outcomes & Retrospective` are maintained as implementation progressed.

This document is maintained in accordance with `docs/PLANS.md`.

## Purpose / Big Picture

Before this work, the system behavior was mostly correct but hard to reason about: users saw "import", "benchmark import/export", and "benchmark" language that mixed distinct jobs (cookbook staging, Label Studio task creation, label export, and evaluation). That ambiguity made it harder to trust iteration loops and to understand where artifacts came from.

After this work, every run-producing flow writes a compact `run_manifest.json` that links source identity, effective run settings, and key artifacts. `labelstudio-benchmark` now has a first-class offline mode (`--no-upload`) so users can evaluate without Label Studio credentials or API calls. Interactive and help text now emphasizes "create labeling tasks", "export completed labels", and "evaluate predictions vs freeform gold". A parity test now guards stage-vs-prediction alignment at the right layer (source identity, coordinate system, and config snapshot).

You can see the behavior by running `cookimport stage`, `cookimport labelstudio-benchmark --no-upload`, and `cookimport labelstudio-eval ...` and inspecting `run_manifest.json` in each run root.

## Progress

- [x] (2026-02-16_12.18.00) Added run-manifest model/writer/loader in `cookimport/runs/manifest.py` with atomic write semantics.
- [x] (2026-02-16_12.20.00) Integrated manifest writing into stage/import/export/eval/benchmark/bench-run flows.
- [x] (2026-02-16_12.22.00) Added explicit non-interactive offline benchmark path via `cookimport labelstudio-benchmark --no-upload`.
- [x] (2026-02-16_12.24.00) Updated interactive menu labels and command help text to match task-vs-gold-vs-eval mental model without breaking command names.
- [x] (2026-02-16_12.27.00) Added parity regression coverage (`tests/test_run_manifest_parity.py`) and resolver coverage (`tests/test_perf_report.py`).
- [x] (2026-02-16_12.31.00) Fixed analytics trust gaps: perf-report run-dir timestamp detection and stage history CSV root alignment with `--out`.
- [x] (2026-02-16_12.36.19) Updated docs (`docs/02-cli/02-cli_README.md`, `docs/06-label-studio/06-label-studio_README.md`, `docs/07-bench/07-bench_README.md`, `docs/08-analytics/08-analytics_readme.md`) and conventions/understandings.

## Surprises & Discoveries

- Observation: Stage history rows were still appended to default output history even when `stage --out <custom_root>` was used.
  Evidence: `tests/test_cli_output_structure.py` needed new assertions for `<custom_root>/.history/performance_history.csv`; behavior was corrected in `cookimport/cli.py`.

- Observation: `perf-report` latest-run auto-discovery only matched legacy timestamp folder style.
  Evidence: Added failing-then-passing resolver tests in `tests/test_perf_report.py` for both `YYYY-MM-DD_HH.MM.SS` and `YYYY-MM-DD-HH-MM-SS`.

- Observation: Benchmark contract confusion came from naming, not from a core scoring bug.
  Evidence: Prediction scoring already used consistent task/gold span coordinate surfaces; adding manifest linkage + explicit offline mode resolved most ambiguity without replacing scoring logic.

- Observation: Full suite includes unrelated fixture failures outside this plan scope.
  Evidence: `pytest -q` ended with 5 failures in paprika/recipesage importer tests tied to missing example fixtures; focused modified-area suite passed.

## Decision Log

- Decision: Treat stage outputs and benchmark prediction artifacts as different products linked by manifest, not as identical files.
  Rationale: Stage produces cookbook objects; benchmark scores span/block coordinates. Correct parity layer is source/config/coordinates.
  Date/Author: 2026-02-16 / Codex

- Decision: Keep existing command names (`labelstudio-import`, `labelstudio-export`, `labelstudio-benchmark`, `labelstudio-eval`) and fix wording/help instead of renaming commands.
  Rationale: Reduces user confusion immediately while preserving script compatibility.
  Date/Author: 2026-02-16 / Codex

- Decision: Implement offline benchmark as `--no-upload` on `labelstudio-benchmark`.
  Rationale: Minimal diff, direct user affordance, and reuses existing pred-run + eval path with explicit side-effect control.
  Date/Author: 2026-02-16 / Codex

- Decision: Make manifest writing best-effort (warn on failure) rather than hard-failing successful run outputs.
  Rationale: Manifest is traceability metadata; artifact production should remain primary.
  Date/Author: 2026-02-16 / Codex

- Decision: Fix analytics mismatches as part of this plan.
  Rationale: Without these fixes, dashboards/perf-report could show misleading state during iteration even when benchmark semantics were corrected.
  Date/Author: 2026-02-16 / Codex

## Outcomes & Retrospective

Primary goal achieved. The system now clearly separates:

- staging cookbook outputs,
- creating Label Studio tasks,
- exporting completed labels,
- evaluating predictions against gold.

Run traceability is now uniform through `run_manifest.json` across stage, Label Studio flows, and bench suite outputs. Users can run an explicit offline benchmark (`--no-upload`) in non-interactive mode with no Label Studio credentials. Analytics now aligns with real run roots and real timestamp formats.

What remains outside this plan:

- unrelated full-suite fixture gaps in paprika/recipesage tests,
- future UX cleanups (for example, optional command aliases) that were intentionally deferred to keep compatibility and minimize scope.

## Context and Orientation

Relevant modules:

- `cookimport/runs/manifest.py`: manifest model and read/write helpers.
- `cookimport/cli.py`: stage, labelstudio-* command wiring, interactive menu text, history append behavior.
- `cookimport/labelstudio/ingest.py`: prediction-run generation, import/upload flow, ingest-side manifest writing.
- `cookimport/labelstudio/export.py`: export flow and export manifest writing.
- `cookimport/bench/pred_run.py`: offline pred-run manifest integration.
- `cookimport/bench/runner.py`: per-item and suite-level bench run manifests.
- `cookimport/analytics/perf_report.py`: latest-run directory resolver and CSV append contracts.

Key artifact surfaces after implementation:

- Stage run root: `<out>/<timestamp>/...` plus `<run_root>/run_manifest.json`.
- Label Studio import run root: `<gold_root>/<timestamp>/labelstudio/<slug>/...` plus `<run_root>/run_manifest.json`.
- Label Studio export root: `<gold_root>/<project_slug>/exports/...` plus `<project_root>/run_manifest.json`.
- Eval output root: `<eval_output_dir>/...` plus `<eval_output_dir>/run_manifest.json`.
- Bench run root: `<bench_runs>/<timestamp>/...` with suite-level and per-item manifests.

## Plan of Work (Implemented)

### Milestone 1: Shared run-manifest model and writers

Implemented `RunSource` and `RunManifest` in `cookimport/runs/manifest.py` with atomic writes (`run_manifest.json.tmp` then replace). Added `load_run_manifest` for tests/tooling. Added package exports in `cookimport/runs/__init__.py` and a short folder note in `cookimport/runs/README.md`.

### Milestone 2: First-class offline benchmark mode

Extended `labelstudio-benchmark` with `--no-upload` in `cookimport/cli.py`.

- upload mode: requires `--allow-labelstudio-write` and Label Studio credentials.
- offline mode: uses `generate_pred_run_artifacts(...)` directly, skips credential resolution, and makes no upload/API calls.

### Milestone 3: Naming clarity without breaking compatibility

Updated interactive menu labels and help text in `cookimport/cli.py` to describe actions as task creation, label export, and evaluation. Command names and existing non-interactive scripts remain valid.

### Milestone 4: Stage-vs-benchmark parity guardrails

Added `tests/test_run_manifest_parity.py` to assert:

- source hash parity between stage and pred-run artifacts,
- shared key run-config fields,
- coordinate bounds parity from staged raw archive vs generated prediction task locations.

### Milestone 5: Analytics trust fixes

Implemented:

- dual timestamp parser in `cookimport/analytics/perf_report.py` for both modern and legacy run-folder formats,
- stage history append root fix in `cookimport/cli.py` so history follows actual `--out` root,
- benchmark/eval CSV append root alignment improvements when output roots are inferred.

### Milestone 6: Documentation and conventions sync

Updated:

- `docs/02-cli/02-cli_README.md`
- `docs/06-label-studio/06-label-studio_README.md`
- `docs/07-bench/07-bench_README.md`
- `docs/08-analytics/08-analytics_readme.md`
- `IMPORTANT CONVENTIONS.md`
- `docs/understandings/2026-02-16_12.30.45-run-manifest-semantics-and-history-root.md`

## Concrete Steps

Commands used for implementation/validation (run from repository root):

    source .venv/bin/activate
    pytest -q tests/test_cli_output_structure.py tests/test_performance_features.py tests/test_perf_report.py tests/test_labelstudio_benchmark_helpers.py tests/test_labelstudio_freeform.py tests/test_bench.py tests/test_run_manifest_parity.py

Observed result:

    80 passed

Broader suite check:

    source .venv/bin/activate
    pytest -q

Observed result:

    5 failed, 372 passed

Failure scope was outside this plan (missing fixture inputs in paprika/recipesage importer tests).

## Validation and Acceptance

Use these checks to confirm behavior end-to-end:

1. Stage manifest + custom output-root history alignment.

    source .venv/bin/activate
    rm -rf /tmp/cookimport_out
    cookimport stage data/input/<small-fixture> --out /tmp/cookimport_out

Expected:

- `/tmp/cookimport_out/<timestamp>/run_manifest.json` exists.
- `/tmp/cookimport_out/.history/performance_history.csv` exists.

2. Offline benchmark without upload.

    source .venv/bin/activate
    rm -rf /tmp/cookimport_eval
    cookimport labelstudio-benchmark --gold-spans <freeform_span_labels.jsonl> --source-file <matching source> --no-upload --eval-output-dir /tmp/cookimport_eval

Expected:

- No Label Studio credential requirement.
- `/tmp/cookimport_eval/eval_report.json` and `eval_report.md` exist.
- `/tmp/cookimport_eval/run_manifest.json` links pred-run and gold paths.

3. Perf-report latest-run detection with modern timestamp folders.

    source .venv/bin/activate
    cookimport perf-report --out-dir /tmp/cookimport_out

Expected:

- Resolver finds latest run without `--run-dir`.
- Summary path and history writes align to `/tmp/cookimport_out`.

## Idempotence and Recovery

- Manifest writes are idempotent per run root: re-running overwrites `run_manifest.json` atomically.
- Offline benchmark mode (`--no-upload`) is safe to repeat because it does not modify Label Studio state.
- Upload mode remains guarded by explicit consent (`--allow-labelstudio-write`) to reduce accidental side effects.
- If a manifest write fails, command behavior remains best-effort: run artifacts still exist, and warning output identifies the manifest write issue.

## Interfaces and Dependencies

Stable internal interfaces introduced/standardized:

- `cookimport.runs.manifest.RunSource`
- `cookimport.runs.manifest.RunManifest`
- `cookimport.runs.manifest.write_run_manifest(run_root: Path, manifest: RunManifest) -> Path`
- `cookimport.runs.manifest.load_run_manifest(path: Path) -> RunManifest`

Manifest contract is intentionally small:

- `schema_version`, `run_kind`, `run_id`, `created_at`
- `source` (`path`, `source_hash`, optional importer)
- `run_config` (effective knobs)
- `artifacts` (semantic artifact-path map)
- optional `notes`

No new third-party dependencies were introduced.

## Plan Revision Notes

- 2026-02-16_12.36.19: Converted initial design-first draft into an implementation-complete ExecPlan record, added front matter, synced progress/discoveries/decisions/outcomes, and documented command/test evidence so a new contributor can verify current behavior without external context.
