---
summary: "AI Onboarding & Project Summary for the cookimport project."
read_when:
  - When an AI agent or new developer needs a technical overview of the architecture, tech stack, and data flow
  - When you need to understand how recipe ingestion and parsing works in this codebase
---

# AI Onboarding & Project Summary: `cookimport` (code-verified on 2026-02-22)

This file is the high-level orientation map for the current implementation.
For subsystem details, use the stage docs in `docs/01-architecture` through `docs/11-reference`.

## 1. Project Purpose

`cookimport` is a deterministic-first local pipeline that imports recipe data from mixed source formats and writes:

- structured recipe outputs (`schema.org`-shaped intermediate + final draft JSON),
- knowledge artifacts (tips, topic candidates, chunks),
- provenance-heavy debug artifacts and reports,
- optional Label Studio artifacts for annotation/evaluation,
- run history metrics for dashboarding and benchmark trend tracking.

Primary roots:

- source input: `data/input`
- staging output: `data/output`
- annotation/benchmark output: `data/golden`

## 2. Runtime Surface

### 2.1 Entrypoints

From `pyproject.toml`:

- `cookimport` -> full Typer CLI (`cookimport/cli.py`)
- `import` and `C3import` -> wrapper that stages default input when called with no subcommand (`cookimport/entrypoint.py`)
- `C3imp` -> interactive wrapper with optional `C3IMP_LIMIT` shortcut (`cookimport/c3imp_entrypoint.py`)

### 2.2 Top-level CLI commands

`cookimport --help` currently exposes:

- `stage`
- `perf-report`
- `stats-dashboard`
- `benchmark-csv-backfill`
- `inspect`
- `labelstudio-import`
- `labelstudio-export`
- `labelstudio-eval`
- `debug-epub-extract`
- `labelstudio-benchmark`
- `bench` (subcommands: `validate`, `run`, `sweep`, `knobs`)
- `tag-catalog` (subcommand: `export`)
- `tag-recipes` (subcommands: `debug-signals`, `suggest`, `apply`)
- `epub` (subcommands: `inspect`, `dump`, `unpack`, `blocks`, `candidates`, `validate`, `race`)

## 3. Architecture (current)

### 3.1 Importer contract and registry

Importers implement:

- `detect(path) -> float`
- `inspect(path) -> WorkbookInspection`
- `convert(path, mapping, progress_callback) -> ConversionResult`

Registry selection is score-based (`best_importer_for_path` in `cookimport/plugins/registry.py`).

### 3.2 Two broad phases

1. Source conversion
- format-specific importer returns `ConversionResult` with recipes/tips/topic candidates/non-recipe blocks/raw artifacts/report.

2. Shared staging/write path
- `cookimport/cli.py` orchestrates workers and split-job merge.
- `cookimport/staging/writer.py` writes standardized outputs.
- `cookimport/staging/draft_v1.py` performs shared recipe shaping (ingredient parsing, instruction parsing, step-ingredient linking, variants, tag helpers).

### 3.3 Run settings + config propagation

Canonical per-run settings live in `cookimport/config/run_settings.py` (`RunSettings`), including:

- worker topology (`workers`, split workers, pages/spine items per job),
- EPUB extractor choices (`unstructured`, `legacy`, `markdown`, `auto`, `markitdown`),
- unstructured tuning options,
- OCR options (`ocr_device`, `ocr_batch_size`).

Interactive flows use the same run settings model and persist last-run snapshots via `cookimport/config/last_run_store.py`.

### 3.4 Split-job model

Large PDF/EPUB runs can split into worker jobs and merge back:

- temporary artifacts in `.job_parts/...`,
- merged output written once at run root,
- recipe IDs and coordinate spaces normalized post-merge.

`markitdown` EPUB extraction is intentionally whole-book only (no spine split support).

## 4. Source Format Coverage

Active importers:

- `cookimport/plugins/excel.py`:
  - layout detection (`wide-table`, `template`, `tall`),
  - sheet-level inspection metadata + mapping stubs.
- `cookimport/plugins/text.py`:
  - `.txt`, `.md`, `.markdown`, `.docx` (and guarded `.doc` fallback behavior),
  - markdown/frontmatter/yield heuristics and DOCX table handling.
- `cookimport/plugins/pdf.py`:
  - PyMuPDF text extraction + layout heuristics,
  - docTR OCR fallback for scanned/low-text PDFs.
- `cookimport/plugins/epub.py`:
  - multi-backend extraction (`legacy`, `unstructured`, `markdown`, `markitdown`),
  - `auto` resolved by orchestration layers before convert,
  - extraction diagnostics and EPUB health artifacts.
- `cookimport/plugins/paprika.py`:
  - `.paprikarecipes` zip/gzip JSON and HTML export merge path.
- `cookimport/plugins/recipesage.py`:
  - JSON export ingestion with recipe normalization.

## 5. Output Contracts

### 5.1 Stage run outputs

`cookimport stage` writes a timestamped run root:

`data/output/<YYYY-MM-DD_HH.MM.SS>/`

Main artifacts:

- `intermediate drafts/<workbook>/r*.jsonld`
- `final drafts/<workbook>/r*.json`
- `tips/<workbook>/...`
- `chunks/<workbook>/...`
- `raw/<importer>/<source_hash>/...`
- `<workbook>.excel_import_report.json`
- `run_manifest.json`

### 5.2 Performance history + dashboard

Stage runs summarize and append history rows to:

- `data/.history/performance_history.csv`

Dashboard output:

