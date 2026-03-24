---
summary: "Current LLM integration boundaries for CodexFarm across recipe, line-role, knowledge, and prelabel flows."
read_when:
  - When changing codex-farm settings or pipeline IDs
  - When debugging optional knowledge-stage artifacts
  - When auditing recipe pipeline enablement/default behavior
  - When reconciling Label Studio prediction-run LLM wiring vs stage wiring
---

# LLM Section Reference

LLM usage in this repo is optional. The direct-exec transport is now mixed by attempt type rather than by stage: recipe, line-role, and knowledge worker assignments all start in one long-lived local workspace-worker session that processes worker-local task files and writes `out/*.json` results incrementally, while stage-specific retry / repair follow-up attempts can still use structured one-shot calls. All three active stages now treat tasks as the normal answer unit inside a shard: line-role splits shards into bounded line packets, recipe usually splits shards into one task per owned recipe, and knowledge splits multi-chunk shards into bounded chunk packets before validation and recovery.

## Runtime surface

Settings and command boundary:

- `cookimport/config/run_settings.py`
- `cookimport/config/codex_decision.py`
- `cookimport/cli.py`
- `cookimport/cli_ui/run_settings_flow.py`

Primary entrypoints:

- `cookimport/staging/import_session.py` for stage/import runs
- `cookimport/staging/pipeline_runtime.py` for the stage-owned `recipe-refine` and `knowledge-final` wrappers that call the recipe and knowledge Codex surfaces from the five-stage runtime
- `cookimport/labelstudio/ingest.py` for prediction-run and Label Studio benchmark/import flows
- `cookimport/entrypoint.py` for saved-settings import passthrough

Shared shard-runtime foundation:

