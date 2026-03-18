---
summary: "Current LLM integration boundaries for CodexFarm across recipe, line-role, knowledge, and prelabel flows."
read_when:
  - When changing codex-farm settings or pipeline IDs
  - When debugging optional knowledge-stage artifacts
  - When auditing recipe pipeline enablement/default behavior
  - When reconciling Label Studio prediction-run LLM wiring vs stage wiring
---

# LLM Section Reference

LLM usage in this repo is optional. Recipe, knowledge, and line-role now each use one direct `codex exec` structured call per shard.

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

- `cookimport/llm/phase_worker_runtime.py` is the shared shard-worker foundation and still defines the manifest/assignment/promotion artifact contract that the direct recipe, knowledge, and line-role runtimes mirror.
- `cookimport/llm/codex_exec_runner.py` is the repo-owned direct structured Codex subprocess seam used by the live recipe, knowledge, and line-role transports.

Recipe CodexFarm path:

- `cookimport/llm/codex_farm_orchestrator.py`
- `cookimport/llm/codex_farm_contracts.py`
- `cookimport/llm/codex_farm_ids.py`
- `cookimport/llm/codex_farm_runner.py`

Other active Codex-backed surfaces:

- Optional knowledge extraction: `cookimport/llm/codex_farm_knowledge_orchestrator.py`, `cookimport/llm/codex_farm_knowledge_jobs.py`, `cookimport/llm/codex_farm_knowledge_contracts.py`, `cookimport/llm/codex_farm_knowledge_models.py`, `cookimport/llm/codex_farm_knowledge_ingest.py`, `cookimport/llm/codex_farm_knowledge_writer.py`, `cookimport/llm/knowledge_prompt_builder.py`
- Canonical line-role: `cookimport/parsing/canonical_line_roles.py`, `cookimport/llm/canonical_line_role_prompt.py`, `cookimport/llm/codex_exec_runner.py`
- Freeform prelabel: `cookimport/labelstudio/prelabel.py`
- Prompt/debug artifact export: `cookimport/llm/prompt_artifacts.py`

Recipe tagging is part of the recipe surface itself. The recipe-correction prompt emits raw selected tags, and deterministic normalization folds them into staged outputs.

The live Codex-backed surfaces are `recipe`, `line_role`, `knowledge`, and `prelabel`.

## Current live surfaces

- `llm_recipe_pipeline`: `off`, `codex-recipe-shard-v1`
- `llm_knowledge_pipeline`: `off`, `codex-knowledge-shard-v1`
- `line_role_pipeline`: `off`, `codex-line-role-shard-v1`
- Prelabel is a separate Codex surface routed through CodexFarm pipeline `prelabel.freeform.v1`

Migration note:

- removed pre-shard public pipeline ids are no longer accepted on active run-setting surfaces; active defaults/help now only advertise the shard-v1 ids
- the shard-v1 work is a runtime refactor over the existing label-first staged importer, not a new pipeline
- shards are ownership units and workers are bounded execution contexts; preview, prompt exports, and reviewer artifacts should describe both instead of pretending one prompt equals one independent task
- the foundation plan froze the ids and runtime contracts first; recipe, knowledge, and line-role now all execute through shard-owned runtime artifacts, and the preview/export cutover has landed on top of those artifacts
- prompt planning now defaults to direct per-phase prompt-count controls (`recipe_prompt_target_count`, `knowledge_prompt_target_count`, `line_role_prompt_target_count`) with current default `5` per enabled phase; lower-level shard-size knobs remain explicit overrides
- knowledge and line-role no longer use the path-mode CodexFarm `process` transport; each sends one inline prompt per shard through `codex exec`
- recipe no longer uses the classic `codex-farm process` transport either; it now renders the shard JSON inline into the checked-in recipe prompt and sends one direct structured call per shard through `codex exec`
- recipe shard JSON and recipe shard outputs now use compact aliases on the live model-facing seam (`sid`, `rid`, `cr`, `tg`, etc.), while deterministic promotion still normalizes the result back into the existing staged outputs

## Policy boundary

- `RunSettings()` defaults are safe/off:
  - `llm_recipe_pipeline=off`
  - `line_role_pipeline=off`
  - `llm_knowledge_pipeline=off`
  - `atomic_block_splitter=off`
