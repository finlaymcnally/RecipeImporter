---
summary: "AI Onboarding & Project Summary for the cookimport project."
read_when:
  - When an AI agent or new developer needs a technical overview of the architecture, tech stack, and data flow
  - When you need to understand how recipe ingestion and parsing works in this codebase
---

# AI Onboarding & Project Summary: `cookimport` (code-verified on 2026-03-03)

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
- `bench` (offline benchmark suite: speed/quality discovery-runs/compare, `gc`, `eval-stage`)
- `tag-catalog` (subcommand: `export`)
- `tag-recipes` (subcommands: `debug-signals`, `suggest`, `apply`)
- `epub` (subcommands: `inspect`, `dump`, `unpack`, `blocks`, `candidates`, `validate`)

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
- OCR options (`ocr_device`, `ocr_batch_size`, PDF OCR policy),
- deterministic parsing knobs (section detector, multi-recipe splitter, instruction segmentation, ingredient parser controls, priority-6 metadata controls),
- optional codex-farm run settings (recipe pass, knowledge pass, tag pass).

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
- `cookimport/plugins/webschema.py`:
  - schema-first web recipe ingestion with deterministic fallback extraction.

## 5. Output Contracts

### 5.1 Stage run outputs

`cookimport stage` writes a timestamped run root:

`data/output/<YYYY-MM-DD_HH.MM.SS>/`

Main artifacts:

- `intermediate drafts/<workbook>/r*.jsonld`
- `final drafts/<workbook>/r*.json`
- `sections/<workbook>/r*.sections.json`
- `tips/<workbook>/...`
- `chunks/<workbook>/...`
- `tables/<workbook>/...` (when table extraction is enabled)
- `raw/<importer>/<source_hash>/...`
- `.bench/<workbook>/stage_block_predictions.json`
- `knowledge/<workbook>/...` (when knowledge extraction is enabled)
- `tags/<workbook>/...` (when LLM tagging is enabled)
- `<workbook>.excel_import_report.json`
- `run_summary.json`
- `run_summary.md`
- `run_manifest.json`

### 5.2 Performance history + dashboard

Stage runs summarize and append history rows to:

- `history_csv_for_output(<stage_output_root>)`
  - default repo-local path: `.history/performance_history.csv`
  - external output-root path: `<stage_output_parent>/.history/performance_history.csv`

Dashboard output:

- `cookimport stats-dashboard` writes to `.history/dashboard` by default for repo-local outputs
- emits `index.html` + local assets + embedded inline JSON fallback for `file://` usage.

### 5.3 Label Studio / benchmark artifacts

- `labelstudio-import` run root pattern:
  - `<output_dir>/<timestamp>/labelstudio/<book_slug>/...`
  - includes `manifest.json`, coverage, tasks JSONL, and optional prelabel report/error artifacts.
- `labelstudio-export` default root when `--run-dir` is not set:
  - `<output_dir>/<source_slug_or_project_slug>/exports/...` (default `output_dir`: `data/golden/pulled-from-labelstudio`)
  - When one source file is detectable, the source filename stem drives the slug so repeat pulls overwrite the same folder even if project names are suffixed (`-2`, `-3`, ...).
- `labelstudio-benchmark` eval roots:
  - default under `data/golden/benchmark-vs-golden/<timestamp>/`
  - may co-locate prediction artifacts under `prediction-run/`.

All run-producing paths now rely on `run_manifest.json` as a stable traceability record (`cookimport/runs/manifest.py`).

## 6. Label Studio and Benchmarking Capabilities

### 6.1 Label Studio import/export scope

- `labelstudio-import`, `labelstudio-export`, and `labelstudio-eval` are freeform-only (`freeform-spans`).
- Legacy Label Studio scopes (`pipeline`, `canonical-blocks`) are treated as historical artifacts and rejected by current export/eval workflows.

### 6.2 Freeform AI prelabel

- prelabel runs use local Codex CLI invocation (`codex exec -`) via `cookimport/labelstudio/prelabel.py`.
- token usage tracking is implemented and persisted in report artifacts.

### 6.3 Evaluation and offline suite

- `labelstudio-eval` and `labelstudio-benchmark` evaluate freeform predictions against freeform gold.
- `bench speed-*`, `bench quality-*`, `bench gc`, and `bench eval-stage` provide offline benchmark/regression tooling.
- `bench quality-lightweight-series` is currently disabled in CLI to prevent accidental heavy runs.

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

- Stage LLM paths are optional run-settings choices:
  - recipe correction: `llm_recipe_pipeline=codex-farm-single-correction-v1`
  - knowledge harvesting: `llm_knowledge_pipeline=codex-farm-knowledge-v1` (knowledge extraction)
  - tag suggestion pass: `llm_tags_pipeline=codex-farm-tags-v1` (tags stage)
- Shared defaults are deterministic: `llm_recipe_pipeline=off`, `line_role_pipeline=off`, `atomic_block_splitter=off`. Codex-enabled paths are explicit opt-ins.
- Label Studio freeform prelabel uses local Codex CLI invocation (`codex exec -` fallback path included).
- Deterministic stage behavior remains the baseline when LLM settings are `off`.
- Legacy modules (`cookimport/llm/client.py`, `cookimport/llm/repair.py`) still exist but are not the primary active stage path.

## 10. Directory Map

```text
cookimport/
├── cli.py                    # Main command surface + interactive mode
├── cli_worker.py             # Worker-side stage/split execution
├── plugins/                  # Importers (excel/text/pdf/epub/paprika/recipesage/webschema)
├── parsing/                  # Signals, ingredient parsing, tips, chunks, EPUB helpers
├── staging/                  # JSON-LD + draft writers and output stats
├── labelstudio/              # Import/export/eval/prelabel
├── analytics/                # perf history + dashboard collection/render
├── bench/                    # Offline benchmark suite tooling
├── tagging/                  # Tag catalog + suggestion/apply pipelines
├── epubdebug/                # EPUB inspection/race/debug commands
├── config/                   # Run settings + last-run persistence
├── runs/                     # run_manifest model/writer
├── llm/                      # codex-farm orchestration + legacy repair modules
└── core/                     # Shared models/reporting/timing/IDs
```

## 11. Recommended Deep Docs

- architecture source of truth: `docs/01-architecture/01-architecture_README.md`
- CLI behavior + interactive flow: `docs/02-cli/02-cli_README.md`
- ingestion specifics: `docs/03-ingestion/03-ingestion_readme.md`
- parsing specifics: `docs/04-parsing/04-parsing_readme.md`
- staging contracts: `docs/05-staging/05-staging_readme.md`
- Label Studio and benchmark semantics: `docs/06-label-studio/06-label-studio_README.md` and `docs/07-bench/07-bench_README.md`
- analytics/dashboard contracts: `docs/08-analytics/08-analytics_readme.md`
- tagging contracts: `docs/09-tagging/09-tagging_README.md`
- codex-farm boundary details: `docs/10-llm/10-llm_README.md`

## 12. Durable Convention File Map

Durable subsystem rules are code-adjacent and should be updated there first:
- `cookimport/CONVENTIONS.md`
- `cookimport/config/CONVENTIONS.md`
- `cookimport/labelstudio/CONVENTIONS.md`
- `cookimport/staging/CONVENTIONS.md`
- `cookimport/plugins/CONVENTIONS.md`
- `cookimport/bench/CONVENTIONS.md`
- `cookimport/analytics/CONVENTIONS.md`
- `tests/CONVENTIONS.md`
