---
summary: "Code-verified architecture source of truth, including chronology of prior attempts and current known gaps."
read_when:
  - When you need end-to-end pipeline architecture and module boundaries
  - When changing output roots, timestamp formats, IDs, split-job behavior, or Label Studio flows
  - When reconciling historical architecture attempts against current code
---

# Architecture Readme

This is the single source of truth for architecture under `docs/01-architecture`.
It merges prior architecture notes and re-verifies them against current code in:
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

## Chronology and Prior Attempts (do not discard)

This section preserves what prior docs attempted, in creation order, so future work does not repeat dead ends.

1. `README.md` (historical, previously in this folder)
- established baseline ingestion -> staging narrative and plugin-registry model.

2. `2026-02-11-remove-root-staging-defaults.md` (historical)
- attempted migration away from root `staging/` defaults.
- current code confirms this is landed (`DEFAULT_OUTPUT = data/output`, Label Studio defaults under `data/golden`).

3. `2026-02-11-standardize-run-timestamps.md` (historical)
- claimed standardized timestamp behavior.
- current code still uses `YYYY-MM-DD_HH.MM.SS` (dot-separated time), not a colon format.

4. `2026-02-11-architecture-doc-merge-verification.md` (this folder, older than this README)
- recorded 3 key truth checks:
  - timestamp format is dot-separated
  - stage report file is at run root (not `reports/`)
  - Label Studio split merge rebases block indices
- all 3 remain true in current code.

5. `2026-02-15_20.44.30-stage-docs-information-architecture-map.md` (migrated from `docs/understandings/`)
- captured a stage-first docs information architecture to prevent discovery notes from becoming a separate silo.
- mapped runtime module ownership to section docs (`02-cli`, `03-ingestion`, `04-parsing`, `05-staging`, `06-label-studio`, `07-bench`, `08-analytics`, `09-tagging`, `11-reference`).

6. `2026-02-15_22.05.45-architecture-merge-verification.md` (migrated from `docs/understandings/`)
- re-verified that stage report JSON is written at run root by active writer flow.
- re-verified that legacy `core/reporting.py` `ReportBuilder` is not current stage output contract.
- re-verified Label Studio split merge block-index rebasing as required for eval alignment.

Current file timestamps in this folder before consolidation:
- `2026-02-11-architecture-doc-merge-verification.md` (mtime `2026-02-15 20:50:55 -0500`)
- `01-architecture_README.md` (mtime `2026-02-15 21:28:01 -0500`)

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
- interactive mode includes one-level back navigation on menu selects via Backspace key binding (`cookimport/cli.py`).
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

## Known Bad / Known Confusions (do not re-litigate without new evidence)

1. Timestamp format docs have drifted repeatedly
- Some docs and notes claim colon-separated time.
- Current code uses dot-separated time (`HH.MM.SS`).
- Do not assume one from docs alone; verify in `strftime` calls.

2. Report path assumptions are easy to get wrong
- Some text/comments imply a `reports/` subfolder for stage outputs.
- Current stage writer writes `<workbook_slug>.excel_import_report.json` at run root.
- `cookimport/core/reporting.py` still contains a legacy `ReportBuilder` that writes to `reports/`; this is not the active stage writer path, but it can mislead documentation work.

3. URN namespace naming drift
- Older architecture examples used `urn:cookimport:*`.
- Code currently emits `urn:recipeimport:*`.
- Any downstream parser/indexer should key off real emitted IDs, not old examples.

4. Split-job merge correctness depends on index rebasing
- Particularly for Label Studio freeform/canonical tasks/eval.
- If block indices are not rebased during merge, eval alignment breaks silently.

5. Benchmark command expectations
- `labelstudio-benchmark` is not eval-only in CLI mode; it performs prediction import/upload first.
- interactive benchmark has an eval-only branch if you already have a prediction run.

6. CLI code has duplicate dead-return tail in stage command
- there is a second unreachable `typer.secho(...); return out` tail after the first return in `stage()` (`cookimport/cli.py`).
- harmless at runtime but easy to misread during maintenance.

## Cross-cutting Conventions

- The import tooling is the Python package `cookimport/`, with CLI entrypoint exposed as `cookimport` via `pyproject.toml`.
- Interactive menu navigation (`C3imp` / `cookimport` with no subcommands) treats `Backspace` as one-level "back" in select prompts.
- Typer command functions that are also called from interactive helpers must use real Python defaults (for example `typing.Annotated[..., typer.Option(...)]`) so direct helper calls do not receive `OptionInfo` placeholders.
- Output timestamp format is standardized in current code as `YYYY-MM-DD_HH.MM.SS` across stage outputs, Label Studio run folders, and benchmark eval folders.
- Discovery-note convention (from retired `docs/understandings`): keep notes focused to one discovery, use timestamped filenames, and merge durable outcomes into the owning stage README to avoid split sources of truth.
- Task-spec convention (from retired `docs/tasks`): preserve task contract details (problem statement, acceptance criteria, verification command(s), evidence, constraints/gotchas, rollback notes) in the owning stage README rather than leaving them in a separate task folder.
- Timestamped task-doc naming pattern to preserve chronology remains: `YYYY-MM-DD_HH.MM.SS - short-title.md`.

## Prior Attempt Ledger (with status)

From the archived architecture docs:

- Attempt: remove root `staging/` default outputs.
  - Status: appears landed and active.
  - Evidence: CLI defaults route stage/inspect to `data/output`; Label Studio artifacts default to `data/golden`.

- Attempt: unify timestamp folder format to a colon-separated time format.
  - Status: not reflected in current code paths.
  - Current reality: dot-separated `YYYY-MM-DD_HH.MM.SS` is still emitted in stage and Label Studio flows.
  - Practical guidance: if standardization is desired, update all timestamp call sites together and then update this doc + conventions in same change.

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