- fully Codex-backed runs now come from enabling those surfaces explicitly, not from a separate deterministic line-role middle mode
- `cookimport/config/codex_decision.py` is the shared approval and metadata layer.
- Execute mode requires explicit approval at the command boundary.
- `--codex-execution-policy plan` writes `codex_execution_plan.json` and returns before live Codex work.
- plan mode is a planning stop, not a real shard-runtime rehearsal. If you need zero-token validation of worker sandboxes, in/out folders, proposal validation, or promotion wiring, redirect `SubprocessCodexFarmRunner` through a fake `codex-farm` executable via `--codex-farm-cmd` so the live subprocess path still runs.
- for path-backed direct-exec phases such as line-role, the fake exec shim must read the deposited task file named in the wrapper prompt; answering from the example JSON embedded in the prompt text will produce false `atomic_index:123` validation failures.
- `labelstudio-import --prelabel` is its own Codex surface; recipe settings do not implicitly approve it.
- `COOKIMPORT_ALLOW_LLM` still blocks unapproved live Codex execution by default.
- current runner behavior assumes current local `codex-farm` support; older benchmark-flag and stderr/progress fallback compatibility paths were intentionally removed during the legacy purge

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

## Plain-English Pipeline

If you want the current Codex-backed flow in operator language instead of artifact language, this is the simplest accurate version:

1. The program parses the cookbook into one ordered set of atomic lines and other deterministic intermediate structures.
2. The program makes a deterministic first pass over those lines before any Codex-backed review.
3. The line-role Codex surface reviews the whole book line set in one file-backed labeling pass. Operator-wise this is just "label the lines."
4. The program groups the corrected recipe-side lines into coherent recipe spans and recipes. Everything not grouped into recipe spans becomes the non-recipe side.
5. The recipe Codex surface reviews the recipe side in owned recipe shards. It returns corrected recipe payloads plus ingredient-step mapping and raw selected tags.
6. The program deterministically validates and promotes those recipe outputs into the final recipe formats.
7. The knowledge Codex surface reviews the non-recipe side. It does not blindly process every leftover line as raw text; the program first builds eligible non-recipe chunks and skips obvious low-signal noise. Codex then keeps/refines useful cooking knowledge while rejecting blurbs, filler, and other author yapping.
8. The program validates owned output coverage, writes artifacts/reports, and emits the final recipe, knowledge, and debug outputs.

Worker/shard mental model:

- A setting such as `5 / 5 / 5` means the runtime aims for about five owned shards/workers for each enabled surface (`line_role`, `recipe`, `knowledge`), not that five agents free-edit shared files in place.
- The durable contract is "immutable input payload in, structured owned output/proposal out." The runtime then validates exact ownership/coverage and promotes only valid results.
- Recipe tags are part of the recipe correction surface, not a fourth independent Codex phase.
- Freeform prelabel is separate again; it is not part of the recipe/line-role/knowledge trio above.

## Artifacts

Recipe passes write under:

- `data/output/<ts>/raw/llm/<workbook_slug>/recipe_manifest.json`
- `data/output/<ts>/raw/llm/<workbook_slug>/recipe_correction_audit/`
- `data/output/<ts>/raw/llm/<workbook_slug>/recipe_phase_runtime/inputs/*.json`
- `data/output/<ts>/raw/llm/<workbook_slug>/recipe_phase_runtime/phase_manifest.json`
- `data/output/<ts>/raw/llm/<workbook_slug>/recipe_phase_runtime/shard_manifest.jsonl`
- `data/output/<ts>/raw/llm/<workbook_slug>/recipe_phase_runtime/worker_assignments.json`
- `data/output/<ts>/raw/llm/<workbook_slug>/recipe_phase_runtime/promotion_report.json`
- `data/output/<ts>/raw/llm/<workbook_slug>/recipe_phase_runtime/telemetry.json`
- `data/output/<ts>/raw/llm/<workbook_slug>/recipe_phase_runtime/failures.json`
- `data/output/<ts>/raw/llm/<workbook_slug>/recipe_phase_runtime/proposals/*.json`

