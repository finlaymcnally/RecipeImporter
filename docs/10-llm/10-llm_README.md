---
summary: "LLM integration notes and boundaries for optional repair passes in the import pipeline."
read_when:
  - When enabling or modifying LLM-assisted repair behavior
  - When auditing deterministic-vs-LLM fallback boundaries
---

# LLM Section Reference

LLM integrations are optional and live under `cookimport/llm/`.

## Core code

- `cookimport/llm/client.py`
- `cookimport/llm/prompts.py`
- `cookimport/llm/repair.py`

Recipe codex-farm integration:

- `cookimport/llm/codex_farm_contracts.py` (Pydantic pass1/pass2/pass3 bundle contracts)
- `cookimport/llm/codex_farm_runner.py` (subprocess boundary + actionable runner errors)
- `cookimport/llm/codex_farm_orchestrator.py` (3-pass orchestration + manifest/override application)
- `cookimport/llm/fake_codex_farm_runner.py` (deterministic test runner)

## Design and rollout plan

- `docs/plans/000-Recipe-Codex-Farm.md`

## History and anti-loop log

- `docs/10-llm/10-llm_log.md`

## Important boundary

Primary stage imports remain deterministic by default; LLM behavior should be explicitly gated and auditable.
`llm_recipe_pipeline` defaults to `off`; when enabled (`codex-farm-3pass-v1`), failures can either fail-fast or deterministic-fallback via `codex_farm_failure_mode`.

codex-farm orchestration settings are run-config surfaced and shared between stage and benchmark prediction generation:
- command/root/workspace: `codex_farm_cmd`, `codex_farm_root`, `codex_farm_workspace_root`
- pass pipeline ids: `codex_farm_pipeline_pass1`, `codex_farm_pipeline_pass2`, `codex_farm_pipeline_pass3`
- pass1 context size: `codex_farm_context_blocks`

Default local pack assets for those pass ids live in `llm_pipelines/`:
- pipeline specs: `llm_pipelines/pipelines/recipe.{chunking,schemaorg,final}.v1.json`
- editable prompts: `llm_pipelines/prompts/recipe.{chunking,schemaorg,final}.v1.prompt.md`
- output schemas: `llm_pipelines/schemas/recipe.{chunking,schemaorg,final}.v1.output.schema.json`

Pass 4 knowledge harvesting:

- `docs/10-llm/knowledge_harvest.md`
- pipeline spec: `llm_pipelines/pipelines/recipe.knowledge.v1.json`
- prompt: `llm_pipelines/prompts/recipe.knowledge.v1.prompt.md`
- output schema: `llm_pipelines/schemas/recipe.knowledge.v1.output.schema.json`

## Understanding Notes (2026-02-22 batch)

### External codex-farm pack configurability contract

Related record:
- `docs/plans/000-Knowledge-Codex-Farm.md`

Durable rules:
- Do not hardcode pass pipeline IDs in orchestration logic.
- Keep pass IDs and workspace controls run-config surfaced (`codex_farm_workspace_root`, `codex_farm_pipeline_pass1/2/3`) and threaded through both stage and prediction-generation flows.
- Runner calls should pass explicit root/workspace inputs so external packs can run without relying on implicit process cwd behavior.
- Persist effective pass IDs in LLM manifests for auditability.

### Local prompt-pack wiring and merge-collision guidance

Related records:
- `docs/plans/000-Knowledge-Codex-Farm.md`
- `llm_pipelines/README.md`

Durable rules:
- Effective prompt file paths are defined by each pipeline JSON `prompt_template_path`, not by filename conventions alone.
- Keep one authoritative filename family and remove/ignore parallel duplicate prompt families to avoid dead edits.
- Default recipe pass IDs are expected to map to local `llm_pipelines/pipelines/recipe.*.v1.json` specs that reference prompt files in `llm_pipelines/prompts/`.
- Prompt edits should be text-only workflow changes; no Python orchestration edits are required when pipeline path wiring is correct.
- Preserve schema link parity (`output_schema_path`) alongside prompt path updates.