- `cookimport/llm/phase_worker_runtime.py` is the shared shard-worker foundation and now also defines the task manifest / task result dataclasses that the direct recipe, knowledge, and line-role runtimes can mirror incrementally.
- `cookimport/llm/codex_exec_runner.py` is the repo-owned direct Codex subprocess seam used by the live recipe, knowledge, and line-role transports. It now supports both one-shot structured prompts and long-lived workspace-worker sessions.
- the direct `codex exec` command always includes `--skip-git-repo-check` because the sterile worker workspaces live outside the repository trust root by design.
- workspace-worker sessions now also get a repo-written `worker_manifest.json` in the worker root and mirrored sterile workspace. The worker contract is now explicit: start from `worker_manifest.json`, then open the repo-written current batch/task surface when it exists (`CURRENT_BATCH.md` / `CURRENT_BATCH_FEEDBACK.md` first for knowledge, `current_batch.json` only when machine-readable task paths are needed, `current_task.json` for narrower fallback/task loops), then use the named `hints/*.md` and `in/*.json` files directly, and stay inside the bounded workspace rather than reaching back into the repo.
- watchdog policy is now split by transport: structured retry / repair calls still treat shell commands as immediate off-contract behavior, while workspace-worker main attempts now use a very broad local-shell policy. The main worker session can use normal local shell shapes, including searches, filters, pipelines, redirections, heredocs, absolute paths, parent-traversal-looking strings, root-relative scratch files, short-lived temp roots such as `/tmp`, and glob reads.
- that workspace-worker policy is now intentionally executable-based rather than path- or shell-shape-policed: main sessions are killed for clearly egregious network/package-manager/remote/container commands, mutating `git` verbs such as `pull` or `reset`, or the separate liveness guards, not for ordinary local shell syntax, heredoc parsing, path strings, or read-only `git` inspection by themselves.
- the shared worker instructions now explicitly steer agents away from broad `assigned_tasks.json` / `assigned_shards.json` inventory dumps and ad hoc shell schedulers. The preferred pattern is: open the repo-named file directly, run one small local helper if needed, and write the final answer only to the approved `out/` path.
- workspace-worker command handling is now explicitly split in repo code: `classify_workspace_worker_command(...)` is reviewer-facing telemetry, while `detect_workspace_worker_boundary_violation(...)` is the kill/no-kill enforcement seam for main worker sessions. Live-status payloads now record both the telemetry label and whether a real boundary violation was detected.
- the relaxed workspace-worker policy now also tolerates the multi-line helper scripts the knowledge workers actually emit in production, including `>/dev/null` sinks and `jq`/`cat` loops over `assigned_tasks.json`, `hints/*.md`, `in/*.json`, and `out/*.json`
- the shared workspace boundary detector now explicitly ignores `jq`'s `//` fallback operator when scanning for absolute-path escapes, so local `jq '{rows: ... // ...}' ... > out/...` helper commands stay inside the relaxed policy
- workspace-worker main attempts now terminate on command policy only when they visibly invoke clearly egregious network/package-manager/remote/container tools or mutating `git` verbs; bounded local `python`/`python3`/`node` transforms, shell scripts, heredocs, arbitrary local path usage, and read-only `git` inspection are tolerated on the main worker path, and the shared loop budget is still intentionally much looser than the earlier startup-only guardrail with extra tolerance right after real `out/*.json` progress.
- validated worker-written `workers/*/out/*.json` files are authoritative for all three workspace-worker stages. `final_agent_message_state` can legitimately be `informational` or `absent` on the main worker path, and those final-message fields are telemetry only unless a structured retry / repair attempt explicitly requires strict JSON.
- knowledge main-worker sessions now also treat a clean mid-queue exit after visible queue advancement as a recoverable runtime failure rather than an accepted finish: live status first records `workspace_validated_task_queue_premature_clean_exit`, then the repo auto-resumes the remaining queue up to a small capped number of times before settling on the final completed/incomplete reason. Final worker artifacts now keep that rescue history under `workspace_relaunch_history`, `workspace_relaunch_reason_codes`, `workspace_premature_clean_exit_count`, and `workspace_relaunch_cap_reached`; if the worker keeps stopping at conversational checkpoints until that cap is exhausted, the terminal reason is now `workspace_validated_task_queue_premature_clean_exit_cap_reached`.

Recipe CodexFarm path:

- `cookimport/llm/codex_farm_orchestrator.py`
- `cookimport/llm/codex_farm_contracts.py`
- `cookimport/llm/codex_farm_ids.py`
- `cookimport/llm/codex_farm_runner.py`

Other active Codex-backed surfaces:

- Optional knowledge extraction: `cookimport/llm/codex_farm_knowledge_orchestrator.py` (thin public facade), `cookimport/llm/knowledge_stage/planning.py`, `runtime.py`, `recovery.py`, `promotion.py`, `reporting.py`, `cookimport/llm/codex_farm_knowledge_jobs.py`, `cookimport/llm/codex_farm_knowledge_contracts.py`, `cookimport/llm/codex_farm_knowledge_models.py`, `cookimport/llm/codex_farm_knowledge_ingest.py`, `cookimport/llm/codex_farm_knowledge_writer.py`, `cookimport/llm/knowledge_prompt_builder.py`
- the knowledge stage now keeps two small runtime ledgers beside the normal manifests: `task_status.jsonl` records per-packet attempt/terminal state, while `stage_status.json` records stage finalization and interruption attribution. `knowledge_stage_summary.json` is the canonical post-run summary view over those ledgers. Interrupted runs should still leave partial `phase_manifest.json`, `promotion_report.json`, `telemetry.json`, and `failures.json` beside those status files.
- recipe and canonical line-role stage roots now also write compact post-run summaries beside their runtime artifacts: `recipe_stage_summary.json` under `raw/llm/<workbook>/recipe_phase_runtime/` and `line_role_stage_summary.json` under `line-role-pipeline/runtime/line_role/`
- canonical line-role runtime telemetry now preserves missing token usage as unavailable instead of coercing it to zero, so `telemetry_summary.json`, `prompt_budget_summary.json`, and benchmark-history token backfill can fail closed on partial usage
- the shared direct-exec runner now also parses the Codex CLI plain-text `Token usage: ...` footer when a workspace-worker session omits JSON `turn.completed` usage, so normal `workers/*/usage.json` artifacts can populate again without weakening the fail-closed summary readers
- when repo supervision decides a workspace-worker session is `completed` or `completed_with_failures`, the shared runner now waits briefly before terminating the subprocess so late `turn.completed` usage can still arrive and populate the normal worker `usage.json` artifacts
- the line-role and knowledge success watchdogs no longer stop a worker the instant outputs stabilize; they now wait for one post-finalize / post-install completion signal, or a short quiet period, before asking the runner to terminate the session
- line-role and knowledge worker roots now also save raw `stdout.txt` / `stderr.txt` sidecars when the direct-exec subprocess emitted text, which makes missing-usage sessions inspectable from the artifact tree
- Canonical line-role: `cookimport/parsing/canonical_line_roles/` (`planning.py`, `policy.py`, `runtime.py`, `validation.py`, plus `contracts.py` / `prompt_inputs.py` / `artifacts.py`), `cookimport/llm/canonical_line_role_prompt.py`, `cookimport/llm/codex_exec_runner.py`
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
- prompt-planning now keeps only the live shard-count controls: `recipe_prompt_target_count` for recipe correction and `line_role_prompt_target_count` for canonical line-role. Knowledge planning always emits one shard per deterministic chunk.
- interactive stage/benchmark adapters now preserve those prompt-target values end to end, so an operator-selected triplet stays literal at execution time instead of collapsing back to defaults
- knowledge no longer uses the path-mode CodexFarm `process` transport. Knowledge worker assignments now start in one long-lived workspace-worker Codex session per worker assignment, and only watchdog-retry / split-retry / repair follow-up attempts still use inline structured calls per shard.
- recipe no longer uses the path-mode CodexFarm `process` transport either. Recipe worker assignments now start in one long-lived workspace-worker Codex session per worker assignment, split multi-recipe shards into recipe-local task files under `assigned_tasks.json`, aggregate validated task outputs back into shard proposals, and only the near-miss repair pass still drops to one inline structured repair call per affected task. Recipe worker roots now also mirror `tools/recipe_worker.py`, `SHARD_PACKET.md`, `CURRENT_TASK.md`, and `CURRENT_TASK_FEEDBACK.md`, and the repo prewrites `scratch/<task_id>.json` drafts plus `scratch/_prepared_drafts.json` before the worker starts. The preferred local loop is now batch draft editing plus one end-of-shard `finalize-all scratch/` pass: read `SHARD_PACKET.md`, use the smaller `scratch/_prepared_drafts.json` draft inventory, edit the prewritten `scratch_draft_path` files directly, and use the current-task sidecars only to locate the active draft or inspect a failure. `assigned_tasks.json` remains present as fallback/debug inventory only; broad inventory dumps are off the happy path. `hint_path` and `input_path` remain fallback surfaces when the shard packet, prepared-drafts manifest, and current-task brief are insufficient. `check-current`, `install-current`, `OUTPUT_CONTRACT.md`, `examples/*.json`, and `tools/recipe_worker.py` now stay recovery/debug references instead of normal startup reads. `current`, `next`, `overview`, `show`, `prepare-all`, `finalize`, and `finalize-all` stay available without encouraging ad hoc heredocs or manifest-dump shell loops. `stamp-status` can bulk-mark prepared drafts as `fragmentary` or `not_a_recipe`, bounded inline Python draft edits are tolerated when every visible path stays workspace-local, startup shell commands under the sterile `~/.codex-recipe/...` execution root now classify the same way in live watchdog checks and telemetry, recipe telemetry now distinguishes `recipe_contract_lookup_command` from `recipe_task_bundle_read_command`, and recipe watchdog recovery is now split by failure shape: mixed-output misses still recover per task, while early whole-shard deaths recover through one shard-packed structured retry so recovered shards land as final `completed` outcomes without the old five-call fan-out. Repaired recipe outputs now also fail closed on one specific compact-contract gap: if the canonical recipe has 2+ non-empty ingredients or 2+ non-empty steps, an empty `m` mapping requires a non-empty `mr` reason token such as `unclear_alignment`, and repo-prepared drafts now prewrite that deterministic `mr` or fail closed to `fragmentary` when the hint packet is too weak.
- the standalone recipe helper loop is now real rather than aspirational: `check-current` writes repo-readable validation feedback, `install-current` advances `current_task.json` plus `CURRENT_TASK*.md`, `finalize-all` now closes the queue immediately, and helper-side prepared-draft metadata refreshes after accepted installs/finalize. Keep the batch `SHARD_PACKET.md -> edit drafts -> finalize-all` path as the normal flow; use the current-task loop when a worker needs to recover or inspect one task precisely.
- recipe progress now reports task-file truth rather than only shard buckets when those worker-local task files exist: the shared spinner counter tracks completed `workers/*/out/*.json` task outputs, while detail lines keep shard-finalization context such as completed shards, queued recipe tasks, workers still finalizing shard aggregation, and live recipe-repair follow-up counts when repair attempts are in flight.
- line-role no longer uses the path-mode CodexFarm `process` transport either. Line-role worker assignments now start in one long-lived workspace-worker Codex session per worker assignment, split each shard into smaller task packets under `assigned_tasks.json`, write one immutable `canonical_line_table.jsonl`, and record packet truth in `task_status.jsonl`; only missing or invalid packets fall back, and reruns resume durable packet outputs instead of re-asking the whole shard.
- knowledge no longer treats the shard as the default answer unit either. Each deterministic knowledge chunk now becomes its own shard and its own task row under `assigned_tasks.json`, task-level validation promotes that one-chunk output directly, and task-scoped watchdog retry / repair replaces the older multi-chunk follow-up story on the normal path.
- knowledge promotion is now task-aware at the shard handoff: each deterministic knowledge chunk is its own shard and task, so valid one-chunk proposals promote directly while missing or semantic-invalid tasks remain unreviewed and the rollups count that state explicitly.
- knowledge phase manifests now also persist the blast-radius policy explicitly in `runtime_metadata`: `bundle_policy` now records the single-chunk task policy, task totals and per-worker task counts show the live queue size, and the old packet-named counters remain as compatibility aliases.
- `cookimport/llm/knowledge_runtime_state.py` now defines the shared packet-ledger vocabulary (`KnowledgePacketRecord`, worker-outcome buckets, follow-up kinds, and `KnowledgeStageRollup`) and `cookimport/llm/knowledge_runtime_replay.py` is the read-only March 20-style replay seam that rebuilds those counts from saved artifacts.
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
- Zero-token prompt inspection lives in prompt preview.
- Zero-token runtime rehearsal lives on the real execute path with `--codex-farm-cmd scripts/fake-codex-farm.py`; that path exercises worker sandboxes, `in/` and `out/` folders, proposal validation, and promotion wiring without spending model tokens.
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
- Prediction-run generation can execute:
  - recipe Codex passes
  - optional knowledge refinement/extraction over seed Stage 7 non-recipe spans
  - canonical line-role Codex labeling
  - freeform prelabel
- `prompt_budget_summary.json` should preserve CodexFarm split token totals (`tokens_input`, `tokens_cached_input`, `tokens_output`) from per-call telemetry rows when they are present in the prediction manifest.

## Plain-English Pipeline

If you want the current Codex-backed flow in operator language instead of artifact language, this is the simplest accurate version:

1. The program parses the cookbook into one ordered set of atomic lines and other deterministic intermediate structures.
2. The program makes a deterministic first pass over those lines before any Codex-backed review.
3. The line-role Codex surface reviews the whole book line set in worker-local shard files. Operator-wise this is still just "label the lines," but the live main path now gives each worker session its assigned local task packets inside those shards and writes one `out/<task_id>.json` per packet. Repo code validates and joins those packet results back into the shard proposal, using deterministic baseline fallback for any missing packet rows instead of rerunning the whole shard.
4. The program groups the corrected recipe-side lines into coherent recipe spans and recipes. Everything not grouped into recipe spans becomes the non-recipe side.
5. The recipe Codex surface reviews the recipe side in owned recipe shards. One worker session processes its assigned recipe task files under `in/` and writes one `out/<task_id>.json` per task. Repo code validates those task outputs, rejoins them into shard proposals, and near-miss invalid tasks can still get one structured repair pass.
6. The program deterministically validates and promotes those recipe outputs into the final recipe formats.
7. The knowledge Codex surface reviews the non-recipe side. The program first builds transport-safe non-recipe chunks, then Codex reviews every built chunk using raw block text plus mechanically true structure rather than deterministic semantic gating. Each knowledge task owns exactly one deterministic chunk plus optional nearby non-authoritative context, and one worker session processes its assigned knowledge task files under `in/` and writes one semantic task-result JSON file per task under `out/`. Repo code validates that one-chunk result, normalizes it into the canonical compact bundle payload, and then keeps/refines useful cooking knowledge while rejecting blurbs, filler, and other author yapping.
8. The program validates owned output coverage, writes artifacts/reports, and emits the final recipe, knowledge, and debug outputs.

Worker/shard mental model:

- A setting such as `10 / 5 / 10` in benchmark interactive mode means the runtime should build ten `line_role` shards, five `recipe` shards, and ten `knowledge` shards unless a phase has fewer owned items total.
- Knowledge keeps a special warning seam: if forcing the chosen shard count makes a bundle exceed the normal chunk-count, char-count, local-gap, or table-isolation heuristics, the planner still honors the requested count but records warnings in the manifest.
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
- `data/output/<ts>/raw/llm/<workbook_slug>/recipe_phase_runtime/task_manifest.jsonl`
- `data/output/<ts>/raw/llm/<workbook_slug>/recipe_phase_runtime/worker_assignments.json`
- `data/output/<ts>/raw/llm/<workbook_slug>/recipe_phase_runtime/promotion_report.json`
- `data/output/<ts>/raw/llm/<workbook_slug>/recipe_phase_runtime/telemetry.json`
- `data/output/<ts>/raw/llm/<workbook_slug>/recipe_phase_runtime/failures.json`
- `data/output/<ts>/raw/llm/<workbook_slug>/recipe_phase_runtime/proposals/*.json`

Recipe runtime note:
- the live recipe implementation now defaults to one candidate-owned shard per recipe, executes those shards through the repo-owned direct recipe worker runtime in `codex_farm_orchestrator.py`, validates exact owned `recipe_id` coverage, and promotes only validated per-recipe outputs
- recipe worker assignments now launch one long-lived workspace-worker Codex session per worker assignment with shared `assigned_shards.json`, worker-local `assigned_tasks.json`, `hints/*.md`, authoritative `in/*.json`, and harvested `out/*.json`; recipe tasks usually own one `recipe_id`, workers write `out/<task_id>.json`, deterministic code rejoins validated task outputs into shard proposals, and only the near-miss repair path still uses one structured direct-exec call per affected task
- recipe worker roots now also carry `OUTPUT_CONTRACT.md` plus `examples/valid_{repaired,fragmentary,not_a_recipe}_task_output.json`; those repo-written sidecars are the worker-facing source of truth for the compact `v` / `sid` / `r` and `rid` / `st` / `sr` / `cr` / `m` / `mr` / `g` / `w` contract, and legacy keys such as `results`, `recipe_id`, `repair_status`, `canonical_recipe`, `not_a_recipe`, and `notes` are rejected on the live runtime seam
- recipe runtime now also writes `task_manifest.jsonl` plus worker-local `assigned_tasks.json`; those task rows are now the normal recipe answer units even when several recipes share one parent shard
- recipe worker roots now also carry `worker_manifest.json`, and the shared worker prompt tells the worker to prefer the named local files first without treating bounded local orientation as off-contract by itself
- recipe and line-role helper CLIs now keep the old `scaffold` / `check` / `install` verbs as compatibility fallbacks, but the cheap recipe happy path is once again batch draft editing plus one `finalize-all` pass rather than a per-task helper loop. Line-role still treats `prepare` / `prepare-all` as fallback/debug draft generation, while recipe now also prewrites those same drafts before the workspace worker starts, keeps `prepare-all` as a regeneration fallback, writes a smaller `scratch/_prepared_drafts.json` with draft/output paths plus short title hints and `current_task_id`, exposes `current|next|check-current|install-current`, and exposes `stamp-status` for bulk terminal-status stamping before `finalize-all`.
- worker assignments now launch concurrently and then merge results back in planned assignment order so runtime artifacts stay stable while multi-worker runs become real
- deterministic code still validates and normalizes recipe outputs locally, but the live promotion seam is now one canonical `AuthoritativeRecipeSemantics` payload per recipe. Codex still emits compact `ingredient_step_mapping` plus raw `selected_tags`, and promotion now records the merged semantic result under `recipe_authority/<workbook_slug>/authoritative_recipe_payloads.json` before intermediate/final drafts are written.
- `CodexFarmApplyResult` now exposes only the canonical `authoritative_recipe_payloads_by_recipe_id` map plus the updated conversion result and recipe-stage telemetry; the older intermediate/final override maps are no longer part of the live orchestrator result contract.
- the model-facing recipe shard now includes a compact candidate-quality hint `q` alongside weak deterministic parse hint `h`, and each recipe result now carries compact status fields (`st`, `sr`) so `fragmentary` / `not_a_recipe` candidates stay visible in proposals/audits but only `repaired` results promote into final recipe outputs
- recipe tag guidance is now recipe-local rather than purely global: single-candidate recipe shards carry a richer `recipe_tagging_guide.v3` with both the broader category catalog and a filtered `tg.s[*]` candidate label surface derived from the current recipe text/hints
- the authoritative recipe contract is now: `recipe_phase_runtime/inputs/*.json` immutable shard payloads, worker-local `workers/*/out/*.json` compact task outputs, `recipe_phase_runtime/proposals/*.json` validated shard proposals, then deterministic promotion into `recipe_authority/<workbook_slug>/authoritative_recipe_payloads.json` plus staged outputs; recipe task rows now include `metadata.input_path`, `metadata.hint_path`, and `metadata.result_path` so the workspace helper installs only to the declared local output path; `recipe_correction_audit/` remains only the per-recipe human/debug summary surface
- file-backed validity is authoritative for recipe workspace workers: if `workers/*/out/*.json` validates, a prose or markdown closing message is telemetry only and does not downgrade the task into a malformed result
- recipe worker shard folders now also write `prompt.txt`, `events.jsonl`, `usage.json`, `last_message.json`, and `cost_breakdown.json`, so prompt-preview and actual-cost reporting can talk about the same visible request/response surface
- recipe worker shard folders now also write `workspace_manifest.json`, and near-miss invalid recipe shard outputs get one repo-owned repair pass with `repair_prompt.txt`, `repair_events.jsonl`, `repair_last_message.json`, `repair_usage.json`, `repair_workspace_manifest.json`, and `repair_status.json`
- strict JSON recipe shard attempts now also write `live_status.json`; malformed shard payloads are rejected before spend with `state: preflight_rejected`, the live watchdog can terminate tool-use or repeated reasoning detours with `state: watchdog_killed`, and recipe repair attempts also preserve `repair_live_status.json` plus `state` / `reason_code` / `reason_detail` / `retryable` fields in shard status artifacts
- `stage_observability.json` now reports the semantic recipe stages `build_intermediate_det`, `recipe_llm_correct_and_link`, and `build_final_recipe`

Knowledge-stage writes:

- `data/output/<ts>/08_nonrecipe_seed_routing.json`
- `data/output/<ts>/08_nonrecipe_review_exclusions.jsonl`
- `data/output/<ts>/09_nonrecipe_authority.json`
- `data/output/<ts>/09_nonrecipe_review_status.json`
- `data/output/<ts>/raw/llm/<workbook_slug>/knowledge_manifest.json`
- `data/output/<ts>/raw/llm/<workbook_slug>/knowledge/in/*.json`
- `data/output/<ts>/raw/llm/<workbook_slug>/knowledge/phase_manifest.json`
- `data/output/<ts>/raw/llm/<workbook_slug>/knowledge/shard_manifest.jsonl`
- `data/output/<ts>/raw/llm/<workbook_slug>/knowledge/task_manifest.jsonl`
- `data/output/<ts>/raw/llm/<workbook_slug>/knowledge/worker_assignments.json`
- `data/output/<ts>/raw/llm/<workbook_slug>/knowledge/promotion_report.json`
- `data/output/<ts>/raw/llm/<workbook_slug>/knowledge/telemetry.json`
- `data/output/<ts>/raw/llm/<workbook_slug>/knowledge/failures.json`
- `data/output/<ts>/raw/llm/<workbook_slug>/knowledge/proposals/*.json`
- `data/output/<ts>/knowledge/<workbook_slug>/snippets.jsonl`
- `data/output/<ts>/knowledge/<workbook_slug>/knowledge.md`
- `data/output/<ts>/knowledge/knowledge_index.json`

`08_nonrecipe_seed_routing.json` is the deterministic Stage 7 routing artifact. `09_nonrecipe_authority.json` is the final machine-readable truth surface for outside-recipe `knowledge` versus `other`. `09_nonrecipe_review_status.json` is the runtime-status artifact for reviewed, skipped, changed, and unresolved review-eligible rows. `snippets.jsonl` remains reviewer-facing evidence only.

Knowledge runtime note:
- the live knowledge implementation is no longer one direct `knowledge/in -> knowledge/out` CodexFarm call
- deterministic chunking still decides eligibility, pruning, and local grouping
- `codex_farm_knowledge_jobs.py` now writes stable shard payload files plus shard-manifest metadata with owned `chunk_id`s and owned block indices
- the live knowledge model call now goes through `codex_exec_runner.py`, but it keeps the same shard-manifest / worker-assignment artifact shape the shared runtime established
- knowledge worker assignments now launch one long-lived workspace-worker Codex session per worker assignment with shared `assigned_shards.json`, a skinny worker-local `assigned_tasks.json`, repo-written `current_batch.json`, `CURRENT_BATCH.md`, `CURRENT_BATCH_FEEDBACK.md`, compatibility `current_task.json` / `CURRENT_TASK*` fallback files for the first active task, authoritative `in/*.json`, harvested `out/*.json`, `scratch/`, `OUTPUT_CONTRACT.md`, `examples/`, and `tools/knowledge_worker.py`; each planned shard is already one single-chunk task, and repo code still batches a few consecutive tasks at a time for the worker loop. The worker starts from the batch bundle, gets a representative good-vs-bad snippet example instead of a first-task front-matter example, uses the repo-written happy-path verbs `current-batch|complete-batch|check-batch|install-batch|explain-failure`, and keeps `python3 tools/knowledge_worker.py debug ...` for narrow recovery/debugging only. The repo advances the queue by contiguous valid prefix while also mirroring the advanced batch bundle back into the live execution workspace so the same worker session can continue with the next batch immediately. `CURRENT_BATCH.md` is now intentionally the cheap first read, `current_batch.json` keeps only batch-local task facts, `assigned_tasks.json` is fallback/debug inventory only, and strong-cue scaffolds are visibly marked `strong_cue_review_required` instead of masquerading as accepted reviewed-empty answers. The default batch caps are now larger (`8` tasks / `48_000` input bytes) so the same worker session amortizes more single-chunk tasks per helper cycle. The prompt, `CURRENT_BATCH.md`, `CURRENT_BATCH_FEEDBACK.md`, and `install-batch` stdout now all frame that handoff as one continuing assignment: re-open the batch brief/feedback after install, and only reopen `current_batch.json` when the next batch's machine-readable task paths are needed. The stage also now owns one conservative no-LLM fast path: single-chunk tasks with strong negative utility cues, no positive utility cues, no strong knowledge cue, and no borderline utility signal can bypass the workspace worker entirely and land as validated repo-owned `other` proposals, with the bypass counts surfaced in `knowledge_stage_summary.json` and `prompt_budget_summary.json`.
- the remaining runtime guardrail is now explicit too: the knowledge main-worker watchdog hard-kills only ad hoc queue-control rewrites. Bounded local automation over only the active batch drafts is tolerated, helper-source spelunking against `tools/knowledge_worker.py` is discouraged/telemetry-only rather than an immediate fatal kill, and `assigned_tasks.json` dumps, single-task helper detours, plus broad shell scheduler loops are now soft stage-violation telemetry rather than immediate kills. The batch contract is still enforced at runtime, but the watchdog now steers more than it kills.
- on the narrower current-task seam, `assigned_tasks.json` is now queue/progress context only, not the current-step authority. The repo-owned `current_task.json`, `CURRENT_TASK.md`, and `CURRENT_TASK_FEEDBACK.md` must advance together and must be mirrored source-to-execution after validation callbacks so stale execution copies cannot drag the worker back to task 1. The helper script and repo-written sidecars now share the same continuation text templates so `install-current` stdout, `CURRENT_TASK_FEEDBACK.md`, and the generated tool do not drift.
- those knowledge `out/*.json` files are semantic task-result candidates, not authoritative compact bundle envelopes; the first landing keeps the worker schema shape compatible by preserving `packet_id` plus one-row `chunk_results`, and repo code still serializes the canonical `v` / `bid` / `r` payload after accepting the worker's semantic judgment
- knowledge runtime now also writes `task_manifest.jsonl` plus worker-local `assigned_tasks.json`; those task rows now match `knowledge/in/*.json` one-for-one because each row owns exactly one chunk and one result path
- knowledge progress now treats tasks as the live truth: stage counters use task totals, worker labels show local task progress, and retry/repair follow-up calls surface in structured `detail_lines` instead of leaving the CLI stuck on shard-only counters such as `task 0/10`
- knowledge worker roots now also carry `worker_manifest.json`, and the shared worker prompt tells the worker to prefer the named local files first while still allowing bounded local orientation and helper shell work inside the worker root; the worker manifest now also advertises `tools_dir` and `mirrored_tool_files` when a stage mirrors a repo-written helper
- `codex_farm_knowledge_ingest.py` validates exact owned `chunk_id` coverage and rejects any `block_decisions` or snippet evidence that point outside the shard's eligible block surface
- the knowledge validator now also rejects low-trust semantic packet shapes such as non-grounded snippet bodies, full-chunk snippet echoes, and substantial verbatim copies of one evidence quote, while deterministic salvage stays narrow to trailing `EOF` and obvious shell-wrapper suffix noise after a valid JSON object
- the helper/runtime seam for those failures is now shared: `tools/knowledge_worker.py check`, local install gating, and the orchestrator all reuse the same validator classification, so snippet-copy-only failures are recognized as narrow near misses instead of three different failure families
- the knowledge semantic boundary is now explicitly utility-first: `knowledge` means durable cooking leverage, not just something cooking-adjacent that happens to be true. Worker-local hints can summarize utility cues such as cause/effect, troubleshooting, substitution, storage/safety, framing, memoir, navigation, and true-but-low-utility filler, while the billed shard payload remains raw block text plus mechanically true structure only
- accepted knowledge semantic outputs now carry a compact operator-facing `reason_code` vocabulary. Positive reasons include `technique_or_mechanism`, `diagnostic_or_troubleshooting`, `reference_or_definition`, and `substitution_storage_or_safety`; negative reasons include `book_framing_or_marketing`, `memoir_or_scene_setting`, `navigation_or_chapter_taxonomy`, `decorative_heading_only`, `true_but_low_utility`, and `not_cooking_knowledge`. `utility_profile` can stay more granular, but it is a worker-local hint surface only and never semantic authority by itself.
- the knowledge prompt/worker contract now also treats short conceptual headings as keepable when they directly introduce useful explanatory blocks in the same owned chunk; decorative or menu-like headings still stay `other`
- the authoritative knowledge contract is now: `knowledge/in/*.json` immutable single-chunk shard payloads, worker-local semantic task-result candidates under `workers/*/out/*.json`, `knowledge/proposals/*.json` validated repo-serialized shard proposals, then deterministic promotion into `08_nonrecipe_seed_routing.json`, `09_nonrecipe_authority.json`, `09_nonrecipe_review_status.json`, and reviewer-facing knowledge artifacts
- valid knowledge worker task files remain authoritative even if the workspace session ends with no final assistant message; `final_agent_message_state` is still recorded in telemetry/live-status for debugging, but follow-up recovery only keys off file-level validation failure
- direct workspace-worker telemetry is now fail-closed on token accounting too: if a workspace session shows real work but no usable Codex usage payload, the runtime summary records `token_usage_status=partial|unavailable` and blanks billed-token totals instead of publishing literal zero spend
- invalid but near-miss knowledge outputs now get one repo-owned repair attempt at task scope; task/shard folders can include `repair_prompt.txt`, `repair_events.jsonl`, `repair_last_message.json`, `repair_usage.json`, and `repair_status.json`, while proposal/status payloads record whether repair was attempted and whether the final validated output came from that repair pass
- snippet-copy-only knowledge failures now have their own narrow recovery rung before the broad repair ladder: `inline_snippet_repair` rewrites snippet bodies only, and those failures no longer jump straight to `repair_skipped_poisoned_worker` before the narrow repair chance is exhausted
- direct knowledge shard folders now also write `workspace_manifest.json`, and retry/repair child attempts write their own workspace manifests beside the attempt-local events/usage files so the sterile cwd provenance is visible from repo artifacts
- strict JSON knowledge shard attempts now also write `live_status.json`; deterministic preflight can stop malformed shard payloads with `state: preflight_rejected`, the live watchdog can kill tool-use / repeated reasoning detours / cohort-runtime outliers with `state: watchdog_killed`, and retryable watchdog kills now get one fresh repo-owned retry packet under `watchdog_retry/` for the affected task, with sibling examples plus its own prompt/events/usage/workspace/status artifacts
- repeated uniform malformed, low-trust, watchdog-boundary, or zero-output task failures can now classify a worker as poisoned, which causes later retry/repair follow-ups to record explicit skip reasons instead of paying for another doomed recovery attempt
- completed knowledge workspace workers should now always carry a non-null `reason_code` in `live_status.json`; successful taskized workers now finish as `workspace_validated_task_queue_completed`, stable-output runs without provable queue completion also fail closed as `workspace_validated_task_queue_incomplete`, genuine clean incomplete exits still land as `workspace_validated_task_queue_incomplete`, premature clean exits after visible queue advancement first surface as `workspace_validated_task_queue_premature_clean_exit` during the auto-resume backstop, repeated conversational stops can now end as `workspace_validated_task_queue_premature_clean_exit_cap_reached`, and true watchdog kills keep their original watchdog reason codes
- the runtime cutover did not require a brand-new pack immediately; `codex-knowledge-shard-v1` still reuses the compact knowledge pack underneath, and the important authority seam is shard ownership plus validation, not a new prompt asset family
- knowledge worker assignments now launch concurrently and merge back in planned order so `running N` reflects real in-flight work
- knowledge progress callbacks now also report task truth rather than shard truth: `task_current/task_total` track single-chunk tasks, detail lines carry completed-shard totals, and `active_tasks` rows identify the worker-owned task queue plus any inline follow-up state
- the billed knowledge payload now avoids chunk-level semantic hints entirely; it carries raw block text, block ids, and mechanically true structure only
- prompt-cost control for this stage lives before worker execution:
  - `cookimport/parsing/chunks.py` still provides deterministic chunk boundaries, but its semantic lane guesses no longer suppress review
  - `build_knowledge_jobs(...)` now writes one local job per deterministic chunk, while keeping deterministic judgments out of the billed reviewer payload
  - table-heavy chunks stay isolated, soft-gap packing can cross small outside-recipe gaps, and there is no second deterministic low-signal pruning pass anymore
  - the shared default knowledge context is now `0` blocks

Inline recipe tagging writes through the normal recipe artifacts:

- `data/output/<ts>/final drafts/<workbook_slug>/r{index}.json` as `recipe.tags`
- `data/output/<ts>/intermediate drafts/<workbook_slug>/r{index}.jsonld` as `keywords`

Line-role prediction artifacts live under:

- `prediction-run/line-role-pipeline/telemetry_summary.json`
- `prediction-run/line-role-pipeline/runtime/phase_manifest.json`
- `prediction-run/line-role-pipeline/runtime/shard_manifest.jsonl`
- `prediction-run/line-role-pipeline/runtime/task_manifest.jsonl`
- `prediction-run/line-role-pipeline/runtime/worker_assignments.json`
- `prediction-run/line-role-pipeline/runtime/proposals/*.json`

Line-role runtime note:
- live line-role execution no longer uses `phase_worker_runtime.py` or `codex-farm process`
- `canonical_line_roles.py` now assigns shard ownership directly, writes authoritative worker-local shard JSON under `line-role-pipeline/runtime/line_role/workers/*/in/*.json`, validates exact owned `atomic_index` coverage, and writes repo-owned worker artifacts under `line-role-pipeline/runtime/line_role/workers/.../shards/<shard_id>/`
- line-role worker assignments now launch one long-lived workspace-worker Codex session per worker assignment with `assigned_shards.json`, shared `prompt.txt`, worker-local `hints/*.md`, authoritative `in/*.json`, richer `debug/*.json`, and harvested `out/*.json`; only watchdog-retry and repair still use structured follow-up attempts on the affected shard
- line-role `assigned_tasks.json` and `current_task.json` are now metadata-first control files. They name `metadata.input_path`, `metadata.hint_path`, `metadata.scratch_draft_path`, and `metadata.result_path`, but they no longer duplicate the full task packet payload that already lives in `in/<task_id>.json`.
- line-role worker roots now also carry a compact `CURRENT_TASK.md`. The cheap happy path is now: open `CURRENT_TASK.md`, inspect the prewritten scratch draft, use the hint for the targeted explanation, and reopen `in/<task_id>.json` only when the draft or hint is insufficient.
- the line-role prompt/hint contract now treats outside-recipe `KNOWLEDGE` as high-evidence and low-default: reusable explanation/reference prose and supported lesson headings can stay `KNOWLEDGE`, while memoir, blurbs, endorsements, book-framing encouragement, and broad action-verb advice should stay `OTHER`
- line-role worker roots now also carry `worker_manifest.json` plus repo-written `examples/*.md` contrast files. The shared worker prompt now frames deterministic labels as a strong prior, tells the model to read the packet-local hint/input files first, and uses the examples only for conservative calibration.
- invalid but near-miss line-role outputs now get one repo-owned repair attempt; parent-shard and split task folders are created before repair/watchdog follow-up artifacts are written, shard folders can include `repair_prompt.txt`, `repair_events.jsonl`, `repair_last_message.json`, `repair_usage.json`, and `repair_status.json`, and the runner payload rows must carry the repair/status annotations because `line-role-pipeline/telemetry_summary.json` is rebuilt from those rows
- direct line-role shard folders now also write `workspace_manifest.json`, and repair attempts write `repair_workspace_manifest.json` so the external sterile worker cwd is traceable from the normal runtime artifact tree
- strict JSON line-role shard attempts now also write `live_status.json`; malformed shard payloads are rejected before spend with `state: preflight_rejected`, the live watchdog can terminate tool-use / repeated reasoning detours / cohort-runtime outliers with `state: watchdog_killed`, and retryable watchdog kills now get one fresh inline retry packet with sibling examples plus `watchdog_retry_*` shard artifacts and propagated `watchdog_retry_*` status fields
- strict JSON watchdog kill reasons now also preserve the offending command text in `reason_detail`, so a `watchdog_command_execution_forbidden` status can distinguish trivial `ls` / `pwd` orientation reflexes from more substantive tool use
- for workspace-worker main attempts only, `command_execution_tolerated: true` now means the worker stayed within the allowed workspace-local command policy; `live_status.json`, shard `status.json`, and direct telemetry rows now also record command-policy classifications/reasons so reviewer artifacts can distinguish helpful local file reads from real drift
- there is no longer any live or compatibility support for a separate LLM recipe gate inside line-role; the only active line-role model surface is the single `line_role` labeling phase
- line-role pre-grouping candidates now default to `within_recipe_span=None`; importer recipe provenance is no longer supplied before deterministic/Codex labeling, and prompt-preview reconstruction mirrors that same span-free contract
- `AtomicLineCandidate` is now a single-line parser record; selective inline `ctx:` rows and cache identity derive neighbor text from explicit ordered-candidate lookup instead of embedded `prev_text` / `next_text` fields
- `workers/*/in/*.json` remain the authoritative stored task payloads the worker reads locally. For line-role, those are sub-shard task packets; for knowledge, those are single-chunk task files with optional nearby context; for recipe, they are still one task per shard on the main path. When a structured follow-up still exists, it must read authority from those stored inputs rather than reconstructing freehand.
- `workers/*/hints/*.md` are worker-facing decision aids. They are not validator authority and are intentionally allowed to be richer, more explanatory summaries than the billed `in/*.json` payload. Line-role hints now include packet interpretation, conservative flip policy, and example-file pointers in addition to the older packet-profile/attention-row summaries.
- line-role now keeps a second local-only debug copy at `workers/*/debug/*.json`; prompt-preview mirrors that as `line-role-pipeline/debug_in/*.json`, while `request_input_file` and budget estimation still point at the compact billed `in/*.json` file.
- those `workers/*/in/*.json` rows are now compact tuples: `{"v":1,"shard_id":...,"packet_summary":...,"default_posture":...,"flip_policy":[...],"example_files":[...],"rows":[[atomic_index,label_code,current_line], ...]}`. The model-facing file stays compact row-wise, but it now carries small packet-level context fields so a cold-start worker can stay conservative without reading repo code.
- `telemetry_summary.json` remains the prompt/debug and post-run cost seam for line-role, but its runtime metadata now describe direct exec instead of CodexFarm `process`
- line-role worker launches are concurrent and then re-collected in planned order so stable artifacts and real worker fan-out coexist

Prompt/debug artifacts:

- `prompts/full_prompt_log.jsonl` is the stable per-call truth
- direct `codex exec` shard telemetry now records `duration_ms`, `started_at_utc`, and `finished_at_utc`; when the global `var/codex_exec_activity.csv` join is missing or stale, prompt-artifact export should backfill recipe/knowledge rows from the stage-local `telemetry.json` keyed by runtime shard id
- `prompts/prompt_log_summary.json` is the small count summary for that log; it separates raw row count from `runtime_shard_count` so bundled recipe outputs do not look like extra Codex calls
- `prompts/prompt_request_response_log.txt` is the human-readable convenience export
- `prompts/prompt_type_samples_from_full_prompt_log.md` is a sampled reviewer view
- `prompts/thinking_trace_summary.jsonl` and `prompts/thinking_trace_summary.md` summarize trace-path coverage, availability, and reasoning-event presence from the merged prompt log
- `prediction-run/prompt_budget_summary.json` is the post-run actual-costs artifact; it merges recipe/knowledge telemetry with line-role telemetry when present and publishes semantic `by_stage` totals instead of an old pass-slot grouping container
- `prediction-run/prompt_budget_summary.json` now also carries pathological direct-exec spend signals such as preflight-rejected shard counts, watchdog-killed shard counts, invalid-output shard counts/tokens, missing-output shard counts, repaired-shard counts, command-executing shard counts, reasoning-heavy shard counts, and merged `pathological_flags` so March 18-style blowups are visible without rereading worker `events.jsonl`
- stage-local direct-exec summaries now also expose `prompt_input_mode_counts`, `workspace_worker_session_count`, `structured_followup_call_count`, and `execution_mode_summary`, so a finished run shows how much work came from main worker sessions versus shard-local retry / repair follow-up calls
- the knowledge stage row inside `prediction-run/prompt_budget_summary.json` now also carries compact packet / worker / follow-up counters copied from `knowledge_stage_summary.json`, so cost review and outcome review use the same vocabulary
- `prediction-run/prompt_budget_summary.json` now also reports requested-vs-actual run-count metadata per active Codex stage (`requested_run_count`, `actual_run_count`, `run_count_status`, `run_count_explanation`) so a finished run shows clearly when a `3/4/5` target was matched or when the planner legally used fewer/more shards
- `prediction-run/prompt_budget_summary.json` now also falls back to current shard-runtime worker telemetry plus the linked processed-run `line-role-pipeline/telemetry_summary.json` when a benchmark/prediction manifest only carries lightweight phase summaries or a metadata-only benchmark copy
- when line-role telemetry only exposes nested batch/attempt summaries, `prompt_budget_summary.json` should still recover those `tokens_total` values so the finished-run whole-run drain is not understated
- for line-role, requested-vs-actual run-count reporting is surface-level: compare the requested line-role target against the actual shard count on the single live `line_role` phase
- `cf-debug preview-prompts --run ... --out ...` rebuilds zero-token prompt previews from an existing processed run, or from a benchmark root that resolves to a predictive-safe processed run, and writes `prompt_preview_manifest.json` plus prompt artifacts under the chosen output dir
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
- knowledge preview now follows the live shard contract exactly: prompt counts come from the deterministic chunk list because `build_knowledge_jobs(...)` writes one shard per chunk and only records compatibility warnings when old bundling knobs are set
- the current default knowledge context is `0` blocks on each side, and that default is shared across stage, benchmark, CLI, and prompt-preview paths
- `build_knowledge_jobs(...)` now always writes one shard per deterministic chunk. Knowledge worker count still controls concurrency, but shard sizing is no longer a live run-setting surface.
- line-role preview must batch the full ordered candidate set and pass `deterministic_label` plus `escalation_reasons` into `build_canonical_line_role_prompt(...)`; preview-only unresolved shortlists are a stale contract and will understate line-role prompt volume.
- line-role prompt reconstruction no longer injects grouped recipe spans or importer provenance. The pre-grouping contract is now span-free: prompt text explicitly says no prior recipe-span authority is provided, and candidate rows default to `within_recipe_span=None` until grouped labels are projected later.
- the active line-role wrapper now teaches `HOWTO_SECTION` as a book-optional, recipe-internal subsection label only (`FOR THE SAUCE`, `TO FINISH`, `FOR SERVING`). Packet files now carry `howto_section_availability` plus `howto_section_policy`, and the wrapper explicitly fences chapter/topic/cookbook-lesson headings back to `KNOWLEDGE` or `OTHER`
- the active line-role wrapper also teaches `INSTRUCTION_LINE` as recipe-local procedure only and explicitly fences cookbook advice / explanatory prose with action verbs back to `KNOWLEDGE` or `OTHER` unless packet-local component structure makes the instruction ownership real
- line-role repair and watchdog-retry prompts now restate the authoritative shard rows inline and tell the model to recompute labels from those rows instead of copying a one-row JSON example or prior invalid output
- line-role shard validation is still structurally strict, but repair/retry promotion now adds a conservative semantic guard: if a repaired output collapses a diverse shard into pathological uniform or near-uniform labels, the shard stays invalid and the stage falls back to deterministic baseline labels instead of silently promoting nonsense
- line-role row transport is now split cleanly by seam: the inline compact prompt uses pipe-delimited target rows plus selective `ctx:` windows, the file-backed billed shard JSON is the tuple-based `v=1` transport, and a parallel debug copy keeps the richer local object rows
- prompt/actual cost reporting for the direct phases now also carries a shared cost-breakdown vocabulary: `visible_input_tokens`, `cached_input_tokens`, `visible_output_tokens`, and `wrapper_overhead_tokens`
- live line-role execution no longer needs one fresh Codex session per shard in the common multi-shard case; it now plans contiguous shards, groups them by worker assignment, lets one workspace-worker Codex session process several local shard files, validates exact owned-row coverage per harvested output file, and promotes accepted rows into the existing `label_llm_correct` outputs.
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
  - knowledge preview on `saltfatacidheatcutdown` moved from `324` prompts to `91`, then to `40`, after noise routing, local bundling, and soft-gap packing landed in the live knowledge job builder; the later low-signal pruning pass was removed because it silently skipped chunks the reviewer still needed to see
  - line-role preview on the same run moved from `45` prompts to `15`, then to `8`, after raw-prompt transport, larger shared batch defaults, and compact row serialization landed in the live line-role path
  - the next cut changed the default control surface from shard size to per-phase prompt target, but knowledge still keeps its hard bundle caps even when that prompt target is explicitly in force
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
  - stop using deterministic semantic lane labels as a reason to skip knowledge review calls
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
- Recipe, knowledge, and line-role now all populate the same typed shared progress contract in `cookimport/core/progress_messages.py`: work-unit label/counter, worker-session counts, repo-follow-up counts, compact artifact counts, and optional worker rows. The main UI rule is that worker rows describe real worker sessions, while repo-owned repair/finalization state must travel through the typed follow-up fields rather than fake `active_tasks` labels.
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
- `docs/plans/2026-03-22_22.36.45-simplify-knowledge-stage-to-single-chunk-review-tasks.md`

## Recent Durable Notes

- In single-book benchmark runs, missing benchmark-level `prompts/` exports does not by itself mean CodexFarm did not run. The lower-level truth is the linked processed stage run under `data/output`, where raw recipe/knowledge inputs, outputs, and `.codex-farm-traces` live.
- After shard-v1 cutover, active run-setting surfaces are already strict about pipeline ids. If legacy behavior still shows up, it is more likely to be a reader/fixture/tooling seam than the live recipe, knowledge, or line-role execution path.
- `prompt_budget_summary.json` must aggregate CodexFarm split tokens from both nested `process_payload.telemetry.rows` and the benchmark single-book top-level `stage_payload.telemetry.rows` layout. Otherwise `tokens_input`, `tokens_cached_input`, and `tokens_output` can drop to null while per-call telemetry still exists.
- `prompt_budget_summary.json` must also prefer one knowledge telemetry layer when aggregate direct-exec payloads duplicate the same stage totals at both the top level and nested worker/runtime levels. Double-counting that stack makes the knowledge stage look more expensive than it was.
- Prompt-cost debugging should separate call-count inflation from prompt-size inflation:
  - call-count inflation on `saltfatacidheatcutdown` came from `175` grouped recipe spans
  - recipe prompt inflation also came from the constant `tagging_guide` payload plus `selected_tags` instructions
- The intended operator shape is still surface-level prompt counts such as `3 / 3 / 3` or `5 / 5 / 5`: one planned shard should correspond closely to one real model call for that surface. Preview and live runtime should be judged against that mental model, not against hidden transport/session turns.
- Line-role transport cost should now be nearly all task prompt, not wrapper overhead. If wrapper chars spike again, inspect raw-prompt transport and compact row serialization before touching the response schema or preview math.
- Current line-role runtime truth is one file-backed `line_role` phase under `line-role-pipeline/runtime/line_role/`. The abandoned inline path and the brief `recipe_region_gate` / `recipe_structure_label` split are historical only; new docs and prompt exports should describe the single file-backed phase plus its immutable line table, packet ledger, and worker `in/*.json` payloads.
- Recipe worker cost regressions are usually readback regressions now, not watchdog regressions. If recipe token spend spikes again, inspect whether workers have slipped back into `OUTPUT_CONTRACT.md` / `examples/*.json` / `tools/recipe_worker.py` or raw `hint_path` / `input_path` rereads before changing retry policy or prompt wording.
- Knowledge queue regressions now split cleanly into two seams:
  - current-task bundle authority and sync
  - conversational premature-clean-exit recovery
  If a worker says "I can continue if you want" mid-queue, do not treat that as success and do not promote `assigned_tasks.json` back into the primary worker surface.
- Main workspace-worker false kills should now be debugged as explicit forbidden-executable or liveness problems. Absolute paths, heredocs, slash-heavy helper payloads, `jq //`, and read-only `git` inspection are telemetry on the main worker path, not kill reasons.
- File-backed line-role observability has to describe both pieces of the request honestly:
  - the visible wrapper prompt
  - the model-facing task file recorded as `request_input_file`
  `prompt_input_mode=path` is the durable vocabulary for that split.
- Regenerated prompt preview on an old benchmark root is forward-looking, not retrospective truth. Use a fresh preview to answer "what would this cost now?", and use finished-run `prompt_budget_summary.json` / `cf-debug actual-costs` to answer "what did that old run actually cost?".
- Large preview-vs-live gaps on current direct-exec runs are usually transport/runtime accounting issues such as cached-input replay, file reads, or larger real outputs than the structural estimate, not evidence that Codex secretly took extra turns or wandered the repo.
- Recipe direct-exec no longer treats `recipe_correction/{in,out}` as runtime truth. Current readers and debug helpers should start from `recipe_phase_runtime/inputs/*.json`, `recipe_phase_runtime/proposals/*.json`, and `recipe_correction_audit/*.json`.
- Stage 7 wording cleanup was a label/reporting pass, not a new runtime. The durable knowledge contract is still:
  - deterministic Stage 7 review routing
  - parser-owned chunk pruning before review
  - immutable `knowledge/in/*.json` inputs
  - validated `knowledge/proposals/*.json` outputs
  - deterministic promotion into explicit final authority plus reviewer snippets
  Operator-facing clarity now comes from using `non-recipe knowledge review` wording and from richer `knowledge_manifest.json.review_summary` counts/paths.
- The March 17 repo-wide cost-honesty pass landed the main structural pieces:
  - recipe moved off classic task-farm transport onto direct exec
  - recipe payloads and outputs use compact aliases on the model-facing seam
  - line-role debug payloads were trimmed toward the actual prompt contract
  - per-shard and per-stage artifacts now expose visible-input / cached-input / visible-output / wrapper-overhead vocabulary
  The remaining expensive validation step is always a real live benchmark run, not more zero-token plumbing work.
- RecipeImport-owned CodexFarm subprocesses should inherit `~/.codex-recipe` from `cookimport/llm/codex_farm_runner.py`, not from ad hoc shell aliases or per-command CLI glue. If the wrong Codex home is in use, debug the runner env injection first.
- `gpt-5.3-codex-spark` plus reasoning effort does not guarantee reasoning-summary events in saved `.trace.json` files. A zero `reasoning_event_count` can be a legitimate upstream Codex CLI event-stream outcome, not an exporter bug.
- Current line-role transport is intentionally split three ways:
  - compact billed shard payload at `line-role-pipeline/runtime/line_role/workers/*/in/*.json`
  - richer local debug copy at `.../debug/*.json`
  - short wrapper prompt that points at `request_input_file`
  The tuple payload is the truth for token-cost work; the debug copy exists so payload compaction does not blind local debugging.
- line-role main workspace workers now use the same rare-kill watchdog contract as recipe and knowledge. The worker is still expected to start from `worker_manifest.json`, `assigned_tasks.json`, `assigned_shards.json`, and the named packet files, but bounded local orientation and helper shell use inside the worker root are telemetry, not kill reasons, unless they turn into a real boundary violation or a pathological no-progress loop.
- `AtomicLineCandidate` is no longer a neighbor-carrying cache object. Neighbor context for line-role prompt text now comes from explicit ordered-candidate lookup helpers, so adjacency-sensitive prompt changes belong in the prompt builder / lookup seam rather than by re-expanding parser records.
- Knowledge direct prompts must describe the real inline JSON contract. `{{INPUT_PATH}}` or file-reading wording is stale on the live knowledge surface; only file-backed line-role should use `prompt_input_mode=path`.
- Live knowledge payloads are intentionally compact and skeptical. They now use short aliases, omit `semantic_hint`, and only expose `suggested_lane` when deterministic evidence is strong enough to be worth a soft prior.
- The live recipe shard contract is similarly compact: minified shard JSON, compact helper hints, compact tag-guide payload, and a first-class candidate-quality/triage seam rather than a schema-shaped metadata dump.
- Recipe correction now has an explicit bad-candidate escape hatch. Shard proposals can return `fragmentary` or `not_a_recipe` with compact reasons, and deterministic promotion only emits final recipes for `repaired` results while preserving rejected candidates in proposals/audits.
- Knowledge reliability now depends on two separate rules that are easy to conflate:
  - shard-count requests are literal for recipe, knowledge, and line-role
  - knowledge still records warnings when a forced shard count creates oversized or non-local bundles
  If knowledge starts producing giant shards again, inspect the forced-count warnings before retuning prompts.
- Knowledge-stage hardening no longer trusts deterministic semantic gating to decide what the reviewer sees. The live stage removed chunk-level semantic hints from the billed payload, removed the low-signal deterministic prefilter, and now uses bounded repair/re-shard paths when a shard returns near-miss invalid JSON.
- Direct recipe / knowledge / line-role shard workers now run from sterile mirrored workspaces under `~/.codex-recipe/recipeimport-direct-exec-workspaces/`, with shard-scoped `AGENTS.md` files and rewritten local paths. If a worker appears to have repo-wide context again, debug the mirror/workdir seam before changing prompts.
- Pathological spend debugging now starts from repo-owned telemetry, not from rereading raw worker traces. `prompt_budget_summary.json` and worker-local artifacts should surface invalid-output spend, repaired-shard counts, command-executing shards, and other direct-exec pathology flags directly.