Recipe runtime note:
- the live recipe implementation now groups nearby recipes into explicit shard payloads, executes them through the repo-owned direct recipe worker runtime in `codex_farm_orchestrator.py`, validates exact owned `recipe_id` coverage, and promotes only validated per-recipe outputs
- worker assignments now launch concurrently and then merge results back in planned assignment order so runtime artifacts stay stable while multi-worker runs become real
- deterministic code still builds the intermediate `RecipeCandidate`, Codex still emits `ingredient_step_mapping` plus raw `selected_tags`, and deterministic code still rebuilds the final cookbook3 draft locally and normalizes tags before write-out
- the authoritative recipe contract is now: `recipe_phase_runtime/inputs/*.json` immutable shard payloads, `recipe_phase_runtime/proposals/*.json` validated shard proposals, then deterministic promotion into staged outputs; `recipe_correction_audit/` remains only the per-recipe human/debug summary surface
- recipe worker shard folders now also write `prompt.txt`, `events.jsonl`, `usage.json`, `last_message.json`, and `cost_breakdown.json`, so prompt-preview and actual-cost reporting can talk about the same visible request/response surface
- `stage_observability.json` now reports the semantic recipe stages `build_intermediate_det`, `recipe_llm_correct_and_link`, and `build_final_recipe`

Knowledge-stage writes:

- `data/output/<ts>/08_nonrecipe_spans.json`
- `data/output/<ts>/09_knowledge_outputs.json`
- `data/output/<ts>/raw/llm/<workbook_slug>/knowledge_manifest.json`
- `data/output/<ts>/raw/llm/<workbook_slug>/knowledge/in/*.json`
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
- the live knowledge model call now goes through `codex_exec_runner.py`, but it keeps the same shard-manifest / worker-assignment artifact shape the shared runtime established
- `codex_farm_knowledge_ingest.py` validates exact owned `chunk_id` coverage and rejects any `block_decisions` or snippet evidence that point outside the shard's eligible block surface
- the authoritative knowledge contract is now: `knowledge/in/*.json` immutable shard payloads, `knowledge/proposals/*.json` validated shard proposals, then deterministic promotion into `08_nonrecipe_spans.json`, `09_knowledge_outputs.json`, and reviewer-facing knowledge artifacts
- the runtime cutover did not require a brand-new pack immediately; `codex-knowledge-shard-v1` still reuses the compact knowledge pack underneath, and the important authority seam is shard ownership plus validation, not a new prompt asset family
- knowledge worker assignments now launch concurrently and merge back in planned order so `running N` reflects real in-flight work
- prompt-cost control for this stage lives before worker execution:
  - `cookimport/parsing/chunks.py` routes obvious blurbs, navigation fragments, attribution-only text, and similar low-value prose to `noise`
  - `build_knowledge_jobs(...)` bundles surviving nearby chunks into local jobs instead of writing one prompt per chunk
  - table-heavy chunks stay isolated, soft-gap packing can cross small outside-recipe gaps, and tiny low-signal chunks can be pruned when they have no heading/highlight/table evidence
  - the shared default knowledge context is now `0` blocks

Inline recipe tagging writes through the normal recipe artifacts:

- `data/output/<ts>/final drafts/<workbook_slug>/r{index}.json` as `recipe.tags`
- `data/output/<ts>/intermediate drafts/<workbook_slug>/r{index}.jsonld` as `keywords`

Line-role prediction artifacts live under:

- `prediction-run/line-role-pipeline/telemetry_summary.json`
- `prediction-run/line-role-pipeline/runtime/phase_manifest.json`
- `prediction-run/line-role-pipeline/runtime/shard_manifest.jsonl`
- `prediction-run/line-role-pipeline/runtime/worker_assignments.json`
- `prediction-run/line-role-pipeline/runtime/proposals/*.json`

