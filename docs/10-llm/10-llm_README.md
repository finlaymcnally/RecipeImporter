---
summary: "Current LLM integration boundaries for CodexFarm across recipe, line-role, knowledge, and prelabel flows."
read_when:
  - When changing codex-farm settings or pipeline IDs
  - When debugging optional knowledge-stage artifacts
  - When auditing recipe pipeline enablement/default behavior
  - When reconciling Label Studio prediction-run LLM wiring vs stage wiring
---

# LLM Section Reference

LLM usage in this repo is optional. The direct-exec transport is now mixed by both attempt type and configured Codex style. Recipe refine stays on the assignment-first `taskfile` contract. For `line_role` and nonrecipe finalize, `codex_exec_style=taskfile-v1` keeps the current assignment-first `task.json` contract, while `codex_exec_style=inline-json-v1` switches those stages to inline JSON prompts plus `codex exec resume --last` follow-up turns for repair/grouping. Deterministic repo code still owns validation, repair rewrites, grounding gates, and final artifact expansion.

The worker-visible self-help surface is now intentionally split. Direct-batch task files (`line_role`, `nonrecipe_classify`, `knowledge_group`) are multiline, semantically ordered, advertise the editable surface through `answer_schema.editable_pointer_pattern`, and omit worker-facing `helper_commands`, `workflow`, `next_action`, and `editable_json_pointers`. For those stages the prompt should treat `task.json` as the whole job; `task-status` and `task-doctor` are optional troubleshooting helpers, and ordinary local reads of `task.json` plus `AGENTS.md` are allowed. Recipe refine still keeps explicit helper metadata in `task.json` because its live contract remains helper-driven.

Single-file `task.json` workers now also have a warning-first shell-drift contract. Off-path shell commands can still record `single_file_shell_drift` metadata so operators can see the worker leaving the paved path, but auto-termination is reserved for actual workspace boundary violations and other hard watchdog failures.

Line-role workspace supervision now treats the runner’s most recent completed stage-helper command as the authoritative live helper signal. That means a later non-helper command such as `task-summary` no longer erases evidence that `same_session_handoff` already completed, and `workspace_final_message_missing_output` is now reserved for cases where neither helper proof nor durable repo-owned outputs show up before the fallback grace window expires.

## Terminology

- `shard`: the planning/scheduling bundle. The interactive `*_prompt_target_count` settings ask for shard counts.
- `task`: the smallest validated work item for recipe. Knowledge and canonical line-role validate one finished shard output per assigned shard.
- `packet`: a compact follow-up payload shape used only for bounded repair / retry paths, not for the happy-path worker control surface.
- `worker`: the long-lived Codex session that executes one or more assigned shards/tasks.

When a stage is 1:1 between tasks and packets, the two can feel interchangeable. The intended distinction is still content versus work item.

## Runtime surface

Settings and command boundary:

- `cookimport/config/run_settings.py`
- `cookimport/config/codex_decision.py`
- `cookimport/cli.py`
- `cookimport/cli_ui/run_settings_flow.py`
- interactive `codex-exec` selection now has a second menu after surface toggles when line-role or knowledge are enabled: `Taskfile workers` (`taskfile-v1`) versus `Inline JSON` (`inline-json-v1`). Recipe correction stays on the taskfile contract.

Primary entrypoints:

- `cookimport/staging/import_session.py` for stage/import runs
- `cookimport/staging/pipeline_runtime.py` for the stage-owned `recipe-refine` and `nonrecipe-finalize` wrappers that call the recipe and knowledge Codex surfaces from the five-stage runtime
- `cookimport/labelstudio/ingest_flows/prediction_run.py` and `cookimport/labelstudio/ingest_flows/upload.py` for prediction-run and Label Studio benchmark/import flows

Shared shard-runtime foundation:

- `cookimport/llm/phase_worker_runtime.py` is the shared shard-worker foundation and now also defines the task manifest / task result dataclasses that the direct recipe, knowledge, and line-role runtimes can mirror incrementally.
- `cookimport/llm/codex_exec_runner.py` is the repo-owned direct Codex subprocess seam used by the live recipe, knowledge, and line-role transports. It now supports both one-shot `packet` calls and long-lived `taskfile` sessions.
- the direct `codex exec` command always includes `--skip-git-repo-check` because the sterile worker workspaces live outside the repository trust root by design.
- `taskfile` sessions now run in a sterile mirrored cwd that exposes only repo-written `task.json` plus `AGENTS.md`. The repo artifact root still keeps `worker_manifest.json`, `in/*.json`, `out/*.json`, `debug/`, and status sidecars, but those are repo-owned observability surfaces rather than the worker-visible startup contract.
- worker completion timing is now a canonical runtime setting instead of a hidden transport literal: `workspace_completion_quiescence_seconds` and `completed_termination_grace_seconds` both default to 15 seconds and are shared by stage, benchmark, prompt-preview-adjacent flows, and Label Studio prediction/import paths.
- `taskfile` sessions now also get a hard filesystem fence on Linux. The repo launches `codex exec` inside an unprivileged mount namespace that hides the normal home tree and sibling direct-exec workspaces, then bind-mounts only the current assigned execution workspace back into view at its original path. The runner also preserves the resolved local Codex toolchain root when that binary lives under the hidden home tree, so npm/nvm-installed `codex` and `node` still start cleanly inside the fence. This is the boundary that stops a worker from rummaging through old run artifacts just because the prompt told it not to.
- the same Linux fence now also preserves the active project virtualenv when it lives under the hidden home tree and injects a repo-owned helper import copy under `CODEX_HOME`, including a generated `bin/` wrapper/shim surface for single-file workers. That keeps `task-summary`, `task-handoff`, and the guarded `cat`/`ls`/`python3`/`python` redirects available inside the sterile workspace without reopening the real repo tree. For single-file workers, the runner also mirrors `_repo_control` into the execution workspace, rewrites same-session state paths to that mirrored root, and syncs the updated control state back after the session so helper validation can run entirely inside the fence.
- canonical line-role task-file extraction now trusts only the repo-authored original task snapshot plus the edited `/units/*/answer` payloads. If a worker also mutates immutable evidence fields while saving `task.json`, line-role records that drift in validation metadata but still expands the answer edits from the original snapshot instead of failing just because the evidence copy was scribbled on.
- the direct `taskfile` stages now treat planned happy-path worker sessions as a hard runtime contract: recipe, knowledge, and line-role all record `planned_happy_path_worker_cap`, `actual_happy_path_worker_sessions`, and repair/follow-up counts separately in repo-owned telemetry and manifests, and the runtime raises if the happy path silently fans out past plan.
- recipe, knowledge, and line-role now allow one bounded fresh-session recovery attempt on the happy path when the first session exits cleanly, leaves recoverable repo-owned worker state behind, and did not hit a hard watchdog boundary. For canonical line-role that recoverable state is the edited `task.json` plus repo-owned same-session state; `answers.json` is no longer part of the happy-path contract. That restart is stage-owned recovery, not a watchdog policy change.
- those same three main worker stages can now also spend one bounded fresh-worker replacement attempt after a catastrophic first worker failure such as a watchdog kill or retryable worker-process timeout. Replacement resets the worker back to the original repo-authored task/state instead of continuing the poisoned workspace.
- watchdog policy is now split by contract: `packet` retry / repair calls still treat shell commands as immediate off-contract behavior, while `taskfile` happy paths are assignment-first, file-first, and warning-first rather than queue-first or shell-first.
- canonical line-role now treats repo-owned same-session completion as the authoritative success signal: the runner keeps the most recent completed stage-helper command separately from the last arbitrary command, so a later `task-summary` read does not hide a successful `same_session_handoff`. Once `_repo_control/line_role_same_session_state.json` says `completed` and the required `workers/*/out/*.json` shard outputs are present/stable, supervision ends the workspace session as `completed` or `completed_with_warnings`; the older final-message missing-output watchdog remains only as a fallback when neither helper-stream proof nor output proof materializes during the configured grace window.
- the shared worker instructions now explicitly steer agents away from broad queue dumps and ad hoc shell schedulers. The preferred pattern for direct-batch stages is: open `task.json` directly, avoid shell on the happy path except for the repo-owned same-session helper command, and let repo code expand validated answers into final `out/` artifacts.
- the shared worker contract is now deliberately calm as well as strict: for direct-batch stages it tells the worker that `task.json` is the whole job, that there is no hidden repo-side context to discover on the happy path, and that brief local rereads or false starts should be corrected rather than treated as fatal.
- `taskfile` command handling is now explicitly split in repo code: `classify_taskfile_worker_command(...)` is reviewer-facing telemetry, while `detect_taskfile_worker_boundary_violation(...)` is the kill/no-kill enforcement seam for main worker sessions. Live-status payloads now record both the telemetry label and whether a real boundary violation was detected.
- the relaxed `taskfile` policy now also tolerates bounded local helper commands inside the worker root when the agent genuinely needs them, but the paved road is still direct file reads over the assignment file, `hints/*.md`, `in/*.json`, and stable `out/*.json` targets.
- the shared workspace boundary detector now explicitly ignores `jq`'s `//` fallback operator when scanning for absolute-path escapes, so local `jq '{rows: ... // ...}' ... > out/...` helper commands stay inside the relaxed policy
- `taskfile` main attempts now only auto-terminate on clear hard-boundary violations. Repeated local helper use, reasoning-without-output, and similar drift signals are kept as warnings in live-status/telemetry instead of kill reasons.
- validated worker-written `workers/*/out/*.json` files are authoritative for all three `taskfile` stages. `final_agent_message_state` can legitimately be `informational` or `absent` on the main worker path, and those final-message fields are telemetry only unless a structured retry / repair attempt explicitly requires strict JSON.
- recipe worker staging now short-circuits terminal scaffold tasks before the workspace session: if the repo-authored task scaffold is already `fragmentary` or `not_a_recipe`, runtime validates and installs that task locally and keeps it out of the live assignment-first worker prompt entirely.
- recipe reporting now surfaces that local bypass explicitly: `promotion_report.json` includes `handled_locally_skip_llm` counts plus per-recipe rows, task-count rollups, and assignment/task-file dispatch labels; `recipe_manifest.json` mirrors the topline count, and `recipe_stage_summary.json` exposes the same count in its high-level followup/context rollups.
- `recipe_stage_summary.json` now uses `followups.label="task_followup"` and reports recipe followup attention in task terms: `handled_locally_skip_llm_count`, `repair_attempted_count`, `repair_completed_count`, `repair_running_count`, and `proposal_count`.
- knowledge main-worker sessions no longer rely on a repo-advanced queue. Classification and grouping both use direct-batch `task.json` editing, missing shard outputs fail closed from the assignment-first session evidence in `live_status.json`, and invalid shard outputs can still get one explicit structured repair attempt before the stage fails closed.

Recipe CodexFarm path:

- `cookimport/llm/codex_farm_orchestrator.py` (thin public facade)
- `cookimport/llm/recipe_stage/planning.py`, `runtime.py`, `validation.py`, `promotion.py`, `reporting.py`
- `cookimport/llm/recipe_stage_shared.py` (private backing implementation during the owner split)
- `cookimport/llm/codex_farm_contracts.py`
- `cookimport/llm/codex_farm_ids.py`
- `cookimport/llm/codex_farm_runner.py`

Other active Codex-backed surfaces:

- Optional knowledge extraction: `cookimport/llm/codex_farm_knowledge_orchestrator.py` (thin public facade), `cookimport/llm/knowledge_stage/planning.py`, `runtime.py`, `recovery.py`, `promotion.py`, `reporting.py`, `cookimport/llm/codex_farm_knowledge_jobs.py`, `cookimport/llm/codex_farm_knowledge_contracts.py`, `cookimport/llm/codex_farm_knowledge_models.py`, `cookimport/llm/codex_farm_knowledge_ingest.py`, `cookimport/llm/codex_farm_knowledge_writer.py`, `cookimport/llm/knowledge_prompt_builder.py`
- the knowledge stage now keeps two small runtime ledgers beside the normal manifests: `task_status.jsonl` records per-shard attempt/terminal state, while `stage_status.json` records stage finalization and interruption attribution. `knowledge_stage_summary.json` is the canonical post-run summary view over those ledgers, including an `attention_summary` block for zero-target failure, follow-up trouble, and unreviewed-work counts. Interrupted runs should still leave partial `phase_manifest.json`, `promotion_report.json`, `telemetry.json`, and `failures.json` beside those status files.
- for assignment-first failures, `task_status.jsonl` is explicit rather than generic: rows can terminate as `validated`, `repair_packet_exhausted`, `process_exited_without_final_packet_state`, or a propagated watchdog reason code depending on what deterministic validation and supervision observed.
- `knowledge_stage_summary.json` now exposes `no_final_output_shard_count` plus `no_final_output_reason_code_counts` as the coarse knowledge no-result rollups. The authoritative failure vocabulary for knowledge packets is still `terminal_reason_code` plus the packet-state rows, not a generic packet bucket.
- recipe and canonical line-role stage roots now also write compact post-run summaries beside their runtime artifacts: `recipe_stage_summary.json` under `raw/llm/<workbook>/recipe_phase_runtime/` and `line_role_stage_summary.json` under `line-role-pipeline/runtime/line_role/`. Those compact summaries now also expose `attention_summary` so non-promoted recipe outcomes, line-role fallback rows, Codex hard-policy rejections, and similar "should be zero" counters are obvious without opening raw proposals.
- canonical line-role runtime telemetry now preserves missing token usage as unavailable instead of coercing it to zero, so `telemetry_summary.json`, `prompt_budget_summary.json`, and benchmark-history token backfill can fail closed on partial usage
- the shared direct-exec runner now also parses the Codex CLI plain-text `Token usage: ...` footer when a `taskfile` session omits JSON `turn.completed` usage, so normal `workers/*/usage.json` artifacts can populate again without weakening the fail-closed summary readers
- when repo supervision decides a `taskfile` session is `completed` or `completed_with_failures`, the shared runner now waits briefly before terminating the subprocess so late `turn.completed` usage can still arrive and populate the normal worker `usage.json` artifacts
- the line-role and knowledge success watchdogs no longer stop a worker the instant outputs stabilize; they now wait for repo-visible completion proof, or a short quiet period, before asking the runner to terminate the session. For line-role specifically, assistant prose is telemetry only on the happy path; helper state plus durable shard outputs are the authority.
- line-role and knowledge worker roots now also save raw `stdout.txt` / `stderr.txt` sidecars when the direct-exec subprocess emitted text, which makes missing-usage sessions inspectable from the artifact tree
- the shared guardrail payloads now also follow the same repo-owned reporting path across those stages: `task_file_guardrails` records deterministic `task.json` size/estimated-token pressure for the real worker-visible file, and `worker_session_guardrails` records planned-versus-actual happy-path sessions plus explicit repair/follow-up counts in worker `status.json`, stage `telemetry.json`, stage summaries, and prompt-budget summaries
- Canonical line-role: `cookimport/parsing/canonical_line_roles/` (`planning.py`, `policy.py`, `runtime.py`, `validation.py`, plus `contracts.py` / `prompt_inputs.py` / `artifacts.py`), `cookimport/llm/canonical_line_role_prompt.py`, `cookimport/llm/codex_exec_runner.py`
- Freeform prelabel: `cookimport/labelstudio/prelabel.py`
- Prompt/debug artifact export: `cookimport/llm/prompt_artifacts.py`

Recipe tagging is part of the recipe surface itself. The recipe-correction prompt emits raw selected tags, and deterministic normalization folds them into staged outputs.

The live Codex-backed surfaces are `recipe`, `line_role`, `knowledge`, and `prelabel`.

Pipeline assets under `llm_pipelines/pipelines/` no longer pin repo-default `codex_model` strings. Runtime model choice now comes from explicit overrides first, then env/config discovery; prompt preview now resolves command-sensitive fallback model/reasoning defaults against the effective Codex command (`codex_farm_cmd` arg first, then processed-run `runConfig.codex_farm_cmd`) and otherwise labels the request as `pipeline/default`.

## Current live surfaces

- `llm_recipe_pipeline`: `off`, `codex-recipe-shard-v1`
- `llm_knowledge_pipeline`: `off`, `codex-knowledge-candidate-v2`
- `line_role_pipeline`: `off`, `codex-line-role-route-v2`
- Prelabel is a separate Codex surface routed through CodexFarm pipeline `prelabel.freeform.v1`

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
- for path-backed direct-exec phases such as line-role, the fake exec shim must read the deposited local shard ledger named in the wrapper prompt or worker control surface; answering from the example JSON embedded in the prompt text will produce false `atomic_index:123` validation failures.
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
  - optional knowledge refinement/extraction over the explicit `nonrecipe-route` candidate queue
  - canonical line-role Codex labeling
  - freeform prelabel
- `prompt_budget_summary.json` should preserve CodexFarm split token totals (`tokens_input`, `tokens_cached_input`, `tokens_output`) from per-call telemetry rows when they are present in the prediction manifest.

## Plain-English Pipeline

If you want the current Codex-backed flow in operator language instead of artifact language, this is the simplest accurate version:

1. The program parses the cookbook into one ordered set of atomic lines and other deterministic intermediate structures.
2. The program makes a deterministic first pass over those lines before any Codex-backed review.
3. The line-role Codex surface reviews the whole book line set in worker-local shard files. The live main path now gives each worker session one repo-written `task.json` containing immutable row evidence plus editable answer slots. After each edit pass the worker runs a repo-owned same-session helper; deterministic code validates those edited answers, rewrites `task.json` into repair mode once if needed, expands accepted answers into shard outputs, and then fails closed if the repair pass is still invalid.
4. The program groups the corrected recipe-side lines into coherent recipe spans and recipes. Everything not grouped into recipe spans becomes the non-recipe side.
5. The recipe Codex surface reviews the recipe side in owned recipe shards. One worker session edits one repo-written `task.json` containing the owned recipe evidence and answer fields for all of its units. The worker then runs the repo-owned same-session helper, which validates those edits, rewrites `task.json` into repair mode once if needed, and only then lets repo code rejoin accepted answers into shard proposals.
6. The program deterministically validates those recipe task outputs, records whether each result is promotable, and only then promotes `repaired` outcomes into the final recipe formats.
7. The knowledge Codex surface finalizes the non-recipe side. The program partitions the category-neutral `nonrecipe-route` candidate queue into worker assignments, writes one repo-owned classification `task.json` per worker session, and asks the worker to make only the block-local `knowledge|other` call there. If any rows survive as `knowledge`, repo code writes a second grouping-only `task.json` containing only those accepted rows. Repo code validates both edited files structurally, promotes only accepted outputs, and keeps grouping pressure out of the original keep/drop call.
8. The program validates owned output coverage, writes artifacts/reports, and emits the final recipe, knowledge, and debug outputs.

Worker/shard mental model:

- A setting such as `10 / 5 / 10` in benchmark interactive mode means the runtime will build at most ten `line_role` shards, five `recipe` shards, and ten `knowledge` shards; phases may use fewer shards only when they have fewer owned items total.
- Recipe, line-role, and knowledge all treat their prompt target counts as hard caps on shard count. When worker count is not overridden separately, implicit worker count is bounded by the final shard count.
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
- the live recipe implementation now treats `recipe_prompt_target_count` as the requested shard count, partitions contiguous recipe candidates across that many recipe shards when possible, executes those shards through the repo-owned direct recipe worker runtime in `recipe_stage/runtime.py`, validates exact owned `recipe_id` coverage in `recipe_stage/validation.py`, and promotes only validated per-recipe outputs through `recipe_stage/promotion.py`
- recipe worker assignments now launch one long-lived `taskfile` Codex session per worker assignment with repo-written `task.json`; each unit owns one `recipe_id`, the worker edits only answer fields in that file, deterministic code writes the final `out/<task_id>.json` artifacts, and shard proposals are rebuilt from the accepted answers
- recipe runtime still writes `task_manifest.jsonl` for reporting, but the live worker surface is the editable task file rather than a repo-advanced packet queue or task inventory dump
- recipe source worker roots still carry `worker_manifest.json` and the usual repo artifacts, but the mirrored worker-visible cwd is just `task.json` plus `AGENTS.md`
- worker assignments now launch concurrently and then merge results back in planned assignment order so runtime artifacts stay stable while multi-worker runs become real
- deterministic code still validates and normalizes recipe outputs locally, but the live promotion seam is now one canonical `AuthoritativeRecipeSemantics` payload per recipe. Codex still emits compact `ingredient_step_mapping` plus raw `selected_tags`, and promotion now records the merged semantic result under `recipe_authority/<workbook_slug>/authoritative_recipe_payloads.json` before intermediate/final drafts are written.
- `CodexFarmApplyResult` now exposes only the canonical `authoritative_recipe_payloads_by_recipe_id` map plus the updated conversion result and recipe-stage telemetry; the older intermediate/final override maps are no longer part of the live orchestrator result contract.
- the model-facing recipe shard now includes a compact candidate-quality hint `q` alongside weak deterministic parse hint `h`, and each recipe result now carries compact status/divestment fields (`st`, `sr`, `db`) so `fragmentary` / `not_a_recipe` candidates stay visible in proposals/audits, recipe-refine can explicitly return owned blocks to nonrecipe, and only `repaired` results promote into final recipe outputs
- `recipe_phase_runtime/promotion_report.json` now distinguishes validated recipe task outcomes from final-authority eligibility: `repair_status` still tells you the valid task result, while `final_recipe_authority_eligibility` tells you whether that result is promotable.
- `recipe_manifest.json` and `recipe_correction_audit/*.json` now carry the final-authority decision explicitly. `repaired` plus successful deterministic assembly becomes `final_recipe_authority_status="promoted"`, while valid `fragmentary` / `not_a_recipe` outcomes remain visible as `final_recipe_authority_status="not_promoted"`.
- recipe tag guidance is now recipe-local rather than purely global: single-candidate recipe shards carry a richer `recipe_tagging_guide.v3` with both the broader category catalog and a filtered `tg.s[*]` candidate label surface derived from the current recipe text/hints
- the authoritative recipe contract is now: `recipe_phase_runtime/inputs/*.json` immutable shard payloads, worker-local `workers/*/out/*.json` compact task outputs, `recipe_phase_runtime/proposals/*.json` validated shard proposals, then deterministic promotion into `recipe_authority/<workbook_slug>/authoritative_recipe_payloads.json` plus staged outputs; recipe task rows now include `metadata.input_path`, `metadata.hint_path`, and `metadata.result_path` so the workspace helper installs only to the declared local output path; `recipe_correction_audit/` remains only the per-recipe human/debug summary surface
- file-backed validity is authoritative for recipe taskfile workers: if `workers/*/out/*.json` validates, a prose or markdown closing message is telemetry only and does not downgrade the task into a malformed result
- recipe worker shard folders now also write `prompt.txt`, `events.jsonl`, `usage.json`, `last_message.json`, and `cost_breakdown.json`, so prompt-preview and actual-cost reporting can talk about the same visible request/response surface
- recipe worker folders now also write `workspace_manifest.json`, `status.json`, and `live_status.json`; `status.json` is the aggregate worker-session artifact, `telemetry.json` is the stage-level session ledger, and shard proposals carry `task_status_by_task_id` so per-task results stay separate from session cost accounting
- repair artifacts are now packet-scoped and bounded: the live recipe path can write `shards/<task_id>/repair_packet.json` and `shards/<task_id>/repair_status.json`, but it no longer writes `same_session_fix_status.json`, `watchdog_retry/`, or recipe draft-install repair scaffolding on the happy path
- `stage_observability.json` now reports the semantic recipe stages `recipe_build_intermediate`, `recipe_refine`, and `recipe_build_final`

Knowledge-stage writes:

- `data/output/<ts>/08_nonrecipe_route.json`
- `data/output/<ts>/08_nonrecipe_exclusions.jsonl`
- `data/output/<ts>/09_nonrecipe_authority.json`
- `data/output/<ts>/09_nonrecipe_knowledge_groups.json`
- `data/output/<ts>/09_nonrecipe_finalize_status.json`
- `data/output/<ts>/recipe_authority/<workbook_slug>/recipe_block_ownership.json`
- `data/output/<ts>/raw/llm/<workbook_slug>/knowledge_manifest.json`
- `data/output/<ts>/raw/llm/<workbook_slug>/nonrecipe_finalize/in/*.json`
- `data/output/<ts>/raw/llm/<workbook_slug>/nonrecipe_finalize/phase_manifest.json`
- `data/output/<ts>/raw/llm/<workbook_slug>/nonrecipe_finalize/shard_manifest.jsonl`
- `data/output/<ts>/raw/llm/<workbook_slug>/nonrecipe_finalize/task_manifest.jsonl`
- `data/output/<ts>/raw/llm/<workbook_slug>/nonrecipe_finalize/worker_assignments.json`
- `data/output/<ts>/raw/llm/<workbook_slug>/nonrecipe_finalize/promotion_report.json`
- `data/output/<ts>/raw/llm/<workbook_slug>/nonrecipe_finalize/telemetry.json`
- `data/output/<ts>/raw/llm/<workbook_slug>/nonrecipe_finalize/failures.json`
- `data/output/<ts>/raw/llm/<workbook_slug>/nonrecipe_finalize/proposals/*.json`
- `data/output/<ts>/knowledge/<workbook_slug>/knowledge.md`
- `data/output/<ts>/knowledge/knowledge_index.json`

`08_nonrecipe_route.json` is the deterministic `nonrecipe-route` artifact. It keeps the candidate queue, exclusions, and previews, but not final semantic category guesses. `09_nonrecipe_authority.json` is the final machine-readable truth surface for outside-recipe `knowledge` versus `other`. `09_nonrecipe_knowledge_groups.json` records the promoted model-authored related-idea groups. `09_nonrecipe_finalize_status.json` is the runtime-status artifact for finalized and unresolved candidate rows. `knowledge.md` remains the reviewer-facing summary surface.

Knowledge runtime note:
- the live knowledge implementation is no longer one direct `knowledge/in -> knowledge/out` CodexFarm call
- knowledge classification now carries its grouping batch limits inside the repo-authored classification `task.json`, so same-session handoff and later grouping batches reuse the same explicit max-units / max-evidence budgets instead of falling back to hidden module literals.
- deterministic repo code now decides only shard sizing and ordering. It does not decide final `knowledge|other` labels or final grouping.
- knowledge shard planning now reads the stage-owned recipe block-ownership contract. Recipe-owned blocks are excluded from owned packet rows and from prompt context text; only nearby owned indices may survive as compact guardrail metadata.
- `codex_farm_knowledge_jobs.py` now writes one ordered shard payload per file under `knowledge/in/*.json`. `knowledge_prompt_target_count` is a hard cap on the number of shard files, and packet-budget pressure is recorded as metadata/warnings rather than silently increasing shard count.
- the live knowledge model call now goes through `codex_exec_runner.py`, and the worker surface is assignment-first rather than leased-packet-first or phase-ledger-first
- knowledge worker assignments now use one happy-path `taskfile` Codex session per worker assignment with repo-written `task.json`: classification starts first, the same session runs one repo-owned validate-and-advance helper, and that helper either rewrites `task.json` into repair mode, rewrites it into the grouping file, or finishes the final `out/*.json` shard artifacts directly when everything is `other`
- knowledge repair rewrites now keep `validation_feedback` unit-local and compact instead of copying the full shared validation-detail blob onto every failed unit; detailed validation history still lives in repo-owned same-session state/telemetry
- knowledge grouping task files are now bounded deterministic batches rather than one flat all-kept-rows file: deterministic code splits large grouping work by row/evidence budget, writes top-level `grouping_batch` progress metadata into `task.json`, and keeps the worker on the same direct-batch open/edit/handoff loop until the final batch completes
- classification `task.json` now includes immutable task-scope `ontology` loaded from the checked-in `cookimport/llm/knowledge_tag_catalog.json` snapshot plus per-unit `candidate_tag_keys` lexical hints; deterministic code validates catalog membership and shape, but the model still makes the semantic keep/drop call
- classification `task.json` now also carries a repo-written `review_contract`. The intended mindset is close semantic review of each owned block, not inventing a packet-wide heuristic or shell-script classifier. The live happy path is direct-batch rather than queue-style: open `task.json` directly, answer all owned units in place, run `task-handoff`, and continue in the same workspace only if the helper rewrites the file into repair mode or grouping mode. `task-template`, `task-apply`, `answers.json`, and the older queue helpers are no longer part of the normal knowledge classification path.
- `live_status.json` plus deterministic validation metadata is now the repo-side truth surface for no-result classification. The happy path no longer depends on `packet_lease_status.json`, `current_packet.json`, or repo-advanced pass control files.
- the old `knowledge_phase_workspace_tools.py` lease/packet helper surface has been removed. The normal paved road is: open `task.json`, edit only the answer fields, save, run the repo-owned same-session helper, and stop when it reports completion.
- knowledge progress now treats shards as the live truth: stage counters use shard totals, worker labels show active shard progress, and follow-up recovery stays scoped to the affected shard
- knowledge source worker roots still carry `worker_manifest.json` plus repo-owned debug/status files, but the mirrored worker-visible cwd is just `task.json` plus `AGENTS.md`
- line-role happy-path `task.json` now keeps the worker-visible evidence raw-text-first as well: immutable row evidence is down to `atomic_index` plus line text, and it no longer exposes copyable deterministic label hints, deterministic reason-hint lists, block provenance, or pre-grouping `within_recipe_span` values in the worker-visible file.
- line-role workers should resolve adjacency-sensitive title/variant/yield calls by reading nearby rows directly from the ordered `task.json` ledger; the worker surface stays compact instead of adding a separate neighbor helper or duplicating adjacent text into every unit.
- knowledge worker hints now stay intentionally compact: `hints/<shard_id>.md` is a worker-calibration sidebar, not a second prompt, and it keeps only shard profile, weak-context reminders, decision policy, example-file pointers, and attention rows before the worker reopens the authoritative `task.json`
- `codex_farm_knowledge_ingest.py` still validates exact owned block coverage plus exact kept-block-to-idea-group coverage, but the worker-facing contract reaches that final packet shape through two validated task-file steps rather than one combined semantic answer
- the knowledge semantic boundary is now ontology-grounded and outcome-first: `knowledge` means a portable concept worth storing and later retrieving on its own, not just something cooking-adjacent that happens to be true. The classification file stays block-local and grouping-free, and a kept row now emits only `category` plus `grounding` to an existing tag or a proposed tag under an existing category.
- the knowledge worker vibe is now explicitly anti-heuristic: the prompt, review contract, and hint sidecar all say that block text is primary evidence, neighboring rows and candidate tags are weak hints only, short conceptual headings can still be keepable, and if the worker feels tempted to invent one rule for many rows it should stop and reread the owned block text instead
- live knowledge validation is still semantic-light, but it now enforces the grounding contract structurally: deterministic code checks ownership, coverage, block order, allowed enum values, and kept-block grouping completeness, plus valid grounding for `knowledge`, checked-in catalog membership for `tag_keys` and `category_keys`, and normalized proposed tags. It still does not reject a structurally valid shard because repo heuristics disagree with the model's semantic judgment.
- accepted knowledge outputs are compact shard outputs: top-level `packet_id`/shard id, ordered `block_decisions`, and model-authored `idea_groups`
- the knowledge prompt/worker contract now also treats short conceptual headings as keepable when they directly introduce useful explanatory blocks in the same owned shard; decorative or menu-like headings still stay `other`
- the knowledge prompt/worker contract must treat packet order as weak context, not proof of semantic continuity: large block-index jumps or abrupt topic shifts are cues that nearby packet rows may be unrelated, so block-local classification stays primary and grouping happens only after accepted rows are already fixed
- the authoritative knowledge contract is now: `knowledge/in/*.json` immutable shard payloads, worker-local shard outputs under `workers/*/out/*.json`, `knowledge/proposals/*.json` validated repo-serialized shard proposals, then deterministic promotion into `08_nonrecipe_route.json`, `09_nonrecipe_authority.json`, `09_nonrecipe_finalize_status.json`, and reviewer-facing knowledge artifacts
- valid knowledge worker shard outputs remain authoritative even if the workspace session ends with no final assistant message; `final_agent_message_state` is still recorded in telemetry/live-status for debugging, but follow-up recovery only keys off file-level validation failure
- direct `taskfile` telemetry is now fail-closed on token accounting too: if a workspace session shows real work but no usable Codex usage payload, the runtime summary records `token_usage_status=partial|unavailable` and blanks billed-token totals instead of publishing literal zero spend
- invalid but near-miss knowledge outputs now get one repo-owned repair attempt at task scope; task/shard folders can include `repair_prompt.txt`, `repair_events.jsonl`, `repair_last_message.json`, `repair_usage.json`, and `repair_status.json`, while proposal/status payloads record whether repair was attempted and whether the final validated output came from that repair pass
- snippet-copy-only knowledge failures now have their own narrow recovery rung before the broad repair ladder: `inline_snippet_repair` rewrites snippet bodies only, and those failures no longer jump straight to `repair_skipped_poisoned_worker` before the narrow repair chance is exhausted
- direct knowledge shard folders now also write `workspace_manifest.json`, and retry/repair child attempts write their own workspace manifests beside the attempt-local events/usage files so the sterile cwd provenance is visible from repo artifacts
- strict JSON knowledge shard attempts now also write `live_status.json`; deterministic preflight can still stop malformed shard payloads before spend, but live `taskfile` supervision now records command/reasoning/outlier drift as warnings and reserves auto-termination for hard-boundary violations
- repeated uniform malformed, low-trust, watchdog-boundary, or zero-output task failures can now classify a worker as poisoned, which causes later retry/repair follow-ups to record explicit skip reasons instead of paying for another doomed recovery attempt
- completed knowledge taskfile workers now preserve warning metadata in `live_status.json`; successful task-file workers can finish as `completed` or `completed_with_warnings`, invalid outputs can still roll into `repair_packet_exhausted` after one repair pass, and hard-boundary interrupts keep their explicit boundary reason codes
- recipe, knowledge, and canonical line-role progress emitters now summarize those repo-owned `live_status.json` files into operator-facing progress rows: `active_tasks` can carry a short visible-activity snippet plus compact attention suffixes, `detail_lines` can report warning/stalled-worker counts plus a short `attention:` summary, and `last_activity_at` now reflects the freshest worker event seen by the stage runtime
- the live activity snippet is derived only from visible Codex event content already present in the direct-exec stream, such as command executions, visible reasoning summaries, agent messages, and lifecycle rows; it stays intentionally short so the shared spinner panel remains readable
- the `[final message, no output]` attention label is intentionally conservative: it should appear only on explicit missing-output failure evidence such as `workspace_final_message_missing_output`, not on a still-running snapshot or a just-finished `completed` / `completed_with_warnings` snapshot before repo-owned output validation/finalization has caught up
- knowledge and canonical line-role runtimes now also run a small progress heartbeat while taskfile workers are active so quiet-worker attention changes appear in the interactive panel before the shard completes; recipe reuses its existing polling loop for the same effect
- the runtime cutover still promotes into the packet-native knowledge pack directly: `recipe.knowledge.packet.v1` remains the final shard output contract, but the live worker-visible task-file contract is now `nonrecipe_classify` first and `knowledge_group` second inside one same-session helper handoff rather than two happy-path worker launches
- promotion/reporting now also carries grounding through the normal artifacts: `promotion_report.json`, `knowledge_manifest.json`, `09_nonrecipe_authority.json`, and `knowledge_stage_summary.json` expose existing-tag versus proposed-tag counts, and the stage writes `knowledge_tag_proposals.jsonl` as the deduplicated sidecar for future catalog growth
- knowledge worker assignments now launch concurrently and merge back in planned order so `running N` reflects real in-flight work
- knowledge progress callbacks now report shard truth: `task_current/task_total` now map to shard-owned work rows, detail lines carry completed-shard totals, and `active_tasks` rows identify the worker-owned shard plus any inline follow-up state
- the billed knowledge payload now avoids chunk-level semantic hints entirely; it carries raw block text, block ids, and mechanically true structure only
- prompt-cost control for this stage lives before worker execution:
  - `cookimport/parsing/chunks.py` still provides deterministic chunk boundaries, but its semantic lane guesses no longer suppress review
  - `build_knowledge_jobs(...)` now sizes ordered candidate packets from those deterministic boundaries, while keeping deterministic judgments out of the billed reviewer payload
  - table-heavy packets stay isolated, soft-gap packing can cross small outside-recipe gaps, and there is no second deterministic low-signal pruning pass anymore
  - the shared default knowledge context is now `0` blocks

Inline recipe tagging writes through the normal recipe artifacts:

- `data/output/<ts>/final drafts/<workbook_slug>/r{index}.json` as `recipe.tags`
- `data/output/<ts>/intermediate drafts/<workbook_slug>/r{index}.jsonld` as `keywords`

Line-role prediction artifacts live under:

- `prediction-run/line-role-pipeline/telemetry_summary.json`
- `prediction-run/line-role-pipeline/runtime/phase_manifest.json`
- `prediction-run/line-role-pipeline/runtime/shard_manifest.jsonl`
- `prediction-run/line-role-pipeline/runtime/shard_status.jsonl`
- `prediction-run/line-role-pipeline/runtime/worker_assignments.json`
- `prediction-run/line-role-pipeline/runtime/proposals/*.json`

Line-role runtime note:
- live line-role execution no longer uses `phase_worker_runtime.py` or `codex-farm process`
- `canonical_line_roles.py` now assigns shard ownership directly, writes authoritative worker-local shard JSON under `line-role-pipeline/runtime/line_role/workers/*/in/*.json`, validates exact owned `atomic_index` coverage, and writes repo-owned worker artifacts under `line-role-pipeline/runtime/line_role/workers/.../shards/<shard_id>/`
- line-role worker assignments now launch one long-lived `taskfile` Codex session per worker assignment with repo-written `task.json`; the source worker root still keeps `prompt.txt`, `debug/*.json`, `in/*.json`, `out/*.json`, and status sidecars for repo validation, but the mirrored worker-visible cwd is only `task.json` plus `AGENTS.md`
- the cheap line-role happy path is now: open `task.json`, read the immutable row evidence once, edit the answer slots, save, run the repo-owned same-session helper, and stop only when that helper reports completion
- the line-role prompt/hint contract now treats outside-recipe `KNOWLEDGE` as high-evidence and low-default: reusable explanation/reference prose and supported lesson headings can stay `KNOWLEDGE`, while memoir, blurbs, endorsements, book-framing encouragement, and broad action-verb advice should stay `OTHER`
- line-role source worker roots still carry `worker_manifest.json` and the usual repo debug/status files, but the shared worker prompt now teaches the mirrored worker-visible cwd as one-file-first: open `task.json`, edit answers in place, save, run the same-session helper, and stop when it reports completion.
- line-role no longer launches a second repo-owned repair worker prompt. The same worker session gets one repo-owned repair rewrite of `task.json` when needed; deterministic code expands accepted task-file answers into `out/<shard_id>.json`, and still-invalid authoritative edits fail closed after that bounded repair pass.
- strict JSON line-role shard attempts now also write `live_status.json`; malformed shard payloads are rejected before spend with `state: preflight_rejected`, while live `taskfile` supervision records command/reasoning/outlier drift as warnings and reserves auto-termination for hard-boundary violations
- strict JSON watchdog kill reasons now also preserve the offending command text in `reason_detail`, so a `watchdog_command_execution_forbidden` status can distinguish trivial `ls` / `pwd` orientation reflexes from more substantive tool use
- for `taskfile` main attempts only, `command_execution_tolerated: true` now means the worker stayed within the allowed workspace-local command policy; `live_status.json`, shard `status.json`, and direct telemetry rows now also record command-policy classifications/reasons so reviewer artifacts can distinguish helpful local file reads from real drift
- there is no longer any live or compatibility support for a separate LLM recipe gate inside line-role; the only active line-role model surface is the single `line_role` labeling phase
- line-role pre-grouping candidates now default to `within_recipe_span=None`; importer recipe provenance is no longer supplied before deterministic/Codex labeling, and prompt-preview reconstruction mirrors that same span-free contract
- `AtomicLineCandidate` is now a single-line parser record; selective inline `ctx:` rows and cache identity derive neighbor text from explicit ordered-candidate lookup instead of embedded `prev_text` / `next_text` fields
- `workers/*/in/*.json` remain the authoritative stored payloads the worker reads locally. For line-role, those are shard-owned row ledgers with optional neighboring context; for knowledge, those are shard-owned compact input files with optional nearby context; for recipe, those are shard-owned task payload files and several recipe tasks may share one parent shard on the main path. When a structured follow-up still exists, it must read authority from those stored inputs rather than reconstructing freehand.
- `workers/*/hints/*.md` are worker-facing decision aids. They are not validator authority. Line-role hints stay intentionally narrow: shard profile, short static reminders, label-code legend, and attention-row summaries beside the authoritative `in/*.json` payload.
- line-role now keeps a second local-only debug copy at `workers/*/debug/*.json`; prompt-preview mirrors that as `line-role-pipeline/debug_in/*.json`, while `request_input_file` and budget estimation still point at the compact billed `in/*.json` file.
- those `workers/*/in/*.json` files are now compact row ledgers: `{"v":1,"shard_id":...,"context_before_rows":[[atomic_index,current_line], ...],"rows":[[atomic_index,label_code,current_line], ...],"context_after_rows":[[atomic_index,current_line], ...]}`. The boundary-context keys are optional and appear only when immediate neighbors exist. The model-facing file stays compact row-wise and carries only direct row evidence plus immediate neighboring context.
- `telemetry_summary.json` remains the prompt/debug and post-run cost seam for line-role, but its runtime metadata now describe direct exec instead of CodexFarm `process`
- line-role worker launches are concurrent and then re-collected in planned order so stable artifacts and real worker fan-out coexist

Prompt/debug artifacts:

- `prompts/full_prompt_log.jsonl` is the stable per-call truth
- direct `codex exec` shard telemetry now records `duration_ms`, `started_at_utc`, and `finished_at_utc`; when the global `var/codex_exec_activity.csv` join is missing or stale, prompt-artifact export should backfill recipe/knowledge rows from the stage-local `telemetry.json` keyed by runtime shard id
- `prompts/prompt_log_summary.json` is the small count summary for that log; it separates raw row count from `runtime_shard_count` so bundled recipe outputs do not look like extra Codex calls
- `prompts/prompt_request_response_log.txt` is the human-readable convenience export
- `prompts/prompt_type_samples_from_full_prompt_log.md` is a sampled reviewer view
- `prompts/activity_traces/<call_id>.json` is the canonical prompt-local export for visible worker activity; it is derived from saved worker files such as `events.jsonl`, `last_message.json`, `usage.json`, `live_status.json`, `workspace_manifest.json`, and optional `stdout.txt` / `stderr.txt`
- `prompts/activity_trace_summary.jsonl` and `prompts/activity_trace_summary.md` summarize activity-trace coverage by reading the prompt-local exported `activity_traces/*.json` files; the exported traces include visible command/message/reasoning entries plus visible file changes when the worker event stream exposed them
- stage-local direct-exec telemetry rows now carry explicit worker artifact paths (`events_path`, `last_message_path`, `usage_path`, `live_status_path`, `workspace_manifest_path`, and optional stdout/stderr sidecars) so prompt publication can export durable traces without stage-specific path guessing
- `prediction-run/prompt_budget_summary.json` is the post-run actual-costs artifact; it merges recipe/knowledge telemetry with line-role telemetry when present and publishes semantic `by_stage` totals instead of an old pass-slot grouping container
- `prediction-run/prompt_budget_summary.json` now also carries pathological direct-exec spend signals such as preflight-rejected shard counts, watchdog-killed shard counts, invalid-output shard counts/tokens, missing-output shard counts, repaired-shard counts, command-executing shard counts, reasoning-heavy shard counts, and merged `pathological_flags` so March 18-style blowups are visible without rereading worker `events.jsonl`
- stage-local direct-exec summaries now also expose `prompt_input_mode_counts`, `taskfile_session_count`, `structured_followup_call_count`, and `execution_mode_summary`, so a finished run shows how much work came from main worker sessions versus shard-local retry / repair follow-up calls
- the knowledge stage row inside `prediction-run/prompt_budget_summary.json` now also carries compact packet / worker / follow-up counters copied from `knowledge_stage_summary.json`, so cost review and outcome review use the same vocabulary
- the knowledge stage now also publishes packet-economics rollups all the way through `raw/llm/<book>/nonrecipe_finalize/telemetry.json`, `knowledge_stage_summary.json`, and `prediction-run/prompt_budget_summary.json`: packet counts, same-session classification/grouping validation counts, grouping-transition counts, repair rewrites, owned-row totals, semantic-payload tokens, protocol-overhead tokens, and per-owned-row cost ratios all use the same repo-owned numbers
- `prediction-run/prompt_budget_summary.json` now also reports requested-vs-actual run-count metadata per active Codex stage (`requested_run_count`, `actual_run_count`, `run_count_status`, `run_count_explanation`) so a finished run shows clearly when a `3/4/5` target was matched or when the planner legally used fewer/more shards
- `prediction-run/prompt_budget_summary.json` now also falls back to current shard-runtime worker telemetry plus the linked processed-run `line-role-pipeline/telemetry_summary.json` when a benchmark/prediction manifest only carries lightweight phase summaries or a metadata-only benchmark copy
- when line-role telemetry only exposes nested batch/attempt summaries, `prompt_budget_summary.json` should still recover those `tokens_total` values so the finished-run whole-run drain is not understated
- for line-role, requested-vs-actual run-count reporting is surface-level: compare the requested line-role target against the actual shard count on the single live `line_role` phase
- `cf-debug preview-prompts --run ... --out ...` rebuilds zero-token prompt previews from an existing processed run, or from a benchmark root that resolves to a predictive-safe processed run, and writes `prompt_preview_manifest.json` plus prompt artifacts under the chosen output dir
- prompt preview manifests now also record `codex_farm_cmd`, and preview rows use that effective command when reconstructing fallback runtime model/reasoning labels
- preview budget estimation is predictive-only: it rebuilds deterministic/`vanilla` shard payloads locally, estimates tokens from reconstructable prompt/output structure, and never reuses Codex-backed run telemetry
- predictive preview is now structural rather than ratio-based: it tokenizes the reconstructed prompt wrapper plus deposited task-file body with `tiktoken`, estimates output tokens from schema-shaped JSON built from the planned shard input, and reports stages as unavailable when that structure cannot be rebuilt safely
- older saved runs that predate the prompt-target fields should default preview planning to the current shard-v1 target count (`5`) for each enabled phase instead of falling back to legacy shard-size defaults
- retrospective “what did this completed run actually cost?” reporting lives in the finished-run `prompt_budget_summary.json` / `actual_costs_json` artifact, not in prompt preview
- when `--run` points at a benchmark root, preview follows `run_manifest.json.artifacts.{processed_output_run_dir,stage_run_dir}` until it reaches the processed stage run with the real staged outputs
- preview manifests now carry `phase_plans` keyed by stage, with worker count, shard count, owned-ID distributions, and first-turn payload distributions; prompt rows also carry `runtime_shard_id`, `runtime_worker_id`, and `runtime_owned_ids`
- `cf-debug preview-shard-sweep --run ... --experiment-file docs/02-cli/shard_sweep_examples.json --out ...` runs several local worker/shard planning variants and writes one sweep manifest plus per-experiment preview dirs
- preview export now always rebuilds recipe and knowledge shard payloads from the predictive-safe processed artifact itself; it does not depend on saved live payload copies under `raw/llm/<workbook_slug>/recipe_phase_runtime/inputs/` or `raw/llm/<workbook_slug>/nonrecipe_finalize/in/`
- preview export also writes `prompt_preview_budget_summary.json` and `prompt_preview_budget_summary.md`; it is predictive-only, prefers the paired deterministic/`vanilla` processed artifact when a benchmark root has both variants, uses structural prompt/output reconstruction for token estimates, reports stages as unavailable when that structure cannot be reconstructed safely, and hard-refuses Codex-backed or ambiguous processed runs
- when preview rebuilds knowledge planning from older deterministic artifacts, stale recipe-local labels that survived outside recipe spans are treated as preview-only excluded `other` rows so old vanilla runs still produce a forward-looking estimate instead of crashing
- reviewer-facing prompt files stay prompt-level on purpose; the durable cutover is to annotate them with runtime ownership metadata (`runtime_shard_id`, `runtime_worker_id`, `runtime_owned_ids`), not to invent a second legacy export family just for shard workers
- when you want “how many Codex jobs actually ran?” on classic shard runtime, prefer stage `call_count` in `prompt_budget_summary.json` or `prompts/prompt_log_summary.json.runtime_shard_count`; raw `full_prompt_log_rows` may be higher because one shard output can expand into several per-item rows
- preview defaults to the shard-v1 surfaces unless explicitly overridden, so it can project post-refactor worker/shard budgets over saved deterministic-only benchmark outputs too
- preview reconstruction is local-only and composed from three seams:
  - recipe prompt inputs from CodexFarm job builders in `codex_farm_orchestrator`
  - knowledge prompt inputs from `codex_farm_knowledge_jobs`, which now plans shard-owned compact payloads for both live non-recipe finalize and preview reconstruction
  - line-role prompt text from `build_canonical_line_role_file_prompt(...)` plus the shared contract file `llm_pipelines/prompts/line-role.shared-contract.v1.md`
- knowledge preview now follows the live packet contract exactly: prompt counts come from the same packet planner as the live runtime, so preview honors the configured knowledge shard cap instead of silently expanding above it
- preview uses the same category-neutral candidate queue as the live knowledge runtime; excluded spans must not silently widen the preview work set
- the current default knowledge context is `0` blocks on each side, and that default is shared across stage, benchmark, CLI, and prompt-preview paths
- `build_knowledge_jobs(...)` now sizes ordered candidate packets from the candidate block queue and keeps one task per packet. When `knowledge_prompt_target_count` is set, it is a hard cap on final shard count; packet budgets still inform metadata and warnings, and knowledge worker count still controls concurrency separately from shard planning.
- line-role preview must batch the full ordered candidate set into the same file-backed shard payload used by the live runtime; preview-only unresolved shortlists are a stale contract and will understate line-role prompt volume.
- line-role prompt reconstruction no longer injects grouped recipe spans or importer provenance. The pre-grouping contract is now span-free: prompt text explicitly says no prior recipe-span authority is provided, and candidate rows default to `within_recipe_span=None` until grouped labels are projected later.
- the active line-role wrapper teaches `HOWTO_SECTION` as a book-optional, recipe-internal subsection label only (`FOR THE SAUCE`, `TO FINISH`, `FOR SERVING`), and the static prompt text explicitly fences chapter/topic/cookbook-lesson headings back to `KNOWLEDGE` or `OTHER`
- the active line-role wrapper also teaches `INSTRUCTION_LINE` as recipe-local procedure only and explicitly fences cookbook advice / explanatory prose with action verbs back to `KNOWLEDGE` or `OTHER` unless shard-local component structure makes the instruction ownership real
- line-role watchdog-retry prompts restate the authoritative shard rows inline and tell the model to recompute labels from those rows instead of copying a one-row JSON example or prior invalid output
- line-role shard validation is still structurally strict, and the semantic guard now applies directly to workspace-ledger harvest plus watchdog retry: if an edited shard collapses a diverse shard into pathological uniform or near-uniform labels, the shard stays invalid and the stage fails closed instead of silently promoting nonsense or borrowing deterministic baseline labels
- line-role row transport is now split cleanly by seam: the inline compact prompt uses pipe-delimited target rows plus selective `ctx:` windows, the file-backed billed shard JSON is the tuple-based `v=1` transport, and a parallel debug copy keeps the richer local object rows
- prompt/actual cost reporting for the direct phases now also carries a shared cost-breakdown vocabulary: `visible_input_tokens`, `cached_input_tokens`, `visible_output_tokens`, and `wrapper_overhead_tokens`
- live line-role execution no longer needs one fresh Codex session per shard in the common multi-shard case; it now plans contiguous shards, groups them by worker assignment, lets one `taskfile` Codex session process several local shard files, validates exact owned-row coverage per harvested output file, and promotes accepted rows into the existing `label_refine` outputs.
- prompt preview does not reconstruct a separate tags surface; inline recipe tags ride on the recipe contract and are projected into outputs after correction/normalization, so tagging changes do not add prompt input tokens unless the recipe prompt itself changes
- preview-only runs may not have `var/run_assets/<run_id>/`; in that case prompt reconstruction falls back to pipeline metadata in `llm_pipelines/`
- preview reconstruction is intentionally preview-only. Do not add a fake execution path into the live orchestrators just to make prompt previews work.
- prompt artifacts are stage-named now (`stage_key`, `stage_label`, `stage_artifact_stem`) and emit stage-named files such as `prompt_nonrecipe_finalize.txt`
- active knowledge-stage follow-up/debug surfaces should use semantic `knowledge` selectors and audit names. Older numbered stage labels belong only to archived local readers.

Run-level observability note:
- `stage_observability.json` at the run root is the canonical stage index. The recipe and knowledge manifests above are stage-local detail, not a second naming system.
- relevant workbook entries inside `stage_observability.json` now also carry `attention_summary`, mirroring the compact stage summaries so reviewers can scan rejection/fallback/failure counts in one run-level file before drilling into stage-local artifacts.

Shard-runtime observability note:
- `phase_worker_runtime.py` standardizes `phase_manifest.json`, `shard_manifest.jsonl`, `worker_assignments.json`, `promotion_report.json`, `telemetry.json`, `failures.json`, per-worker status files, and per-shard proposals as the runtime-artifact family the active recipe, knowledge, and line-role phases now populate with real work
- those active shard runtimes now also launch worker assignments concurrently up to the resolved worker count instead of looping through assigned workers one at a time; recipe still runs one classic CodexFarm process per worker assignment, while knowledge and line-role direct runtimes use one direct `codex exec` `taskfile` session per worker assignment and let that session work through its assigned shard files locally

## Runner and contract notes

- `SubprocessCodexFarmRunner` validates configured pipeline IDs via `codex-farm pipelines list --root ... --json`.
- `SubprocessCodexFarmRunner` now forces RecipeImport-owned CodexFarm subprocesses onto `~/.codex-recipe` by default by injecting `CODEX_HOME` plus `CODEX_FARM_CODEX_HOME_RECIPE` at the transport layer; explicit subprocess env overrides still win.
- `SubprocessCodexFarmRunner` now maps RecipeImport benchmark mode to CodexFarm's `--recipeimport-benchmark-mode line_label_v1`; ordinary `extract` mode sends no benchmark-only process flag.
- For zero-token handoff rehearsal, point `--codex-farm-cmd` at `scripts/fake-codex-farm.py` and still run execute mode with `--allow-codex`; RecipeImport will exercise the real shard-runtime folders through the subprocess runner without live model calls.
- shard-v1 recipe workers still explicitly run `codex-farm process --runtime-mode classic_task_farm_v1 --workers 1`; knowledge and line-role now use the direct `codex exec` `taskfile` transport instead of classic `process`, with one live worker session per worker assignment rather than one fresh model session per shard
- when `recipe_worker_count`, `knowledge_worker_count`, or `line_role_worker_count` are unset, shard-v1 now defaults live and preview worker planning to the planned shard/job count for that one book+phase, capped at `20`
- the old misleading state was “planned N workers, launched one assignment loop”; current shard-v1 runtime behavior is “planned N workers, launch up to N worker assignments concurrently” with shard count still acting as the true upper bound
- RecipeImport no longer labels shard-v1 work as `structured_loop_agentic_v1`; recipe still keeps the classic per-assignment process path intentionally, while knowledge and line-role already use live multi-shard workspace-session reuse on their direct worker paths
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
- Knowledge pack is `recipe.knowledge.packet.v1`
- Canonical line-role has one shared prompt contract plus thin worker/file wrappers.
- Shared line-role Codex batching now assumes the larger compact-shape default (`240`) rather than the older small-batch preview shape.

Structured output contract:

- Codex schemas must stay inside the OpenAI strict subset.
- Top-level properties must also appear in `required`.
- Nullable fields must still be present and use `null` when empty.
- `ingredient_step_mapping` is on-wire as an array of mapping-entry objects and is normalized back to the internal dict form after validation.

## Related docs

- `docs/10-llm/10-llm_log.md`

## Recent Durable Notes

- In single-book benchmark runs, missing benchmark-level `prompts/` exports does not by itself mean CodexFarm did not run. The lower-level truth is the linked processed stage run under `data/output`, where raw recipe/knowledge inputs, outputs, and `.codex-farm-traces` live.
- After shard-v1 cutover, active run-setting surfaces are already strict about pipeline ids. If legacy behavior still shows up, it is more likely to be a reader/fixture/tooling seam than the live recipe, knowledge, or line-role execution path.
- `prompt_budget_summary.json` must aggregate CodexFarm split tokens from both nested `process_payload.telemetry.rows` and the benchmark single-book top-level `stage_payload.telemetry.rows` layout. Otherwise `tokens_input`, `tokens_cached_input`, and `tokens_output` can drop to null while per-call telemetry still exists.
- `prompt_budget_summary.json` must also prefer one knowledge telemetry layer when aggregate direct-exec payloads duplicate the same stage totals at both the top level and nested worker/runtime levels. Double-counting that stack makes the knowledge stage look more expensive than it was.
- The intended operator shape is still surface-level prompt counts such as `3 / 3 / 3` or `5 / 5 / 5`: one planned shard should correspond closely to one real model call for that surface. Preview and live runtime should be judged against that mental model, not against hidden transport/session turns.
- Line-role transport cost should now be nearly all task prompt, not wrapper overhead. If wrapper chars spike again, inspect raw-prompt transport and compact row serialization before touching the response schema or preview math.
- Current line-role runtime truth is one file-backed `line_role` phase under `line-role-pipeline/runtime/line_role/`. The abandoned inline path and the brief `recipe_region_gate` / `recipe_structure_label` split are historical only; new docs and prompt exports should describe the single file-backed phase plus its immutable line table, shard-owned row ledger, and worker `in/*.json` payloads.
- Recipe worker cost regressions are usually readback regressions now, not watchdog regressions. If recipe token spend spikes again, inspect whether workers have slipped back into raw task-file rereads, auxiliary file exploration, or wider-than-needed workspace exploration before changing retry policy or prompt wording.
- Knowledge regressions now split cleanly into two seams:
  - assignment-first shard coverage
  - bounded structured repair after validation
  If a worker stops after writing only part of its declared shard outputs, treat that as a failed assignment session rather than reintroducing a worker-owned queue control file.
- Main `taskfile` false kills should now be debugged as explicit forbidden-executable or liveness problems. Absolute paths, heredocs, slash-heavy helper payloads, `jq //`, and read-only `git` inspection are telemetry on the main worker path, not kill reasons.
- File-backed line-role observability has to describe both pieces of the request honestly:
  - the visible wrapper prompt
  - the model-facing task file recorded as `request_input_file`
  `prompt_input_mode=path` is the durable vocabulary for that split.
- Regenerated prompt preview on an old benchmark root is forward-looking, not retrospective truth. Use a fresh preview to answer "what would this cost now?", and use finished-run `prompt_budget_summary.json` / `cf-debug actual-costs` to answer "what did that old run actually cost?".
- Large preview-vs-live gaps on current direct-exec runs are usually transport/runtime accounting issues such as cached-input replay, file reads, or larger real outputs than the structural estimate, not evidence that Codex secretly took extra turns or wandered the repo.
- Recipe stage readers should not treat `recipe_correction/{in,out}` as runtime truth. Current readers and debug helpers should start from `recipe_phase_runtime/inputs/*.json`, `recipe_phase_runtime/proposals/*.json`, and `recipe_correction_audit/*.json`.
- The numbered-stage wording cleanup was a label/reporting pass, not a new runtime. The durable knowledge contract is still:
  - deterministic `nonrecipe-route` review routing
  - deterministic non-recipe routing plus packet planning before review
  - immutable `knowledge/in/*.json` inputs
  - validated `knowledge/proposals/*.json` outputs
  - deterministic promotion into explicit final authority plus reviewer snippets
  Operator-facing clarity now comes from using `non-recipe finalize` wording and from richer `knowledge_manifest.json.review_summary` counts/paths.
- RecipeImport-owned CodexFarm subprocesses should inherit `~/.codex-recipe` from `cookimport/llm/codex_farm_runner.py`, not from ad hoc shell aliases or per-command CLI glue. If the wrong Codex home is in use, debug the runner env injection first.
- `gpt-5.3-codex-spark` plus reasoning effort does not guarantee reasoning-summary events in saved `.trace.json` files. A zero `reasoning_event_count` can be a legitimate upstream Codex CLI event-stream outcome, not an exporter bug.
- Current line-role transport is intentionally split three ways:
  - compact billed shard payload at `line-role-pipeline/runtime/line_role/workers/*/in/*.json`
  - richer local debug copy at `.../debug/*.json`
  - short wrapper prompt that points at `request_input_file`
  The billed payload is now raw-text-first: owned rows are `[atomic_index, current_line]` plus optional `context_before_rows` / `context_after_rows`, while the debug copy stays repo-owned.
- line-role main taskfile workers now use the same rare-kill watchdog contract as the other workspace stages, and the active control surface is now the same task-file-first contract: start from `task.json`. Bounded local orientation and helper shell use inside the worker root are telemetry, not kill reasons, unless they turn into a real boundary violation or a pathological no-progress loop.
- line-role work ledgers are now scaffolds, not answer seeds. `work/<shard_id>.json` starts as owned `atomic_index` rows only, the worker fills labels directly from raw text/context, and repo runtime validates ownership/completeness/field shape without comparing accepted labels to deterministic baseline labels.
- line-role prompt guidance now explicitly treats variant runs as local context, not sticky state: a fresh title-like line followed by a strict yield line or ingredients should reset to `RECIPE_TITLE`, and strict yield headers in that pattern should stay `YIELD_LINE` rather than drifting into `RECIPE_NOTES`.
- the checked-in line-role prompt examples now pin that reset with a failure-shaped sequence: `Bright Cabbage Slaw` -> `Serves 4 generously` -> `1/2 medium red onion, sliced thinly` must break out of the nearby `Variations` prose instead of extending `RECIPE_VARIANT`.
- `AtomicLineCandidate` is no longer a neighbor-carrying cache object. Neighbor context for line-role prompt text now comes from explicit ordered-candidate lookup helpers, so adjacency-sensitive prompt changes belong in the prompt builder / lookup seam rather than by re-expanding parser records.
- line-role now has one semantic prompt source at `llm_pipelines/prompts/line-role.shared-contract.v1.md`; the inline prompt, file-backed prompt, and `taskfile` prompt are transport wrappers around that shared contract and should not restate label semantics independently.
- Knowledge direct prompts must describe the real task-file contract. The live knowledge worker opens `task.json`, edits owned answer fields in place, and lets deterministic code expand the final shard outputs; it is no longer a leased-packet inline JSON surface.
- Live knowledge payloads are intentionally compact and skeptical. They use short aliases, omit semantic hinting, and expose only nonrecipe-owned packet blocks plus mechanically true nonrecipe context and guardrails.
- The live recipe shard contract is similarly compact: minified shard JSON, compact helper hints, compact tag-guide payload, and a first-class candidate-quality/triage seam rather than a schema-shaped metadata dump.
- Recipe correction now has an explicit bad-candidate escape hatch. Shard proposals can return `fragmentary` or `not_a_recipe` with compact reasons, and deterministic promotion only emits final recipes for `repaired` results while preserving rejected candidates in proposals/audits.
- Knowledge reliability now depends on two separate rules that are easy to conflate:
  - shard-count requests are literal for recipe, knowledge, and line-role
  - knowledge still records warnings when a forced shard count creates oversized or non-local bundles
  If knowledge starts producing giant shards again, inspect the forced-count warnings before retuning prompts.
- Knowledge-stage hardening no longer trusts deterministic semantic gating to decide what the reviewer sees. The live stage removed chunk-level semantic hints from the billed payload, removed the low-signal deterministic prefilter, and now uses bounded repair/re-shard paths when a shard returns near-miss invalid JSON.
- Direct recipe / knowledge / line-role shard workers now run from sterile mirrored workspaces under `~/.codex-recipe/recipeimport-direct-exec-workspaces/`, with shard-scoped `AGENTS.md` files and rewritten local paths. If a worker appears to have repo-wide context again, debug the mirror/workdir seam before changing prompts.
- Same-session knowledge workers no longer require a leased-packet queue controller to finish cleanly. When all expected shard outputs are present and stay stable through the completion-wait window, the watchdog now closes the workspace session even if Codex never emits a final clean-exit signal.
- Pathological spend debugging now starts from repo-owned telemetry, not from rereading raw worker traces. `prompt_budget_summary.json` and worker-local artifacts should surface invalid-output spend, repaired-shard counts, command-executing shards, and other direct-exec pathology flags directly.
