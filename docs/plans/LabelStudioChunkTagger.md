---
summary: "ExecPlan for adding Label Studio benchmark mode with chunked tasks and golden set export."
read_when:
  - When implementing Label Studio benchmark mode or label export tooling
  - When modifying chunking for labeling tasks or golden set generation
---

# Label Studio Benchmark Mode ExecPlan

This ExecPlan is a living document. The sections `Progress`, `Surprises & Discoveries`, `Decision Log`, and `Outcomes & Retrospective` must be kept up to date as work proceeds.

This document is maintained in accordance with `docs/PLANS.md`.

## Purpose / Big Picture

After this change, a human can point the importer at a cookbook file (PDF/EPUB/etc.) and get a Label Studio project preloaded with chunked tasks for labeling. The system uses the existing importer routing rules to pick the correct pipeline, produces a full extracted text archive, generates both structural and atomic chunks, uploads tasks to Label Studio with stable IDs, and exports labeled data back into a golden set format that the tip evaluation harness can score. You can see it working by running a single CLI command to create a project and import tasks, then running a second CLI command to export labeled data into `labeled_chunks.jsonl` and `golden_set_tip_eval.jsonl` that can be fed into `python tools/tip_eval.py score`.

## Progress

- [x] (2026-01-28 00:00Z) Drafted the ExecPlan and recorded repo context, decisions, and validation steps.
- [x] (2026-01-28 18:05Z) Added Label Studio client utilities and CLI commands for import/export.
- [x] (2026-01-28 18:05Z) Added extraction archive + chunking pipeline (structural + atomic) with coverage report.
- [x] (2026-01-28 18:05Z) Implemented project creation/import, resume/overwrite behavior, and task manifest output.
- [x] (2026-01-28 18:05Z) Implemented export mapping from annotations into labeled chunks + tip eval golden set.
- [x] (2026-01-28 18:05Z) Updated docs, added module note, and added tests for chunk IDs + export mapping.

## Surprises & Discoveries

- Observation: CLI pipeline selection uses `cookimport.plugins.registry.best_importer_for_path` and is currently wired through `cookimport/cli.py::stage`.
  Evidence: `cookimport/cli.py` calls `registry.best_importer_for_path` per input file.
- Observation: Stable IDs for staged outputs are derived from provenance, falling back to `location.chunk_index` when `row_index` is missing.
  Evidence: `cookimport/staging/writer.py` computes IDs using `row_index` or `location.chunk_index`.

## Decision Log

- Decision: Implement new CLI commands as `labelstudio-import` and `labelstudio-export` under `cookimport/cli.py`.
  Rationale: Matches current flat command style (`stage`, `inspect`), avoids nested command plumbing, and remains easy to discover.
  Date/Author: 2026-01-28, Codex
- Decision: Use a single Label Studio project with a `chunk_level` field rather than two separate projects.
  Rationale: Keeps labeling in one place while allowing filtering by chunk level; avoids duplicate config and export flows.
  Date/Author: 2026-01-28, Codex
- Decision: Treat the tip-eval golden set as derived from atomic chunks only, with `tip` assigned when `content_type == "tip"` and `value_usefulness != "useless"`.
  Rationale: Avoids rewarding useless tips while keeping the mapping simple and explicit; non-tip content types are treated as `not_tip`, and `mixed`/`unclear` are excluded by default.
  Date/Author: 2026-01-28, Codex
- Decision: Keep Label Studio API integration dependency-free by using `urllib.request` + JSON instead of adding `requests`.
  Rationale: Minimizes new dependencies and fits the existing dependency footprint; HTTP usage is straightforward.
  Date/Author: 2026-01-28, Codex
- Decision: Store chunk stable IDs in task `data.chunk_id` and use a `manifest.json` to track uploads.
  Rationale: Label Studio task IDs are server-assigned; a stable chunk ID is needed for resume and export mapping.
  Date/Author: 2026-01-28, Codex

## Outcomes & Retrospective