Line-role runtime note:
- live line-role execution no longer uses `phase_worker_runtime.py` or `codex-farm process`
- `canonical_line_roles.py` now assigns shard ownership directly, writes authoritative worker-local shard JSON under `line-role-pipeline/runtime/line_role/workers/*/in/*.json`, sends one short file-backed wrapper prompt per shard through `codex_exec_runner.py`, validates exact owned `atomic_index` coverage, and writes repo-owned worker artifacts under `line-role-pipeline/runtime/line_role/workers/.../shards/<shard_id>/`
- there is no longer any live or compatibility support for a separate LLM recipe gate inside line-role; the only active line-role model surface is the single `line_role` labeling phase
- line-role pre-grouping candidates now default to `within_recipe_span=None`; importer recipe provenance is no longer supplied before deterministic/Codex labeling, and prompt-preview reconstruction mirrors that same span-free contract
- `AtomicLineCandidate` is now a single-line parser record; selective inline `ctx:` rows and cache identity derive neighbor text from explicit ordered-candidate lookup instead of embedded `prev_text` / `next_text` fields
- `workers/*/in/*.json` are now the authoritative model-facing task payloads; `prompt.txt` is only the short wrapper that points at that file
- line-role now keeps a second local-only debug copy at `workers/*/debug/*.json`; prompt-preview mirrors that as `line-role-pipeline/debug_in/*.json`, while `request_input_file` and budget estimation still point at the compact billed `in/*.json` file.
- those `workers/*/in/*.json` rows are now compact tuples: `{"v":1,"shard_id":...,"rows":[[atomic_index,label_code,current_line], ...]}`. The richer deterministic/rule metadata moved to the debug copy, and the model-facing file still avoids repeated neighbor context.
- `telemetry_summary.json` remains the prompt/debug and post-run cost seam for line-role, but its runtime metadata now describe direct exec instead of CodexFarm `process`
- line-role worker launches are concurrent and then re-collected in planned order so stable artifacts and real worker fan-out coexist

Prompt/debug artifacts:

- `prompts/full_prompt_log.jsonl` is the stable per-call truth
- `prompts/prompt_log_summary.json` is the small count summary for that log; it separates raw row count from `runtime_shard_count` so bundled recipe outputs do not look like extra Codex calls
- `prompts/prompt_request_response_log.txt` is the human-readable convenience export
- `prompts/prompt_type_samples_from_full_prompt_log.md` is a sampled reviewer view
- `prompts/thinking_trace_summary.jsonl` and `prompts/thinking_trace_summary.md` summarize trace-path coverage, availability, and reasoning-event presence from the merged prompt log
- `prediction-run/prompt_budget_summary.json` is the post-run actual-costs artifact; it merges recipe/knowledge telemetry with line-role telemetry when present and publishes semantic `by_stage` totals instead of an old pass-slot grouping container
- `prediction-run/prompt_budget_summary.json` now also reports requested-vs-actual run-count metadata per active Codex stage (`requested_run_count`, `actual_run_count`, `run_count_status`, `run_count_explanation`) so a finished run shows clearly when a `3/4/5` target was matched or when the planner legally used fewer/more shards
- `prediction-run/prompt_budget_summary.json` now also falls back to current shard-runtime worker telemetry plus the linked processed-run `line-role-pipeline/telemetry_summary.json` when a benchmark/prediction manifest only carries lightweight phase summaries or a metadata-only benchmark copy
- when line-role telemetry only exposes nested batch/attempt summaries, `prompt_budget_summary.json` should still recover those `tokens_total` values so the finished-run whole-run drain is not understated
- for line-role, requested-vs-actual run-count reporting is surface-level: compare the requested line-role target against the actual shard count on the single live `line_role` phase
- `cf-debug preview-prompts --run ... --out ...` rebuilds zero-token prompt previews from an existing processed run or benchmark run root and writes `prompt_preview_manifest.json` plus prompt artifacts under the chosen output dir
- preview budget estimation is predictive-only: it rebuilds deterministic/`vanilla` shard payloads locally, estimates tokens from reconstructable prompt/output structure, and never reuses Codex-backed run telemetry
- predictive preview is now structural rather than ratio-based: it tokenizes the reconstructed prompt wrapper plus deposited task-file body with `tiktoken`, estimates output tokens from schema-shaped JSON built from the planned shard input, and reports stages as unavailable when that structure cannot be rebuilt safely
- older saved runs that predate the prompt-target fields should default preview planning to the current shard-v1 target count (`5`) for each enabled phase instead of falling back to legacy shard-size defaults
- retrospective “what did this completed run actually cost?” reporting lives in the finished-run `prompt_budget_summary.json` / `actual_costs_json` artifact, not in prompt preview
- when `--run` points at a benchmark root, preview follows `run_manifest.json.artifacts.{processed_output_run_dir,stage_run_dir}` until it reaches the processed stage run with the real staged outputs
- preview manifests now carry `phase_plans` keyed by stage, with worker count, shard count, owned-ID distributions, and first-turn payload distributions; prompt rows also carry `runtime_shard_id`, `runtime_worker_id`, and `runtime_owned_ids`
- `cf-debug preview-shard-sweep --run ... --experiment-file docs/examples/shard_sweep_examples.json --out ...` runs several local worker/shard planning variants and writes one sweep manifest plus per-experiment preview dirs
- preview export now always rebuilds recipe and knowledge shard payloads from the predictive-safe processed artifact itself; it does not depend on saved live payload copies under `raw/llm/<workbook_slug>/recipe_phase_runtime/inputs/` or `raw/llm/<workbook_slug>/knowledge/in/`
- preview export also writes `prompt_preview_budget_summary.json` and `prompt_preview_budget_summary.md`; it is predictive-only, prefers the paired deterministic/`vanilla` processed artifact when a benchmark root has both variants, uses structural prompt/output reconstruction for token estimates, reports stages as unavailable when that structure cannot be reconstructed safely, and hard-refuses Codex-backed or ambiguous processed runs
- reviewer-facing prompt files stay prompt-level on purpose; the durable cutover is to annotate them with runtime ownership metadata (`runtime_shard_id`, `runtime_worker_id`, `runtime_owned_ids`), not to invent a second legacy export family just for shard workers
- when you want “how many Codex jobs actually ran?” on classic shard runtime, prefer stage `call_count` in `prompt_budget_summary.json` or `prompts/prompt_log_summary.json.runtime_shard_count`; raw `full_prompt_log_rows` may be higher because one shard output can expand into several per-item rows
- preview defaults to the shard-v1 surfaces unless explicitly overridden, so it can project post-refactor worker/shard budgets over saved deterministic-only benchmark outputs too
- preview reconstruction is local-only and composed from three seams:
  - recipe prompt inputs from CodexFarm job builders in `codex_farm_orchestrator`
  - knowledge prompt inputs from `codex_farm_knowledge_jobs`, which now plans shard-owned compact payloads for both live non-recipe knowledge review and preview reconstruction
  - line-role prompt text from `build_canonical_line_role_prompt`
