---
summary: "Code-verified architecture source of truth for current runtime contracts and module boundaries."
read_when:
  - When you need end-to-end pipeline architecture and module boundaries
  - When changing output roots, timestamp formats, IDs, split-job behavior, or Label Studio flows
  - When updating command entrypoints, plugin interfaces, or stage output contracts
---

# Architecture Readme

This is the source of truth for current architecture behavior under `docs/01-architecture`.
For architecture versions, build/fix-attempt history, and anti-loop notes, read `docs/01-architecture/01-architecture_log.md`.

Code verification references:
- `pyproject.toml`
- `cookimport/cli.py`
- `cookimport/cli_worker.py`
- `cookimport/paths.py`
- `cookimport/runs/manifest.py`
- `cookimport/staging/import_session.py`
- `cookimport/staging/writer.py`
- `cookimport/staging/pdf_jobs.py`
- `cookimport/labelstudio/ingest.py`
- `cookimport/labelstudio/export.py`
- `cookimport/plugins/base.py`
- `cookimport/plugins/registry.py`
- `cookimport/core/reporting.py`
- `cookimport/entrypoint.py`
- `cookimport/c3imp_entrypoint.py`

## What This Project Is

`cookimport` is a deterministic recipe-import pipeline with optional Label Studio integration for task generation and evaluation.

Architecture priorities:
- deterministic outputs first (no mandatory LLM path)
- stable file/folder conventions for artifacts
- split-job support for large PDF/EPUB inputs
- reproducible provenance and IDs across reruns/merges
- side-by-side support for processing output (`data/output`) and annotation/benchmark output (`data/golden`)

## Runtime Architecture (current code)

### Phase 1: Source conversion
- importers implement `detect`, `inspect`, `convert` via `Importer` protocol (`cookimport/plugins/base.py`).
- `ImporterRegistry.best_for_path()` picks the highest `detect` score (`cookimport/plugins/registry.py`).
- conversion produces `ConversionResult` with recipes/tips/topics/non-recipe blocks/raw artifacts/report fields.

### Phase 2: Output shaping and writing
- for stage runs, `cookimport/cli.py` orchestrates parallel jobs and final merge for split inputs.
- worker-side split execution lives in `cookimport/cli_worker.py`.
- output-writing primitives live in `cookimport/staging/writer.py`.
- split merge helpers and recipe-ID reassignment logic live in `cookimport/staging/pdf_jobs.py`.
- stage import session now builds the label-first authority seam before drafting: `label_det`, optional `label_llm_correct`, and `group_recipe_spans` artifacts are written under the stage run root and drive downstream stage block predictions.
- if label-first regrouping yields zero recipes after importer candidates existed, the stage session stays on the authoritative label-first result and writes `group_recipe_spans/<workbook_slug>/authority_mismatch.json` instead of silently reverting to candidate-first ownership.
- Stage 7 non-recipe rows now drive table extraction, chunking, and stage-backed Label Studio knowledge counts; `ConversionResult.non_recipe_blocks` is repopulated only afterward as a compatibility cache.

### Optional Label Studio lane
- `cookimport/labelstudio/ingest.py` can:
  - run conversion (including split jobs for PDF/EPUB)
  - reuse the shared stage import session for processed outputs in benchmark/prediction flows
  - generate tasks for `freeform-spans` (segment-based freeform labeling tasks)
  - write run artifacts (`manifest.json`, tasks JSONL, coverage, extracted archive/text)
  - upload tasks when write consent is explicit
  - perform merge-time block-index rebasing across split jobs
  - treat processed `stage_block_predictions.json` as the primary benchmark scoring input, with freeform projection artifacts derived from the same authoritative label-first bundle instead of a second diagnostic rerun

### Current authority boundaries

- label-first grouped spans and normalized block labels are the recipe/non-recipe authority boundary for stage-backed flows.
- Stage 7 owns outside-recipe classification (`knowledge` vs `other`) for runtime decisions and benchmark evidence.
- scalar confidence is persisted with labeled rows and compatibility recipe metadata, but grouping and Stage 7 ownership do not use it as authority.
- low-confidence deterministic line-role cases may still escalate to Codex in `cookimport/parsing/canonical_line_roles.py`; that is an escalation seam, not the main runtime truth boundary.
- `decided_by` and `reason_tags` are the persisted decision-trace fields on current labeled rows.
- authoritative line/block/span artifacts now also persist `trust_score`, `escalation_score`, and `escalation_reasons`; compatibility `confidence` on those seams is a trust alias for older readers.

