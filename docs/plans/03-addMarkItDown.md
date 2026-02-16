---
summary: "ExecPlan and implementation log for adding a MarkItDown EPUB extraction backend with markdown provenance."
read_when:
  - "When changing EPUB extractor backends or markdown provenance behavior"
  - "When wiring a new extractor option through run settings, stage, and benchmark prediction flows"
---

# Add MarkItDown EPUB→Markdown extraction backend to EpubImporter

This ExecPlan is a living document. The sections `Progress`, `Surprises & Discoveries`, `Decision Log`, and `Outcomes & Retrospective` must be kept up to date as work proceeds.

This document must be maintained in accordance with `PLANS.md` at the repository root. In particular: keep the plan self-contained, keep `Progress` accurate at every stopping point, and record key decisions and surprises as they happen.


## Purpose / Big Picture

EPUB ingestion is still fragile for messy spine HTML. This change adds `markitdown` as a third EPUB extractor mode (alongside existing `unstructured` and `legacy`) so the pipeline can run `EPUB -> markdown -> Block` before the existing segmentation and extraction stages.

User-visible outcome: `cookimport stage --epub-extractor markitdown <file.epub>` now writes a raw markdown artifact (`markitdown_markdown.md`), produces blocks with markdown line provenance (`md_line_start` / `md_line_end`), and records the backend in report metadata (`epubBackend`) while preserving run-config history/analytics wiring.


## Progress

- [x] (2026-02-16 04:59Z) Drafted this ExecPlan.
- [x] (2026-02-16 17:50Z) Inventory complete: confirmed insertion point at `EpubImporter._extract_docpack(...)` and existing run-setting propagation paths in `cookimport/cli.py` + `cookimport/labelstudio/ingest.py`.
- [x] (2026-02-16 17:53Z) Added MarkItDown dependency in `pyproject.toml` (`markitdown>=0.1.4,<0.2`).
- [x] (2026-02-16 17:56Z) Added prototyping smoke script `scripts/markitdown_epub_smoke.py` and confirmed conversion output on `tests/fixtures/sample.epub`.
- [x] (2026-02-16 17:58Z) Implemented deterministic markdown->block parser in `cookimport/parsing/markdown_blocks.py` with `md_line_start/md_line_end` provenance.
- [x] (2026-02-16 18:00Z) Wired MarkItDown backend into `cookimport/plugins/epub.py`, including report field `epubBackend` and raw artifact `markitdown_markdown.md`.
- [x] (2026-02-16 18:01Z) Updated CLI/config surface and pipeline-option wiring (`RunSettings` enum/validation, stage + benchmark pass-through, split planners, effective-worker derivation).
- [x] (2026-02-16 18:03Z) Added/updated tests for parser, importer, run-settings behavior, CLI output, toggle editor, and benchmark split planning.
- [x] (2026-02-16 18:05Z) Validation complete: targeted suites pass; full `pytest` run completes with 5 unrelated pre-existing fixture failures (`paprika`/`recipesage` tests).
- [x] (2026-02-16 18:05Z) Updated docs/understandings/conventions and finalized this ExecPlan as an implementation record.


## Surprises & Discoveries

- Observation: MarkItDown conversion is whole-book and has no spine-range API, so split EPUB jobs cannot be supported for `markitdown`.
  Evidence: `EpubImporter._extract_docpack(...)` now rejects `start_spine/end_spine` for `markitdown`; stage/benchmark split planners skip EPUB splitting when extractor is `markitdown`.
- Observation: Existing full-suite failures are unrelated to this feature and are fixture-path/data issues in Paprika/RecipeSage tests.
  Evidence: `pytest` run showed 5 failures in `tests/test_paprika_importer.py` and `tests/test_recipesage_importer.py` due missing files under `docs/template/examples/...`.
- Observation: MarkItDown smoke conversion on fixture EPUB returns metadata headers + markdown TOC before recipe headings.
  Evidence: `scripts/markitdown_epub_smoke.py tests/fixtures/sample.epub` preview includes title/author metadata and TOC links before `# Best Pancakes`.


## Decision Log

- Decision: Make MarkItDown an alternate EPUB extraction backend (opt-in via CLI/env) rather than replacing the current HTML-spine parser.
  Rationale: Keeps backward compatibility and allows per-file bakeoffs; avoids destabilizing existing “good” EPUBs.
  Date/Author: 2026-02-16 / ChatGPT

