---
summary: "Current LLM integration boundaries for CodexFarm across recipe, line-role, knowledge, and prelabel flows."
read_when:
  - When changing codex-farm settings or pipeline IDs
  - When debugging optional knowledge-stage artifacts
  - When auditing recipe pipeline enablement/default behavior
  - When reconciling Label Studio prediction-run LLM wiring vs stage wiring
---

# LLM Section Reference

LLM usage in this repo is optional. All live Codex-backed surfaces now run through CodexFarm.

## Runtime surface

Settings and command boundary:

- `cookimport/config/run_settings.py`
- `cookimport/config/codex_decision.py`
- `cookimport/cli.py`
- `cookimport/cli_ui/run_settings_flow.py`

Primary entrypoints:

- `cookimport/staging/import_session.py` for stage/import runs
- `cookimport/labelstudio/ingest.py` for prediction-run and Label Studio benchmark/import flows
- `cookimport/entrypoint.py` for saved-settings import passthrough

Shared shard-runtime foundation:

- `cookimport/llm/phase_worker_runtime.py` writes phase/shard manifests, per-worker sandboxes, per-shard proposals, promotion summaries, and runtime telemetry for the later shard-v1 phase cutovers.

Recipe CodexFarm path:

- `cookimport/llm/codex_farm_orchestrator.py`
- `cookimport/llm/codex_farm_contracts.py`
- `cookimport/llm/codex_farm_ids.py`
- `cookimport/llm/codex_farm_runner.py`

Other active Codex-backed surfaces:

- Optional knowledge extraction: `cookimport/llm/codex_farm_knowledge_orchestrator.py`, `cookimport/llm/codex_farm_knowledge_jobs.py`, `cookimport/llm/codex_farm_knowledge_contracts.py`, `cookimport/llm/codex_farm_knowledge_models.py`, `cookimport/llm/codex_farm_knowledge_ingest.py`, `cookimport/llm/codex_farm_knowledge_writer.py`
- Canonical line-role: `cookimport/parsing/canonical_line_roles.py`, `cookimport/llm/canonical_line_role_prompt.py`, `cookimport/llm/phase_worker_runtime.py`
- Freeform prelabel: `cookimport/labelstudio/prelabel.py`
- Prompt/debug artifact export: `cookimport/llm/prompt_artifacts.py`

Recipe tagging is part of the recipe surface itself. The recipe-correction prompt emits raw selected tags, and deterministic normalization folds them into staged outputs.

The live Codex-backed surfaces are `recipe`, `line_role`, `knowledge`, and `prelabel`.

## Current live surfaces

- `llm_recipe_pipeline`: `off`, `codex-recipe-shard-v1`
- `llm_knowledge_pipeline`: `off`, `codex-knowledge-shard-v1`
- `line_role_pipeline`: `off`, `deterministic-v1`, `codex-line-role-shard-v1`
- Prelabel is a separate Codex surface routed through CodexFarm pipeline `prelabel.freeform.v1`

Migration note:

- legacy ids such as `codex-farm-single-correction-v1`, `codex-farm-knowledge-v1`, and `codex-line-role-v1` are no longer accepted on active run-setting surfaces; active defaults/help now only advertise the shard-v1 ids
- the foundation plan froze the ids and runtime contracts first; recipe, knowledge, and line-role now all execute through the shard-worker runtime, while preview/export cleanup remains a later coordinated cutover

`cookimport/llm/codex_exec.py` is a fail-closed retired transport and should not be treated as an active backend.

## Policy boundary

- `RunSettings()` defaults are safe/off:
  - `llm_recipe_pipeline=off`
  - `line_role_pipeline=off`
  - `llm_knowledge_pipeline=off`
  - `atomic_block_splitter=off`
- `cookimport/config/codex_decision.py` is the shared approval and metadata layer.
- Execute mode requires explicit approval at the command boundary.
- `--codex-execution-policy plan` writes `codex_execution_plan.json` and returns before live Codex work.
- `labelstudio-import --prelabel` is its own Codex surface; recipe settings do not implicitly approve it.
- `COOKIMPORT_ALLOW_LLM` still blocks unapproved live Codex execution by default.
- `COOKIMPORT_ALLOW_CODEX_FARM` is a retired transition gate and no longer acts as the approval gate.

