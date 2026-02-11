---
summary: "How labelstudio-benchmark now emits stage-style processed output for manual upload checks."
read_when:
  - Extending labelstudio benchmark output artifacts
  - Debugging where benchmark writes processed cookbook files vs eval reports
---

# Benchmark Processed Output Path

- `labelstudio-benchmark` now passes `processed_output_root` into `run_labelstudio_import`.
- The import path writes stage-style outputs (`intermediate drafts`, `final drafts`, `tips`, optional `chunks`, `raw`, and report) from the same conversion result used for prediction task generation.
- Default processed destination is `data/output/`; benchmark/eval artifacts remain under `data/golden/`.
- Override processed destination with `--processed-output-dir`.