### Current recipe LLM contract

- the canonical public recipe pipeline id is `codex-farm-single-correction-v1`.
- the active recipe Codex path is one correction stage that updates an intermediate `RecipeCandidate`, returns `ingredient_step_mapping`, and rebuilds final cookbook drafts locally.
- current semantic recipe-stage observability for new runs uses:
  - `build_intermediate_det`
  - `recipe_llm_correct_and_link`
  - `build_final_recipe`

### Known current debt

- historical benchmark/follow-up compatibility reads should stay narrow (`pass4_knowledge_manifest.json`, archived prompt-task sample paths), but new outputs and reviewer-facing summaries should stay on semantic stage rows plus current manifests/audits.

## Docs Ownership Map

Use this mapping when updating architecture-adjacent docs so current contracts stay with the owning section:

- `cookimport/cli.py` and entrypoint wrappers -> `docs/02-cli/`
- importer registry/plugins + split-job planning/merge -> `docs/03-ingestion/`
- ingredient/instruction/step-link/tip/chunk logic -> `docs/04-parsing/`
- draft conversion + writers + output contracts -> `docs/05-staging/`
- Label Studio import/export/eval/benchmark workflows -> `docs/06-label-studio/`
- offline benchmark suite loops -> `docs/07-bench/`
- perf report + dashboard + metrics history surfaces -> `docs/08-analytics/`
- auto-tagging rules and commands -> `docs/09-tagging/`
- schemas/inventories/reference artifacts -> `docs/11-reference/`

Reason this exists:
- New work should start from the relevant stage folder README, not from ad-hoc discovery-note folders.

## Command Topology and Entrypoints

Primary entrypoints (`pyproject.toml`):
- `cookimport = cookimport.cli:app`
- `import = cookimport.entrypoint:main`
- `C3import = cookimport.entrypoint:main`
- `C3imp = cookimport.c3imp_entrypoint:main`

Behavior:
- `cookimport` with no subcommand starts interactive mode (`@app.callback`, `cookimport/cli.py`).
- interactive mode includes one-level back navigation via `Esc` key binding (`cookimport/cli.py`) across select and text/confirm/password prompts.
- `import`/`C3import` wrappers call stage-on-default-input shortcuts when invoked without normal subcommands (`cookimport/entrypoint.py`).
- `C3imp` wrapper optionally sets `C3IMP_LIMIT` before entering interactive mode (`cookimport/c3imp_entrypoint.py`).

## Canonical Defaults and Paths

Defaults in `cookimport/cli.py`:
- `DEFAULT_INPUT = data/input`
- `DEFAULT_OUTPUT = data/output`
- `DEFAULT_GOLDEN = data/golden`
- `DEFAULT_GOLDEN_SENT_TO_LABELSTUDIO = data/golden/sent-to-labelstudio`
- `DEFAULT_GOLDEN_PULLED_FROM_LABELSTUDIO = data/golden/pulled-from-labelstudio`
- `DEFAULT_GOLDEN_BENCHMARK = data/golden/benchmark-vs-golden`
- `DEFAULT_HISTORY = .history`
- `DEFAULT_BENCH_SUITES = data/golden/bench/suites`
- `DEFAULT_BENCH_RUNS = data/golden/bench/runs`
- `DEFAULT_BENCH_SPEED_ROOT = data/golden/bench/speed`
- `DEFAULT_BENCH_SPEED_SUITES = data/golden/bench/speed/suites`
- `DEFAULT_BENCH_SPEED_RUNS = data/golden/bench/speed/runs`
- `DEFAULT_BENCH_SPEED_COMPARISONS = data/golden/bench/speed/comparisons`

Command defaults:
- `stage --out` default: `data/output`
- `inspect --out` default: `data/output`
- `labelstudio-import --output-dir` default: `data/golden/sent-to-labelstudio`
- `labelstudio-export --output-dir` default: `data/golden/pulled-from-labelstudio`
- `labelstudio-benchmark --output-dir` default: `data/golden/benchmark-vs-golden`
- `labelstudio-benchmark --processed-output-dir` default: `data/output`
- `stats-dashboard --out-dir` default: `.history/dashboard`

Interactive defaults:
- settings `output_dir` defaults to `data/output` and drives interactive stage target.
- interactive Label Studio import/export/benchmark paths resolve to workflow-specific golden roots under `DEFAULT_GOLDEN`.