Benchmark split:

- `cookimport labelstudio-benchmark` can run Codex-backed prediction surfaces with explicit approval.
- `cookimport bench speed-run` can include Codex permutations, but only with explicit confirmation.
- `cookimport bench quality-run` is deterministic-only and now rejects `--include-codex-farm`.

## Prediction-run versus stage boundary

- Stage/import runs can execute recipe Codex and optional knowledge extraction.
- Inline recipe tags are part of the recipe correction call and ride along with normal recipe processing.
- Prediction-run generation can plan or execute:
  - recipe Codex passes
  - optional knowledge refinement/extraction over seed Stage 7 non-recipe spans
  - canonical line-role Codex labeling
  - freeform prelabel
- Prediction-run plan mode happens after deterministic conversion and archive preparation so the plan artifact can enumerate concrete recipe bundles, knowledge jobs, and line-role batches.
- `prompt_budget_summary.json` should preserve CodexFarm split token totals (`tokens_input`, `tokens_cached_input`, `tokens_output`) from per-call telemetry rows when they are present in the prediction manifest.

## Artifacts

Recipe passes write under:

- `data/output/<ts>/raw/llm/<workbook_slug>/recipe_correction/{in,out}/`
- `data/output/<ts>/raw/llm/<workbook_slug>/recipe_manifest.json`
- `data/output/<ts>/raw/llm/<workbook_slug>/recipe_correction_audit/`
- `data/output/<ts>/raw/llm/<workbook_slug>/recipe_phase_runtime/phase_manifest.json`
- `data/output/<ts>/raw/llm/<workbook_slug>/recipe_phase_runtime/shard_manifest.jsonl`
- `data/output/<ts>/raw/llm/<workbook_slug>/recipe_phase_runtime/worker_assignments.json`
- `data/output/<ts>/raw/llm/<workbook_slug>/recipe_phase_runtime/promotion_report.json`
- `data/output/<ts>/raw/llm/<workbook_slug>/recipe_phase_runtime/telemetry.json`
- `data/output/<ts>/raw/llm/<workbook_slug>/recipe_phase_runtime/failures.json`
- `data/output/<ts>/raw/llm/<workbook_slug>/recipe_phase_runtime/proposals/*.json`

Recipe runtime note:
- the live recipe implementation now groups nearby recipes into explicit shard payloads, executes them through `phase_worker_runtime.py`, validates exact owned `recipe_id` coverage, and promotes only validated per-recipe outputs
- deterministic code still builds the intermediate `RecipeCandidate`, Codex still emits `ingredient_step_mapping` plus raw `selected_tags`, and deterministic code still rebuilds the final cookbook3 draft locally and normalizes tags before write-out
- runtime artifacts now live under `recipe_phase_runtime/`, while compatibility per-recipe artifacts for prompt/debug readers still bridge through `recipe_correction/{in,out}/`
- `stage_observability.json` now reports the semantic recipe stages `build_intermediate_det`, `recipe_llm_correct_and_link`, and `build_final_recipe`

Knowledge-stage writes:

- `data/output/<ts>/08_nonrecipe_spans.json`
- `data/output/<ts>/09_knowledge_outputs.json`
- `data/output/<ts>/raw/llm/<workbook_slug>/knowledge/{in,out}/`
- `data/output/<ts>/raw/llm/<workbook_slug>/knowledge_manifest.json`
- `data/output/<ts>/raw/llm/<workbook_slug>/knowledge/phase_manifest.json`
- `data/output/<ts>/raw/llm/<workbook_slug>/knowledge/shard_manifest.jsonl`
- `data/output/<ts>/raw/llm/<workbook_slug>/knowledge/worker_assignments.json`
- `data/output/<ts>/raw/llm/<workbook_slug>/knowledge/promotion_report.json`
- `data/output/<ts>/raw/llm/<workbook_slug>/knowledge/telemetry.json`
- `data/output/<ts>/raw/llm/<workbook_slug>/knowledge/failures.json`
- `data/output/<ts>/raw/llm/<workbook_slug>/knowledge/proposals/*.json`
- `data/output/<ts>/knowledge/<workbook_slug>/snippets.jsonl`
- `data/output/<ts>/knowledge/<workbook_slug>/knowledge.md`
- `data/output/<ts>/knowledge/knowledge_index.json`