### Pass4 knowledge chunk index mapping contract

Related record:
- `docs/plans/000-Knowledge-Codex-Farm2.md`

Durable rules:
- Knowledge chunk `blockIds` from chunking are relative to the provided sequence, not absolute `full_text` indices.
- Pass4 job bundle construction must map relative chunk indices back to absolute block indices for auditable evidence pointers.
- Because recipe spans are removed from `nonRecipeBlocks`, absolute indices can contain gaps; chunking should run on contiguous absolute-index sequences to keep `block_start_index`/`block_end_index` meaningful.

Cross-boundary reminder:
- If split-run evidence offsets look wrong, verify ingestion merged `full_text.json` rebasing in `docs/03-ingestion/03-ingestion_readme.md` before changing pass4 logic.

## Merged Task Specs (2026-02-22 batch)

### 2026-02-22_14.43.25 recipe-side codex-farm integration baseline

- Stage and benchmark prediction generation share one optional 3-pass codex-farm gate (`llm_recipe_pipeline`; default `off` for deterministic runs).
- Run settings + CLI expose codex-farm command/root/workspace/pass IDs/context/failure mode.
- Orchestrator writes `raw/llm/<workbook_slug>/llm_manifest.json` and applies pass outputs through writer overrides to intermediate/final drafts.
- Prediction-run metadata keeps `llm_codex_farm` fields for parity and auditability.

### 2026-02-22_14.57.46 external pack configurability wiring

- External-pack compatibility requires explicit run-config wiring for:
  - `codex_farm_workspace_root`
  - `codex_farm_pipeline_pass1`
  - `codex_farm_pipeline_pass2`
  - `codex_farm_pipeline_pass3`
- Orchestrator runner calls must forward root/workspace/pass IDs from run config (no hardcoded IDs at call sites).
- Effective pass IDs must be persisted in manifests to make unknown-pipeline failures diagnosable.

### 2026-02-22_15.29.13 prompt-pack merge reconciliation

- Concurrent edits in `llm_pipelines/` can leave dead prompt filename families.
- The active source of truth remains pipeline JSON references under `llm_pipelines/pipelines/recipe.*.v1.json`; only those referenced prompt files are live.
- Keep pack-asset tests (`tests/test_llm_pipeline_pack.py`, `tests/test_llm_pipeline_pack_assets.py`) as the anti-regression guardrail for prompt/schema path drift.

### 2026-02-22_15.31.57 prompt template extension migration (`.prompt.md`)

- Active prompt templates are markdown files (`*.prompt.md`) across prelabel + codex-farm packs.
- Runtime and pipeline-spec paths should always be migrated together when renaming prompt assets.
- Keep `*.prompt.md` naming pattern (not plain `.md`) so prompt-role semantics stay visible in filenames.

### 2026-02-22_16.18.38 pass4 codex-farm knowledge harvesting

- Optional pass4 is enabled by run settings (`llm_knowledge_pipeline=codex-farm-knowledge-v1` + pass4 pipeline/context knobs).
- Job bundles are staged at `raw/llm/<workbook_slug>/pass4_knowledge/in/` with strict output ingest from `.../out/`.
- User-facing artifacts are written under:
  - `knowledge/<workbook_slug>/snippets.jsonl`
  - `knowledge/<workbook_slug>/knowledge.md`
  - `knowledge/knowledge_index.json`

### 2026-02-22_16.20.10 local editable pass prompt files (historical merge note)

- One parallel implementation first introduced local prompt assets as `*.prompt.txt`.
- Current repo contract is `*.prompt.md`; treat `.txt` references in older task notes as superseded branch history.
- Durable rule: prompt edits should remain text-only (`llm_pipelines/prompts` / `llm_pipelines/pipelines`) and should not require orchestrator Python edits when pipeline-path wiring is correct.