- knowledge preview now follows the live bundle contract exactly: prompt counts come from contiguous bundled `chunks[*]` payloads, not one chunk per prompt
- the current default knowledge context is `0` blocks on each side, and that default is shared across stage, benchmark, CLI, and prompt-preview paths
- when explicit `knowledge_prompt_target_count` is driving the shard plan, knowledge bundling should not split again on the older per-bundle char cap
- line-role preview must batch the full ordered candidate set and pass `deterministic_label` plus `escalation_reasons` into `build_canonical_line_role_prompt(...)`; preview-only unresolved shortlists are a stale contract and will understate line-role prompt volume.
- line-role prompt reconstruction no longer injects grouped recipe spans or importer provenance. The pre-grouping contract is now span-free: prompt text explicitly says no prior recipe-span authority is provided, and candidate rows default to `within_recipe_span=None` until grouped labels are projected later.
- line-role row transport is now split cleanly by seam: the inline compact prompt uses pipe-delimited target rows plus selective `ctx:` windows, the file-backed billed shard JSON is the tuple-based `v=1` transport, and a parallel debug copy keeps the richer local object rows
- prompt/actual cost reporting for the direct phases now also carries a shared cost-breakdown vocabulary: `visible_input_tokens`, `cached_input_tokens`, `visible_output_tokens`, and `wrapper_overhead_tokens`
- live line-role execution no longer fans out through one-shot prompt batches inside `canonical_line_roles.py`; it now plans contiguous shards, sends the built prompt text itself through direct `codex exec`, validates exact owned-row coverage on the way back, and promotes accepted rows into the existing `label_llm_correct` outputs.
- prompt preview does not reconstruct a separate tags surface; inline recipe tags ride on the recipe contract and are projected into outputs after correction/normalization, so tagging changes do not add prompt input tokens unless the recipe prompt itself changes
- preview-only runs may not have `var/run_assets/<run_id>/`; in that case prompt reconstruction falls back to pipeline metadata in `llm_pipelines/`
- preview reconstruction is intentionally preview-only. Do not add a fake execution path into the live orchestrators just to make prompt previews work.
- prompt artifacts are stage-named now (`stage_key`, `stage_label`, `stage_artifact_stem`) and emit stage-named files such as `prompt_nonrecipe_knowledge_review.txt`
- active knowledge-stage follow-up/debug surfaces should use semantic `knowledge` selectors and audit names. Older numbered stage labels belong only to archived local readers.

