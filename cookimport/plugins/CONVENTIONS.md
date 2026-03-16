# Ingestion Split/Merge Conventions

Durable split/merge and extraction contracts across importers, worker payloads, and merge orchestration.

## Ingestion Split/Merge Rule

- Split PDF/EPUB workers write raw artifacts to `.job_parts/<workbook>/job_<index>/raw`, then the main process merges IDs/outputs and moves raw artifacts into run `raw/`.
- `epub_extractor=markitdown` is intentionally whole-book only: do not split EPUB by spine ranges for this extractor.
- `epub_extractor=markdown` is spine-range capable and should stay split-compatible; `markitdown` remains the whole-book markdown path.
- Unstructured EPUB diagnostics now include both raw and normalized spine XHTML artifacts (`raw_spine_xhtml_*.xhtml`, `norm_spine_xhtml_*.xhtml`) in `raw/epub/<source_hash>/`; keep both when changing EPUB diagnostics.
- EPUB HTML extractors (`beautifulsoup` + `unstructured`) must run through shared `cookimport/parsing/epub_postprocess.py` cleanup before segmentation/signals so BR/table splitting, bullet stripping, and noise filtering remain consistent.
- EPUB extraction reports should always emit raw artifact `epub_extraction_health.json` plus stable warning keys (`epub_*`) in `ConversionReport.warnings` when thresholds trip.
- EPUB/PDF standalone knowledge-block analysis should emit `task X/Y` progress updates and uses bounded container-level parallelism controlled by `C3IMP_STANDALONE_ANALYSIS_WORKERS` (default `4`).
- Unstructured HTML parser `v2` requires `body.Document`/`div.Page`-style inputs; adapter-level wrapping is required before `partition_html(..., html_parser_version=\"v2\")` on generic EPUB XHTML.
- `.job_parts` should be removed after successful merge; if it remains, treat it as evidence of merge failure/interruption.
- Split-merge paths that run codex-farm must rebuild merged `raw/<importer>/<source_hash>/full_text.json` and rebase block indices before recipe-correction bundle generation.
- `stage` builds and passes a base `MappingConfig` to workers, so worker conversion typically skips importer `inspect()` unless planning/split metadata requires it.
- Topic/Tip writer paths may call file-hash resolution many times; when provenance lacks `file_hash`, hashing must be cached by source file metadata to avoid repeated whole-file reads in high-cardinality merge runs.
- Any payload returned from split workers (especially `ConversionResult.raw_artifacts[*].metadata`) must stay process-pickle-safe primitives; module objects in metadata will fail split benchmark/stage merges with `cannot pickle 'module' object`.