## Timestamp Convention (critical)

Current canonical run-folder timestamp format:
- `YYYY-MM-DD_HH.MM.SS`
- implemented via `strftime("%Y-%m-%d_%H.%M.%S")`

Verified call sites:
- stage run root (`cookimport/cli.py`)
- Label Studio prediction/import run root (`cookimport/labelstudio/ingest.py`)
- benchmark eval default output (`cookimport/cli.py`)

## Stage Output Contract

For `cookimport stage`, each run uses a timestamped root:

- `<out>/<timestamp>/stage_observability.json`
- `<out>/<timestamp>/intermediate drafts/<workbook_slug>/r{index}.jsonld`
- `<out>/<timestamp>/final drafts/<workbook_slug>/r{index}.json`
- `<out>/<timestamp>/sections/<workbook_slug>/r{index}.sections.json` (+ `sections.md` when `--write-markdown`)
- `<out>/<timestamp>/tips/<workbook_slug>/t{index}.json`
- `<out>/<timestamp>/tips/<workbook_slug>/tips.md`
- `<out>/<timestamp>/tips/<workbook_slug>/topic_candidates.json` (+ `topic_candidates.md` when topic candidates exist and `--write-markdown`)
- `<out>/<timestamp>/chunks/<workbook_slug>/c{index}.json` (+ `chunks.md` when chunks exist and `--write-markdown`)
- `<out>/<timestamp>/tables/<workbook_slug>/tables.jsonl` (+ `tables.md` when `--table-extraction on` and `--write-markdown`)
- `<out>/<timestamp>/.bench/<workbook_slug>/stage_block_predictions.json`
- `<out>/<timestamp>/raw/<importer>/<source_hash>/<location_id>.<ext>`
- `<out>/<timestamp>/<workbook_slug>.excel_import_report.json`
- `<out>/<timestamp>/run_manifest.json`

Optional stage lanes:
- `<out>/<timestamp>/label_det/<workbook_slug>/...` for deterministic authoritative labeled-line and block-label artifacts
- `<out>/<timestamp>/label_llm_correct/<workbook_slug>/...` for final corrected authoritative labels plus label diffs when line-role correction is enabled
- `<out>/<timestamp>/group_recipe_spans/<workbook_slug>/...` for deterministic recipe-span grouping and normalized authoritative block-label outputs
- `<out>/<timestamp>/knowledge/<workbook_slug>/...` and `<out>/<timestamp>/knowledge/knowledge_index.json` when knowledge-pass artifacts exist
- `<out>/<timestamp>/tags/<workbook_slug>/...` and `<out>/<timestamp>/tags/tags_index.json` when tags-pass artifacts exist

Important clarification:
- report file is written at run root, not in a stage `reports/` subfolder.

References:
- writers and paths: `cookimport/staging/writer.py`
- stage orchestration: `cookimport/cli.py`, `cookimport/cli_worker.py`
- run-manifest schema/write: `cookimport/runs/manifest.py`

## ID and Provenance Rules

Stage recipe/tip/topic IDs use the `urn:recipeimport:*` namespace.

Examples from current code:
- recipe IDs via helper: `urn:recipeimport:{source_type}:{source_hash}:{location_id}`
- writer-generated fallback recipe IDs for Excel-like flow: `urn:recipeimport:excel:{file_hash}:{sheet_slug}:r{row_index}`
- tip/topic IDs similarly use `urn:recipeimport:tip:*` and `urn:recipeimport:topic:*`
- Label Studio freeform-span export IDs still use `urn:cookimport:freeform_span:*` (legacy scope-local identifier format).

References:
- ID helper: `cookimport/core/reporting.py`
- writer ID assignment: `cookimport/staging/writer.py`
- freeform span export IDs: `cookimport/labelstudio/export.py`

## Split-Job Architecture

Stage split jobs (`cookimport stage`):
- planning uses page ranges for PDF and spine ranges for EPUB
- each worker parses a subset
- split workers write temporary raw artifacts to:
  - `<out>/<timestamp>/.job_parts/<workbook_slug>/job_<index>/raw/...`
- split merge rebuilds merged `full_text.json` blocks under `<out>/<timestamp>/raw/<importer>/<source_hash>/full_text.json` when per-job full-text blocks exist
- merge step combines logical results, reassigns recipe IDs globally, writes final outputs once, then merges raw files into `<out>/<timestamp>/raw/...`
- `.job_parts` is cleaned after successful merge

