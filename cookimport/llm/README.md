# cookimport/llm

Optional LLM integration lives here.

Start points:
- `phase_worker_runtime.py` is the shared shard/worker runtime foundation.
- `codex_exec_runner.py` is the shared direct `codex exec` subprocess seam.
- `codex_farm_runner.py` is the `codex-farm process` runner seam.
- `prompt_preview.py`, `prompt_artifacts.py`, and `prompt_budget.py` own prompt/cost inspection surfaces.

Active worker surfaces:
- Recipe is packet-first on the happy path. Worker roots expose `worker_manifest.json`, `assigned_shards.json`, `current_packet.json`, `current_hint.md`, `current_result_path.txt`, `packet_lease_status.json`, authoritative `in/*.json`, and harvested `out/*.json`. The live recipe path does not use `assigned_tasks.json`, `SHARD_PACKET.md`, current-task sidecars, `scratch/`, or helper install/check loops.
- Canonical line-role is still shard-ledger-first. Worker roots expose `CURRENT_PHASE*`, `assigned_shards.json`, authoritative `in/*.json`, editable `work/*.json`, optional `repair/*.json`, harvested `out/*.json`, and `tools/line_role_worker.py`.
- Knowledge is packet-first like recipe, but packet kinds are two-pass shard-local review packets. Worker roots expose `worker_manifest.json`, `assigned_shards.json` for context, `current_packet.json`, `current_hint.md`, `current_result_path.txt`, `packet_lease_status.json`, authoritative `in/*.json`, fallback `OUTPUT_CONTRACT.md` plus `examples/`, and harvested `out/*.json`.

Current ownership split:
- Repo code owns shard planning, packet leasing, exact ownership validation, proposal assembly, promotion, and telemetry.
- The model owns the fuzzy semantic calls inside the leased packet contract.
- File-backed validated `out/*.json` is authoritative on the workspace-worker path; final prose messages are telemetry only.

Runtime notes:
- Workspace-worker sessions run from a sterile mirrored workspace under `~/.codex-recipe/...` with a repo-written `AGENTS.md` and `worker_manifest.json`; the repo artifact root stays authoritative.
- Watchdog policy is transport-specific. Structured retry/repair calls still fail closed on shell drift, while main workspace-worker attempts allow bounded local shell use and only kill for real boundary violations or no-progress loops.
- `scripts/fake-codex-farm.py` mirrors the live direct-exec contract closely enough for zero-token tests; knowledge fake exec now synthesizes leased packet outputs rather than driving a helper-owned phase loop.

Owner packages:
- Recipe: `recipe_stage/` plus `recipe_stage_shared.py` during the owner split.
- Knowledge: `knowledge_stage/`.
- Line-role: `parsing/canonical_line_roles/`.

Read `docs/10-llm/10-llm_README.md` for the full current contract surface.