`08_nonrecipe_spans.json` and `09_knowledge_outputs.json` are now the machine-readable outside-span contract. They preserve deterministic seed authority, final authority, and the refinement report that explains any Codex changes. `snippets.jsonl` remains reviewer-facing evidence only.

Knowledge runtime note:
- the live knowledge implementation is no longer one direct `knowledge/in -> knowledge/out` CodexFarm call
- deterministic chunking still decides eligibility, pruning, and local grouping
- `codex_farm_knowledge_jobs.py` now writes stable shard payload files plus shard-manifest metadata with owned `chunk_id`s and owned block indices
- `phase_worker_runtime.py` executes those shard payloads under bounded workers and records runtime telemetry
- `codex_farm_knowledge_ingest.py` validates exact owned `chunk_id` coverage and rejects any `block_decisions` or snippet evidence that point outside the shard's eligible block surface
- only validated shard payloads are copied back into compatibility `knowledge/out/` files for older prompt/debug readers; invalid raw proposals stay in `knowledge/proposals/`

Inline recipe tagging writes through the normal recipe artifacts:

- `data/output/<ts>/final drafts/<workbook_slug>/r{index}.json` as `recipe.tags`
- `data/output/<ts>/intermediate drafts/<workbook_slug>/r{index}.jsonld` as `keywords`

Line-role prediction artifacts live under:

- `prediction-run/line-role-pipeline/telemetry_summary.json`
- `prediction-run/line-role-pipeline/guardrail_report.json`
- `prediction-run/line-role-pipeline/guardrail_changed_rows.jsonl`
- `prediction-run/line-role-pipeline/runtime/phase_manifest.json`
- `prediction-run/line-role-pipeline/runtime/shard_manifest.jsonl`
- `prediction-run/line-role-pipeline/runtime/worker_assignments.json`
- `prediction-run/line-role-pipeline/runtime/proposals/*.json`
- alternate reviewer copies:
  - `prediction-run/line-role-pipeline/do_no_harm_diagnostics.json`
  - `prediction-run/line-role-pipeline/do_no_harm_changed_rows.jsonl`

Prompt/debug artifacts:

- `prompts/full_prompt_log.jsonl` is the stable per-call truth
- `prompts/prompt_request_response_log.txt` is the human-readable convenience export
- `prompts/prompt_type_samples_from_full_prompt_log.md` is a sampled reviewer view
- `prompts/thinking_trace_summary.jsonl` and `prompts/thinking_trace_summary.md` summarize trace-path coverage, availability, and reasoning-event presence from the merged prompt log
- `prediction-run/prompt_budget_summary.json` merges recipe/knowledge telemetry with line-role telemetry when present and now publishes semantic `by_stage` totals instead of an old pass-slot grouping container
- `cf-debug preview-prompts --run ... --out ...` rebuilds zero-token prompt previews from an existing processed run or benchmark run root and writes `prompt_preview_manifest.json` plus prompt artifacts under the chosen output dir
- preview manifests now carry `phase_plans` keyed by stage, with worker count, shard count, owned-ID distributions, and first-turn payload distributions; prompt rows also carry `runtime_shard_id`, `runtime_worker_id`, and `runtime_owned_ids`
- `cf-debug preview-shard-sweep --run ... --experiment-file docs/examples/shard_sweep_examples.json --out ...` runs several local worker/shard planning variants and writes one sweep manifest plus per-experiment preview dirs
- when a processed run already has live CodexFarm input files under `raw/llm/<workbook_slug>/{recipe_correction,knowledge}/in/`, preview export reuses those exact payloads before falling back to local reconstruction
- preview export also writes `prompt_preview_budget_summary.json` and `prompt_preview_budget_summary.md`, with heuristic token estimates plus blunt warnings, but the main table is now worker/shard-centric instead of prompt-count-centric
- preview reconstruction is local-only and composed from three seams:
  - recipe prompt inputs from CodexFarm job builders in `codex_farm_orchestrator`
  - knowledge prompt inputs from `codex_farm_knowledge_jobs`, which now plans shard-owned compact payloads for both live knowledge harvest and preview reconstruction
  - line-role prompt text from `build_canonical_line_role_prompt`