- Decision: Preserve traceability by storing the raw MarkItDown Markdown as a raw artifact, and attach markdown line ranges to each generated `Block`.
  Rationale: MarkItDown does not naturally expose spine/XHTML node provenance; markdown line anchoring + stored markdown keeps “100% traceability” meaningful.
  Date/Author: 2026-02-16 / ChatGPT

- Decision: Default backend remains the current EPUB extractor; MarkItDown backend is selectable and fails with a clear error if the dependency is missing.
  Rationale: Avoids surprising behavior changes and prevents silent fallbacks that make debugging harder.
  Date/Author: 2026-02-16 / ChatGPT

- Decision: Treat `markitdown` as whole-book extraction and disable EPUB split planning for this mode.
  Rationale: Split workers operate on spine ranges, but MarkItDown does not expose spine-range conversion; forcing splits would duplicate/incorrectly segment content.
  Date/Author: 2026-02-16 / ChatGPT

- Decision: Pass `epub_extractor` explicitly into benchmark prediction generation (`generate_pred_run_artifacts`/`run_labelstudio_import`) while still setting env for importer runtime.
  Rationale: Keeps run manifests/history deterministic for selected extractor and avoids env-only ambiguity in run-config construction.
  Date/Author: 2026-02-16 / ChatGPT


## Outcomes & Retrospective

Implemented and validated:
- Added `markitdown` dependency and a smoke script for quick EPUB->markdown validation.
- Added deterministic markdown parsing to blocks with line provenance metadata.
- Added MarkItDown extractor path in EPUB importer with raw markdown artifact output and report field `epubBackend`.
- Extended `epub_extractor` option surface (`unstructured|legacy|markitdown`) across run settings, stage CLI, benchmark CLI, and prediction import run-config tracking.
- Added split-planning safeguards so `markitdown` EPUB runs do not attempt spine splits, and adjusted effective-worker derivation accordingly.
- Added targeted tests that pass for the new behavior.

Remaining/known gap:
- Repository-wide `pytest` currently has 5 unrelated fixture/data failures (`paprika`/`recipesage`) that predate this change and were left untouched.


## Context and Orientation

This repository is a Python 3.12 project called `cookimport`. It ingests recipe sources of multiple formats via a plugin system. Each importer plugin lives under `cookimport/plugins/` and implements three core entry points:

1) `detect(path) -> float` returns confidence (0.0–1.0) that it can handle the file.
2) `inspect(path) -> WorkbookInspection` returns a quick analysis / mapping stub.
3) `convert(path, mapping, progress_callback) -> ConversionResult` performs full extraction.

For EPUB specifically, `cookimport/plugins/epub.py` contains `EpubImporter`, which currently parses EPUB spine documents and HTML blocks (e.g., `h1..h6`, `p`, `li`) into a linear list of `Block` objects. A `Block` is the low-level text unit used throughout the pipeline (think: one paragraph, heading line, or list item, plus metadata). Downstream, blocks get “signals” added in `cookimport/parsing/signals.py` (booleans like `is_heading`, `starts_with_quantity`, etc.), and segmentation heuristics turn block ranges into `RecipeCandidate` records (`cookimport/core/models.py`). Later writers emit intermediate JSON-LD and final cookbook3 drafts.

This ExecPlan adds another way to produce the same `Block` stream for EPUB: instead of parsing EPUB HTML directly, we convert the entire EPUB into Markdown using MarkItDown, then parse Markdown into blocks. Everything downstream should remain unchanged: the importer still returns `ConversionResult`, segmentation still runs, writers still run.

Terminology used in this plan:

- “Backend” means: a distinct extraction implementation that produces blocks for the EPUB importer. Backends must produce the same kind of `Block` stream so the rest of the pipeline can treat them identically.
- “Markdown provenance” means: each block includes `md_line_start` / `md_line_end` indices pointing to where that block came from within the markdown artifact we store.


## Plan of Work

You will implement the MarkItDown EPUB→Markdown backend in small, verifiable milestones.

First, you will inspect the existing EPUB importer to identify how it currently creates blocks (the “existing extractor paths (unstructured/legacy)” backend). You will not change existing behavior yet.

Second, you will add MarkItDown as a dependency. You will add a tiny, repo-local smoke test script (prototyping) that converts a synthetic EPUB to Markdown and prints a short preview. This de-risks integration before touching the importer.

