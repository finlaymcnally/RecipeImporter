---
summary: "LLM architecture/build/fix-attempt log used to avoid repeating failed paths."
read_when:
  - When you are going in multi-turn circles on LLM behavior or implementation
  - When the human says "we are going in circles on this"
  - When you need prior architecture versions, builds, or fix attempts before trying another change
---

# LLM Build and Fix Log

Use this file for LLM debugging history that still applies to the current codebase. Retired rollout notes, removed UI paths, and old gating experiments were intentionally pruned.

## 2026-03-15 docs cleanup for current LLM surfaces

Problem captured:
- The section docs had accumulated stale rollout history that no longer matched the live CLI and prediction-run code.

Durable cleanup:
- Removed QualitySuite Codex-permutation notes because `bench quality-run` is deterministic-only now and rejects `--include-codex-farm`.
- Removed recipe-only prediction-run wording; `generate_pred_run_artifacts(...)` now plans or runs recipe Codex, pass4 knowledge, line-role, and prelabel surfaces.
- Removed retired env-gate and old interactive-editor history that no longer explains current behavior.

Anti-loop note:
- If docs and CLI disagree, trust the current command boundary in `cookimport/cli.py` and `cookimport/labelstudio/ingest.py` before preserving more historical wording.

## 2026-03-15 prompt artifact seams and Codex backend map

Problem captured:
- Prompt artifact export was too tightly coupled to the current raw CodexFarm folder layout, and some callers still acted as if the repo had mixed Codex backends.

Durable decisions:
- `prompts/full_prompt_log.jsonl` is the stable downstream prompt artifact.
- Keep discovery and rendering separate in `cookimport/llm/prompt_artifacts.py`:
  - `discover_codexfarm_prompt_run_descriptors(...)`
  - `render_prompt_artifacts_from_descriptors(...)`
  - `build_codex_farm_prompt_response_log(...)`
- All five live Codex-backed surfaces (`recipe`, `line_role`, `knowledge`, `tags`, `prelabel`) run through CodexFarm now.
- `cookimport/llm/codex_exec.py` is fail-closed compatibility only.

Anti-loop note:
- If prompt artifact work requires renderer edits for every new raw layout, the bug is in discovery coupling, not rendering.

## 2026-03-14 merged-repair schema and trace boundary

Problem captured:
- The merged-repair path mixed together three separate failure classes: invalid structured-output schema rules, stale on-wire payload shape, and missing thinking traces that looked like exporter bugs.

Durable decisions:
- Use native nested objects for recipe payload fields on the wire.
- Keep `ingredient_step_mapping` as an array of mapping-entry objects on the wire, then normalize back into the repo's internal dict form.
- Bucket 1 fixed behavior owns pass1 hints, pass pipeline IDs, pass3 skip behavior, and retry attempt count; tests should not expect stale overrides to win.
- Missing thinking traces are usually upstream capture/classification gaps, not a markdown-rendering bug.

Anti-loop note:
- If a merged-repair run fails before useful output, inspect schema validity, fixed-behavior policy, and trace capture before rewriting prompt text.

## 2026-03-14 recipe pipeline versus pass4 knowledge

Problem captured:
- `codex-farm-2stage-repair-v1` made it easy to conflate the recipe sub-pipeline with the whole Codex-backed workflow.

Durable decisions:
- `llm_recipe_pipeline` and `llm_knowledge_pipeline` are separate surfaces.
- Switching between `codex-farm-3pass-v1` and `codex-farm-2stage-repair-v1` changes only the recipe extraction path.
- Pass4 remains its own later stage with the same `pass4_knowledge` artifact tree.

Anti-loop note:
- If a recipe pipeline rename seems to imply pass4 moved or vanished, inspect `llm_knowledge_pipeline` wiring first.

## 2026-03-13 structural audits and new recipe-pipeline seams

Problem captured:
- Structural success/failure checks and prototype pipeline additions were easy to scatter across orchestrator code without updating the rest of the surface area.

Durable decisions:
- Keep shared structural success rules in `cookimport/llm/codex_farm_contracts.py`.
- Feed those rules from named transport/runtime audits rather than ad hoc orchestrator strings.
- Any new `llm_recipe_pipeline` must be wired through:
  - `RunSettings`
  - codex decision/approval logic
  - orchestrator planning/manifests
  - benchmark/debug expectations

