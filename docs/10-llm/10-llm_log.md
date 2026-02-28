---
summary: "LLM architecture/build/fix-attempt log used to avoid repeating failed paths."
read_when:
  - When you are going in multi-turn circles on LLM behavior or implementation
  - When the human says "we are going in circles on this"
  - When you need prior architecture versions, builds, or fix attempts before trying another change
---

# LLM Build and Fix Log

Use this file for LLM debugging history that still applies to the current codebase.

## 2026-02-27_19.51.50 docs parity audit for runtime + nearby LLM code

Problem captured:
- `docs/10-llm/10-llm_README.md` covered core pass4/pass5 files but missed several runtime-adjacent modules that materially shape behavior (prediction-run entrypoints, pass4 helper contracts/ingest/writer, pass5 provider validation layer).

Decisions/actions captured:
- Expanded `10-llm_README.md` runtime-surface inventory to include:
  - entrypoint + prediction-run wrappers (`cookimport/entrypoint.py`, `cookimport/labelstudio/ingest.py`, `cookimport/bench/pred_run.py`)
  - pass4 helper modules (`codex_farm_knowledge_contracts/models/ingest/writer`, `non_recipe_spans`)
  - pass5 provider + standalone tagging CLI modules (`cookimport/tagging/codex_farm_tags_provider.py`, `cookimport/tagging/cli.py`)
  - stage evidence/report plumbing that consumes pass4 artifacts (`cookimport/staging/stage_block_predictions.py`, `cookimport/staging/writer.py`, `cookimport/core/models.py`)
  - shared codex-farm runner/id helper modules used by pass4/pass5
- Clarified prediction-run boundary: prediction generation wires recipe-pass settings only; pass4/pass5 remain stage-only.
- Added explicit note that speed-regression runner forces all LLM pipelines off for deterministic timing baselines.

Verification/evidence captured:
- Re-verified current docs statements against active code paths:
  - `cookimport/config/run_settings.py`
  - `cookimport/cli.py`
  - `cookimport/cli_worker.py`
  - `cookimport/entrypoint.py`
  - `cookimport/labelstudio/ingest.py`
  - `cookimport/bench/pred_run.py`
  - `cookimport/bench/speed_runner.py`
  - `cookimport/llm/codex_farm_orchestrator.py`
  - `cookimport/llm/codex_farm_contracts.py`
  - `cookimport/llm/codex_farm_ids.py`
  - `cookimport/llm/codex_farm_runner.py`
  - `cookimport/llm/codex_farm_knowledge_orchestrator.py`
  - `cookimport/llm/codex_farm_knowledge_jobs.py`
  - `cookimport/llm/codex_farm_knowledge_contracts.py`
  - `cookimport/llm/codex_farm_knowledge_models.py`
  - `cookimport/llm/codex_farm_knowledge_ingest.py`
  - `cookimport/llm/codex_farm_knowledge_writer.py`
  - `cookimport/llm/non_recipe_spans.py`
  - `cookimport/staging/stage_block_predictions.py`
  - `cookimport/staging/writer.py`
  - `cookimport/core/models.py`
  - `cookimport/tagging/cli.py`
  - `cookimport/tagging/orchestrator.py`
  - `cookimport/tagging/llm_second_pass.py`
  - `cookimport/tagging/codex_farm_tags_provider.py`

## 2026-02-27_19.45.57 docs cleanup to remove stale LLM history noise

Problem captured:
- `docs/10-llm/10-llm_README.md` and this log had large merged-task archives that duplicated old task files and hid current runtime boundaries.

Decisions/actions captured:
- Pruned retired task-merge chronology that no longer maps cleanly to active runtime behavior.
- Kept only durable, code-verified contracts still relevant for debugging today.
- Marked `cookimport/llm/client.py`, `cookimport/llm/prompts.py`, and `cookimport/llm/repair.py` as legacy/non-runtime for stage/pred-run flows.

Verification/evidence captured:
- Re-verified docs against active code paths:
  - `cookimport/config/run_settings.py`
  - `cookimport/cli.py`
  - `cookimport/cli_worker.py`
  - `cookimport/labelstudio/ingest.py`
  - `cookimport/llm/codex_farm_orchestrator.py`
  - `cookimport/llm/codex_farm_knowledge_orchestrator.py`
  - `cookimport/tagging/orchestrator.py`