- knowledge preview now follows the live bundle contract exactly: prompt counts come from contiguous bundled `chunks[*]` payloads, not one chunk per prompt
- the current default knowledge context is `0` blocks on each side, and that default is shared across stage, benchmark, CLI, and prompt-preview paths
- line-role preview must batch the full ordered candidate set and pass `deterministic_label` plus `escalation_reasons` into `build_canonical_line_role_prompt(...)`; preview-only unresolved shortlists are a stale contract and will understate line-role prompt volume.
- live line-role execution no longer fans out through one-shot prompt batches inside `canonical_line_roles.py`; it now plans contiguous shards, writes raw prompt-text shard inputs for `line-role.canonical.v1`, validates exact owned-row coverage on the way back, and promotes accepted rows into the existing `label_llm_correct` outputs.
- prompt preview does not reconstruct a separate tags surface; inline recipe tags ride on the recipe contract and are projected into outputs after correction/normalization, so tagging changes do not add prompt input tokens unless the recipe prompt itself changes
- preview-only runs may not have `var/run_assets/<run_id>/`; in that case prompt reconstruction falls back to pipeline metadata in `llm_pipelines/`
- preview reconstruction is intentionally preview-only. Do not add a fake execution path into the live orchestrators just to make prompt previews work.
- prompt artifacts are stage-named now (`stage_key`, `stage_label`, `stage_artifact_stem`) and emit stage-named files such as `prompt_extract_knowledge_optional.txt`
- active knowledge-stage follow-up/debug surfaces should use semantic `knowledge` selectors and audit names. Older numbered stage labels belong only to archived local readers.

Prompt cost notes worth keeping in mind:

- the first 2026-03-16 prompt audit measured about `663k` live-like input tokens on an `~86k` token source book
- after the current shared line-role and knowledge cuts, the same benchmark preview rebuild measures about `386k` live-like input tokens and `~449k` estimated total tokens
- the implemented low-risk trims are:
  - drop empty recipe `draft_hint`
  - remove recipe hint provenance from correction payloads
  - reduce knowledge context blocks from `12 -> 4 -> 2`
  - skip knowledge calls already marked `suggested_lane=noise`
  - blank line-role neighbor context for outside-recipe rows

Where prompt cuts should live:

- recipe prompt body reductions should usually happen in the shared `MergedRecipeRepairInput` serializer so live recipe runs and preview reconstruction stay aligned
- knowledge prompt count reductions should usually happen in `build_knowledge_jobs(...)`, because both live harvest and preview reconstruction consume that builder
- obvious junk suppression for knowledge cost should also live in `chunks.py` lane scoring so live harvest and preview both skip the same blurbs / navigation / attribution fragments
- chunk-count suppression should also live in `chunks.py`: collapsing standalone heading/bridge chunks before bundling is cheaper and safer than trying to fix that fragmentation in the prompt layer
- when `build_knowledge_jobs(...)` skips every chunk, `run_codex_farm_knowledge_harvest(...)` must short-circuit before invoking Codex or writing misleading empty-output manifests

Run-level observability note:
- `stage_observability.json` at the run root is the canonical stage index. The recipe and knowledge manifests above are stage-local detail, not a second naming system.

Shard-runtime observability note:
- `phase_worker_runtime.py` standardizes `phase_manifest.json`, `shard_manifest.jsonl`, `worker_assignments.json`, `promotion_report.json`, `telemetry.json`, `failures.json`, per-worker status files, and per-shard proposals as the runtime-artifact family that later cutovers will populate with real phase work

