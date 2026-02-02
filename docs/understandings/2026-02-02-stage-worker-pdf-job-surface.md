---
summary: "Notes on current stage->worker flow and PDF conversion surfaces relevant to job splitting."
read_when:
  - When adding job-level parallelism or page-range processing for PDF ingestion
---

# Stage/Worker/PDF Surfaces (2026-02-02)

- `cookimport/cli.py` `stage` plans jobs (one per file, or multiple page-range jobs for large PDFs), spins a `ProcessPoolExecutor`, and calls either `cookimport/cli_worker.py:stage_one_file` (non-split) or `cookimport/cli_worker.py:stage_pdf_job` (split). Progress updates come through a `multiprocessing.Manager().Queue()` and are rendered in the Live dashboard with page-range labels.
- `stage_one_file` in `cookimport/cli_worker.py` resolves the importer, runs `importer.inspect` if no mapping, then `importer.convert`, applies optional limits, builds knowledge chunks, enriches the report, and writes outputs via `cookimport/staging/writer.py`.
- `stage_pdf_job` runs a page-range conversion, writes raw artifacts into a `.job_parts/<workbook_slug>/job_<index>/raw/` temp folder, and returns a mergeable `ConversionResult` payload to the main process.
- `cookimport/plugins/pdf.py:PdfImporter.convert` can now process a page range (OCR or text extraction) and initially assigns recipe IDs as `urn:recipeimport:pdf:{file_hash}:c{i}` before the merge step rewrites them to a global sequence.
- `cookimport/ocr/doctr_engine.py:ocr_pdf` accepts `start_page` and `end_page` (exclusive), and returns absolute page numbers (1-based) for OCR blocks.