Label Studio split jobs (`run_labelstudio_import`):
- similar parallel conversion split is used when configured
- merge rebases block-index-like fields (`start_block`, `end_block`, `block_index`, related variants) by cumulative prior job block counts
- this is critical so canonical/freeform tasks and evals share one global block coordinate space

References:
- stage planning/merge/raw merge: `cookimport/cli.py`, `cookimport/cli_worker.py`, `cookimport/staging/pdf_jobs.py`
- labelstudio offset/rebase merge: `cookimport/labelstudio/ingest.py`

## Label Studio Artifact Contract

`labelstudio-import` / `generate_pred_run_artifacts` run root:
- `<output_dir>/<timestamp>/labelstudio/<book_slug>/`

Core artifacts:
- `extracted_archive.json`
- `extracted_text.txt`
- `coverage.json`
- `manifest.json`
- `run_manifest.json`
- `label_studio_tasks.jsonl` (optional in offline prediction runs when `--no-write-labelstudio-tasks`; required in upload mode)
- `project.json` (upload/import mode only)
- `stage_block_predictions.json` (present when copied from processed stage output)
- `prelabel_report.json`, `prelabel_errors.jsonl`, `prelabel_prompt_log.md` (when prelabeling is enabled)

Behavioral constraints:
- write operations are gated (`--allow-labelstudio-write` required in non-interactive commands)
- prediction-run generation (`generate_pred_run_artifacts`) is first-class offline behavior and does not require Label Studio credentials
- benchmark command (`labelstudio-benchmark`) is prediction-first by default; in CLI mode it uploads by default unless `--no-upload`
- benchmark can run evaluate-only with `--predictions-in`
- benchmark co-locates prediction run under eval output as `prediction-run/`
- benchmark prediction-generation scratch is rooted under the resolved benchmark eval directory so one benchmark session does not create extra sibling timestamp roots under `data/golden/benchmark-vs-golden`
- benchmark processed outputs are stage-backed; `prediction-run/` is the task/manifest shell around those shared artifacts, not a second primary shaping pipeline

## Scripts Folder Note

- `scripts/` is currently used for repo-local helpers only:
  - test/dev wrappers,
  - benchmark/export packaging utilities,
  - narrow replay/smoke diagnostics.
- Remove unrelated stack helpers instead of letting `scripts/` become a junk drawer. The documented standard is to keep only tools that map to real recipeimport workflows or explicit migration/debug guardrails.

References:
- commands + guards + benchmark flow: `cookimport/cli.py`
- import/task generation/upload artifacts: `cookimport/labelstudio/ingest.py`
- export run manifest wiring: `cookimport/labelstudio/export.py`

## Run Manifest And History Root Contract

`run_manifest.json` is the cross-command traceability join point for run roots generated by:
- `stage`
- `generate_pred_run_artifacts` (`run_kind=bench_pred_run` by default)
- `labelstudio-import`
- `labelstudio-export`
- `labelstudio-eval`
- `labelstudio-benchmark`

Current non-emitter clarification:
- `cookimport bench speed-run` writes `run_manifest.json`.
- Other `cookimport bench ...` flows currently write benchmark artifacts/telemetry without `run_manifest.json`.

Manifest responsibilities:
- source identity (`path`, `source_hash`)
- effective run config snapshot/hash/summary
- key artifact pointers needed to trace stage/prediction/eval relationships without reading internals
- semantic stage observability (`cookimport/runs/stage_observability.py`) is the shared run-level source for stage naming; do not infer current stage meaning only from raw LLM directory names or old pass-slot labels

History-root rule:
- for repo-local outputs (default `data/output`), stage/benchmark history writes append to `<repo>/.history/performance_history.csv`
- for external output roots (for example `/tmp/out`), history writes append to `<output_root parent>/.history/performance_history.csv`

Path helper rule:
- canonical helper is `history_csv_for_output(output_root)` in `cookimport/paths.py`; `cookimport.analytics.perf_report.history_path(...)` delegates to that helper.

Timestamp compatibility rule:
- tooling that resolves latest runs must support both timestamp folder styles:
  - `YYYY-MM-DD_HH.MM.SS`
  - `YYYY-MM-DD-HH-MM-SS`

Offline benchmark rule:
- `labelstudio-benchmark --no-upload` is a first-class offline mode (prediction + eval locally, no Label Studio credential resolution/upload calls).

