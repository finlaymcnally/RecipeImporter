---
summary: "Why labelstudio-benchmark defaults now route to data/golden."
read_when:
  - Changing benchmark artifact destination defaults
  - Debugging interactive vs CLI benchmark output roots
---

# Benchmark Output Root (Golden)

- `labelstudio-benchmark` now defaults `--output-dir` to `data/golden` so benchmark artifacts are treated as golden/evaluation assets, not staging outputs.
- Interactive `cookimport` benchmark menu now bypasses `cookimport.json.output_dir` and always passes:
  - `output_dir=data/golden`
  - `eval_output_dir=data/golden/eval-vs-pipeline/<timestamp>`
- Label Studio import/export flows now also default to `data/golden`.