Third, you will implement a Markdown-to-Blocks converter. This converter must be deterministic and must classify blocks into the same “types” that the pipeline already understands (at minimum: headings, list items, paragraphs). It must also attach markdown line ranges to blocks and carry a backend identifier into block metadata.

Fourth, you will wire this backend into `EpubImporter.convert()`. The importer will be able to choose between the existing extraction logic and the MarkItDown backend based on a new configuration surface (CLI flag + env var). The default must remain the existing extractor so existing workflows behave the same.

Fifth, you will add tests. Tests must include: (a) unit tests for markdown parsing to blocks, and (b) an integration test that runs the importer on a generated EPUB and asserts that MarkItDown backend produces expected blocks and stores the markdown artifact. Finally, you will run an end-to-end manual `cookimport stage` run on a real EPUB and capture proof.


## Milestones

### Milestone 1: Repo reconnaissance and minimal insertion design

At the end of this milestone, you will know exactly where in `cookimport/plugins/epub.py` to hook a backend switch without touching segmentation or writers, and you will have identified any existing utilities you can reuse (for example: if the text/markdown importer already has markdown parsing utilities).

Work:

- Locate the existing EPUB importer:
  - Open `cookimport/plugins/epub.py`.
  - Find the `EpubImporter` class and the `convert()` method.
  - Find the function(s) that extract blocks (the plan assumes a helper like `_extract_docpack(...)` exists; confirm the real name and signature).

- Identify existing “block typing” conventions:
  - Open `cookimport/core/blocks.py` and `cookimport/core/models.py` to see what fields `Block` expects and what values are valid for `Block.type` (or equivalent).
  - Search the codebase for `Block(` construction to see typical values for `type` and `features`.

- Search for any existing markdown parsing:
  - Open `cookimport/plugins/text.py` and look for markdown header parsing or markdown-to-block logic.
  - If an existing helper exists, plan to reuse or extract it to a shared module rather than duplicating logic.

Proof:

- In `Artifacts and Notes`, record a short note listing:
  - The exact helper/function you will extend in `EpubImporter` (name + where it lives).
  - The set of `Block.type` values you will emit from the markdown parser (exact strings/enums).
  - Where raw artifacts are written today and how you will add the new markdown artifact (path and mechanism).


### Milestone 2: Add MarkItDown dependency + smoke test (prototyping)

At the end of this milestone, a developer can run a local command that converts an EPUB to Markdown via MarkItDown and prints a preview, without involving the pipeline.

Key MarkItDown facts you must embed in code/comments (do not rely on external docs at runtime):

- The package name is `markitdown`.
- The Python API is:

  - `from markitdown import MarkItDown`
  - `md = MarkItDown(enable_plugins=False)` (keep plugins off for deterministic behavior)
  - `result = md.convert("path/to/file.epub")`
  - `markdown = result.text_content`

Dependency change:

- Decide how this repository manages dependencies:
  - If the repo has `pyproject.toml`, add `markitdown==0.1.4` (or a pinned compatible range like `>=0.1.4,<0.2`) under the main dependencies or a clearly named optional dependency group (recommended: `markitdown`).
  - If the repo uses `requirements.txt` / `requirements-dev.txt`, add the pin there instead.

You are allowed to make this dependency optional, but you must then ensure the CLI and tests either install the extra or skip gracefully with a clear message. If you make it required, tests and the MarkItDown backend should work out of the box.

Smoke test script:

- Create a new script at `scripts/markitdown_epub_smoke.py` (create `scripts/` if it does not exist).
- The script must:
  1) Accept a path to an `.epub` as the only argument.
  2) Convert it to markdown using MarkItDown (plugins disabled).
  3) Print:
     - total markdown character count
     - first ~30 lines of markdown
- The script must exit non-zero with a friendly error if:
  - the path is missing or not an `.epub`
  - MarkItDown is not installed

Proof:

- Run:

    (repo root)$ python -m pip install -e .
    (repo root)$ python scripts/markitdown_epub_smoke.py data/input/<some>.epub

- Copy a short transcript into `Artifacts and Notes` showing markdown output is produced.


### Milestone 3: Implement Markdown → Block stream conversion

At the end of this milestone, you will have a deterministic function that takes markdown text and returns a list of `Block` objects that look like the existing EPUB blocks (heading blocks, list item blocks, paragraph blocks), with per-block markdown line provenance.

Implementation approach:

- Add a new module (recommended) `cookimport/parsing/markdown_blocks.py`. If you found an existing markdown parser in Milestone 1, prefer extracting it into a shared module and using it from both places.

- Define a single entry point:

  - `def markdown_to_blocks(markdown_text: str, *, source_path: Path, extraction_backend: str) -> list[Block]:`

Parsing rules (keep them simple and deterministic):

- Split markdown into lines and keep 1-based line numbers for provenance.
- Headings:
  - A line that matches `^#{1,6}\s+` is a heading.
  - Heading level is the number of `#` characters.
  - Create one `Block` with `type` set to the project’s heading type (whatever Milestone 1 determined).
  - Store `heading_level` and `md_line_start==md_line_end==line_number` in block metadata (`features` or the repo’s equivalent).
- List items:
  - Lines that match unordered list markers (`- `, `* `, `+ `) or ordered list (`^\d+\.\s+`) are list items.
  - Create one `Block` per list item line, with `type` set to the project’s list-item type (likely the same used for `<li>` in EPUB HTML extraction).
  - Store `md_line_start/md_line_end`.
- Paragraphs:
  - Accumulate consecutive non-empty lines that are not headings/list items into a paragraph “chunk”.
  - Break paragraphs on blank lines.
  - Create one `Block` per paragraph chunk.
  - Set `md_line_start` and `md_line_end` to the first and last line numbers included.
- Ignore (or treat as paragraph text) markdown constructs you do not need yet (tables, blockquotes, links). Do not attempt to “render” markdown; keep raw text in `Block.text`.

Every `Block` produced by this function must include:

- `features["extraction_backend"] = extraction_backend` (for this backend, value is `markitdown`)
- a stable provenance anchor: `features["md_line_start"]`, `features["md_line_end"]`
- `source_path` (or whatever the repo uses to store the original path/file hash)

Proof:

- Add unit tests for `markdown_to_blocks` that feed a small markdown string with:
  - a title heading
  - an “Ingredients” heading + 3 list items
  - an “Instructions” heading + 2 numbered items
- Assert:
  - correct block count
  - headings have correct levels
  - list items are preserved as separate blocks
  - markdown line provenance is correct


### Milestone 4: Wire MarkItDown backend into `EpubImporter`

At the end of this milestone, `EpubImporter.convert()` can generate the block stream via existing extractors (`unstructured` / `legacy`) or the new MarkItDown backend (`markitdown`), and it records which backend was used plus a raw markdown artifact for inspection.

Backend selection design:

- Use explicit backend identifiers that match `epub_extractor` values:
  - `unstructured`
  - `legacy`
  - `markitdown`

- Add a selection mechanism with a clear precedence order:

  1) If the user explicitly requested a backend via CLI flag (implemented in Milestone 5), use it.
  2) Else if an environment variable is set, use it.
  3) Else default to `unstructured` (current default behavior).

Environment variable:

- Use `C3IMP_EPUB_EXTRACTOR` with allowed values:
  - `unstructured`
  - `legacy`
  - `markitdown`

Implementation steps in `cookimport/plugins/epub.py`:

- Refactor existing extraction logic into backend-specific helpers, without behavior change:
  - `_extract_docpack_with_ebooklib(...)`
  - `_extract_docpack_with_zip(...)`

- Implement MarkItDown extraction helper:

  - `_extract_docpack_markitdown(...) -> (blocks, raw_artifacts, warnings)`

  This helper must:
  1) Convert the EPUB to markdown using MarkItDown with plugins disabled.
  2) Parse markdown into `Block`s using `markdown_to_blocks(...)`.
  3) Store the raw markdown as a raw artifact (recommended: write a `.md` file into the run’s `rawArtifacts/` folder and also include the path in the raw artifacts manifest, rather than stuffing huge markdown into JSON).
  4) Ensure every block includes the backend tag and markdown line provenance.

- Preserve existing output contracts:
  - The rest of `convert()` should still:
    - enrich signals on blocks
    - run candidate detection and field extraction
    - return a `ConversionResult` as before

Reporting:

- Add a single explicit field to the per-file conversion report indicating the backend used (`epubBackend` in report JSON).

Failure modes:

- If the user explicitly selects `markitdown` but `markitdown` cannot be imported, raise a clear exception that explains how to install the dependency.
- Do not silently fall back to existing extractor paths (unstructured/legacy) when `markitdown` was explicitly requested; silent fallback makes debugging impossible.

Proof:

