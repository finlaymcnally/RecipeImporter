---
summary: "Ingestion architecture/build/fix-attempt log to avoid repeated dead ends and circular debugging."
read_when:
  - When you are going in multi-turn circles on ingestion behavior or implementation
  - When the human says "we are going in circles on this"
  - When you need prior architecture versions, build attempts, or failed fixes before trying another change
---

# Ingestion Log

Read `docs/03-ingestion/03-ingestion_readme.md` first. This file is only for active anti-loop notes that still explain current ingestion behavior.

## Consolidation Note

`docs/03-ingestion` intentionally keeps only:
- `docs/03-ingestion/03-ingestion_readme.md`
- `docs/03-ingestion/03-ingestion_log.md`

If you need older archaeology than the notes below, use `git log` / `git show`.

## Historical Attempts Worth Keeping

### 2026-02-12: Source-first convergence

Still true:
- importers can differ early
- they converge at source-first `ConversionResult`
- downstream staging owns recipe and non-recipe authority

Anti-loop note:
- do not try to force every importer into the same early extraction shape just to make the architecture feel cleaner

### 2026-02-15: Split-merge architecture

Still true:
- split workers write raw artifacts under `.job_parts/<workbook>/job_<index>/raw/...`
- the main process merges successful job payloads once per source file
- successful merges remove `.job_parts/<workbook>`
- leftover `.job_parts` is failure/interruption evidence and should be treated as a debugging artifact

Anti-loop note:
- source-job merge is the first seam to inspect when split outputs look shifted, duplicated, or partially missing

### 2026-02-16: MarkItDown split contract

Still true:
- `markitdown` is a whole-book EPUB extractor
- it cannot honor spine-range split jobs
- split-planning rules must stay aligned anywhere EPUB jobs are planned

Anti-loop note:
- do not fake range support for `markitdown`; the correct fix is to keep planner/runtime behavior honest

### 2026-02-16: Unstructured parser-v2 caveat

Still true:
- parser-v2 failures can come from input-shape mismatch, not EPUB corruption
- unstructured parser/preprocess options must propagate through run settings and runtime env vars together
- raw spine XHTML artifacts are the fastest way to debug parser-shape failures

Anti-loop note:
- if `v2` breaks on otherwise normal books, inspect adapter normalization and raw/norm XHTML artifacts before changing extractor defaults

### 2026-02-19: Shared EPUB join point

Still true:
- `cookimport/plugins/epub.py:_extract_docpack(...)` is the main join point where extractor-specific block extraction converges
- shared cleanup belongs in the shared post-extraction path, not copied into each extractor
- `epub_extraction_health.json` plus promoted warning keys are part of the active debug surface

Anti-loop note:
- when extractor outputs differ, debug extractor-specific block shape first; do not fork downstream boundary logic per extractor

### 2026-02-22: Progress liveness

Still true:
- CLI liveness is callback-driven
- long phases need explicit progress messages or the spinner looks frozen
- elapsed-time suffixes are a UI aid only, not a data-contract change

Anti-loop note:
- if users report “it hangs after candidate extraction,” inspect callback coverage before changing worker orchestration

### 2026-02-22: Split-run merged `full_text.json`

Still true:
- split jobs already emit per-job `full_text`
- merge must rebuild one workbook-level `raw/.../full_text.json`
- offsets must match merged canonical block order so downstream first-stage provenance stays aligned

Anti-loop note:
- if split-run provenance or prompt windows look shifted, inspect merged `full_text.json` and offset application first

### 2026-02-25: Explicit EPUB extractor modes

Still true:
- runtime has four mutually exclusive EPUB extractor modes: `unstructured`, `beautifulsoup`, `markdown`, `markitdown`
- unstructured-only knobs must not be described as affecting other extractors
- canonical naming is `beautifulsoup`, not alternate aliases

Anti-loop note:
- if analytics or manifests split one extractor into multiple names, fix normalization/reporting before touching importer logic

### 2026-02-27: Recipe-likeness gating

Still true:
- recipe-likeness gating is deterministic
- optional recipe Codex passes do not replace the deterministic gate
- defaults must stay aligned across stage, benchmark, and run settings

Anti-loop note:
- if gating differs between entry paths, inspect run-setting defaults before retuning thresholds

### 2026-02-27: Shared section detector

Still true:
- shared section detection is the active path across Text, Excel, EPUB, and PDF
- section behavior is still deterministic and LLM-free
- `shared_v1` is the active backend contract

Anti-loop note:
- when section outputs differ between runs, compare run config and importer input shape before rewriting classifier heuristics

### 2026-02-27: WebSchema importer

Still true:
- local web ingestion is owned by a dedicated `webschema` importer
- selection is still registry score-based, not a forced stage `--pipeline`
- `.json` overlap with RecipeSage is resolved by guarded detection

Anti-loop note:
- if a schema-like `.json` file routes incorrectly, debug detection precedence before broadening either importer

### 2026-02-27: Shared multi-recipe splitter

Still true:
- the active shared splitter surface is `multi_recipe_splitter=off|rules_v1`
- Text, EPUB, and PDF use the same shared splitter module
- `multi_recipe_split_trace` is first-line evidence when boundaries are unexpectedly accepted or rejected

Anti-loop note:
- read trace output before changing thresholds or adding importer-specific split heuristics

### 2026-02-28: Deterministic EPUB/PDF pattern filtering

Still true:
- EPUB and PDF both run shared deterministic pattern detection
- suppression must stay visible through diagnostics and non-recipe preservation
- `pattern_diagnostics.json` is part of the active evidence contract

Anti-loop note:
- do not “clean up” false positives by silently deleting suppressed text

### 2026-03-04: Shared line-role inflight resolution

Still true:
- line-role inflight defaults are resolved in shared ingestion seams, not only in one CLI wrapper
- split context can change the default inflight choice

Anti-loop note:
- if line-role concurrency differs by entry path, debug shared ingestion resolution before changing command-specific wrappers
