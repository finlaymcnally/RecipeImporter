# cookimport/llm

Optional LLM integrations live here.

Recipe codex-farm flow is implemented in `codex_farm_orchestrator.py` with strict contracts in `codex_farm_contracts.py` and subprocess/fake runners in `codex_farm_runner.py` and `fake_codex_farm_runner.py`.

Run settings now include the recipe pipeline toggle plus optional workspace override (`codex_farm_workspace_root`) so recipeimport can target external codex-farm pipeline packs without code edits.

Codex Farm model discovery for interactive run settings now comes from `codex-farm models list --json`, and subprocess orchestration validates configured pipeline ids via `codex-farm pipelines list --root ... --json` before recipe-correction execution.

When `codex-farm process --json` fails and returns a `run_id`, runner errors now include a follow-up summary from `codex-farm run errors --run-id ... --json`.
If that summary reports `no last agent message` (typically `nonzero_exit_no_payload` chunk failures), the runner now treats it as recoverable partial-output mode so orchestrators can continue and mark only affected bundles as missing.

Runner process metadata now surfaces CodexFarm `process --json.telemetry_report` as `telemetry_report`, best-effort `run autotune --json` output as `autotune_report`, and keeps `codex_exec_activity.csv` slices as `telemetry`; recipe/knowledge/tags manifests persist all three for prompt-tuning analysis.

When a caller provides a progress callback, `SubprocessCodexFarmRunner` now executes `codex-farm process --progress-events --json`, parses `__codex_farm_progress__` stderr JSON events, and forwards spinner-friendly `task X/Y` status messages through the existing callback channel used by stage + benchmark flows.

Canonical line-role fallback support now lives in `canonical_line_role_prompt.py` plus CodexFarm-backed adapters in `parsing/canonical_line_roles.py` (`line-role.canonical.v1`) and `labelstudio/prelabel.py` (`prelabel.freeform.v1`).

Prediction runs now also write `prediction-run/prompt_budget_summary.json`, which merges codex-farm stage telemetry plus line-role telemetry into one repo-owned budget artifact.

Prompt artifact export now lives in `prompt_artifacts.py`. It has a descriptor boundary:
- `discover_codexfarm_prompt_run_descriptors(...)` adapts current raw CodexFarm layout.
- `discover_prompt_run_descriptors(...)` is a pluggable dispatcher so future stage/cookbook layouts can provide new discovery adapters without changing rendering.
- `render_prompt_artifacts_from_descriptors(...)` writes `prompts/` artifacts from normalized stage descriptors.
- `build_prompt_response_log(...)` is the topology-neutral builder that accepts either explicit descriptors or injected discoverers.
- `build_codex_farm_prompt_response_log(...)` is the convenience wrapper used by CLI call sites.
- `prompt_preview.py` is the zero-token existing-output helper used by `cf-debug preview-prompts`; it rebuilds prompt previews from saved stage artifacts without invoking Codex.

Compact recipe prompt variants now live behind explicit pipeline ids (`recipe.correction.compact.v1` and `recipe.knowledge.compact.v1`), and those ids are now the default recipe-correction / knowledge-stage selections when CodexFarm recipe parsing or optional knowledge extraction is enabled. Line-role prompt compaction is controlled locally by `COOKIMPORT_LINE_ROLE_PROMPT_FORMAT=compact_v1`, which now also becomes the default when unset.

Knowledge harvest now runs only over Stage 7 `knowledge` spans from `cookimport/staging/nonrecipe_stage.py`. The deterministic ownership artifacts are `08_nonrecipe_spans.json` and `09_knowledge_outputs.json`; the LLM side still writes raw `knowledge/{in,out}` plus optional reviewer artifacts `knowledge/<workbook_slug>/snippets.jsonl` and `knowledge.md`.

The canonical recipe path is now `llm_recipe_pipeline=codex-farm-single-correction-v1`. It runs one compact correction stage (`recipe.correction.compact.v1`), updates the intermediate `RecipeCandidate`, and rebuilds final cookbook3 drafts locally from the corrected candidate plus `ingredient_step_mapping`.

Current recipe-object transport note: the correction loader uses native nested objects for `canonical_recipe`. Fake-runner outputs follow the same contract.

Current recipe-correction hardening note: manifest rows expose `final_mapping_status` / `final_mapping_reason` for the deterministic final assembly that consumes `ingredient_step_mapping`.

Default behavior remains deterministic unless a non-`off` recipe Codex pipeline is explicitly enabled.
