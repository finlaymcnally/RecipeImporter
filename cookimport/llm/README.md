# cookimport/llm

Optional LLM integration lives here.

Start points:
- `phase_worker_runtime.py` is the shared shard/worker runtime foundation.
- `codex_exec_runner.py` is the shared direct `codex exec` subprocess seam.
  - `codex_exec_types.py` now owns the shared direct-exec protocol/live-snapshot/watchdog contract dataclasses that `codex_exec_runner.py` re-exports.
  - `codex_exec_workspace.py` owns direct-exec workspace preparation and mirror-manifest shaping. It now resolves the small runner-owned hook surface explicitly instead of inheriting the runner namespace wholesale.
  - `codex_exec_telemetry.py` owns direct-exec event parsing, token-usage/status summarization, live-activity/watchdog summaries, and final-message assessment.
  - `codex_exec_taskfile_policy.py` owns taskfile/single-file workspace command parsing plus boundary/drift policy classification; `codex_exec_runner.py` re-exports the current policy helpers and limits.
  - `codex_exec_command_builder.py` owns `codex exec` argv construction plus Linux taskfile fs-cage command assembly; `codex_exec_runner.py` keeps thin wrappers so the current monkeypatch/import surface stays stable.
- `codex_farm_runner.py` is the `codex-farm process` runner seam.
- `taskfile_prompt_contract.py` owns the shared section renderer used by the surviving taskfile worker prompts so recipe, knowledge, and line-role stay on one prompt skeleton while keeping stage-local semantics.
- `prompt_preview.py`, `prompt_artifacts.py`, and `prompt_budget.py` own prompt/cost inspection surfaces.
  - `prompt_artifacts.py` is now a thin public facade over `prompt_artifacts_discovery.py`, `prompt_artifacts_loader.py`, and `prompt_artifacts_activity.py`.
  - `full_prompt_log.jsonl` is supposed to be actual-call truth; structured-session packet turns are exported as separate rows instead of being collapsed to one shard row, and reconstructed fallback rows do not count when a runtime shard has no real call evidence.
  - `prompt_budget.py` is now a thin facade over `prompt_budget_runtime.py` and `prompt_budget_preview.py`.

Active worker surfaces:
- Recipe stays on assignment-first taskfile workers. Canonical line-role plus knowledge now default to the thinner inline-JSON path, while `line_role_codex_exec_style=taskfile-v1` or `knowledge_codex_exec_style=taskfile-v1` still keep the direct-batch editable `task.json` contract for comparison or debugging.
- When line-role or knowledge do use taskfile mode, the happy path is direct-batch: open `task.json` directly, read the full assignment, edit only `/units/*/answer`, run `task-handoff`, and keep any repair/grouping follow-up in the same workspace session.
- Knowledge now uses that direct-batch contract twice when needed: first a block-local classification file with immutable ontology context, then one or more bounded grouping-only files built only from accepted knowledge rows.
- The source worker roots still keep repo-owned `worker_manifest.json`, `prompt.txt`, `in/*.json`, `out/*.json`, `debug/`, and repair/status files for validation and debugging, but those are no longer the model-visible startup surface.

Current ownership split:
- Repo code owns shard planning, immutable assignment files, exact ownership validation, proposal assembly, bounded repair, promotion, and telemetry.
- The model owns the fuzzy semantic calls inside the assignment contract.
- File-backed validated `out/*.json` is authoritative on the `taskfile` path; final prose messages are telemetry only.
- For knowledge classification specifically, repo code owns the checked-in tag catalog and validates catalog membership, but the model still decides whether a block is retrieval-grade enough to keep.

Runtime notes:
- Workspace-worker sessions run from a sterile mirrored workspace under `~/.codex-recipe/...` with a repo-written `AGENTS.md` plus one visible `task.json`; the repo artifact root stays authoritative for manifests, debug files, and promoted outputs.
- `shard_survivability.py` is the deterministic preflight seam for Codex Exec shard sizing. It counts prompt/output tokens, applies conservative stage budgets, writes `shard_survivability_report.json` beside live direct-exec stages, and gives prompt preview plus live runtimes the same minimum-safe shard recommendation.
- Worker-visible `task.json` is no longer one-size-fits-all. Recipe refine still carries helper metadata and helper-oriented affordances, while canonical line-role plus knowledge write slimmer, multiline direct-batch task files that treat the file itself as the primary review surface.
- Repo-owned guardrails now travel with that runtime: per-worker `status.json`, stage `telemetry.json`, phase manifests, stage summaries, and prompt-budget summaries all record planned happy-path worker-session caps separately from repair/follow-up work plus deterministic `task.json` size metadata.
- Watchdog policy is contract-specific. `packet` retry/repair calls still fail closed on shell drift, while main `taskfile` attempts are warning-first and only auto-terminate for real boundary violations.
- `taskfile_progress.py` is the shared operator-summary helper: it reads repo-owned `live_status.json`, derives compact attention labels plus `last_activity_at`, and lets recipe/knowledge/line-role progress callbacks surface stuck or suspicious workers without giving deterministic code semantic authority over model answers. Its missing-output label is conservative on purpose: transient in-flight `has_final_agent_message` snapshots should not be treated as terminal by themselves.
- Completion timing is now one shared runtime policy surface: `workspace_completion_quiescence_seconds` and `completed_termination_grace_seconds` default to 15 seconds and are threaded through stage, benchmark, Label Studio import/prediction, and direct-exec runtime paths from canonical run settings.
- `scripts/fake-codex-farm.py` mirrors the live direct-exec contract closely enough for zero-token tests; fake direct-exec workers now synthesize assignment-owned outputs rather than queue or phase control loops.
- Knowledge grounding now rides through the normal runtime artifacts: kept blocks emit only `category` plus `grounding`, under-grounded `knowledge` rows are demoted to `other` instead of forcing tag-invention repair, `knowledge_manifest.json` plus `knowledge_stage_summary.json` expose existing-tag versus proposed-tag counts and grounding-gate demotions, and the stage writes `knowledge_tag_proposals.jsonl` when the model needs a new tag under an existing category.

Owner packages:
- Recipe: `recipe_stage/` owns the extracted helpers. `recipe_stage_shared.py` is now the shrinking runtime coordinator, with `recipe_stage/task_file_contract.py` owning worker-visible task payload/schema helpers and `recipe_stage/worker_io.py` owning prompt/jsonl/input writing plus local path helpers.
- Knowledge: `knowledge_stage/`.
  - `knowledge_stage/structured_session_contract.py` owns the inline-JSON packet/prompt/answer helpers that were previously embedded in `workspace_run.py`.
  - `knowledge_stage/recovery_status.py` owns task-status tracking, stale-followup finalization, and stage-status writing that were previously embedded in `recovery.py`.
  - `knowledge_stage/runtime.py` and `knowledge_stage/recovery.py` now import their `_shared` and owner-module dependencies explicitly instead of cloning `_shared` into module globals.
- Line-role: `parsing/canonical_line_roles/`.

Change map:
- If you are changing direct `codex exec` behavior, start in `codex_exec_runner.py` and the matching `codex_exec_*` owner module, read `docs/10-llm/10-llm_README.md` first, and run `pytest tests/llm/test_codex_exec_runner.py tests/llm/test_codex_exec_runner_taskfile.py -q`.
- If you are changing shared worker contract timing, progress, or taskfile behavior, check both this folder and `parsing/canonical_line_roles/` because line-role and knowledge now share the same assignment-first runtime family.

Read `docs/10-llm/10-llm_README.md` for the full current contract surface.