Label Studio benchmark mode is implemented end-to-end. New CLI commands create projects, upload chunked tasks, and export annotations into labeled chunks plus a tip-eval golden set. The system now writes extracted text archives, coverage reports, and manifests under `data/output/<timestamp>/labelstudio/<book_slug>/`, and docs/tests were added to keep the workflow verifiable. Remaining work is operational: run a real Label Studio instance and validate chunk quality on sample cookbooks.

## Context and Orientation

The existing CLI is in `cookimport/cli.py` and uses Typer. It currently supports `stage` (full import) and `inspect` (layout inspection). Importer routing is handled by `cookimport/plugins/registry.py::best_importer_for_path`, which chooses an importer based on file type. Each importer returns a `ConversionResult` defined in `cookimport/core/models.py` that includes recipes, tips, topic candidates, raw artifacts, and a conversion report. Staging output is written by `cookimport/staging/writer.py`, which also defines how stable IDs are assigned from provenance.

Tip evaluation currently relies on `tools/tip_eval.py` and is documented in `docs/Tip_Evaluation_Harness.md`. It expects a JSONL file with `id`, `text`, `anchors`, and `label`, where `label` is one of `tip`, `not_tip`, `narrative`, `reference`, or `recipe_specific`.

The Label Studio benchmark mode will reuse importer routing, add a new extraction archive, and create Label Studio tasks that carry chunk metadata. It must preserve all extracted text (coverage) and provide stable chunk IDs to allow resume and export mapping.

## Plan of Work

Start by adding a new `cookimport/labelstudio/` package that encapsulates three responsibilities: extraction archiving, chunking into structural/atomic chunks, and Label Studio API interactions. Then wire two new CLI commands into `cookimport/cli.py` to call this package. The import command should run the existing importer conversion, build the archive and chunks, create or reuse a Label Studio project, upload tasks, and write a manifest with coverage statistics. The export command should download annotations from Label Studio, merge them with the local task manifest, and write both a full-fidelity labeled chunks JSONL and a tip-eval golden set JSONL.

To ensure non-lossy coverage, extend each importer (PDF, EPUB, text, and Excel) to emit a new raw artifact representing the complete extracted text stream. For PDF/EPUB, this should be a list of blocks with location metadata; for text, a list of lines with line numbers and a full normalized text string; for Excel, a per-row text bundle (concatenate title/ingredients/instructions). The Label Studio chunker will use these artifacts to produce the full archive and to derive standalone (non-recipe) chunks. Recipe-derived chunks will come from `ConversionResult.recipes` to preserve parsed structure.

The chunker should output two sets of chunks by default: structural chunks (recipe blocks, section intros, sidebars) and atomic chunks (paragraphs, step lines, ingredient lines). For standalone text (non-recipe), reuse `cookimport/parsing/tips.py::chunk_standalone_blocks` plus `cookimport/parsing/atoms.py::split_text_to_atoms` so the standalone path mirrors existing tip extraction atomization. For recipe chunks, split `RecipeCandidate.recipeIngredient` into ingredient-line atoms and `RecipeCandidate.recipeInstructions` into step-line atoms; keep the full recipe as a single structural chunk. Each chunk gets a stable ID derived from file hash, chunk level, location metadata, and a short hash of normalized chunk text.

Implement a Label Studio client that can: (1) list projects by title, (2) create a project with a known label config, (3) import tasks in bulk, (4) delete a project (for `--overwrite`), and (5) export tasks/annotations. The import command should default to resume mode, which checks the local manifest to skip already-uploaded chunk IDs; `--overwrite` should delete and recreate the project before uploading.

Finally, update documentation: add a short Label Studio benchmarking guide for non-coders (local run, import command, labeling guidance, export command, evaluation harness run), update `docs/IMPORTANT CONVENTIONS.md` to include the new label-studio output folder conventions, and add a short `cookimport/labelstudio/README.md` with a brief overview of the module. Keep all notes short and add `read_when` hints where appropriate.

## Concrete Steps

From the repo root (`/home/mcnal/projects/recipeimport`), set up a local virtual environment and install dev dependencies:

    python -m venv .venv
    source .venv/bin/activate
    python -m pip install --upgrade pip
    pip install -e ".[dev]"

Add the new module structure:

    mkdir -p cookimport/labelstudio

