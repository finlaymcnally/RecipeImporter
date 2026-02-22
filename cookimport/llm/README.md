# cookimport/llm

Optional LLM integrations live here.

Recipe codex-farm flow is implemented in `codex_farm_orchestrator.py` with strict pass contracts in `codex_farm_contracts.py` and subprocess/fake runners in `codex_farm_runner.py` and `fake_codex_farm_runner.py`.

Run settings now include explicit pass pipeline ids (`codex_farm_pipeline_pass1/2/3`) plus optional workspace override (`codex_farm_workspace_root`) so recipeimport can target external codex-farm pipeline packs without code edits.

Default behavior remains deterministic unless `llm_recipe_pipeline=codex-farm-3pass-v1` is explicitly enabled.
