# cookimport/llm

Optional LLM integration lives here.

Start points:
- `phase_worker_runtime.py` is the shared shard/worker runtime foundation.
- `codex_exec_runner.py` is the shared direct `codex exec` subprocess seam.
- `codex_farm_runner.py` is the `codex-farm process` runner seam.
- `prompt_preview.py`, `prompt_artifacts.py`, and `prompt_budget.py` own prompt/cost inspection surfaces.

Active worker surfaces:
- Recipe, canonical line-role, and knowledge all use the same happy path now: the worker-visible sterile workspace contains one repo-written `task.json`, the worker should start with `python3 -m cookimport.llm.editable_task_file --summary` plus narrow `--show-unit` or `--show-unanswered` reads instead of dumping the whole file, that summary now samples large unit-id lists instead of echoing every unanswered unit, the worker edits only `/units/*/answer`, and repo code expands accepted answers into the stage artifacts.
- Knowledge now uses that happy path twice when needed: first a block-local classification file with immutable ontology context, then one or more bounded grouping-only files built only from accepted knowledge rows.
- The source worker roots still keep repo-owned `worker_manifest.json`, `prompt.txt`, `in/*.json`, `out/*.json`, `debug/`, and repair/status files for validation and debugging, but those are no longer the model-visible startup surface.

Current ownership split:
- Repo code owns shard planning, immutable assignment files, exact ownership validation, proposal assembly, bounded repair, promotion, and telemetry.
- The model owns the fuzzy semantic calls inside the assignment contract.
- File-backed validated `out/*.json` is authoritative on the workspace-worker path; final prose messages are telemetry only.
- For knowledge classification specifically, repo code owns the checked-in tag catalog and validates catalog membership, but the model still decides whether a block is retrieval-grade enough to keep.

Runtime notes:
- Workspace-worker sessions run from a sterile mirrored workspace under `~/.codex-recipe/...` with a repo-written `AGENTS.md` plus one visible `task.json`; the repo artifact root stays authoritative for manifests, debug files, and promoted outputs.
- Repo-owned guardrails now travel with that runtime: per-worker `status.json`, stage `telemetry.json`, phase manifests, stage summaries, and prompt-budget summaries all record planned happy-path worker-session caps separately from repair/follow-up work plus deterministic `task.json` size metadata.
- Watchdog policy is transport-specific. Structured retry/repair calls still fail closed on shell drift, while main workspace-worker attempts are warning-first and only auto-terminate for real boundary violations.
- `workspace_worker_progress.py` is the shared operator-summary helper: it reads repo-owned `live_status.json`, derives compact attention labels plus `last_activity_at`, and lets recipe/knowledge/line-role progress callbacks surface stuck or suspicious workers without giving deterministic code semantic authority over model answers. Its missing-output label is conservative on purpose: transient in-flight `has_final_agent_message` snapshots should not be treated as terminal by themselves.
- `scripts/fake-codex-farm.py` mirrors the live direct-exec contract closely enough for zero-token tests; fake direct-exec workers now synthesize assignment-owned outputs rather than queue or phase control loops.
- Knowledge grounding now rides through the normal runtime artifacts: kept blocks must emit `retrieval_concept` plus `grounding`, `knowledge_manifest.json` and `knowledge_stage_summary.json` expose existing-tag versus proposed-tag counts, and the stage writes `knowledge_tag_proposals.jsonl` when the model needs a new tag under an existing category.

Owner packages:
- Recipe: `recipe_stage/` plus `recipe_stage_shared.py` during the owner split.
- Knowledge: `knowledge_stage/`.
- Line-role: `parsing/canonical_line_roles/`.

Read `docs/10-llm/10-llm_README.md` for the full current contract surface.
