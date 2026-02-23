---
summary: "LLM architecture/build/fix-attempt log used to avoid repeating failed paths."
read_when:
  - When you are going in multi-turn circles on LLM behavior or implementation
  - When the human says "we are going in circles on this"
  - When you need prior architecture versions, builds, or fix attempts before trying another change
---

# LLM Build and Fix Log

Read this file when troubleshooting loops across turns, or when someone says "we are going in circles on this."

## How to use this log

- Capture architecture versions, build attempts, and fix attempts before trying a new approach.
- Include why each attempt worked or failed to prevent repeating dead ends.

## Entries

### 2026-02-19_15.49.52 split README vs log

- Created `10-llm_log.md` to keep architecture/build/fix-attempt history separate from reference documentation.
- Kept `10-llm_README.md` focused on current-state LLM reference and linked this log from it.

## 2026-02-22 understanding notes (chronological)

### 2026-02-22_14.57.53 hardcoded pass IDs vs external pack integration

Related record:
- `docs/plans/000-Knowledge-Codex-Farm.md`

Preserved findings:
- Hardcoded recipe pass IDs and implicit workspace assumptions break external codex-farm pack compatibility.
- External integrations need explicit run-config controls for workspace root and pass IDs.

Durable rules:
- Keep pass IDs/workspace-root configurable and threaded end-to-end (stage + prediction generation).
- Persist effective pipeline IDs in manifests to make "unknown pipeline" failures diagnosable.

### 2026-02-22_15.29.13 prompt-pack merge collision

Related record:
- `llm_pipelines/README.md`

Preserved findings:
- Concurrent edits can leave multiple filename families; only pipeline-referenced files are active, duplicates become dead/confusing.

Durable rules:
- Reconcile to one filename family referenced by `llm_pipelines/pipelines/recipe.*.v1.json`.
- Ensure prompt templates keep required placeholders (for example `{{INPUT_PATH}}`) and schema linkage is still valid.

### 2026-02-22_16.20.24 local prompt-pack contract

Related record:
- `docs/plans/000-Knowledge-Codex-Farm.md`

Preserved rules:
- Default codex-farm root is local `llm_pipelines/` when not overridden.
- Default recipe pass IDs are:
  - `recipe.chunking.v1`
  - `recipe.schemaorg.v1`
  - `recipe.final.v1`
- Editing referenced local prompt files should directly affect runtime pass prompts without Python code changes.

### 2026-02-22_16.40.05 pass4 knowledge chunk index mapping

Related record:
- `docs/plans/000-Knowledge-Codex-Farm2.md`

Preserved findings:
- Chunk `blockIds` are relative to the sequence passed into chunking, not absolute full-text indices.
- `nonRecipeBlocks` can have absolute-index gaps after recipe removal, so naive whole-list chunking can blur evidence boundary semantics.

Durable rule:
- Split non-recipe blocks into contiguous absolute-index sequences before chunking, then map chunk-relative ids back to absolute block indices for evidence pointers.

## 2026-02-22 merged task-spec batch (chronological)

### 2026-02-22_14.43.25 recipe codex-farm integration (recipeimport side)

Related ExecPlans:
- `docs/plans/000-Recipe-Codex-Farm.md`
- `docs/plans/000-Knowledge-Codex-Farm.md`

Problem captured:
- Stage and benchmark prediction generation needed one shared optional 3-pass codex-farm integration while keeping deterministic default behavior.

Decisions/actions captured:
- Added run-setting contract for `llm_recipe_pipeline`, `codex_farm_cmd`, `codex_farm_root`, `codex_farm_context_blocks`, `codex_farm_failure_mode`.
- Threaded flags through `cookimport stage` and `cookimport labelstudio-benchmark`.
- Added orchestrator contract modules and `raw/llm/<workbook_slug>/llm_manifest.json` output.
- Applied orchestrator results in stage single-file and split-merge paths plus pred-run generation metadata.

Verification/evidence preserved:
- Recorded targeted run:
  - `pytest -q tests/test_run_settings.py tests/test_cli_llm_flags.py tests/test_writer_overrides.py tests/test_codex_farm_contracts.py tests/test_codex_farm_orchestrator.py tests/test_run_manifest_parity.py`
- Recorded result: `15 passed, 2 warnings in 2.29s`.
- Additional run captured: `tests/test_labelstudio_benchmark_helpers.py` -> `38 passed, 2 warnings in 3.32s`.

Constraints and rollback preserved:
- No live codex-farm/token-spend verification run.
- Runtime rollback remains `--llm-recipe-pipeline off`.

### 2026-02-22_14.57.46 codex-farm external pack config wiring

Related ExecPlan:
- `docs/plans/000-Knowledge-Codex-Farm.md`

