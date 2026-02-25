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

- Historical implementation plans were archived from `docs/tasks/000-Recipe-Codex-Farm.md` and are now merged into this README and `docs/10-llm/10-llm_log.md`.

## History and anti-loop log

- `docs/10-llm/10-llm_log.md`

## Important boundary

Primary stage imports remain deterministic by default; LLM behavior should be explicitly gated and auditable.
`llm_recipe_pipeline` is policy-locked to `off` for now (recipe codex-farm parsing correction must remain OFF until benchmark quality materially improves). Non-`off` values are rejected in CLI/pred-run entry points.
If this policy is lifted in the future, failures can either fail-fast or deterministic-fallback via `codex_farm_failure_mode`.

Policy-lock implementation details (merged from `2026-02-23_11.39.45-recipe-codex-farm-policy-lock.md`):
- CLI + pred-run normalizers fail fast for non-`off` `llm_recipe_pipeline` values.
- Run-settings migration (`RunSettings.from_dict`) coerces legacy non-`off` persisted values back to `off` with warning text.
- Run-settings UI intentionally exposes only `off` so accidental toggles are prevented.

codex-farm orchestration settings are run-config surfaced and shared between stage and benchmark prediction generation:
- command/root/workspace: `codex_farm_cmd`, `codex_farm_root`, `codex_farm_workspace_root`
- pass pipeline ids: `codex_farm_pipeline_pass1`, `codex_farm_pipeline_pass2`, `codex_farm_pipeline_pass3`, `codex_farm_pipeline_pass4_knowledge`, `codex_farm_pipeline_pass5_tags`
- pass1 context size: `codex_farm_context_blocks`
- pass4 context size: `codex_farm_knowledge_context_blocks`
- tag catalog path for pass5: `tag_catalog_json`

Default local pack assets for those pass ids live in `llm_pipelines/`:
- pipeline specs: `llm_pipelines/pipelines/recipe.{chunking,schemaorg,final}.v1.json`
- editable prompts: `llm_pipelines/prompts/recipe.{chunking,schemaorg,final}.v1.prompt.md`
- output schemas: `llm_pipelines/schemas/recipe.{chunking,schemaorg,final}.v1.output.schema.json`

Pass 4 knowledge harvesting:

- `docs/10-llm/knowledge_harvest.md`
- pipeline spec: `llm_pipelines/pipelines/recipe.knowledge.v1.json`
- prompt: `llm_pipelines/prompts/recipe.knowledge.v1.prompt.md`
- output schema: `llm_pipelines/schemas/recipe.knowledge.v1.output.schema.json`

Pass 5 tag suggestions:

- `docs/10-llm/tags_pass.md`
- pipeline spec: `llm_pipelines/pipelines/recipe.tags.v1.json`
- prompt: `llm_pipelines/prompts/recipe.tags.v1.prompt.md`
- output schema: `llm_pipelines/schemas/recipe.tags.v1.output.schema.json`

## Understanding Notes (2026-02-22 batch)

### External codex-farm pack configurability contract

Related record:
- `docs/tasks/000-Knowledge-Codex-Farm.md` (retired; merged into `docs/10-llm/*` on 2026-02-23)

Durable rules:
- Do not hardcode pass pipeline IDs in orchestration logic.
- Keep pass IDs and workspace controls run-config surfaced (`codex_farm_workspace_root`, `codex_farm_pipeline_pass1/2/3`) and threaded through both stage and prediction-generation flows.
- Runner calls should pass explicit root/workspace inputs so external packs can run without relying on implicit process cwd behavior.
- Persist effective pass IDs in LLM manifests for auditability.

### Local prompt-pack wiring and merge-collision guidance

Related records:
- `docs/tasks/000-Knowledge-Codex-Farm.md` (retired; merged into `docs/10-llm/*` on 2026-02-23)
- `llm_pipelines/README.md`

Durable rules:
- Effective prompt file paths are defined by each pipeline JSON `prompt_template_path`, not by filename conventions alone.
- Keep one authoritative filename family and remove/ignore parallel duplicate prompt families to avoid dead edits.
- Default recipe pass IDs are expected to map to local `llm_pipelines/pipelines/recipe.*.v1.json` specs that reference prompt files in `llm_pipelines/prompts/`.
- Prompt edits should be text-only workflow changes; no Python orchestration edits are required when pipeline path wiring is correct.
- Preserve schema link parity (`output_schema_path`) alongside prompt path updates.

### Pass4 knowledge chunk index mapping contract

Related record:
- `docs/tasks/000-Knowledge-Codex-Farm2.md` (retired; merged into `docs/10-llm/*` on 2026-02-23)

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

### 2026-02-25 pass5 codex-farm tag suggestions

