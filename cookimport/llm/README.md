# cookimport/llm

Optional LLM integrations live here.

Recipe codex-farm flow is implemented in `codex_farm_orchestrator.py` with strict pass contracts in `codex_farm_contracts.py` and subprocess/fake runners in `codex_farm_runner.py` and `fake_codex_farm_runner.py`.

Run settings now include explicit pass pipeline ids (`codex_farm_pipeline_pass1/2/3`) plus optional workspace override (`codex_farm_workspace_root`) so recipeimport can target external codex-farm pipeline packs without code edits.

Codex Farm model discovery for interactive run settings now comes from `codex-farm models list --json`, and subprocess orchestration validates configured pipeline ids via `codex-farm pipelines list --root ... --json` before pass execution.

When `codex-farm process --json` fails and returns a `run_id`, runner errors now include a follow-up summary from `codex-farm run errors --run-id ... --json`.
If that summary reports `no last agent message` (typically `nonzero_exit_no_payload` chunk failures), the runner now treats it as recoverable partial-output mode so orchestrators can continue and mark only affected bundles as missing.

Runner process metadata now surfaces CodexFarm `process --json.telemetry_report` as `telemetry_report`, best-effort `run autotune --json` output as `autotune_report`, and keeps `codex_exec_activity.csv` slices as `telemetry`; recipe/pass4/pass5 manifests persist all three for prompt-tuning analysis.

When a caller provides a progress callback, `SubprocessCodexFarmRunner` now executes `codex-farm process --progress-events --json`, parses `__codex_farm_progress__` stderr JSON events, and forwards spinner-friendly `task X/Y` status messages through the existing callback channel used by stage + benchmark flows.

Canonical line-role fallback support now lives in `canonical_line_role_prompt.py` (prompt construction) and `codex_exec.py` (shared `codex exec -` invocation helper reused by prelabel + line-role paths).

Prediction runs now also write `prediction-run/prompt_budget_summary.json`, which merges codex-farm pass telemetry plus line-role telemetry into one repo-owned per-pass budget artifact.

Compact recipe prompt variants now live behind explicit pipeline ids (`recipe.schemaorg.compact.v1`, `recipe.final.compact.v1`, and `recipe.knowledge.compact.v1`), and those compact ids are now the default pass2/pass3/pass4 selections when CodexFarm recipe parsing or knowledge harvest is enabled. Line-role prompt compaction is controlled locally by `COOKIMPORT_LINE_ROLE_PROMPT_FORMAT=compact_v1`, which now also becomes the default when unset.

The step4 prototype adds `llm_recipe_pipeline=codex-farm-2stage-repair-v1`, which keeps pass1 chunking but swaps the pass2/pass3 seam for one merged compact stage (`recipe.merged-repair.compact.v1`). The merged stage emits one canonical recipe object; recipeimport derives schema.org and `RecipeDraftV1` shapes locally and writes per-recipe audit files under `raw/llm/<workbook>/merged_repair_audit/`.

Current pass2/pass3 hardening note: malformed pass2 `field_evidence` is recovered into `{}` with a warning, extracted ingredient/instruction arrays are control-byte sanitized, overlap-truncated pass1 rows record `pass1_degradation_reasons`, and manifest rows now expose `pass3_mapping_status` / `pass3_mapping_reason` when pass3 returns or skips ingredient-step mapping work.

Default behavior remains deterministic unless a non-`off` recipe Codex pipeline is explicitly enabled.