Problem captured:
- Hardcoded pass IDs and implicit workspace assumptions blocked clean external-pack integration.

Decisions/actions captured:
- Added run settings for `codex_farm_workspace_root` and `codex_farm_pipeline_pass1/2/3`.
- Threaded those settings through stage, benchmark prediction generation, and Label Studio import paths.
- Updated orchestrator/runner calls and persisted effective pass IDs in `llm_manifest.json`.

Verification/evidence preserved:
- Recorded compile check + targeted test suite.
- Recorded result: `52 passed, 2 warnings in 3.51s`.

Constraints and rollback preserved:
- No live codex-farm execution.
- Keep defaults (`recipe.chunking.v1`, `recipe.schemaorg.v1`, `recipe.final.v1`) as deterministic fallback path.

### 2026-02-22_15.29.13 codex-farm prompt-pack merge reconcile

Problem captured:
- Concurrent edits in `llm_pipelines/` caused prompt filename drift and duplicate doc text.

Decisions/actions captured:
- Reconciled to one working local prompt-pack contract under `llm_pipelines/pipelines/recipe.*.v1.json`.
- Kept freeform prelabel templates intact and de-duplicated LLM docs.
- Added/kept pack-asset tests to ensure referenced prompts/schemas exist.

Verification/evidence preserved:
- Recorded command:
  - `pytest -q tests/test_llm_pipeline_pack.py tests/test_llm_pipeline_pack_assets.py tests/test_codex_farm_orchestrator.py`
- Recorded result: `8 passed, 2 warnings`.

### 2026-02-22_15.31.57 prompt-template `.md` extension migration

Related ExecPlan:
- `docs/plans/000-AI-span-freeform-fr.md`

Problem captured:
- Prompt templates moved from `.txt` to markdown but runtime/spec/test path wiring had to remain synchronized.

Decisions/actions captured:
- Renamed prompt templates to `*.prompt.md`.
- Updated Label Studio prelabel runtime template paths and recipe pipeline JSON references.
- Updated tests and docs to enforce new extension contract.

Verification/evidence preserved:
- Recorded command:
  - `pytest -q tests/test_labelstudio_prelabel.py tests/test_llm_pipeline_pack_assets.py tests/test_llm_pipeline_pack.py`
- Recorded result: `15 passed, 2 warnings in 1.43s`.

Rollback path preserved:
- Rename prompts back to `.prompt.txt` and revert path references together if contract changes.

### 2026-02-22_16.18.38 pass4 knowledge codex-farm harvest

Related ExecPlan:
- `docs/plans/000-Knowledge-Codex-Farm2.md`

Problem captured:
- Needed optional pass4 knowledge extraction for non-recipe blocks with durable, auditable stage artifacts.

Decisions/actions captured:
- Added pass4 run-setting/CLI controls:
  - `llm_knowledge_pipeline`
  - `codex_farm_pipeline_pass4_knowledge`
  - `codex_farm_knowledge_context_blocks`
- Added job-bundle/output contract under `raw/llm/<workbook_slug>/pass4_knowledge/{in,out}/`.
- Added user-facing knowledge writes under `knowledge/<workbook_slug>/` plus run-level `knowledge_index.json`.

Verification/evidence preserved:
- Recorded targeted suite:
  - `tests/test_non_recipe_spans.py`
  - `tests/test_knowledge_job_bundles.py`
  - `tests/test_knowledge_output_ingest.py`
  - `tests/test_knowledge_writer.py`
  - `tests/test_codex_farm_knowledge_orchestrator.py`
  - `tests/test_llm_pipeline_pack.py`
  - `tests/test_llm_pipeline_pack_assets.py`
  - `tests/test_run_settings.py`
  - `tests/test_cli_llm_flags.py`
  - `tests/test_run_manifest_parity.py`
- Recorded result: `25 passed, 2 warnings in 2.26s`.

Constraint preserved:
- No live codex-farm/token-spend verification run.

### 2026-02-22_16.20.10 codex-farm local prompt files (branch-history note)

Related ExecPlan:
- `docs/plans/000-Knowledge-Codex-Farm.md`

Problem captured:
- Needed editable local pass prompts and schemas in `llm_pipelines/` instead of Python-embedded prompt text.

Decisions/actions captured:
- Added local recipe pipeline specs + prompt + schema assets and tests to enforce path presence.
- Historical detail: this task record references `*.prompt.txt` prompt assets on one branch line.

Superseded-path reminder:
- Repository contract was later reconciled to `*.prompt.md`; treat `.txt` references as historical branch drift, not current state.

Verification/evidence preserved:
- Recorded command:
  - `pytest -q tests/test_llm_pipeline_pack.py tests/test_codex_farm_orchestrator.py`
- Task evidence recorded added local pipeline/spec/schema files and passing test run (result text not timestamped beyond task record).
