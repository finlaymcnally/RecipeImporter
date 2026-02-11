---
summary: "How interactive C3imp routes Label Studio artifacts to configurable output roots."
read_when:
  - Extending C3imp interactive output path behavior
  - Debugging why interactive Label Studio runs do or do not write to data/output
---

# Interactive Output Root (Label Studio)

- Interactive mode reads `output_dir` from `cookimport.json` for stage/inspect artifact roots.
- Default interactive `output_dir` is `data/output/`.
- Non-interactive `labelstudio-import`, `labelstudio-export`, and `labelstudio-benchmark` default `--output-dir` to `data/golden/`.
- Interactive Label Studio flows now always route artifacts to `data/golden`:
  - import/export output root: `data/golden`
  - `output_dir=data/golden` for prediction import scratch artifacts
  - `eval_output_dir=data/golden/eval-vs-pipeline/<timestamp>` for benchmark reports and co-located prediction artifacts
- Freeform gold discovery still scans `data/output/` and `data/golden/` so existing exports remain discoverable.
