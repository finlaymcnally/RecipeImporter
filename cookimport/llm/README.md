# cookimport/llm

Optional LLM integration lives here.

Start points:
- `phase_worker_runtime.py` is the shared shard/worker runtime foundation.
- `codex_exec_runner.py` is the shared direct `codex exec` subprocess seam.
- `codex_farm_runner.py` is the `codex-farm process` runner seam.
- `prompt_preview.py`, `prompt_artifacts.py`, and `prompt_budget.py` own prompt/cost inspection surfaces.

Active worker surfaces:
- Recipe, canonical line-role, and knowledge all use the same happy path now: the worker-visible sterile workspace contains one repo-written `task.json`, the worker edits only `/units/*/answer`, and repo code expands accepted answers into the stage artifacts.
- Knowledge now uses that happy path twice when needed: first a block-local classification file, then a grouping-only file built only from accepted knowledge rows.
- The source worker roots still keep repo-owned `worker_manifest.json`, `prompt.txt`, `in/*.json`, `out/*.json`, `debug/`, and repair/status files for validation and debugging, but those are no longer the model-visible startup surface.

Current ownership split:
- Repo code owns shard planning, immutable assignment files, exact ownership validation, proposal assembly, bounded repair, promotion, and telemetry.
- The model owns the fuzzy semantic calls inside the assignment contract.
- File-backed validated `out/*.json` is authoritative on the workspace-worker path; final prose messages are telemetry only.

Runtime notes:
- Workspace-worker sessions run from a sterile mirrored workspace under `~/.codex-recipe/...` with a repo-written `AGENTS.md` plus one visible `task.json`; the repo artifact root stays authoritative for manifests, debug files, and promoted outputs.
- Repo-owned guardrails now travel with that runtime: per-worker `status.json`, stage `telemetry.json`, phase manifests, stage summaries, and prompt-budget summaries all record planned happy-path worker-session caps separately from repair/follow-up work plus deterministic `task.json` size metadata.
- Watchdog policy is transport-specific. Structured retry/repair calls still fail closed on shell drift, while main workspace-worker attempts are warning-first and only auto-terminate for real boundary violations.
- `scripts/fake-codex-farm.py` mirrors the live direct-exec contract closely enough for zero-token tests; fake direct-exec workers now synthesize assignment-owned outputs rather than queue or phase control loops.

Owner packages:
- Recipe: `recipe_stage/` plus `recipe_stage_shared.py` during the owner split.
- Knowledge: `knowledge_stage/`.
- Line-role: `parsing/canonical_line_roles/`.

Read `docs/10-llm/10-llm_README.md` for the full current contract surface.
