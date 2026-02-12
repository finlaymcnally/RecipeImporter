# Architecture Readme

This file consolidates the old `docs/architecture/` docs and revalidates them against current code.

## Scope and Intent

This project (`cookimport`) is a deterministic recipe-import pipeline with optional Label Studio workflows for annotation/evaluation. The architecture is optimized around:

- stable, auditable extraction outputs
- predictable folder/file conventions
- split-job processing for large PDF/EPUB sources
- deterministic IDs/provenance that survive reruns and merging

## Chronology of Architecture Notes (merged from `docs/architecture`)

1. `docs/architecture/README.md` (created 2026-02-10 23:22)
- Established the baseline architecture narrative (ingestion -> transformation, plugin registry, output layout).

2. `docs/architecture/2026-02-11-remove-root-staging-defaults.md` (created 2026-02-11 18:20)
- Captured the shift away from root-level `staging/` defaults.
- This change *is* reflected in current code.

3. `docs/architecture/2026-02-11-standardize-run-timestamps.md` (created 2026-02-11 18:20)
- Claimed timestamps were standardized to a colon-separated time format.
- Current code still uses `YYYY-MM-DD_HH.MM.SS` (dot-separated time), so this effort is either incomplete or regressed.

## Current Architecture (code-verified)

## High-level Flow

Two-phase pipeline:

1. Ingestion/importer phase
- Each importer detects/inspects/converts input into `ConversionResult` + `RecipeCandidate` + extracted blocks/artifacts.
- Core interface: `cookimport/plugins/base.py`.
- Registry and selection: `cookimport/plugins/registry.py`.

2. Staging/transformation/output phase
- Writes intermediate schema.org Recipe JSON, final cookbook3 JSON, tips/topic candidates, optional knowledge chunks, raw artifacts, and report JSON.
- Output writers: `cookimport/staging/writer.py`.
- Orchestration: `cookimport/cli.py` and worker helpers in `cookimport/cli_worker.py`.

For Label Studio workflows, `cookimport/labelstudio/ingest.py` can run conversion, generate tasks, upload tasks, and emit run artifacts/manifests.

## Source Locations (where architecture lives)

- CLI + orchestration: `cookimport/cli.py`
- Worker execution for stage split jobs: `cookimport/cli_worker.py`
- Plugin interface/registry: `cookimport/plugins/base.py`, `cookimport/plugins/registry.py`
- Importers: `cookimport/plugins/*.py`
- Writers/output conventions: `cookimport/staging/writer.py`
- Split range planning + recipe ID reassignment: `cookimport/staging/pdf_jobs.py`
- Report enrichment/hash helpers: `cookimport/core/reporting.py`
- Label Studio import/task generation/merge/rebase: `cookimport/labelstudio/ingest.py`

## Output Roots and Defaults

Current defaults in code:

- `stage`/`inspect` output root: `data/output`
- interactive settings default `output_dir`: `data/output` (used for stage/inspect)
- non-interactive `labelstudio-import`/`labelstudio-export`/`labelstudio-benchmark` default `--output-dir`: `data/golden`
- interactive Label Studio flows also route artifact roots to `data/golden`
- benchmark additionally emits processed cookbook output to `data/output` by default (`--processed-output-dir`)

Code references:
- defaults/constants: `cookimport/cli.py`
- labelstudio import runner + processed output hook: `cookimport/labelstudio/ingest.py`

## Run Folder Timestamp Format (important)

Current code format is:

- `YYYY-MM-DD_HH.MM.SS` (dot-separated time)

References:
- stage run root creation: `cookimport/cli.py`
- labelstudio run root creation: `cookimport/labelstudio/ingest.py`
- benchmark eval folder default timestamp: `cookimport/cli.py`

Known mismatch from prior docs:
- Old architecture note says colon-separated time.
- That is not what current code emits.

## Stage Output Structure

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
- report file is written at run root, not in a `reports/` subfolder.

References:
- writers and paths: `cookimport/staging/writer.py`
- stage orchestration: `cookimport/cli.py`, `cookimport/cli_worker.py`

## ID and Provenance Behavior

IDs are deterministic and mostly provenance-based, but the exact URN prefix in code is `urn:recipeimport`, not `urn:cookimport`.

Examples from current code:
- recipe IDs via helper: `urn:recipeimport:{source_type}:{source_hash}:{location_id}`
- writer-generated fallback recipe IDs for Excel-like flow: `urn:recipeimport:excel:{file_hash}:{sheet_slug}:r{row_index}`
- tip/topic IDs similarly use `urn:recipeimport:tip:*` and `urn:recipeimport:topic:*`

