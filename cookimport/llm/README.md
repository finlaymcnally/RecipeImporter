# cookimport/llm

Optional LLM integrations live here.

Recipe codex-farm flow is implemented in `codex_farm_orchestrator.py` with strict contracts in `codex_farm_contracts.py` and subprocess/fake runners in `codex_farm_runner.py` and `fake_codex_farm_runner.py`.
The shared shard-runtime foundation now lives in `phase_worker_runtime.py`: it writes phase/shard manifests, round-robin worker assignments, per-worker sandboxes, per-shard proposed outputs, promotion summaries, and telemetry without promoting anything itself.
Shard-v1 recipe work still calls CodexFarm in explicit classic one-shot mode: `codex-farm process --runtime-mode classic_task_farm_v1 --workers 1`. Knowledge and line-role now bypass that path and run one direct `codex exec --json --output-schema ... -` call per shard with the full shard prompt sent once on stdin.
When shard-v1 worker counts are left unset, recipe, knowledge, and line-role now default to the planned shard/job count for that book+phase, capped at `20`; explicit `*_worker_count` overrides still win.
The shared phase-worker runtime now also launches assigned workers concurrently instead of iterating worker assignments in one serial loop. Recipe shard workers still run one classic CodexFarm call each, while direct knowledge and direct line-role runtimes now also execute their assigned workers concurrently, so `active workers: N` corresponds to real in-flight worker assignments rather than preplanned buckets waiting their turn.
Shard-v1 recipe, knowledge, and line-role planning now also expose per-phase prompt-count targets (`*_prompt_target_count`) and default them to `5`. The lower-level shard-size knobs still exist as explicit overrides, but the default operator mental model is now “prompts per phase,” not “items per shard.”
Recipe still uses path-mode prompt transport under CodexFarm process. Knowledge no longer does: `cookimport/llm/knowledge_prompt_builder.py` renders the compact knowledge instructions plus the owned shard JSON inline, and `cookimport/llm/codex_exec_runner.py` sends that prompt directly to `codex exec`. Line-role also no longer does: `canonical_line_roles.py` now sends `build_canonical_line_role_prompt(...)` output directly to `codex exec`, keeps `workers/*/in/*.json` only as debug copies, and writes per-shard `prompt.txt` / `events.jsonl` / `usage.json` / `proposal.json` artifacts under `line-role-pipeline/runtime/workers/<worker>/shards/<shard>/`.
`cf-debug preview-prompts` is predictive-only now: it prefers the paired `vanilla` benchmark artifact when one exists, rebuilds planned shard payloads locally, tokenizes reconstructable prompt/output structure, reports stages as unavailable instead of faking prompt-length guesses when structure is missing, ignores stale live `raw/llm/.../{recipe_correction,knowledge}/in/` payload copies, and hard-refuses Codex-backed or ambiguous processed runs. Retrospective costs now live under the post-run artifact surface instead of preview.

Run settings now include shard-v1 pipeline ids plus optional shard worker/size/turn knobs, and they reject removed recipe/knowledge/line-role ids instead of normalizing them.
Run settings also include the optional workspace override (`codex_farm_workspace_root`) so recipeimport can target external codex-farm pipeline packs without code edits.
RecipeImport now also forces its CodexFarm subprocesses onto the dedicated `~/.codex-recipe` home by default at the runner layer, so recipe/knowledge/line-role/prelabel/model-discovery calls do not silently fall back to the main `~/.codex` profile. Explicit subprocess env overrides can still replace that home when needed.
See `RECIPE_CODEX_HOME.md` in this folder for the AI-coder explainer on how RecipeImport forces CodexFarm onto the dedicated recipe Codex home.

Codex Farm model discovery for interactive run settings now comes from `codex-farm models list --json`, and subprocess orchestration validates configured pipeline ids via `codex-farm pipelines list --root ... --json` before recipe-correction execution.

When `codex-farm process --json` fails and returns a `run_id`, runner errors now include a follow-up summary from `codex-farm run errors --run-id ... --json`.
If that summary reports `no last agent message` (typically `nonzero_exit_no_payload` chunk failures), the runner now treats it as recoverable partial-output mode so orchestrators can continue and mark only affected bundles as missing.

Runner process metadata now surfaces CodexFarm `process --json.telemetry_report` as `telemetry_report`, best-effort `run autotune --json` output as `autotune_report`, and keeps `codex_exec_activity.csv` slices as `telemetry`; recipe/knowledge/tags manifests persist all three for prompt-tuning analysis.

For zero-token runtime rehearsal, point `--codex-farm-cmd` at `scripts/fake-codex-farm.py` and still run execute mode with `--allow-codex`. That path exercises the real shard-runtime input/output folder choreography through the subprocess runner without calling a live model.

When a caller provides a progress callback, `SubprocessCodexFarmRunner` requires `codex-farm process --progress-events --json`, parses `__codex_farm_progress__` stderr JSON events, and forwards spinner-friendly `task X/Y` status messages through the existing callback channel used by stage + benchmark flows.
The runner also suppresses legacy `run=... queued=... running=...` stderr snapshots when they are just redundant progress noise beside the structured progress channel.