Prompt cost notes worth keeping in mind:

- the first 2026-03-16 prompt audit measured about `663k` live-like input tokens on an `~86k` token source book
- after the current shared line-role and knowledge cuts, the same benchmark preview rebuild measures about `386k` live-like input tokens and `~449k` estimated total tokens
- after the prompt-target + path-handoff update on 2026-03-17, the same `saltfatacidheatcutdown` preview rebuild measures `15` total prompts (`5` recipe, `5` line-role, `5` knowledge), about `188k` estimated input tokens, and about `224k` estimated total tokens
- the biggest measured fan-out reductions came from shared builders, not preview-only tricks:
  - knowledge preview on `saltfatacidheatcutdown` moved from `324` prompts to `91`, then to `40`, after noise routing, local bundling, soft-gap packing, and low-signal pruning landed in the live knowledge job builder
  - line-role preview on the same run moved from `45` prompts to `15`, then to `8`, after raw-prompt transport, larger shared batch defaults, and compact row serialization landed in the live line-role path
  - the next cut landed by changing the default control surface from shard size to per-phase prompt target, then removing the remaining knowledge bundle char-cap split when that prompt target is explicitly in force
- the durable shape lessons are:
  - knowledge prompt count fell because contiguous chunks were packed across neighboring seed spans, not only within each individual seed span
  - after that, remaining knowledge prompt count was mostly gap-limited by hard breaks between chunk runs
  - line-role cost after the transport fix mostly lived in repeated per-row keys and duplicated inline neighbor text, so the right seam is one ordered contiguous slice without in-slice line repetition
  - after those cuts, most remaining prompt budget is real task payload rather than wrapper waste
- recipe live spend can still be far above the visible prompt text because classic path handoff lets Codex reread deposited shard files through shell commands; treat finished-run `prompt_budget_summary.json` as the authority for actual cost
- the implemented low-risk trims are:
  - drop empty recipe `draft_hint`
  - remove recipe hint provenance from correction payloads
  - reduce knowledge context blocks from `12 -> 4 -> 2 -> 0`
  - skip knowledge calls already marked `suggested_lane=noise`
  - bundle local knowledge chunks instead of writing one chunk per prompt
  - compact line-role rows into batch-level legends and one ordered contiguous slice with no inline neighbor duplication
  - remove recipe-range authority from line-role prompts so Codex reviews the deterministic labels without inherited recipe membership
  - switch active shard-v1 packs to file-path prompt transport so prompt wrapper text only carries instructions plus `INPUT_PATH`, while the task payload already lives in the worker folder on disk
  - default active shard-v1 phases to `*_prompt_target_count=5`, with older shard-size knobs retained only as explicit lower-level overrides

Where prompt cuts should live:

- recipe prompt body reductions should usually happen in the shared `MergedRecipeRepairInput` serializer so live recipe runs and preview reconstruction stay aligned
- knowledge prompt count reductions should usually happen in `build_knowledge_jobs(...)`, because both live harvest and preview reconstruction consume that builder
- obvious junk suppression for knowledge cost should also live in `chunks.py` lane scoring so live harvest and preview both skip the same blurbs / navigation / attribution fragments
- chunk-count suppression should also live in `chunks.py`: collapsing standalone heading/bridge chunks before bundling is cheaper and safer than trying to fix that fragmentation in the prompt layer
- when `build_knowledge_jobs(...)` skips every chunk, `run_codex_farm_nonrecipe_knowledge_review(...)` must short-circuit before invoking Codex or writing misleading empty-output manifests

Run-level observability note:
- `stage_observability.json` at the run root is the canonical stage index. The recipe and knowledge manifests above are stage-local detail, not a second naming system.

Shard-runtime observability note:
- `phase_worker_runtime.py` standardizes `phase_manifest.json`, `shard_manifest.jsonl`, `worker_assignments.json`, `promotion_report.json`, `telemetry.json`, `failures.json`, per-worker status files, and per-shard proposals as the runtime-artifact family the active recipe, knowledge, and line-role phases now populate with real work
- those active shard runtimes now also launch worker assignments concurrently up to the resolved worker count instead of looping through assigned workers one at a time; recipe still runs one classic CodexFarm process per worker assignment, while knowledge and line-role direct runtimes do the same with direct `codex exec` shard calls