Wire the CLI commands into `cookimport/cli.py` and add new modules as described in Interfaces and Dependencies. After implementation, run tests:

    pytest tests/test_labelstudio_chunks.py tests/test_labelstudio_export.py

Optional smoke test (requires a running Label Studio instance and API key):

    cookimport labelstudio-import data/input/sample.epub --project-name "sample-benchmark" --label-studio-url http://localhost:8080 --label-studio-api-key $LABEL_STUDIO_API_KEY
    cookimport labelstudio-export --project-name "sample-benchmark" --label-studio-url http://localhost:8080 --label-studio-api-key $LABEL_STUDIO_API_KEY

## Validation and Acceptance

Acceptance is satisfied when all of the following are true:

- Running `cookimport labelstudio-import` on a supported cookbook file auto-selects the correct importer, writes an extracted archive, emits chunk tasks, and creates or updates a Label Studio project with tasks uploaded.
- The output folder contains `extracted_archive.json`, `label_studio_tasks.jsonl`, and `manifest.json` with coverage statistics and stable IDs.
- The Label Studio UI shows readable text with line breaks preserved, plus metadata fields (chunk level, location, source file) visible in each task.
- Running `cookimport labelstudio-export` produces `labeled_chunks.jsonl` (full fidelity) and `golden_set_tip_eval.jsonl` (tip-eval mapping) without losing provenance.
- `python tools/tip_eval.py score --labels golden_set_tip_eval.jsonl` runs without errors and reports precision/recall (values depend on labels but command must succeed).

## Idempotence and Recovery

All generated chunk IDs are deterministic. Running the import command again with `--resume` should skip tasks already recorded in the manifest, preventing duplicates. If a run fails midway, rerun with `--resume` to continue, or with `--overwrite` to delete and recreate the project. The extraction archive and task JSONL are versioned under a timestamped output directory, so reruns never overwrite prior artifacts unless explicitly directed.

## Artifacts and Notes

Expected output layout (relative to `--output-dir`, default `data/output`):

    {output_dir}/{timestamp}/labelstudio/{book_slug}/
      extracted_archive.json
      extracted_text.txt
      coverage.json
      label_studio_tasks.jsonl
      manifest.json
      project.json
      exports/
        labelstudio_export.json
        labeled_chunks.jsonl
        golden_set_tip_eval.jsonl

Example task line (JSONL) with stable chunk ID and display text:

    {"data": {"chunk_id": "urn:recipeimport:chunk:pdf:abcd1234:atomic:page12:block33:7f2c91", "text_display": "Use cold butter...", "text_raw": "Use cold butter...", "chunk_level": "atomic", "chunk_type_hint": "paragraph", "source_file": "Cookbook.pdf", "book_id": "Cookbook", "pipeline_used": "pdf", "location": {"page": 12, "block_index": 33, "atom_index": 2}, "context_before": "...", "context_after": "..."}}

Example manifest entry:

    {"project_name": "sample-benchmark", "project_id": 12, "task_count": 420, "chunk_ids": ["urn:recipeimport:chunk:..."], "coverage": {"extracted_chars": 1034221, "chunked_chars": 1018742, "missing_blocks": 12}}

Example golden set line:

    {"id": "urn:recipeimport:chunk:...", "text": "Use cold butter...", "anchors": {}, "label": "tip", "notes": "value_usefulness=useful; tags=timing"}

## Interfaces and Dependencies

Add a new package `cookimport/labelstudio` with the following modules and interfaces:

- `cookimport/labelstudio/models.py`:
  - `ChunkRecord` dataclass with fields: `chunk_id`, `chunk_level`, `chunk_type`, `text_raw`, `text_display`, `source_file`, `book_id`, `pipeline_used`, `location`, `context_before`, `context_after`, `chunk_type_hint`, `text_hash`.
  - `ArchiveBlock` dataclass for the full extracted archive, including `index`, `text`, and location metadata (page, chapter, line, etc.).
  - `CoverageReport` dataclass for extracted vs chunked character counts and warnings.
