---
summary: "Notes on worker progress reporting and split-job scheduling in the stage CLI."
read_when:
  - When adjusting the CLI worker dashboard or progress updates
  - When debugging stalled progress during split EPUB/PDF jobs
---

The stage CLI builds a list of `JobSpec` entries, splitting large EPUB/PDF inputs into spine/page-range jobs when configured. Each job runs in a ProcessPool worker (`stage_epub_job`, `stage_pdf_job`, or `stage_one_file`) and reports progress through a `multiprocessing.Manager().Queue()` to the live dashboard. The dashboard only knows what the workers last reported, so stale entries can appear if no updates arrive. After all split jobs for a file finish, the main process merges results; the progress bar tracks job completion, not merge time.