## Runner and contract notes

- `SubprocessCodexFarmRunner` validates configured pipeline IDs via `codex-farm pipelines list --root ... --json`.
- `SubprocessCodexFarmRunner` now forces RecipeImport-owned CodexFarm subprocesses onto `~/.codex-recipe` by default by injecting `CODEX_HOME` plus `CODEX_FARM_CODEX_HOME_RECIPE` at the transport layer; explicit subprocess env overrides still win.
- shard-runtime worker assignments now also force `codex-farm process --workers 1` for `structured_loop_agentic_v1`, so one RecipeImport worker assignment no longer fans back out into several CodexFarm process workers
- that improves worker-count honesty, but it is still not true multi-shard Codex session reuse: the runner still shells out through `codex-farm process`, and `max_turns_per_shard` remains a repo-side planning/manifest field rather than a transport-enforced limit
- Runner resolves each pipeline's `output_schema_path` and passes it explicitly as `--output-schema`.
- `process --json` metadata is persisted as the semantic recipe-correction `process_run`.
- Persisted process metadata includes:
  - `telemetry_report`
  - `autotune_report`
  - compact CSV `telemetry` slices
- When callers provide progress callbacks, runner prefers `codex-farm process --progress-events --json` and retries once without that flag if the binary does not support it.
- Runner still recognizes the older stderr progress shape (`run=... queued=... running=... done=...`) and treats those lines as progress/control output instead of surfacing them as stderr noise in interactive benchmark/status flows.
- Current runners must emit structured progress events and JSON stdout when `--json` is requested; previous stderr-only progress lines are only a compatibility fallback and should not be the target contract for new codex-farm builds.
- Recoverable partial-output failures include `no last agent message` and `nonzero_exit_no_payload`.
- In benchmark recipe mode, those recoverable failures can trigger selective retry of only missing recipe-correction bundles.
- Recipe pass block extraction falls back to `full_text.lines` when cached payloads are missing `full_text.blocks`.

Compact/default contract:

- Default recipe correction pack id is `recipe.correction.compact.v1`
- Knowledge pack remains `recipe.knowledge.compact.v1`
- Canonical line-role prompt format is `compact_v1`.

Structured output contract:

- Codex schemas must stay inside the OpenAI strict subset.
- Top-level properties must also appear in `required`.
- Nullable fields must still be present and use `null` when empty.
- `ingredient_step_mapping` is on-wire as an array of mapping-entry objects and is normalized back to the internal dict form after validation.

## Inactive modules

These files still exist, but they are not the current stage/prediction/tag runtime path:

- `cookimport/llm/client.py`
- `cookimport/llm/prompts.py`
- `cookimport/llm/repair.py`
- `cookimport/llm/codex_exec.py`

## Related docs

- `docs/10-llm/10-llm_log.md`
- `docs/10-llm/knowledge_harvest.md`

## Recent Durable Notes

- In single-offline benchmark runs, missing benchmark-level `prompts/` exports does not by itself mean CodexFarm did not run. The lower-level truth is the linked processed stage run under `data/output`, where raw recipe/knowledge inputs, outputs, and `.codex-farm-traces` live.
- `prompt_budget_summary.json` must aggregate CodexFarm split tokens from both nested `process_payload.telemetry.rows` and the benchmark single-offline top-level `stage_payload.telemetry.rows` layout. Otherwise `tokens_input`, `tokens_cached_input`, and `tokens_output` can drop to null while per-call telemetry still exists.
- Prompt-cost debugging should separate call-count inflation from prompt-size inflation:
  - call-count inflation on `saltfatacidheatcutdown` came from `175` grouped recipe spans
  - recipe prompt inflation also came from the constant `tagging_guide` payload plus `selected_tags` instructions
- `gpt-5.3-codex-spark` plus reasoning effort does not guarantee reasoning-summary events in saved `.trace.json` files. A zero `reasoning_event_count` can be a legitimate upstream Codex CLI event-stream outcome, not an exporter bug.
