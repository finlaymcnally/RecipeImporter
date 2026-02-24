---
summary: "Stage (menu 1) and benchmark (menu 5) share conversion, but differ in their primary artifacts and scoring contract."
read_when:
  - "When deciding whether 'Generate predictions + evaluate vs freeform gold' can replace a normal stage/import run"
  - "When trying to reuse benchmark outputs for Cookbook import"
---

# Stage (Menu 1) vs Benchmark (Menu 5): Pipeline Similarity

## TL;DR

- They share the same core **convert -> write cookbook outputs** machinery.
- They differ in **what is considered the primary output**:
  - Menu `1)` is about staged cookbook artifacts (`final drafts`, `tips`, etc.).
  - Menu `5)` is about prediction-task artifacts + an eval report (scoring is task-vs-gold, not cookbook-vs-gold).
- Yes: menu `5)` can still leave you with staged cookbook outputs you can import, but those are **side artifacts** of the benchmark flow.

## What Menu 1 Does (Stage)

Menu option:
- `Stage files from data/input - produce cookbook outputs`

Primary code path:
- `cookimport/cli.py:stage` -> workers in `cookimport/cli_worker.py` (`stage_one_file`, split-job helpers, merge)

Primary artifacts written:
- Staged cookbook outputs under `data/output/<timestamp>/...` (intermediate/final drafts, tips, chunks, report, raw artifacts).
- Optional knowledge artifacts when enabled (knowledge harvest is stage-specific).

## What Menu 5 Does (Benchmark)

Menu option:
- `Generate predictions + evaluate vs freeform gold`

Primary code path:
- `cookimport/cli.py:labelstudio_benchmark`
  - offline mode: `generate_pred_run_artifacts(...)` in `cookimport/labelstudio/ingest.py`
  - upload mode: `run_labelstudio_import(...)` (still builds the same on-disk prediction-run artifacts, then uploads)
  - eval: loads predicted ranges from `label_studio_tasks.jsonl` and gold spans from `freeform_span_labels.jsonl`, then writes `eval_report.*`

Primary artifacts written:
- Prediction-run artifacts under `data/golden/benchmark/<timestamp>/...` (not under `data/output`).
- Eval artifacts under `data/golden/benchmark/<timestamp>/`:
  - `eval_report.json`, `eval_report.md`, plus misses/false-positives JSONL.
- Optional staged cookbook outputs under `data/output/<timestamp>/...` via the `processed_output_dir` / `processed_output_root` path.

## Where The Pipelines Are The Same

Shared upstream processing (both menu paths):
- Select an importer (via plugin registry) and run `importer.convert(...)` (including split-job conversion when applicable).
- Produce a `ConversionResult` that feeds the staging writers.
- Write stage-style cookbook outputs using the same staging writer functions (`write_intermediate_outputs`, `write_draft_outputs`, `write_tip_outputs`, `write_report`, etc.).

In other words: benchmark is not a totally separate importer; it reuses the same conversion + staging machinery, then adds task-generation + eval.

## Where The Pipelines Differ

Different "source of truth" artifacts:
- Stage: cookbook outputs are the point of the run.
- Benchmark: scoring uses **prediction task artifacts** (`label_studio_tasks.jsonl`) vs **freeform gold** (`freeform_span_labels.jsonl`).
  - Cookbook outputs are not the scored surface.

Stage-only extras:
- Stage can run `llm_knowledge_pipeline` (codex-farm knowledge harvest) and emit `knowledge/` artifacts; benchmark does not.

Output roots differ:
- Stage outputs: `data/output/<timestamp>/...`
- Benchmark prediction/eval outputs: `data/golden/benchmark/<timestamp>/...` (plus optional `data/output/<timestamp>/...` side artifacts)
- Interactive all-method benchmark keeps eval artifacts under `data/golden/.../all-method-benchmark/...` but writes processed cookbook outputs under `data/output/<benchmark_timestamp>/all-method-benchmark/<source_slug>/config_*/<prediction_timestamp>/...`.

Naming nuance (easy to trip on):
- Stage uses a slugified workbook dir name (`workbook_slug`) for output subfolders.
- Benchmark "processed outputs" currently use `path.stem` directly for that subfolder name.

## Can A Benchmark Run Be Used For Cookbook Import?

Yes, for menu `5)` runs:
- The benchmark flow writes staged cookbook outputs as a convenience side artifact (see `processed_output_root` in `generate_pred_run_artifacts`).
- Use the printed `Processed output: ...` path (or the `processed_output_run_dir` in the benchmark run manifest) as the directory you import into your Cookbook program.

Notes:
- If you only want cookbook outputs, menu `1)` is simpler and avoids benchmark-only artifacts (tasks + eval report).
- Interactive all-method benchmark still writes importable cookbook outputs, but nests them by benchmark timestamp + config under `data/output/...`.
- Offline suite runs (`cookimport bench run`) do not write processed cookbook outputs by default; they focus on prediction+eval artifacts.
