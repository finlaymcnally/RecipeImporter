PDF importer notes:
Durable split/merge and extractor contracts live in `cookimport/plugins/CONVENTIONS.md`.

- Uses PyMuPDF line-level spans to capture font size/alignment and clusters columns by x0 gaps.
- Recipe segmentation scans each column stream for title + ingredient anchors (OCR-aware).

EPUB importer notes:
- Uses ebooklib when available; otherwise reads container.xml + OPF spine from the EPUB zip to extract XHTML blocks.
- Falls back to yield-line anchors and heuristic step detection when explicit section headers are missing.
- When yield anchors are used, title backtracking walks consecutive title-like blocks to avoid leaving duplicate title lines in the previous recipe.
- Warns when standalone topic coverage drops below 90% of standalone blocks.
- Standalone knowledge-block analysis now runs per-topic-container with bounded parallelism (`C3IMP_STANDALONE_ANALYSIS_WORKERS`, default `4`) and emits `task X/Y` progress updates during conversion.
