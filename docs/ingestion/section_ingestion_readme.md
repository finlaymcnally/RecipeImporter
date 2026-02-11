---
summary: "Ingestion pipeline reference: importers, job splitting, merge behavior, and known limitations."
read_when:
  - Working on ingestion/importers or job splitting
  - Debugging extraction or merge issues
  - Needing a single-source overview of the ingestion section
---

# Ingestion Section Reference

This document consolidates all prior `docs/ingestion/*` notes and ExecPlans into one reference. It is meant to be the single source of truth for how ingestion works, where the code lives, why key choices were made, and what is known to be imperfect.

## Scope and Inputs/Outputs

Ingestion is the stage that reads source files and converts them into `RecipeCandidate` objects, along with tips, topics, raw artifacts, and reports.

- **Input folder:** `data/input`
- **Output root:** `data/output` (default for `stage` and `inspect`)
- **Benchmark root:** `data/golden` (default for Label Studio import/export/benchmark)
- **Output structure:** Each run creates a timestamped folder (e.g., `2026-02-11_14.30.22/`) containing:
  - `intermediate drafts/`: RecipeSage JSON-LD (raw extraction)
  - `final drafts/`: RecipeDraftV1 format
  - `tips/`: Tip/knowledge snippets and `tips.md` summary
  - `topics/`: Standalone topic candidates (for evaluation/prefiltering)
  - `chunks/`: Knowledge chunks and `chunks.md` summary
  - `raw/`: Raw artifacts (text, images) for audit
  - `reports/`: Conversion report JSON (including timing and stats)

## Code Map (Where Things Live)

- **CLI entrypoint and orchestration:** `cookimport/cli.py`
- **Worker execution:** `cookimport/cli_worker.py`
- **Importer registry:** `cookimport/plugins/registry.py`
- **Importer implementations:** (`cookimport/plugins/`)
  - `excel.py`: Excel (.xlsx) layouts (Wide, Tall, Template)
  - `epub.py`: EPUB (.epub) segmentation
  - `pdf.py`: PDF (.pdf) with column clustering and OCR fallback
  - `text.py`: Plain text, Markdown, and Word (.docx)
  - `paprika.py`: Paprika (.paprikarecipes) imports
  - `recipesage.py`: RecipeSage JSON normalization
- **OCR implementation:** `cookimport/ocr/doctr_engine.py`
- **Staging & Writing:** (`cookimport/staging/`)
  - `pdf_jobs.py`: Job planning and ID reassignment for split jobs
  - `writer.py`: Output writers for all artifacts
  - `draft_v1.py`: Recipe candidate to Draft V1 conversion
  - `jsonld.py`: Recipe candidate to JSON-LD conversion
- **Core models:** `cookimport/core/models.py`
- **Shared parsing utilities:** `cookimport/parsing/`

## Stage/Worker Flow

The `stage` CLI prepares jobs and dispatches them to workers, then merges split results in the main process.

1. **Job Planning:** `cookimport/cli.py` plans jobs. One per file, or multiple page-range/spine-range jobs for large PDFs/EPUBs.
2. **Dispatch:** Uses `ProcessPoolExecutor` to call `cookimport/cli_worker.py`.
3. **Execution:** Workers resolve importers, run conversion, apply limits, and build chunks.
4. **Progress:** Updates flow through a `multiprocessing.Manager().Queue()` to the live dashboard.
5. **Merge:** For split jobs, the main process merges `ConversionResult` payloads, rewrites recipe IDs to a global sequence, and updates tip references.
6. **Final Write:** Outputs are written via `cookimport/staging/writer.py`.

## Supported Formats and Behaviors

| Format | Importer | Status | Notes |
| --- | --- | --- | --- |
| Excel (.xlsx) | `excel.py` | Complete | Wide/Tall/Template layout detection |
| EPUB (.epub) | `epub.py` | Complete | Spine extraction, block-based segmentation |
| PDF (.pdf) | `pdf.py` | Complete | Column clustering, OCR fallback |
| Text (.txt, .md) | `text.py` | Complete | Multi-recipe splitting, YAML frontmatter |
| Word (.docx) | `text.py` | Complete | Table extraction, paragraph parsing |
| Paprika (.paprikarecipes) | `paprika.py` | Complete | ZIP of gzip JSON |
| RecipeSage (.json) | `recipesage.py` | Complete | Schema validation + normalization |

## Importer Details

### Excel (`cookimport/plugins/excel.py`)
- **Layouts:** Wide (one row/recipe), Tall (multi-row/recipe), Template (fixed labels).
- **Behaviors:** Header row detection, combined column support, merged cell handling.