Canonical line-role fallback support now lives in `canonical_line_role_prompt.py` plus direct-exec orchestration in `parsing/canonical_line_roles.py` and Codex-backed prelabel adapters in `labelstudio/prelabel.py` (`prelabel.freeform.v1`).

Prediction runs now also write `prediction-run/prompt_budget_summary.json`, which is the post-run actual-costs artifact: it merges recipe, knowledge, and line-role telemetry into one repo-owned whole-run budget summary, including nested line-role batch/attempt telemetry when the top-level benchmark copy only has metadata. Run manifests now also expose that file under `actual_costs_json`.

Prompt artifact export now lives in `prompt_artifacts.py`. It has a descriptor boundary:
- `discover_codexfarm_prompt_run_descriptors(...)` adapts current raw CodexFarm layout.
- the discoverer also follows benchmark `run_manifest.json` pointers like `stage_run_dir` / `processed_output_run_dir` when the prompt request starts from an eval root instead of the real stage run root.
- prompt export also supplements recipe/knowledge rows with copied live `line-role-pipeline/prompts/*` artifacts plus `line_role` rows in `prompts/full_prompt_log.jsonl` when a processed run has canonical line-role Codex interactions.
- prompt export also writes `prompts/thinking_trace_summary.jsonl` and `prompts/thinking_trace_summary.md` from the final merged prompt log so reviewers can inspect trace coverage without chasing raw `.trace.json` paths under `data/output`.
- `discover_prompt_run_descriptors(...)` is a pluggable dispatcher so future stage/cookbook layouts can provide new discovery adapters without changing rendering.
- `render_prompt_artifacts_from_descriptors(...)` writes `prompts/` artifacts from normalized stage descriptors.
- `build_prompt_response_log(...)` is the topology-neutral builder that accepts either explicit descriptors or injected discoverers.
- `build_codex_farm_prompt_response_log(...)` is the convenience wrapper used by CLI call sites.
- `prompt_preview.py` is the zero-token existing-output helper used by `cf-debug preview-prompts`; it rebuilds prompt previews from saved stage artifacts without invoking Codex.

Compact recipe prompt variants now live behind explicit pipeline ids (`recipe.correction.compact.v1` and `recipe.knowledge.compact.v1`), and those ids are now the default recipe-correction / knowledge-stage selections when CodexFarm recipe parsing or optional knowledge extraction is enabled. Line-role prompt compaction is controlled locally by `COOKIMPORT_LINE_ROLE_PROMPT_FORMAT=compact_v1`, which now also becomes the default when unset.

Knowledge harvest now reviews the seed Stage 7 non-recipe spans from `cookimport/staging/nonrecipe_stage.py`, plans explicit shard entries in `codex_farm_knowledge_jobs.py`, executes each shard through `codex_exec_runner.py`, validates exact owned `chunk_id` coverage plus in-surface block evidence in `codex_farm_knowledge_ingest.py`, and then merges surviving `block_decisions` back into final `knowledge` versus `other` authority. Reviewer artifacts still land under `knowledge/<workbook_slug>/snippets.jsonl` and `knowledge.md`, while runtime artifacts now also live under `raw/llm/<workbook_slug>/knowledge/` as `phase_manifest.json`, `shard_manifest.jsonl`, `worker_assignments.json`, `promotion_report.json`, `telemetry.json`, `failures.json`, per-shard proposals, and per-shard `prompt.txt` / `events.jsonl` / `usage.json` files under `workers/<worker>/shards/<shard>/`.

The live knowledge phase still reuses the compact pack id `recipe.knowledge.compact.v1` underneath the shard runtime. The important cutover is that shard ownership, worker reuse, proposal validation, and fallback behavior are now repo-owned instead of being implicit in one direct bundle pass. Prompt-preview and prompt/debug readers now pair `raw/llm/<workbook_slug>/knowledge/in/` with validated `raw/llm/<workbook_slug>/knowledge/proposals/` files directly.

The canonical recipe setting id is now `llm_recipe_pipeline=codex-recipe-shard-v1`. The live recipe phase now groups nearby recipes into explicit shard payloads, executes those shards through `phase_worker_runtime.py` using the compact pack id `recipe.correction.compact.v1`, validates exact owned `recipe_id` coverage, and then promotes validated per-recipe outputs back into deterministic final assembly. Runtime artifacts live under `raw/llm/<workbook_slug>/recipe_phase_runtime/`, while compatibility per-recipe artifacts still bridge through `raw/llm/<workbook_slug>/recipe_correction/{in,out}` plus `recipe_correction_audit/`.

Current recipe-object transport note: the correction loader uses native nested objects for `canonical_recipe`. Fake-runner outputs follow the same contract.

Current recipe-correction hardening note: manifest rows expose `final_mapping_status` / `final_mapping_reason` for the deterministic final assembly that consumes `ingredient_step_mapping`.

Default behavior remains deterministic unless a non-`off` recipe Codex pipeline is explicitly enabled.
