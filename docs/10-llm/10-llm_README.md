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
