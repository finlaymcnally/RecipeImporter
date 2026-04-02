# cookimport/llm

Optional LLM integration lives here.

Start points:
- `phase_worker_runtime.py` is the shared shard/worker runtime foundation.
- `codex_exec_runner.py` is the shared direct `codex exec` subprocess seam.
- `codex_farm_runner.py` is the `codex-farm process` runner seam.
- `prompt_preview.py`, `prompt_artifacts.py`, and `prompt_budget.py` own prompt/cost inspection surfaces.

Active worker surfaces:
- Recipe, canonical line-role, and knowledge all use assignment-first taskfile workers, but the happy path now differs by stage. Recipe refine still uses the richer helper-driven surface inside `task.json`. Canonical line-role plus knowledge classification/grouping are direct-batch: open `task.json` directly, read the full assignment, edit only `/units/*/answer`, run `task-handoff`, and keep any repair/grouping follow-up in the same workspace session.
- Knowledge now uses that direct-batch contract twice when needed: first a block-local classification file with immutable ontology context, then one or more bounded grouping-only files built only from accepted knowledge rows.
- The source worker roots still keep repo-owned `worker_manifest.json`, `prompt.txt`, `in/*.json`, `out/*.json`, `debug/`, and repair/status files for validation and debugging, but those are no longer the model-visible startup surface.

Current ownership split:
- Repo code owns shard planning, immutable assignment files, exact ownership validation, proposal assembly, bounded repair, promotion, and telemetry.
- The model owns the fuzzy semantic calls inside the assignment contract.
- File-backed validated `out/*.json` is authoritative on the `taskfile` path; final prose messages are telemetry only.
- For knowledge classification specifically, repo code owns the checked-in tag catalog and validates catalog membership, but the model still decides whether a block is retrieval-grade enough to keep.

Runtime notes:
- Workspace-worker sessions run from a sterile mirrored workspace under `~/.codex-recipe/...` with a repo-written `AGENTS.md` plus one visible `task.json`; the repo artifact root stays authoritative for manifests, debug files, and promoted outputs.
- Worker-visible `task.json` is no longer one-size-fits-all. Recipe refine still carries helper metadata and helper-oriented affordances, while canonical line-role plus knowledge write slimmer, multiline direct-batch task files that treat the file itself as the primary review surface.
- Repo-owned guardrails now travel with that runtime: per-worker `status.json`, stage `telemetry.json`, phase manifests, stage summaries, and prompt-budget summaries all record planned happy-path worker-session caps separately from repair/follow-up work plus deterministic `task.json` size metadata.
- Watchdog policy is contract-specific. `packet` retry/repair calls still fail closed on shell drift, while main `taskfile` attempts are warning-first and only auto-terminate for real boundary violations.
- `taskfile_progress.py` is the shared operator-summary helper: it reads repo-owned `live_status.json`, derives compact attention labels plus `last_activity_at`, and lets recipe/knowledge/line-role progress callbacks surface stuck or suspicious workers without giving deterministic code semantic authority over model answers. Its missing-output label is conservative on purpose: transient in-flight `has_final_agent_message` snapshots should not be treated as terminal by themselves.
- Completion timing is now one shared runtime policy surface: `workspace_completion_quiescence_seconds` and `completed_termination_grace_seconds` default to 15 seconds and are threaded through stage, benchmark, Label Studio import/prediction, and direct-exec runtime paths from canonical run settings.
- `scripts/fake-codex-farm.py` mirrors the live direct-exec contract closely enough for zero-token tests; fake direct-exec workers now synthesize assignment-owned outputs rather than queue or phase control loops.
- Knowledge grounding now rides through the normal runtime artifacts: kept blocks emit only `category` plus `grounding`, under-grounded `knowledge` rows are demoted to `other` instead of forcing tag-invention repair, `knowledge_manifest.json` plus `knowledge_stage_summary.json` expose existing-tag versus proposed-tag counts and grounding-gate demotions, and the stage writes `knowledge_tag_proposals.jsonl` when the model needs a new tag under an existing category.

Owner packages:
- Recipe: `recipe_stage/` plus `recipe_stage_shared.py` during the owner split.
- Knowledge: `knowledge_stage/`.
- Line-role: `parsing/canonical_line_roles/`.

Read `docs/10-llm/10-llm_README.md` for the full current contract surface.
