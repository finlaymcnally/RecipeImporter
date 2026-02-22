---
summary: "Ingestion architecture/build/fix-attempt log to avoid repeated dead ends and circular debugging."
read_when:
  - When you are going in multi-turn circles on ingestion behavior or implementation
  - When the human says "we are going in circles on this"
  - When you need prior architecture versions, build attempts, or failed fixes before trying another change
---

# Ingestion Log

Read the current runtime docs first in `docs/03-ingestion/03-ingestion_readme.md`. Use this log to understand prior attempts and avoid retrying failed paths.

## Consolidation Context

The prior ingestion README consolidation pass described `docs/03-ingestion` as a unified source of truth (recorded as of 2026-02-16, re-verified on 2026-02-19).

It combined and superseded:
- `docs/03-ingestion/2026-02-12_10.17.19-import-pipeline-convergence.md`
- `docs/03-ingestion/2026-02-12-unstructured-epub-adapter.md`
- `docs/03-ingestion/03-ingestion_README.md`

## Document Chronology (Source Merge Order)

Order below is based on source document filenames/timestamps and last consolidation date:
1. `2026-02-12_10.17.19-import-pipeline-convergence.md`
2. `2026-02-12-unstructured-epub-adapter.md`
3. `03-ingestion_README.md` (later consolidation pass, modified on 2026-02-15)
4. `docs/understandings/2026-02-16_13.02.32-markitdown-extractor-split-contract.md` (merged)
5. `docs/understandings/2026-02-16_14.00.37-unstructured-v2-body-document-and-epub-option-propagation.md` (merged)
6. `docs/understandings/IMPORTANT-UNDERSTANDING-epub-extractor-types.md` (merged, undated durable reference)
7. `docs/03-ingestion/03-ingestion_readme.md` (consolidated and re-verified on 2026-02-19)

## Historical Attempts (Preserve To Avoid Rework Loops)

### 2026-02-12 10:17:19: Pipeline convergence note

Established and still true:
- Importers differ early (block-first vs record-first vs structured-first).
- They converge at `ConversionResult` and downstream writer pipeline.
- Chunking is fed from non-recipe/topic paths post-convert.

Do not re-litigate unless code changed:
- “Should we force all importers into same early extraction model?”
- Existing design intentionally allows importer-specific extraction while standardizing handoff contract.

### 2026-02-12: Unstructured EPUB adapter note

Established and still true:
- Unstructured is default EPUB extractor.
- Adapter emits traceability metadata and diagnostics JSONL artifact.
- Deterministic role assignment exists and is covered by unit tests.

Do not re-litigate unless objective evidence appears:
- “Need to revert default to legacy parser globally.”
- Current default was chosen to retain richer semantic signals and traceability.

### 2026-02-15: Prior ingestion README consolidation

Preserved decisions:
- Split-job merge architecture for PDF + EPUB.
- Main-process merge + ID rewrite strategy.
- Serial fallback for environments blocking multiprocessing.
- Raw artifact merge from temporary `.job_parts` workspace.

Known incomplete idea intentionally not implemented:
- Earlier EPUB split plan considered overlap + owned-range filtering.
- Implemented version uses straightforward spine ranges without overlap.
- If boundary errors become frequent, revisit overlap as a targeted fix, not a broad redesign.

### 2026-02-15_22.06.34: Split-merge and ID rewrite discovery map

Merged source:
- `docs/understandings/2026-02-15_22.06.34-ingestion-split-merge-and-id-rewrite-map.md`

Preserved operational details:
- Split workers write raw artifacts under `.job_parts/<workbook>/job_<index>/raw/...` and return merge payloads.
- Main-process merge sorts by source range, rewrites recipe IDs globally (`c0..cN`), then rebuilds tips/chunks once.
- Raw merge collisions are renamed with `job_<index>_...` prefixes so artifacts are not dropped.
- `.job_parts` is expected to be removed on successful merge; leftover `.job_parts` is usually merge-failure/interruption evidence and should be treated as debug signal.
- Stage builds and passes `base_mapping` for workers; worker `inspect()` is mainly a split-planning concern, not the normal non-split conversion initialization path.

### 2026-02-16_13.02.32: MarkItDown extractor split contract

Merged source:
- `docs/understandings/2026-02-16_13.02.32-markitdown-extractor-split-contract.md`

Preserved contract:
- `epub_extractor` remains the single run-setting knob across stage and benchmark prediction generation.
- `markitdown` is whole-book EPUB conversion and cannot honor spine-range split jobs.
- `auto` is resolved once before worker launch to a concrete backend; workers should only see effective backends.
- Split-planner parity must be maintained in both planners together:
  - `cookimport/cli.py:_plan_jobs(...)`
  - `cookimport/labelstudio/ingest.py:_plan_parallel_convert_jobs(...)`