- Run `cookimport stage` on an EPUB with the env var forced:

    (repo root)$ C3IMP_EPUB_EXTRACTOR=markitdown cookimport stage data/input/<book>.epub

- Confirm in the output folder:
  - a markdown artifact exists (e.g., `raw/epub/<hash>/markitdown_markdown.md`)
  - the blocks JSON artifact exists and includes `extraction_backend=markitdown`
  - the conversion report includes the backend name


### Milestone 5: Add CLI switch for EPUB extractor backend

At the end of this milestone, a user can select the backend without environment variables.

Implementation:

- Locate the Typer CLI command for stage (`cookimport stage <path>`). The architecture doc suggests stage orchestration lives around `cli_worker.stage_one_file(...)`.
- Add an option to the stage command:

  - `--epub-extractor [unstructured|legacy|markitdown]`

- Thread that option through to the importer call in a way consistent with the codebase:
  - If there is already a “run context” or “conversion options” object passed around, add `epub_extractor` to it.
  - If not, it is acceptable to set a field on the mapping stub for EPUB runs (since `convert(path, mapping, ...)` already accepts `mapping`).
  - As a last resort, you can set the env var inside the CLI process before calling conversion, but prefer explicit Python-level wiring so library callers don’t need env vars.

Proof:

- Run:

    (repo root)$ cookimport stage --epub-extractor markitdown data/input/<book>.epub

- Verify artifacts and report match Milestone 4’s proof, and that running without the flag continues to use the existing backend.


### Milestone 6: Tests and end-to-end acceptance

At the end of this milestone, the new backend is covered by tests and proven working on at least one real EPUB.

Tests:

1) Unit tests for `markdown_to_blocks` (Milestone 3).

2) Importer-level integration test:
   - Create a synthetic EPUB during the test run (do not commit binary fixtures unless necessary).
   - Use `ebooklib` (already a project dependency) to generate an EPUB containing:
     - `# Pancakes` (title)
     - `## Ingredients` + list items like `- 1 cup flour`
     - `## Instructions` + numbered steps like `1. Mix…`
   - Run the EPUB importer conversion with MarkItDown backend forced.
   - Assert:
     - blocks include headings/list items as separate blocks
     - every block has `extraction_backend == "markitdown"`
     - markdown artifact was written and contains the recipe text

3) CLI smoke integration (optional but recommended if the repo already tests Typer commands):
   - Use Typer’s CLI test runner to invoke `cookimport stage --epub-extractor markitdown <tmp.epub>`.
   - Assert exit code is 0 and output folder contains the markdown artifact.

End-to-end manual acceptance:

- Pick one real-world EPUB that previously extracted poorly.
- Run both backends and compare at least:
  - number of extracted blocks
  - presence of headings and list items
  - whether ingredient lines are cleanly separated

Commands:

    (repo root)$ cookimport stage data/input/bad_book.epub
    (repo root)$ cookimport stage --epub-extractor markitdown data/input/bad_book.epub

Record a short “before vs after” snippet in `Artifacts and Notes` (block counts and the first few blocks is enough).


## Concrete Steps

All commands below assume you are in the repository root directory.

1) Install the project in editable mode and add MarkItDown dependency.

- First, inspect dependency mechanism:

    (repo root)$ ls
    (repo root)$ ls pyproject.toml requirements.txt requirements-dev.txt setup.cfg setup.py

- Then modify the appropriate file to include:

    markitdown==0.1.4

  If your dependency system prefers ranges, use:

    markitdown>=0.1.4,<0.2

- Install:

    (repo root)$ python -m pip install -e .

  If you made MarkItDown an optional extra, install:

    (repo root)$ python -m pip install -e ".[markitdown]"

2) Run the MarkItDown smoke test.

    (repo root)$ python scripts/markitdown_epub_smoke.py data/input/<some>.epub

Expected output should include “chars:” and a preview of markdown headings/lists.

3) Run unit tests.

Preferred:

    (repo root)$ python -m pytest

If the repo uses a different runner, find it in `pyproject.toml` / `Makefile` / CI config and use that. Update this section once you confirm the canonical test command.

4) Run end-to-end stage for manual verification:

    (repo root)$ cookimport stage --epub-extractor markitdown data/input/<book>.epub


## Validation and Acceptance

This change is accepted only when all of the following are true:

- The project can be installed and run with MarkItDown available (dependency resolved).
- There is a deterministic Markdown→Blocks converter with unit tests, and those tests pass.
- `EpubImporter` can run with MarkItDown backend selected and produces:
  - a `Block` stream where headings and list items are separate blocks
  - per-block backend tag and markdown line provenance
  - a raw markdown artifact written to the output run folder
  - a report or manifest field indicating the backend used
- The default run (no flag, no env var) continues to use the existing EPUB extraction behavior.
- Targeted tests for this feature pass; full-suite failures (if any) are triaged and documented as unrelated.


## Idempotence and Recovery

- Dependency installation is idempotent. Re-running `pip install -e .` is safe.
- `cookimport stage` should remain safe to run multiple times; it should write to a new timestamped output folder and not overwrite previous runs.
- If MarkItDown conversion fails on a specific EPUB, you must surface the exception clearly and still allow users to run the existing unstructured/legacy backends unchanged.
- If you add a report field, keep it backward compatible by giving it a default value for old paths and ensuring Pydantic models can load existing reports.


## Artifacts and Notes

Smoke script proof:

    (repo root)$ python scripts/markitdown_epub_smoke.py tests/fixtures/sample.epub
    chars: 439
    lines: 40
    preview:
    **Title:** Sample Cookbook
    ...
    # Best Pancakes
    ...

Manual stage proof:

    (repo root)$ cookimport stage tests/fixtures/sample.epub --out /tmp/recipeimport_markitdown_demo --workers 1 --epub-split-workers 4 --epub-extractor markitdown
    Processing 1 file(s) as 1 job(s) using 1 workers...
    ✔ sample.epub: 2 recipes, 0 tips (0.46s)
    Run: /tmp/recipeimport_markitdown_demo/2026-02-16_13.05.08

Artifact/report checks:

    /tmp/recipeimport_markitdown_demo/2026-02-16_13.05.08/raw/epub/<hash>/markitdown_markdown.md
    sample.excel_import_report.json -> "epubBackend": "markitdown"
    sample.excel_import_report.json -> "runConfig": {"epub_extractor": "markitdown", "effective_workers": 1, ...}
    raw/.../full_text.json -> block features include extraction_backend=markitdown, md_line_start, md_line_end

Targeted test proof:

    (repo root)$ pytest tests/test_markdown_blocks.py tests/test_epub_importer.py tests/test_labelstudio_ingest_parallel.py tests/test_cli_output_structure.py tests/test_toggle_editor.py tests/test_run_settings.py tests/test_labelstudio_benchmark_helpers.py
    63 passed in 4.39s

Full-suite note:

    (repo root)$ pytest
    378 passed, 5 failed (existing fixture-path failures in paprika/recipesage tests; unrelated to MarkItDown changes)


## Interfaces and Dependencies

Dependencies:

- Add `markitdown` (Microsoft MarkItDown) as `>=0.1.4,<0.2`.
- Do not enable MarkItDown plugins by default. Use `MarkItDown(enable_plugins=False)` to preserve determinism.

New/updated interfaces:

1) Markdown conversion wrapper (`cookimport/parsing/markitdown_adapter.py`):

    def convert_path_to_markdown(path: Path) -> str:
        """
        Convert the file at `path` to Markdown using MarkItDown, returning Markdown text.
        Must raise a clear, user-actionable exception if markitdown is missing.
        Must not use LLM features or plugins.
        """

2) Markdown-to-blocks converter (recommended location: `cookimport/parsing/markdown_blocks.py`):

    def markdown_to_blocks(markdown_text: str, *, source_path: Path, extraction_backend: str) -> list[Block]:
        """
        Deterministically parse markdown into the project’s Block stream.
        Must populate per-block md_line_start/md_line_end and extraction_backend metadata.
        """

3) EPUB importer backend selection (`cookimport/plugins/epub.py`):

- `EpubImporter.convert()` must select between:
  - existing extractor paths (`unstructured` / `legacy`)
  - the new MarkItDown backend

- It must record which backend was used in the run artifacts/report.

CLI surface:

- Add a stage option `--epub-extractor` with values `unstructured`, `legacy`, and `markitdown`.
- Default remains `unstructured` (or the current behavior if it already has a default).

No LLM wiring is part of this plan. The MarkItDown usage in this plan is strictly “EPUB → Markdown” conversion, with plugins off and no LLM clients configured.


---

Plan change note (required when revising): Updated to reflect completed implementation (MarkItDown backend, run-settings wiring, split-planning constraints, tests, and docs updates).