## Plugin Contract

Importer protocol contract:
- `detect(path) -> float`
- `inspect(path) -> WorkbookInspection`
- `convert(path, mapping, progress_callback=...) -> ConversionResult`

Selection:
- registry asks each importer for `detect` score and selects highest.

References:
- protocol: `cookimport/plugins/base.py`
- registry: `cookimport/plugins/registry.py`

## Deterministic-First Boundary

Current architecture is still deterministic-first:
- no always-on LLM dependency in the primary staging path
- rule/heuristic extraction + deterministic serialization is the default behavior
- LLM module exists (`cookimport/llm/`) but not as a required stage path

## Cross-cutting Conventions

- The import tooling is the Python package `cookimport/`, with CLI entrypoint exposed as `cookimport` via `pyproject.toml`.
- Interactive menu navigation (`C3imp` / `cookimport` with no subcommands) treats `Esc` as one-level "back" in select prompts and prompt inputs.
- Typer command functions that are also called from interactive helpers must use real Python defaults (for example `typing.Annotated[..., typer.Option(...)]`) so direct helper calls do not receive `OptionInfo` placeholders.
- Output timestamp format is standardized in current code as `YYYY-MM-DD_HH.MM.SS` across stage outputs, Label Studio run folders, and benchmark eval folders.
- Durable subsystem conventions live with their code:
  - `cookimport/CONVENTIONS.md`
  - `cookimport/config/CONVENTIONS.md`
  - `cookimport/labelstudio/CONVENTIONS.md`
  - `cookimport/staging/CONVENTIONS.md`
  - `cookimport/plugins/CONVENTIONS.md`
  - `cookimport/bench/CONVENTIONS.md`
  - `cookimport/analytics/CONVENTIONS.md`
  - `tests/CONVENTIONS.md`
- When adding a new durable rule, document it in the nearest code-local `CONVENTIONS.md` first; only add pointers in docs when discoverability needs to change.
- Discovery-note convention: keep notes focused to one discovery, use timestamped filenames, and merge durable outcomes into the owning stage README to avoid split sources of truth.

## Change Checklist (safe architecture edits)

1. Update code and docs atomically
- At minimum: update this file plus the relevant section readmes (`docs/03-ingestion/03-ingestion_readme.md`, `docs/04-parsing/04-parsing_readme.md`, `docs/06-label-studio/06-label-studio_README.md`, `docs/05-staging/05-staging_readme.md`).

2. For output path or timestamp changes
- check stage (`cookimport/cli.py`)
- check labelstudio import (`cookimport/labelstudio/ingest.py`)
- check benchmark eval folder generation (`cookimport/cli.py`)
- check tests and any scripts that glob run folders.

3. For split-job behavior changes
- preserve recipe ID reassignment semantics (`cookimport/staging/pdf_jobs.py`)
- preserve raw artifact merge expectations (`cookimport/cli.py` + `cookimport/cli_worker.py`)
- preserve block-index rebasing for Label Studio merges (`cookimport/labelstudio/ingest.py`).

4. For plugin interface changes
- update protocol + registry + importer implementations together.

5. If you touch report-file placement
- keep `staging/writer.py` as canonical for stage report output contract.
- either remove or clearly isolate legacy `ReportBuilder` expectations in `core/reporting.py` so docs do not drift again.

## Flowchart Branching Contracts

Keep these flowchart/runtime invariants aligned:

- `cookimport stage` and `run_labelstudio_import(...)` share the same importer conversion branching model (including split planning and merge behavior). The README flowchart should not imply two different file-type conversion engines.
- PDF split only activates when all are true: `pdf_split_workers > 1`, `pdf_pages_per_job > 0`, and inspection yields more than one range.
- EPUB split eligibility depends on the effective extractor:
  - `unstructured` / `beautifulsoup` / `markdown` support spine-range split jobs.
  - `markitdown` is whole-book only and does not split by spine.
  - stage/benchmark flows require explicit extractor choice; there is no auto-resolution branch.
- Freeform Label Studio prelabeling has two behavior-changing permutations that should stay visible in flow docs:
  - upload mode: `annotations` vs `predictions`
  - granularity: `span` (actual freeform) vs `block` (block-based mode)

Anti-loop note:
- If flowcharts and runtime behavior diverge, update this file and the README chart in the same change so future debugging does not branch on stale docs.