### EPUB (`cookimport/plugins/epub.py`)
- **Flow:** Spine parse → Linear blocks → Signal enrichment → Segmentation.
- **Segmentation:** Anchors on yield (`Serves 4`) and ingredient headers. Backtracks for titles.
- **Notes:** ATK-style relies on yield anchors. Variant sections stay with parents.

### PDF (`cookimport/plugins/pdf.py`)
- **Flow:** PyMuPDF text extract → Column clustering → Block pipeline.
- **Column Detection:** Gap threshold (~50pts) indicates breaks.
- **OCR Fallback:** docTR (CRNN + ResNet) for scanned pages or low-text results.

### Text and Word (`cookimport/plugins/text.py`)
- **Splitting:** Headerless files split on yield phrases; headered files split on `#` or `##`.
- **Word Tables:** Maps header row to recipe fields; each row is a recipe.

## Shared Text Processing (`cookimport/parsing/`)
- **Cleaning (`cleaning.py`):** NFKC normalization, Mojibake repair, hyphenation repair.
- **Signals (`signals.py`):** Feature detection (`is_heading`, `is_ingredient_likely`, etc.).
- **Patterns (`patterns.py`):** Shared regexes for quantities, units, time, and yield.

## Job Splitting and Merge

Large PDFs and EPUBs are split when `--workers > 1`.
- **PDF Slicing:** Uses `--pdf-pages-per-job`. Slices are 0-based page ranges.
- **EPUB Slicing:** Uses `--epub-spine-items-per-job`. Slices are 0-based spine indices.
- **Merge Logic:** Main process sorts recipes by provenance (`start_page`/`start_spine`), rewrites IDs to `c0..cN`, and updates tip `sourceRecipeId` links.
- **Raw Artifacts:** Written to `.job_parts/<slug>/job_N/raw/` then moved to final `raw/` on merge.

## Run Organization and Standardization

### Default Output Roots
Routine usage no longer creates a top-level `staging/` directory in the project root.
- `cookimport stage` and `cookimport inspect` default to `data/output`.
- Interactive `output_dir` defaults to `data/output`.
- Label Studio flows (import/export/benchmark) default to `data/golden`.
- *Why:* To keep the project root clean and organize artifacts by intent (output vs. golden/ground-truth).

### Standardized Run Timestamps
Run folders use a standardized format: `YYYY-MM-DD_HH.MM.SS` (e.g., `2026-02-11_14.30.22`).
- *Note:* While some earlier documentation suggested `YYYY-MM-DD_HH:MM:SS`, colons are avoided in filenames for cross-platform compatibility (specifically Windows/NTFS).
- This format is used consistently across stage outputs, Label Studio runs, and benchmark evaluations.

## Known Limitations and Gotchas

- **EPUB Boundaries:** Split jobs may break recipes that span spine boundaries (no current overlap handling).
- **PDF Ordering:** PyMuPDF default ordering is tiled; clustering is essential for multi-column layouts.
- **OCR Noise:** Can misread `l`/`I` as quantities.
- **Serial Fallback:** If `ProcessPoolExecutor` fails (e.g., permission issues), the CLI falls back to serial execution.
- **Mapping/Inspect:** `stage` does not automatically call `importer.inspect` in non-split paths; it uses a provided `MappingConfig`.

## Historical Notes (Why Things Look This Way)

- **2026-02-11:** Standardized output roots to `data/output` and `data/golden` to remove top-level `staging/` noise. Standardized timestamps to `YYYY-MM-DD_HH.MM.SS`.
- **2026-02-10:** Aligned parsing lanes; `writer.py` treats legacy `NARRATIVE` lane as noise in reports.
- **2026-02-02:** PDF and EPUB page/spine splitting implemented with ID rewriting and merge logic.
- **2026-02-01:** Established performance baseline and added timing scaffolds to the pipeline.
- **2026-01-31:** Implemented step-ingredient splitting for complex instruction parsing.
- **2026-02-01 (Earlier):** EPUB split plan initially considered overlap/owned-ranges, but simplified spine-range splitting was implemented instead. Boundary errors may require revisiting the overlap plan.

## Quick Debug Checklist
1. Check `registry.py` for importer detection.
2. Verify `page_count` or `spine_count` in inspection if splitting fails.
3. Check `.job_parts` for leftovers if output seems partial or duplicated.
4. Verify ID rewriting in `pdf_jobs.py:reassign_recipe_ids` if links are broken.