Anti-loop note:
- If a new recipe pipeline works only after changing the orchestrator, assume the implementation is incomplete.

## 2026-03-06 safe defaults and human-owned Codex decision boundary

Problem captured:
- Generic CLI/helper flows could still drift into Codex-backed execution without one clear approval layer.

Durable decisions:
- Shared defaults are deterministic and safe/off.
- `cookimport/config/codex_decision.py` is the single decision and metadata layer for live Codex surfaces.
- `labelstudio-import --prelabel` is explicitly classified as its own Codex surface.
- Benchmark, stage, import, and interactive top-tier flows all rely on the same decision metadata contract.

Anti-loop note:
- If a run used Codex "mysteriously," inspect decision metadata before touching prompt or runner code.

## 2026-03-06 plan mode, compact defaults, and pass4 benchmark enablement

Problem captured:
- Plan mode was initially too shallow to be useful, compact defaults were controlled in too many places, and benchmark prediction generation had dropped pass4 settings.

Durable decisions:
- `--codex-execution-policy plan` runs deterministic prep first, then writes `codex_execution_plan.json` before stopping.
- Compact defaults must stay aligned across:
  - `cookimport/config/run_settings.py`
  - CLI defaults in `cookimport/cli.py`
  - canonical line-role prompt-format resolution
- Benchmark prediction generation now forwards pass4 settings into shared `RunSettings`.
- `knowledge/<workbook_slug>/block_classifications.jsonl` is the primary outside-span contract; `snippets.jsonl` remains compatibility/reviewer evidence.

Anti-loop note:
- If compact prompts or pass4 behavior look half-enabled, check control-surface alignment and shared `RunSettings` wiring before editing prompts.

## 2026-03-03 runner reliability and prompt provenance hardening

Problem captured:
- CodexFarm failures and prompt-debug artifacts were noisy, brittle, or easy to misread.

Durable decisions:
- Progress callbacks use `codex-farm process --progress-events --json` when supported, with a retry without that flag for older binaries.
- `prompts/full_prompt_log.jsonl` is the source-of-truth prompt artifact; sampled text files are convenience views only.
- `no last agent message` / `nonzero_exit_no_payload` failures are recoverable partial-output cases.
- Recipe pass extraction falls back to `full_text.lines` when cached payloads are missing `full_text.blocks`.

Anti-loop note:
- Empty pass output with populated input is often a CodexFarm precheck/auth/quota problem first, not a prompt problem.

## 2026-02-28 subprocess schema, connection, and telemetry boundary

Problem captured:
- Caller-side CodexFarm integration had drifted around model discovery, pipeline validation, schema enforcement, and process metadata capture.

Durable decisions:
- Interactive model discovery uses `codex-farm models list --json`.
- Subprocess-backed recipe/pass4/pass5 flows validate pipeline IDs up front with `codex-farm pipelines list --root <pack> --json`.
- Runner resolves each pipeline's `output_schema_path` and passes it as `--output-schema`.
- When `process --json` returns a `run_id`, runner can enrich failures with `codex-farm run errors --run-id ... --json`.
- Pass metadata persists `telemetry_report`, `autotune_report`, and compact CSV `telemetry` slices.
- Telemetry/autotune ingestion is non-fatal and stays centralized in the runner.

Anti-loop note:
- Do not duplicate pipeline/schema/telemetry logic in each orchestrator; keep it centralized in `cookimport/llm/codex_farm_runner.py`.

## 2026-02-25 pass4 and pass5 artifact boundaries

Problem captured:
- Missing pass4/pass5 artifacts were often misdiagnosed as prompt-quality problems instead of wiring regressions.

Durable decisions:
- Keep pass4 table hints aligned across single-file, split-merge, and processed-output paths.
- When pass4 is off, deterministic knowledge-lane chunk mapping still backfills stage knowledge labels.
- Pass5 writes:
  - `tags/<workbook_slug>/r{index}.tags.json`
  - `tags/<workbook_slug>/tagging_report.json`
  - `tags/tags_index.json`
- Raw pass5 CodexFarm IO stays under `raw/llm/<workbook_slug>/pass5_tags/`.
- `codex_farm_failure_mode` controls pass5 hard-stop versus warn-and-continue behavior.

Anti-loop note:
- If `KNOWLEDGE=0` appears with pass4 off, or `tags/` is missing after stage, debug wiring and run settings before changing prompt assets.
