---
summary: "How labelstudio-benchmark now reuses split-job conversion for faster predictions."
read_when:
  - Optimizing labelstudio benchmark runtime for large PDF/EPUB inputs
  - Debugging split-job behavior in benchmark prediction imports
---

# Benchmark Parallel Conversion Path

- `cookimport labelstudio-benchmark` now passes worker/split settings into `run_labelstudio_import`.
- `run_labelstudio_import` plans PDF/EPUB split jobs with the same range planners used by stage imports (`plan_pdf_page_ranges` / `plan_job_ranges`).
- Split jobs run in a process pool, then merge into one `ConversionResult` (recipes/tips/raw artifacts + recipe ID reassignment) before chunk/task generation.
