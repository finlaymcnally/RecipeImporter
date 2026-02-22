# cookimport/llm

Optional LLM integrations live here.

Recipe codex-farm flow is implemented in `codex_farm_orchestrator.py` with strict pass contracts in `codex_farm_contracts.py` and subprocess/fake runners in `codex_farm_runner.py` and `fake_codex_farm_runner.py`.

Default behavior remains deterministic unless `llm_recipe_pipeline=codex-farm-3pass-v1` is explicitly enabled.
