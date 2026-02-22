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