- Effective worker reporting must stay honest when split capability changes:
  - `cookimport/config/run_settings.py:compute_effective_workers(...)`.
- `labelstudio_benchmark(...)` must forward selected extractor explicitly so manifests/history rows record the true extractor used.

Anti-loop note:
- Do not "fix" markitdown split errors by forcing pseudo-ranges; extractor behavior is whole-book by design.

### 2026-02-16_14.00.37: Unstructured v2 input-shape caveat + option propagation

Merged source:
- `docs/understandings/2026-02-16_14.00.37-unstructured-v2-body-document-and-epub-option-propagation.md`

Discovery preserved:
- `partition_html(..., html_parser_version=\"v2\")` can fail on normal EPUB XHTML with:
  - `No <body class='Document'> or <div class='Page'> element found in the HTML.`
- This is usually parser-v2 input-shape mismatch, not EPUB corruption.

Durable contract:
- Keep parser default at `v1` for broad compatibility.
- When parser `v2` is requested, compatibility wrapping/annotation must happen in adapter layer (`cookimport/parsing/unstructured_adapter.py`) so all flows share behavior.
- EPUB unstructured option triplet must propagate in every run-producing path (not stage only):
  - `epub_unstructured_html_parser_version`
  - `epub_unstructured_skip_headers_footers`
  - `epub_unstructured_preprocess_mode`
- These options must appear in run config, drive `C3IMP_EPUB_UNSTRUCTURED_*` runtime env vars, and be reflected in diagnostics metadata.

Debugging evidence worth preserving:
- Per-spine `raw_spine_xhtml_*.xhtml` and `norm_spine_xhtml_*.xhtml` artifacts made parser-shape failures and preprocessing effects visible quickly without reopening EPUB internals repeatedly.

### 2026-02-19_14.19.06: EPUB postprocess + health wiring map

Merged source:
- `docs/understandings/2026-02-19_14.19.06-epub-postprocess-health-wiring-map.md`

Preserved contract:
- `cookimport/plugins/epub.py:_extract_docpack(...)` is the shared join point where extractor-specific block extraction converges before downstream segmentation.
- Shared EPUB postprocess (`postprocess_epub_blocks`) applies to `legacy`/`unstructured`/`markdown`; `markitdown` intentionally bypasses this cleanup path.
- EPUB extraction health is computed from final blocks and persisted as `epub_extraction_health.json`; warning keys are promoted into `ConversionReport.warnings`.
- Spine metadata now uses typed `EpubSpineItem` records so zip-fallback and ebooklib flows apply the same nav/TOC skip logic.

Anti-loop note:
- Do not duplicate cleanup logic per extractor backend; keep common cleanup centralized in the shared join point.

### 2026-02-19_14.55.51: auto extractor resolution + scoped env overrides

Merged source:
- `docs/understandings/2026-02-19_14.55.51-auto-extractor-resolution-and-env-scope.md`

Preserved rule:
- Resolve `auto` once per EPUB in parent orchestration, then pass effective backend (`legacy|unstructured|markdown`) explicitly to worker jobs.
- Persist requested/effective selection rationale for reproducibility (`epub_extractor_auto.json` and run-config/report surfaces).
- Prediction generation must scope and restore `C3IMP_EPUB_*` env vars to prevent cross-run/test drift.

Rejected path:
- Setting extractor env vars globally without restoration causes later runs/tests to inherit stale settings and produce inconsistent behavior.

### 2026-02-20_12.31.31: direct-probe importer-init rule

Merged source:
- `docs/understandings/2026-02-20_12.31.31-auto-probe-overrides-init.md`

Preserved discovery:
- Auto-selection probe path uses direct `_extract_docpack(...)` calls and does not execute `convert(...)`.
- Runtime fields consumed by `_extract_docpack(...)` (for example `_overrides`) must be initialized in `EpubImporter.__init__`.

Concrete regression captured:
- `stage --epub-extractor auto` failed on real runs with missing `_overrides`.
- Fix was to initialize `self._overrides = None` in importer constructor.
- Regression test anchor:
  - `tests/test_epub_auto_select.py::test_select_epub_extractor_auto_real_importer_supports_direct_probe`

### Undated durable reference: EPUB extractor mode semantics

Merged source:
- `docs/understandings/IMPORTANT-UNDERSTANDING-epub-extractor-types.md`

Preserved baseline:
- Extractor modes are mutually exclusive (`unstructured`, `legacy`, `markdown`, `auto`, `markitdown`) and feed one downstream segmentation pipeline.
- `markitdown` remains whole-book only (no spine-range split support).
- `auto` uses deterministic sampled-spine scoring and persists rationale artifacts for auditability.
