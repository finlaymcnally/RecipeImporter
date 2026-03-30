# cookimport/llm

Optional LLM integration lives here.

Start points:
- `phase_worker_runtime.py` is the shared shard/worker runtime foundation.
- `codex_exec_runner.py` is the shared direct `codex exec` subprocess seam.
- `codex_farm_runner.py` is the `codex-farm process` runner seam.
- `prompt_preview.py`, `prompt_artifacts.py`, and `prompt_budget.py` own prompt/cost inspection surfaces.

Active worker surfaces:
- Recipe is assignment-first on the happy path. Worker roots expose `worker_manifest.json`, `assigned_tasks.json`, authoritative `in/*.json`, optional `hints/*.md`, harvested `out/*.json`, and shard-local repair artifacts only when validation rejects a task output.
- Canonical line-role is assignment-first too. Worker roots expose `worker_manifest.json`, `assigned_shards.json`, authoritative `in/*.json`, optional `hints/*.md`, `debug/*.json`, harvested `out/*.json`, and fallback `OUTPUT_CONTRACT.md`.
- Knowledge is assignment-first like line-role. Worker roots expose `worker_manifest.json`, `assigned_shards.json`, authoritative `in/*.json`, optional `hints/*.md`, harvested `out/*.json`, worker-local `scratch/`, and fallback `OUTPUT_CONTRACT.md` plus `examples/`.

Current ownership split:
- Repo code owns shard planning, immutable assignment files, exact ownership validation, proposal assembly, bounded repair, promotion, and telemetry.
- The model owns the fuzzy semantic calls inside the assignment contract.
- File-backed validated `out/*.json` is authoritative on the workspace-worker path; final prose messages are telemetry only.

Runtime notes:
- Workspace-worker sessions run from a sterile mirrored workspace under `~/.codex-recipe/...` with a repo-written `AGENTS.md` and `worker_manifest.json`; the repo artifact root stays authoritative.
- Watchdog policy is transport-specific. Structured retry/repair calls still fail closed on shell drift, while main workspace-worker attempts allow bounded local shell use and only kill for real boundary violations or no-progress loops.
- `scripts/fake-codex-farm.py` mirrors the live direct-exec contract closely enough for zero-token tests; fake direct-exec workers now synthesize assignment-owned outputs rather than queue or phase control loops.

Owner packages:
- Recipe: `recipe_stage/` plus `recipe_stage_shared.py` during the owner split.
- Knowledge: `knowledge_stage/`.
- Line-role: `parsing/canonical_line_roles/`.

Read `docs/10-llm/10-llm_README.md` for the full current contract surface.
