---
summary: "Why benchmark/import could look stuck after split-job merge and how progress now advances through later phases."
read_when:
  - Debugging C3imp or labelstudio-benchmark runs that appear frozen after split-job conversion
  - Extending Label Studio import progress/status reporting
---

# Label Studio Post-Merge Progress Phases

- In split-job imports, `Merged split job results.` was the last emitted progress update before a sequence of heavy operations (archive build, processed output writes, chunk/task generation, Label Studio upload, artifact writes).
- Those later phases could take minutes on large EPUB/PDF inputs, so interactive benchmark status looked frozen even when work was still running.
- `run_labelstudio_import` now emits progress updates for each major post-merge phase and for upload batch progress (`Uploaded X/Y task(s)`), making long benchmark runs observable end-to-end.
