---
summary: "Why split-job Label Studio prediction merges must reindex block coordinates."
read_when:
  - Debugging zero-match freeform benchmark reports after split-job prediction imports
  - Changing Label Studio split-job merge behavior for PDF/EPUB imports
---

# Label Studio Split-Job Block Reindexing

- EPUB/PDF split jobs emit local block indices starting at `0` within each job.
- Freeform/canonical gold exports use one global block index space for the whole source file.
- Without merge-time reindexing, benchmark predictions stay in per-job local coordinates and eval can report `0` matches even when extracted recipes are visibly correct.
- `cookimport/labelstudio/ingest.py` now rebases job results during `_merge_parallel_results` by adding cumulative prior-job extracted block counts to block-location fields before chunk/task generation.
