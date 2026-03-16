# cookimport/llm

Optional LLM integrations live here.

Recipe codex-farm flow is implemented in `codex_farm_orchestrator.py` with strict contracts in `codex_farm_contracts.py` and subprocess/fake runners in `codex_farm_runner.py` and `fake_codex_farm_runner.py`.

Run settings now include explicit pass pipeline ids (`codex_farm_pipeline_pass1/2/3`) plus optional workspace override (`codex_farm_workspace_root`) so recipeimport can target external codex-farm pipeline packs without code edits.

Codex Farm model discovery for interactive run settings now comes from `codex-farm models list --json`, and subprocess orchestration validates configured pipeline ids via `codex-farm pipelines list --root ... --json` before pass execution.

When `codex-farm process --json` fails and returns a `run_id`, runner errors now include a follow-up summary from `codex-farm run errors --run-id ... --json`.
If that summary reports `no last agent message` (typically `nonzero_exit_no_payload` chunk failures), the runner now treats it as recoverable partial-output mode so orchestrators can continue and mark only affected bundles as missing.

Runner process metadata now surfaces CodexFarm `process --json.telemetry_report` as `telemetry_report`, best-effort `run autotune --json` output as `autotune_report`, and keeps `codex_exec_activity.csv` slices as `telemetry`; recipe/pass4/pass5 manifests persist all three for prompt-tuning analysis.

When a caller provides a progress callback, `SubprocessCodexFarmRunner` now executes `codex-farm process --progress-events --json`, parses `__codex_farm_progress__` stderr JSON events, and forwards spinner-friendly `task X/Y` status messages through the existing callback channel used by stage + benchmark flows.

Canonical line-role fallback support now lives in `canonical_line_role_prompt.py` plus CodexFarm-backed adapters in `parsing/canonical_line_roles.py` (`line-role.canonical.v1`) and `labelstudio/prelabel.py` (`prelabel.freeform.v1`).

Prediction runs now also write `prediction-run/prompt_budget_summary.json`, which merges codex-farm pass telemetry plus line-role telemetry into one repo-owned per-pass budget artifact.

Prompt artifact export now lives in `prompt_artifacts.py`. It has a descriptor boundary:
- `discover_codexfarm_prompt_run_descriptors(...)` adapts current raw CodexFarm layout.
- `discover_prompt_run_descriptors(...)` is a pluggable dispatcher so future stage/cookbook layouts can provide new discovery adapters without changing rendering.
- `render_prompt_artifacts_from_descriptors(...)` writes `prompts/` artifacts from normalized stage descriptors.
- `build_prompt_response_log(...)` is the topology-neutral builder that accepts either explicit descriptors or injected discoverers.
- `build_codex_farm_prompt_response_log(...)` is the convenience wrapper used by CLI call sites.

Compact recipe prompt variants now live behind explicit pipeline ids (`recipe.schemaorg.compact.v1`, `recipe.final.compact.v1`, and `recipe.knowledge.compact.v1`), and those compact ids are now the default pass2/pass3/knowledge-stage selections when CodexFarm recipe parsing or optional knowledge extraction is enabled. Line-role prompt compaction is controlled locally by `COOKIMPORT_LINE_ROLE_PROMPT_FORMAT=compact_v1`, which now also becomes the default when unset.

Knowledge harvest now runs only over Stage 7 `knowledge` spans from `cookimport/staging/nonrecipe_stage.py`. The deterministic ownership artifacts are `08_nonrecipe_spans.json` and `09_knowledge_outputs.json`; the LLM side still writes raw `knowledge/{in,out}` plus optional reviewer artifacts `knowledge/<workbook_slug>/snippets.jsonl` and `knowledge.md`.

The canonical recipe path is now `llm_recipe_pipeline=codex-farm-single-correction-v1`. It runs one compact correction stage (`recipe.correction.compact.v1`), updates the intermediate `RecipeCandidate`, and rebuilds final cookbook3 drafts locally from the corrected candidate plus `ingredient_step_mapping`.

Current recipe-object transport note: pass2, pass3, and merged-repair loaders now accept both native nested objects and legacy JSON-string wrapper fields. New pack assets and fake-runner outputs use native nested objects, while old benchmark artifacts still load through the compatibility shim.

Current pass2/pass3 hardening note: malformed pass2 `field_evidence` is recovered into `{}` with a warning, extracted ingredient/instruction arrays are control-byte sanitized, overlap-truncated pass1 rows record `pass1_degradation_reasons`, and manifest rows now expose `pass3_mapping_status` / `pass3_mapping_reason` when pass3 returns or skips ingredient-step mapping work.

Default behavior remains deterministic unless a non-`off` recipe Codex pipeline is explicitly enabled.