## Runner and contract notes

- `SubprocessCodexFarmRunner` validates configured pipeline IDs via `codex-farm pipelines list --root ... --json`.
- `SubprocessCodexFarmRunner` now forces RecipeImport-owned CodexFarm subprocesses onto `~/.codex-recipe` by default by injecting `CODEX_HOME` plus `CODEX_FARM_CODEX_HOME_RECIPE` at the transport layer; explicit subprocess env overrides still win.
- `SubprocessCodexFarmRunner` now maps RecipeImport benchmark mode to CodexFarm's `--recipeimport-benchmark-mode line_label_v1`; ordinary `extract` mode sends no benchmark-only process flag.
- For zero-token handoff rehearsal, point `--codex-farm-cmd` at `scripts/fake-codex-farm.py` and still run execute mode with `--allow-codex`; RecipeImport will exercise the real shard-runtime folders through the subprocess runner without live model calls.
- shard-v1 recipe workers still explicitly run `codex-farm process --runtime-mode classic_task_farm_v1 --workers 1`; knowledge and line-role now use one direct `codex exec` call per shard, so the “one shard equals one real model call” contract is literal on those surfaces
- when `recipe_worker_count`, `knowledge_worker_count`, or `line_role_worker_count` are unset, shard-v1 now defaults live and preview worker planning to the planned shard/job count for that one book+phase, capped at `20`
- the old misleading state was “planned N workers, launched one assignment loop”; current shard-v1 runtime behavior is “planned N workers, launch up to N worker assignments concurrently” with shard count still acting as the true upper bound
- RecipeImport no longer labels shard-v1 work as `structured_loop_agentic_v1`; the classic runtime choice is intentional so prompt-target counts describe real shard-call count instead of hidden extra session turns. True multi-shard session reuse would be a future transport change, not the current default.
- classic path handoff is still not a free lunch on recipe: Codex may `cat` / `sed` / `jq` the deposited shard files during one task, so raw prompt size and real token spend can diverge sharply there
- Runner resolves each pipeline's `output_schema_path` and passes it explicitly as `--output-schema`.
- `process --json` metadata is persisted as the semantic recipe-correction `process_run`.
- Persisted process metadata includes:
  - `telemetry_report`
  - `autotune_report`
  - compact CSV `telemetry` slices
- When callers provide progress callbacks, runner requires `codex-farm process --progress-events --json`.
- Current runners must emit structured progress events plus JSON stdout when `--json` is requested; older stderr-only progress and missing-flag fallbacks are no longer supported.
- Direct line-role and knowledge runtimes now also emit repo-owned structured stage-progress callback payloads (task counters, effective worker counts, active shard labels, queued-shard detail) so CLI benchmark/import spinners and `processing_timeseries*.jsonl` capture the same stage metadata.
- The shared recipe `phase_worker_runtime.py` seam now emits the same outer structured progress snapshots for recipe shard work, reporting configured workers, queued shards, and active worker buckets even though each worker still runs one classic CodexFarm `process` call for its assigned shard set.
- Recoverable partial-output failures include `no last agent message` and `nonzero_exit_no_payload`.
- In benchmark recipe mode, those recoverable failures can trigger selective retry of only missing recipe-correction bundles.
- Recipe pass block extraction falls back to `full_text.lines` when cached payloads are missing `full_text.blocks`.

Compact/default contract:

- Default recipe correction pack id is `recipe.correction.compact.v1`
- Knowledge pack remains `recipe.knowledge.compact.v1`
- Canonical line-role prompt format is `compact_v1`.
- Shared line-role Codex batching now assumes the larger compact-shape default (`240`) rather than the older small-batch preview shape.

Structured output contract:

- Codex schemas must stay inside the OpenAI strict subset.
- Top-level properties must also appear in `required`.
- Nullable fields must still be present and use `null` when empty.
- `ingredient_step_mapping` is on-wire as an array of mapping-entry objects and is normalized back to the internal dict form after validation.

## Related docs

- `docs/10-llm/10-llm_log.md`
- `docs/10-llm/nonrecipe_knowledge_review.md`

## Recent Durable Notes

