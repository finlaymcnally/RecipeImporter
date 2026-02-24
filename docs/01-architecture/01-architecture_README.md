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
- `cookimport/cli.py`
- `cookimport/cli_worker.py`
- `cookimport/staging/writer.py`
- `cookimport/staging/pdf_jobs.py`
- `cookimport/labelstudio/ingest.py`
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

### Optional Label Studio lane
- `cookimport/labelstudio/ingest.py` can:
  - run conversion (including split jobs for PDF/EPUB)
  - generate tasks for `pipeline`, `canonical-blocks`, or `freeform-spans`
  - write run artifacts (`manifest.json`, tasks JSONL, coverage, extracted archive/text)
  - upload tasks when write consent is explicit
  - perform merge-time block-index rebasing across split jobs

## Stage-First Docs IA Map (migrated from `docs/understandings`)

This mapping is preserved so future docs changes stay aligned to code ownership:

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

Command defaults:
- `stage --out` default: `data/output`
- `inspect --out` default: `data/output`
- `labelstudio-import --output-dir` default: `data/golden`
- `labelstudio-export --output-dir` default: `data/golden`
- `labelstudio-benchmark --output-dir` default: `data/golden`
- `labelstudio-benchmark --processed-output-dir` default: `data/output`

Interactive defaults:
- settings `output_dir` defaults to `data/output` and drives interactive stage target.
- interactive Label Studio import/export/benchmark paths are driven with `DEFAULT_GOLDEN`.

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

- `<out>/<timestamp>/intermediate drafts/<workbook_slug>/r{index}.jsonld`
- `<out>/<timestamp>/final drafts/<workbook_slug>/r{index}.json`
- `<out>/<timestamp>/tips/<workbook_slug>/t{index}.json`
- `<out>/<timestamp>/tips/<workbook_slug>/tips.md`
- `<out>/<timestamp>/tips/<workbook_slug>/topic_candidates.json`
- `<out>/<timestamp>/tips/<workbook_slug>/topic_candidates.md`
- `<out>/<timestamp>/chunks/<workbook_slug>/c{index}.json` (+ `chunks.md` when chunks exist)
- `<out>/<timestamp>/raw/<importer>/<source_hash>/<location_id>.<ext>`
- `<out>/<timestamp>/<workbook_slug>.excel_import_report.json`

Important clarification:
- report file is written at run root, not in a stage `reports/` subfolder.

References:
- writers and paths: `cookimport/staging/writer.py`
- stage orchestration: `cookimport/cli.py`, `cookimport/cli_worker.py`

## ID and Provenance Rules

Active namespace is `urn:recipeimport` (not `urn:cookimport`).

Examples from current code:
- recipe IDs via helper: `urn:recipeimport:{source_type}:{source_hash}:{location_id}`
- writer-generated fallback recipe IDs for Excel-like flow: `urn:recipeimport:excel:{file_hash}:{sheet_slug}:r{row_index}`
- tip/topic IDs similarly use `urn:recipeimport:tip:*` and `urn:recipeimport:topic:*`

References:
- ID helper: `cookimport/core/reporting.py`
- writer ID assignment: `cookimport/staging/writer.py`

## Split-Job Architecture

Stage split jobs (`cookimport stage`):
- planning uses page ranges for PDF and spine ranges for EPUB
- each worker parses a subset
- split workers write temporary raw artifacts to:
  - `<out>/<timestamp>/.job_parts/<workbook_slug>/job_<index>/raw/...`
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

`labelstudio-import` run root:
- `<output_dir>/<timestamp>/labelstudio/<book_slug>/`

Core artifacts:
- `extracted_archive.json`
- `extracted_text.txt`
- `label_studio_tasks.jsonl`
- `coverage.json`
- `manifest.json`
- `project.json`

Behavioral constraints:
- write operations are gated (`--allow-labelstudio-write` required in non-interactive commands)
- benchmark command (`labelstudio-benchmark`) is upload-first in CLI mode; it generates/imports prediction tasks before scoring
- benchmark co-locates prediction run under eval output as `prediction-run/`

References:
- commands + guards + benchmark flow: `cookimport/cli.py`
- import/task generation/upload/artifacts: `cookimport/labelstudio/ingest.py`

## Run Manifest And History Root Contract

`run_manifest.json` is the cross-command traceability join point for run roots generated by:
- `stage`
- `labelstudio-import`
- `labelstudio-export`
- `labelstudio-eval`
- `labelstudio-benchmark`
- bench prediction/eval/suite flows

Manifest responsibilities:
- source identity (`path`, `source_hash`)
- effective run config snapshot/hash/summary
- key artifact pointers needed to trace stage/prediction/eval relationships without reading internals

History-root rule:
- stage history writes append to `<stage --out>/.history/performance_history.csv`
- benchmark history writes append to `<processed_output_dir>/.history/performance_history.csv`

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
- Discovery-note convention (from retired `docs/understandings`): keep notes focused to one discovery, use timestamped filenames, and merge durable outcomes into the owning stage README to avoid split sources of truth.
- Task-spec convention (from retired `docs/tasks`): preserve task contract details (problem statement, acceptance criteria, verification command(s), evidence, constraints/gotchas, rollback notes) in the owning stage README rather than leaving them in a separate task folder.
- Timestamped task-doc naming pattern to preserve chronology remains: `YYYY-MM-DD_HH.MM.SS - short-title.md`.

## Change Checklist (safe architecture edits)

1. Update code and docs atomically
- At minimum: update this file plus the relevant section readmes (`docs/03-ingestion/03-ingestion_README.md`, `docs/04-parsing/04-parsing_README.md`, `docs/06-label-studio/06-label-studio_README.md`, `docs/05-staging/05-staging_README.md`).

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
  - `unstructured` / `legacy` / `markdown` support spine-range split jobs.
  - `markitdown` is whole-book only and does not split by spine.
  - stage/benchmark flows require explicit extractor choice; there is no auto-resolution branch.
- Freeform Label Studio prelabeling has two behavior-changing permutations that should stay visible in flow docs:
  - upload mode: `annotations` vs `predictions`
  - granularity: `span` (actual freeform) vs `block` (legacy block mode)

Anti-loop note:
- If flowcharts and runtime behavior diverge, update this file and the README chart in the same change so future debugging does not branch on stale docs.

## Merged Understandings Batch (2026-02-23 cleanup)

### Cross-cutting pytest low-noise output contract

Merged sources:
- `docs/understandings/2026-02-22_23.25.11-pytest-progress-glyph-suppression.md`
- `docs/understandings/2026-02-22_23.35.37-pytest-addopts-override-noise-gap.md`

Durable rules:
- `pytest.ini` quiet flags alone are not sufficient under pytest 9; compact output relies on both:
  - `console_output_style = classic`
  - glyph suppression in `tests/conftest.py:pytest_report_teststatus(...)`
- Compact mode should remain enforced in `tests/conftest.py:pytest_configure(...)` (`no_header`, `no_summary`, warnings suppression, verbose clamp) so `-o addopts=''` does not re-enable noisy separators by accident.
- Intentional verbose debugging remains opt-in via `COOKIMPORT_PYTEST_VERBOSE_OUTPUT=1`.