- `cookimport/labelstudio/chunking.py`:
  - `build_extracted_archive(result: ConversionResult, raw_artifacts: list[RawArtifact]) -> list[ArchiveBlock]`.
  - `chunk_structural(result: ConversionResult, archive: list[ArchiveBlock]) -> list[ChunkRecord]`.
  - `chunk_atomic(result: ConversionResult, archive: list[ArchiveBlock]) -> list[ChunkRecord]`.
  - `compute_coverage(archive, chunks) -> CoverageReport`.
  - `normalize_display_text(text: str) -> str` (fix soft hyphens, join hyphenated line breaks, preserve line breaks).
- `cookimport/labelstudio/client.py`:
  - `LabelStudioClient(base_url: str, api_key: str)` with helper methods `get`, `post`, `delete`, and `download_json` implemented via `urllib.request`.
  - `find_project_by_title(title: str) -> dict | None`.
  - `create_project(title: str, label_config: str, description: str) -> dict`.
  - `delete_project(project_id: int) -> None`.
  - `import_tasks(project_id: int, tasks: list[dict]) -> dict` (bulk import).
  - `export_tasks(project_id: int, download_all: bool = True) -> list[dict]` (JSON export).
- `cookimport/labelstudio/label_config.py`:
  - `LABEL_CONFIG_XML` string with two required single-choice fields and one multi-choice field, using `Choices`/`Choice` tags.
  - Use Label Studio `Choices` for single and multiple choice classification and `Text` tags for data display.
- `cookimport/labelstudio/ingest.py`:
  - `run_labelstudio_import(...)` function invoked by CLI; handles archive, chunking, project creation, and task upload.
- `cookimport/labelstudio/export.py`:
  - `run_labelstudio_export(...)` function invoked by CLI; downloads export JSON and maps to labeled chunks and golden set.

Label config (XML) must include the two required fields and optional tags. Use this exact structure:

    <View>
      <Header value="Cookbook Chunk Labeling"/>
      <Text name="text_display" value="$text_display"/>
      <Text name="text_raw" value="$text_raw"/>
      <Header value="Content Type"/>
      <Choices name="content_type" toName="text_display" choice="single" required="true">
        <Choice value="tip"/>
        <Choice value="recipe"/>
        <Choice value="step"/>
        <Choice value="ingredient"/>
        <Choice value="fluff"/>
        <Choice value="other"/>
        <Choice value="mixed"/>
      </Choices>
      <Header value="Value / Usefulness"/>
      <Choices name="value_usefulness" toName="text_display" choice="single" required="true">
        <Choice value="useful"/>
        <Choice value="neutral"/>
        <Choice value="useless"/>
        <Choice value="unclear"/>
      </Choices>
      <Header value="Optional Tags"/>
      <Choices name="tags" toName="text_display" choice="multiple">
        <Choice value="technique"/>
        <Choice value="troubleshooting"/>
        <Choice value="substitution"/>
        <Choice value="timing"/>
        <Choice value="storage"/>
        <Choice value="equipment"/>
        <Choice value="food_safety"/>
        <Choice value="measurement"/>
        <Choice value="science"/>
        <Choice value="make_ahead"/>
      </Choices>
    </View>

Export mapping rules in `cookimport/labelstudio/export.py`:

- Parse Label Studio export JSON; for each task, locate the latest annotation and extract results by `from_name` (`content_type`, `value_usefulness`, `tags`).
- Save `labeled_chunks.jsonl` with the original task data plus `labels` object: `{content_type, value_usefulness, tags}`.
- For tip-eval golden set, include only atomic chunks. Map to harness labels as:
  - `tip` if `content_type == "tip"` and `value_usefulness != "useless"`.
  - `not_tip` if `content_type` is any of `recipe`, `step`, `ingredient`, `fluff`, `other`.
  - Exclude `mixed` and `unclear` from the golden set (write to `skipped.jsonl` or keep a `skipped` count in the summary).
- Preserve provenance fields (`chunk_id`, `source_file`, `location`, `pipeline_used`) in both outputs.

Change note (2026-01-28): Replaced the placeholder request text with a full ExecPlan that captures scope, interfaces, Label Studio integration details, and validation steps.

Change note (2026-01-28): Marked the plan complete and updated Progress/Outcomes after implementing Label Studio benchmark mode, docs, and tests.