- In single-offline benchmark runs, missing benchmark-level `prompts/` exports does not by itself mean CodexFarm did not run. The lower-level truth is the linked processed stage run under `data/output`, where raw recipe/knowledge inputs, outputs, and `.codex-farm-traces` live.
- After shard-v1 cutover, active run-setting surfaces are already strict about pipeline ids. If legacy behavior still shows up, it is more likely to be a reader/fixture/tooling seam than the live recipe, knowledge, or line-role execution path.
- `prompt_budget_summary.json` must aggregate CodexFarm split tokens from both nested `process_payload.telemetry.rows` and the benchmark single-offline top-level `stage_payload.telemetry.rows` layout. Otherwise `tokens_input`, `tokens_cached_input`, and `tokens_output` can drop to null while per-call telemetry still exists.
- `prompt_budget_summary.json` must also prefer one knowledge telemetry layer when aggregate direct-exec payloads duplicate the same stage totals at both the top level and nested worker/runtime levels. Double-counting that stack makes the knowledge stage look more expensive than it was.
- Prompt-cost debugging should separate call-count inflation from prompt-size inflation:
  - call-count inflation on `saltfatacidheatcutdown` came from `175` grouped recipe spans
  - recipe prompt inflation also came from the constant `tagging_guide` payload plus `selected_tags` instructions
- The intended operator shape is still surface-level prompt counts such as `3 / 3 / 3` or `5 / 5 / 5`: one planned shard should correspond closely to one real model call for that surface. Preview and live runtime should be judged against that mental model, not against hidden transport/session turns.
- Line-role transport cost should now be nearly all task prompt, not wrapper overhead. If wrapper chars spike again, inspect raw-prompt transport and compact row serialization before touching the response schema or preview math.
- Current line-role runtime truth is one file-backed `line_role` phase under `line-role-pipeline/runtime/line_role/`. The abandoned inline path and the brief `recipe_region_gate` / `recipe_structure_label` split are historical only; new docs and prompt exports should describe the single file-backed phase plus its worker `in/*.json` payloads.
- File-backed line-role observability has to describe both pieces of the request honestly:
  - the visible wrapper prompt
  - the model-facing task file recorded as `request_input_file`
  `prompt_input_mode=path` is the durable vocabulary for that split.
- Regenerated prompt preview on an old benchmark root is forward-looking, not retrospective truth. Use a fresh preview to answer "what would this cost now?", and use finished-run `prompt_budget_summary.json` / `cf-debug actual-costs` to answer "what did that old run actually cost?".
- Large preview-vs-live gaps on current direct-exec runs are usually transport/runtime accounting issues such as cached-input replay, file reads, or larger real outputs than the structural estimate, not evidence that Codex secretly took extra turns or wandered the repo.
- Recipe direct-exec no longer treats `recipe_correction/{in,out}` as runtime truth. Current readers and debug helpers should start from `recipe_phase_runtime/inputs/*.json`, `recipe_phase_runtime/proposals/*.json`, and `recipe_correction_audit/*.json`.
- Stage 7 wording cleanup was a label/reporting pass, not a new runtime. The durable knowledge contract is still:
  - deterministic seed non-recipe spans
  - parser-owned chunk pruning before review
  - immutable `knowledge/in/*.json` inputs
  - validated `knowledge/proposals/*.json` outputs
  - deterministic promotion into final authority plus reviewer snippets
  Operator-facing clarity now comes from using `non-recipe knowledge review` wording and from richer `knowledge_manifest.json.review_summary` counts/paths.
- The March 17 repo-wide cost-honesty pass landed the main structural pieces:
  - recipe moved off classic task-farm transport onto direct exec
  - recipe payloads and outputs use compact aliases on the model-facing seam
  - line-role debug payloads were trimmed toward the actual prompt contract
  - per-shard and per-stage artifacts now expose visible-input / cached-input / visible-output / wrapper-overhead vocabulary
  The remaining expensive validation step is always a real live benchmark run, not more zero-token plumbing work.
- RecipeImport-owned CodexFarm subprocesses should inherit `~/.codex-recipe` from `cookimport/llm/codex_farm_runner.py`, not from ad hoc shell aliases or per-command CLI glue. If the wrong Codex home is in use, debug the runner env injection first.
- `gpt-5.3-codex-spark` plus reasoning effort does not guarantee reasoning-summary events in saved `.trace.json` files. A zero `reasoning_event_count` can be a legitimate upstream Codex CLI event-stream outcome, not an exporter bug.