- `cookimport stats-dashboard` writes to `<output_root parent>/.history/dashboard/`
- emits `index.html` + local assets + embedded inline JSON fallback for `file://` usage.

### 5.3 Label Studio / benchmark artifacts

- `labelstudio-import` run root pattern:
  - `<output_dir>/<timestamp>/labelstudio/<book_slug>/...`
  - includes `manifest.json`, coverage, tasks JSONL, and optional prelabel report/error artifacts.
- `labelstudio-export` default root when `--run-dir` is not set:
  - `<output_dir>/<project_slug>/exports/...` (default `output_dir`: `data/golden/pulled-from-labelstudio`)
- `labelstudio-benchmark` eval roots:
  - default under `data/golden/benchmark-vs-golden/<timestamp>/`
  - may co-locate prediction artifacts under `prediction-run/`.

All run-producing paths now rely on `run_manifest.json` as a stable traceability record (`cookimport/runs/manifest.py`).

## 6. Label Studio and Benchmarking Capabilities

### 6.1 Import scopes

`labelstudio-import` supports:

- `pipeline`
- `canonical-blocks`
- `freeform-spans`

### 6.2 Freeform AI prelabel

- prelabel runs use local Codex CLI invocation (`codex exec -`) via `cookimport/labelstudio/prelabel.py`.
- token usage tracking is implemented and persisted in report artifacts.

### 6.3 Evaluation and offline suite

- `labelstudio-eval` and `labelstudio-benchmark` support canonical/freeform evaluation paths.
- `bench run/sweep` provide fully offline prediction+eval loops from suite manifests in `data/golden/bench/suites`.

## 7. Tagging Subsystem

Tagging is now a first-class command surface:

- catalog export from DB (`tag-catalog export`)
- deterministic suggestion + optional LLM second pass (`tag-recipes suggest`)
- DB apply path with dry-run default (`tag-recipes apply`)

Core modules: `cookimport/tagging/*`.

## 8. Tech Stack (active dependencies)

From `pyproject.toml`:

- CLI/UI: Typer, Rich, Questionary
- models/validation: Pydantic v2
- source parsing: BeautifulSoup4, lxml, EbookLib, PyMuPDF, openpyxl, python-docx
- OCR: python-doctr
- EPUB extraction helpers: unstructured, markitdown, markdownify
- parsing heuristics: ingredient-parser-nlp, rapidfuzz
- tests: pytest
- optional DB flows: psycopg

Important clarification:

- Label Studio integration uses an internal REST client (`cookimport/labelstudio/client.py`), not the Label Studio SDK package.

## 9. LLM Boundary (current)

- `cookimport/llm/repair.py` and `cookimport/llm/client.py` still exist as optional/legacy repair plumbing; `LLMClient` provider path remains mock-backed.
- active operational LLM usage today is concentrated in Label Studio freeform prelabel flows (Codex CLI).
- deterministic extraction is still the default stage pipeline behavior.

## 10. Current Health Snapshot (review run on 2026-02-22)

Test sweep in project venv:

- command run: `pytest`
- result: `450 passed`, `5 failed`, `21 warnings` (455 collected)

Current failing area:

1. Missing importer fixture files
- tests reference `docs/template/examples/...` paths that do not exist in repo.
- affected tests:
  - `tests/test_paprika_importer.py`
  - `tests/test_recipesage_importer.py`

2. Error-path validation bug in importer `inspect(...)`
- `WorkbookInspection` does not allow a top-level `warnings` field, but exception handlers in:
  - `cookimport/plugins/paprika.py`
  - `cookimport/plugins/recipesage.py`
  return `WorkbookInspection(..., warnings=[...])`, which raises a Pydantic validation error instead of returning a graceful inspection payload.

3. RecipeSage convert pre-try hash call
- `cookimport/plugins/recipesage.py` computes `file_hash = compute_file_hash(path)` before its `try` block, so missing-path errors raise immediately instead of returning a normal `ConversionResult` with report errors.

## 11. Directory Map

```text
cookimport/
├── cli.py                    # Main command surface + interactive mode
├── cli_worker.py             # Worker-side stage/split execution
├── plugins/                  # Importers (excel/text/pdf/epub/paprika/recipesage)
├── parsing/                  # Signals, ingredient parsing, tips, chunks, EPUB helpers
├── staging/                  # JSON-LD + draft writers and output stats
├── labelstudio/              # Import/export/eval/prelabel
├── analytics/                # perf history + dashboard collection/render
├── bench/                    # Offline benchmark suite tooling
├── tagging/                  # Tag catalog + suggestion/apply pipelines
├── epubdebug/                # EPUB inspection/race/debug commands
├── config/                   # Run settings + last-run persistence
├── runs/                     # run_manifest model/writer
├── llm/                      # Optional/legacy LLM repair boundary
└── core/                     # Shared models/reporting/timing/IDs
```

## 12. Recommended Deep Docs

- architecture source of truth: `docs/01-architecture/01-architecture_README.md`
- CLI behavior + interactive flow: `docs/02-cli/02-cli_README.md`
- ingestion specifics: `docs/03-ingestion/03-ingestion_readme.md`
- parsing specifics: `docs/04-parsing/04-parsing_readme.md`
- staging contracts: `docs/05-staging/05-staging_readme.md`
- Label Studio and benchmark semantics: `docs/06-label-studio/06-label-studio_README.md` and `docs/07-bench/07-bench_README.md`
- analytics/dashboard contracts: `docs/08-analytics/08-analytics_readme.md`