## 2026-02-23_11.39.45 recipe codex-farm policy lock

Problem captured:
- Recipe codex-farm parsing correction must remain disabled until benchmark quality materially improves.

Decisions/actions captured:
- Locked recipe pipeline normalization to `off` in:
  - `cookimport/cli.py:_normalize_llm_recipe_pipeline`
  - `cookimport/labelstudio/ingest.py:_normalize_llm_recipe_pipeline`
- Updated `RunSettings.from_dict` to coerce legacy non-`off` persisted values back to `off` with warning text.
- Run-settings UI contract remains `off`-only for recipe pipeline selection.

Verification/evidence preserved:
- `pytest tests/cli/test_cli_llm_flags.py tests/llm/test_run_settings.py tests/labelstudio/test_labelstudio_ingest_parallel.py::test_llm_recipe_pipeline_normalizer_rejects_codex_farm_enablement`

Rollback path preserved:
- If policy changes, update both normalizers plus run-settings enum/UI filtering in one change.

## 2026-02-25_16.21.30 pass4 table-hint parity across stage/split/processed outputs

Problem captured:
- Pass4 table hints can disappear when non-split, split-merge, and processed-output paths diverge.

Decisions/actions preserved:
- Keep table annotation before chunking in all key paths:
  - `cookimport/cli_worker.py:stage_one_file`
  - `cookimport/cli.py:_merge_split_jobs`
  - `cookimport/labelstudio/ingest.py:_write_processed_outputs`
- Keep pass4 hint mapping by absolute non-recipe indices in `cookimport/llm/codex_farm_knowledge_jobs.py`.

Anti-loop note:
- Debug stage/merge parity first when hints are missing; do not start by changing pass4 prompt/schema assets.

## 2026-02-25_16.24.24 pass5 stage-tagging outputs and failure mode

Problem captured:
- Missing `tags/` artifacts were often misdiagnosed as tagging quality issues instead of wiring/gating failures.

Decisions/actions preserved:
- Pass5 runs after stage writes final drafts and reads from `final drafts/<workbook_slug>/`.
- Output contract:
  - `tags/<workbook_slug>/r{index}.tags.json`
  - `tags/<workbook_slug>/tagging_report.json`
  - `tags/tags_index.json`
- Raw codex-farm IO stays under `raw/llm/<workbook_slug>/pass5_tags/`.
- `codex_farm_failure_mode` controls hard-stop (`fail`) vs warn-and-continue (`fallback`).

## 2026-02-25_19.20.00 deterministic knowledge fallback when pass4 is off

Problem captured:
- Stage evidence previously risked `KNOWLEDGE=0` when pass4 was disabled, despite deterministic knowledge-lane chunks.

Decisions/actions preserved:
- Prefer pass4 snippet provenance when available.
- When pass4 is off or missing snippets, backfill stage knowledge labels from deterministic `ChunkLane.KNOWLEDGE` chunk-to-block mapping.

Anti-loop note:
- If `KNOWLEDGE=0` appears with pass4 disabled, treat it as a wiring regression.

## 2026-02-27_19.45.57 docs runtime-scope cleanup

Problem captured:
- LLM docs had large archive sections that implied broader active runtime use than current code executes.

Durable decisions/actions:
- Keep docs focused on active stage pass4/pass5 behavior and policy-lock boundaries.
- Keep recipe pass implementation files documented as shipped code, but clearly label runtime lock state.
- Keep prediction-run boundary explicit (recipe-pass settings only).

Anti-loop note:
- If LLM behavior appears inconsistent, verify normalization/policy-lock path first (`run_settings` + CLI + Label Studio ingest) before editing pass assets.

## 2026-02-27_19.51.50 provenance note

Source understanding merged:
- `docs/understandings/2026-02-27_19.51.50-llm-docs-parity-runtime-surface-map.md`

Current status:
- Its module-parity findings are retained in this log and reflected in `10-llm_README.md`.