- Optional pass5 is enabled by run settings (`llm_tags_pipeline=codex-farm-tags-v1` + `tag_catalog_json` + `codex_farm_pipeline_pass5_tags`).
- Job bundles are staged at `raw/llm/<workbook_slug>/pass5_tags/in/` with strict output ingest from `.../out/`.
- User-facing artifacts are written under:
  - `tags/<workbook_slug>/r{index}.tags.json`
  - `tags/<workbook_slug>/tagging_report.json`
  - `tags/tags_index.json`

### 2026-02-22_16.20.10 local editable pass prompt files (historical merge note)

- One parallel implementation first introduced local prompt assets as `*.prompt.txt`.
- Current repo contract is `*.prompt.md`; treat `.txt` references in older task notes as superseded branch history.
- Durable rule: prompt edits should remain text-only (`llm_pipelines/prompts` / `llm_pipelines/pipelines`) and should not require orchestrator Python edits when pipeline-path wiring is correct.

## Task Archive Merge (2026-02-23_13.35.17)

### Source task docs consolidated and retired from `docs/tasks`

- `docs/tasks/000-Recipe-Codex-Farm.md`
- `docs/tasks/000-Knowledge-Codex-Farm.md`
- `docs/tasks/000-Knowledge-Codex-Farm2.md`
- These docs were merged into this README plus `docs/10-llm/10-llm_log.md`; the task files were retired after merge.

### Preserved implementation contracts from those task records

- Keep recipe codex-farm explicitly opt-in (`llm_recipe_pipeline`), with deterministic default behavior and policy lock to `off` until quality gates are met.
- Keep failure boundary split:
  - setup/subprocess/root issues fail fast unless caller explicitly sets fallback mode,
  - per-recipe output/parse failures degrade to deterministic recipe-level fallback without aborting whole-run processing.
- Keep split-run parity contract: merged runs must rebuild one merged `full_text.json` before pass1 so absolute block-index context and evidence mapping remain valid.
- Keep external-pack contract: pass pipeline IDs and workspace root remain run-config surfaced, threaded through stage + prediction-generation flows, and persisted as effective IDs in `llm_manifest.json`.
- Keep pass4 knowledge contract: chunk IDs from chunker are relative, so job building must map to absolute block indices and chunk contiguous absolute-index sequences.

### Preserved anti-loop caveats from the retired task plans

- Prompt pack source of truth remains pipeline JSON references (`llm_pipelines/pipelines/*.json`), not filename conventions or duplicate prompt families.
- `*.prompt.txt` references in older notes are superseded; current contract is `*.prompt.md`.
- CLI help tests can hide long option names under narrow terminal width; preserve wide-column test env when asserting long LLM flag names.
- Continue avoiding live codex-farm token-spend validation unless explicitly approved.

## Merged Understandings Batch (2026-02-25 pass4/pass5 wiring)

### 2026-02-25_16.21.30 table extraction wiring required for pass4 parity

Merged source:
- `docs/understandings/2026-02-25_16.21.30-table-extraction-stage-pass4-wiring.md`

Durable pass4 wiring contract:
- Non-split stage path must annotate table rows before chunking and before pass4 job building in `cookimport/cli_worker.py:stage_one_file`.
- Split runs must apply the same annotation on merged `non_recipe_blocks` in `cookimport/cli.py:_merge_split_jobs` (workers only emit temporary raw artifacts).
- Processed-output snapshots used by Label Studio/benchmark parity must mirror the same annotation + table-writer steps in `cookimport/labelstudio/ingest.py:_write_processed_outputs`.
- Pass4 job bundles (`cookimport/llm/codex_farm_knowledge_jobs.py`) attach table hints by absolute non-recipe indices; missing hints usually mean non-recipe index drift from merged `full_text` ordering.

Anti-loop notes:
- If pass4 table hints disappear only in split or benchmark flows, debug stage/merge/processed-output wiring parity before changing prompt/schema logic.
- Keep one table-annotation contract across stage and pred-run generation; do not fork a pass4-only table path.

### 2026-02-25_16.24.24 pass5 stage-tagging artifact and failure semantics

Merged source:
- `docs/understandings/2026-02-25_16.24.24-pass5-stage-tagging-wiring.md`

Durable pass5 wiring contract:
- Stage writes normal cookbook artifacts first, then optional pass5 tagging (`llm_tags_pipeline`).
- Pass5 reads staged drafts from `final drafts/<workbook_slug>/`.
- Pass5 writes:
  - `tags/<workbook_slug>/r{index}.tags.json`
  - `tags/<workbook_slug>/tagging_report.json`
  - run-level `tags/tags_index.json`
- Raw pass5 codex-farm IO is under `raw/llm/<workbook_slug>/pass5_tags/` with `in/`, `out/`, and `pass5_tags_manifest.json`.
- `codex_farm_failure_mode` controls behavior:
  - `fail`: stage exits on pass5 setup/execution failure.
  - `fallback`: warning + continue without pass5 artifacts.

Anti-loop note:
- Missing `tags/` outputs are usually wiring/gating/failure-mode issues, not deterministic tagging engine regressions.
