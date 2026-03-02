---
summary: "Need-to-know-only benchmark package for CodexFarm on/off comparison across four runs."
read_when:
  - "When sharing compact benchmark artifacts with external AI tools"
  - "When comparing codex-farm-3pass-v1 vs off without raw payload bloat"
---

# CodexFarm Benchmark Need-To-Know Package

Created: 2026-03-02_07.53.59
Source package: `docs/2026-03-02_01.35.21_codexfarm_benchmark_comparison_package`

This package keeps only comparison-critical artifacts for each run:

- `need_to_know_summary.json`
- `eval_report.md`
- `correct_label_lines.sample.jsonl` (first 80 inferred-correct lines)
- `wrong_label_lines.sample.jsonl` (first 80)
- `missed_gold_lines.sample.jsonl` (first 80)
- `unmatched_pred_blocks.sample.jsonl` (first 80)

`correct_label_lines.sample.jsonl` is generated from canonical line labels and excludes any line index present in `wrong_label_lines.jsonl`.

Files intentionally removed because they are not required to judge codex-farm vs non-codex quality:

- `prediction-run/raw/**` (prompt/response payloads)
- `prediction-run/extracted_archive.json`
- `prediction-run/label_studio_tasks.jsonl`
- `prediction-run/extracted_text.txt`
- `aligned_prediction_blocks.jsonl`
- full `wrong_label_lines.jsonl` / `missed_gold_lines.jsonl` / `unmatched_pred_blocks.jsonl`
- timing traces (`processing_timeseries_*.jsonl`)

Use `comparison_summary.json` for quick codex-vs-baseline deltas by source book.

## Flattened run artifacts

Each timestamped run folder is now also mirrored as a single markdown file named
`YYYY-MM-DD_HH.MM.SS.md` in this directory (for example `2026-03-02_01.01.06.md`),
containing the complete contents of that run.
