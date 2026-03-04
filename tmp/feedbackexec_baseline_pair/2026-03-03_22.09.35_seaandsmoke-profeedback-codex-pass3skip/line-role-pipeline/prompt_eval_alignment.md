# Prompt ↔ Eval Alignment

This run uses canonical line-label scoring.

## Prompt Families

- Recipe-object extraction pipeline: `codex-farm-3pass-v1` (legacy recipe span/schema prompts).
- Atomic block splitter: `atomic-v1` (deterministic block-to-line atomization).
- Canonical line-role pipeline: `codex-line-role-v1` (direct one-label-per-line predictions).

## Artifact Families

- `eval_report.json` + `eval_report.md`: canonical benchmark metrics.
- `wrong_label_lines.jsonl` + `aligned_prediction_blocks.jsonl`: evaluator diagnostics.
- `line-role-pipeline/line_role_predictions.jsonl`: direct canonical line-role outputs.
- `line-role-pipeline/line_role_flips_vs_baseline.jsonl`: inferred baseline-vs-candidate deltas.
- `line-role-pipeline/slice_metrics.json`: slice-level quality signals.
- `line-role-pipeline/knowledge_budget.json`: `KNOWLEDGE` usage inside vs outside recipe spans.