References:
- ID helper: `cookimport/core/reporting.py`
- writer ID assignment: `cookimport/staging/writer.py`

## Split-job Architecture (PDF/EPUB)

Stage split jobs (`cookimport stage`):

- planning uses page ranges for PDF and spine ranges for EPUB
- each worker parses a subset
- split workers write temporary raw artifacts to:
  - `<out>/.job_parts/<workbook_slug>/job_<index>/raw/...`
- merge step combines logical results, reassigns recipe IDs globally, writes final outputs once, then merges raw files into `<out>/raw/...`
- `.job_parts` is cleaned after successful merge

Label Studio split jobs (`run_labelstudio_import`):

- similar parallel conversion split is used when configured
- merge rebases block-index-like fields (`start_block`, `end_block`, `block_index`, related variants) by cumulative prior job block counts
- this is critical so canonical/freeform tasks and evals share one global block coordinate space

References:
- stage planning/merge/raw merge: `cookimport/cli.py`, `cookimport/cli_worker.py`, `cookimport/staging/pdf_jobs.py`
- labelstudio offset/rebase merge: `cookimport/labelstudio/ingest.py`

## Label Studio Architecture Notes

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
- benchmark path is upload-first, not pure offline eval; it runs prediction import before scoring
- benchmark co-locates prediction run under eval output as `prediction-run/`

References:
- commands + guards + benchmark flow: `cookimport/cli.py`
- import/task generation/upload/artifacts: `cookimport/labelstudio/ingest.py`

## Plugin Architecture

Importer protocol contract:
- `detect(path) -> float`
- `inspect(path) -> WorkbookInspection`
- `convert(path, mapping, progress_callback=...) -> ConversionResult`

Selection:
- registry asks each importer for `detect` score and selects highest.

References:
- protocol: `cookimport/plugins/base.py`
- registry: `cookimport/plugins/registry.py`

## Deterministic-first Design

Current architecture is still deterministic-first:
- no always-on LLM dependency in the primary staging path
- rule/heuristic extraction + deterministic serialization is the default behavior
- LLM module exists (`cookimport/llm/`) but not as a required stage path

## Known Bad / Known Confusions (to avoid repeating loops)

1. Timestamp format docs have drifted repeatedly
- Some docs and notes claim colon-separated time.
- Current code uses dot-separated time (`HH.MM.SS`).
- Do not assume one from docs alone; verify in `strftime` calls.

2. Report path assumptions are easy to get wrong
- Some text/comments imply a `reports/` subfolder for stage outputs.
- Current stage writer writes `<workbook_slug>.excel_import_report.json` at run root.

3. URN namespace naming drift
- Older architecture examples used `urn:cookimport:*`.
- Code currently emits `urn:recipeimport:*`.
- Any downstream parser/indexer should key off real emitted IDs, not old examples.

4. Split-job merge correctness depends on index rebasing
- Particularly for Label Studio freeform/canonical tasks/eval.
- If block indices are not rebased during merge, eval alignment breaks silently.

5. Benchmark command expectations
- `labelstudio-benchmark` is not eval-only in CLI mode.
- It performs import/upload unless you use alternate flows.

## Cross-cutting Conventions

- The import tooling is the Python package `cookimport/`, with CLI entrypoint exposed as `cookimport` via `pyproject.toml`.
- Interactive menu navigation (`C3imp` / `cookimport` with no subcommands) treats `Backspace` as one-level "back" in select prompts.
- Typer command functions that are also called from interactive helpers must use real Python defaults (for example `typing.Annotated[..., typer.Option(...)]`) so direct helper calls do not receive `OptionInfo` placeholders.
- Output timestamp format is standardized in current code as `YYYY-MM-DD_HH.MM.SS` across stage outputs, Label Studio run folders, and benchmark eval folders.

## What We Know Was Tried Before (and status)

From the archived architecture docs:

- Attempt: remove root `staging/` default outputs.
  - Status: appears landed and active.
  - Evidence: CLI defaults route stage/inspect to `data/output`; Label Studio artifacts default to `data/golden`.

- Attempt: unify timestamp folder format to a colon-separated time format.
  - Status: not reflected in current code paths.
  - Current reality: dot-separated `YYYY-MM-DD_HH.MM.SS` is still emitted in stage and Label Studio flows.
  - Practical guidance: if standardization is desired, update all timestamp call sites together and then update this doc + conventions in same change.

## If You Need to Change Architecture Safely

1. Update code and docs atomically
- At minimum: update the relevant section readmes (`docs/architecture/architecture_readme.md`, `docs/ingestion/section_ingestion_readme.md`, `docs/parsing/section_parsing_readme.md`, `docs/label-studio/label_studio_readme.md`).

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
