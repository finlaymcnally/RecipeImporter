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
- Removed recipe-only prediction-run wording; `generate_pred_run_artifacts(...)` now plans or runs recipe Codex, knowledge-stage, line-role, and prelabel surfaces.
- Removed retired env-gate and old interactive-editor history that no longer explains current behavior.

Anti-loop note:
- If docs and CLI disagree, trust the current command boundary in `cookimport/cli.py` and `cookimport/labelstudio/ingest.py` before preserving more historical wording.

## 2026-03-16 prompt preview reconstruction and stage-key cutover

Problem captured:
- zero-token prompt preview needed to work on existing benchmark/stage roots even when no live Codex run assets were present
- prompt exports and sampled artifacts were still carrying pass-slot file/row naming in places where the runtime had already moved to semantic stage names
- prompt-budget review was hard to act on without one concrete audit of where the tokens were really going

Durable decisions:
- prompt preview reconstruction composes existing recipe job builders, knowledge job builders, and canonical line-role prompt builders rather than inventing a second preview-only prompt stack
- when `var/run_assets/<run_id>/` is absent, preview reconstruction should fall back to pipeline metadata from `llm_pipelines/`
- `prompt_budget_summary.json` and adjacent prompt-review surfaces should publish semantic `by_stage` / `knowledge` naming, not old slot-group or `fourth-stage` naming
- prompt artifact rows/files should key off semantic stage metadata only:
  - `stage_key`
  - `stage_label`
  - `stage_artifact_stem`
- the deleted all-method per-source scheduler branch was dead test coverage, not a live runtime contract

Evidence worth keeping:
- audited preview run totals came out to about `663k` input tokens on an `~86k` token book
- the first implemented cut bundle brought the same run down to about `461,865` live-like input tokens before the second cut bundle landed
- the lowest-risk savings in that run were:
  - drop recipe `draft_hint` (`~92k`)
  - trim knowledge context blocks to `2` per side (`~121k`)
  - skip noise-lane knowledge prompts (`~25k`)
  - trim line-role neighbor context outside recipe spans (`~27k` or more depending on aggressiveness)

Anti-loop note:
- if prompt preview work starts reintroducing `task1` / `task4` / `task5` names into new artifacts, the regression is in artifact naming, not the underlying prompt builders

## 2026-03-16 prompt-cut shared builder seam

Problem captured:
- it was tempting to implement prompt-volume reductions only in preview rendering, which would make token audits look better without changing live Codex cost

Durable decisions:
- recipe prompt body cuts should land in the shared serializer for `MergedRecipeRepairInput`, not only in `prompt_preview.py`
- knowledge prompt count cuts should land in `build_knowledge_jobs(...)`, because both live harvest and preview reconstruction consume that builder
- if `build_knowledge_jobs(...)` returns no work, `run_codex_farm_knowledge_harvest(...)` must short-circuit before Codex invocation or empty-manifest writing
- the first low-risk cut bundle was intentionally conservative (`knowledge` context width `12 -> 4`, skip only `noise`, keep `draft_hint` optional but omit it when empty); the second bundle then took the next cheap cuts (`4 -> 2`, drop recipe hint provenance, blank outside-recipe line-role neighbors)

Anti-loop note:
- if preview token counts drop but live runs do not, the optimization probably landed in a preview-only seam

## 2026-03-16 prompt preview tags boundary

Problem captured:
- inline tag projection was easy to misinterpret as a fourth previewable prompt family or a hidden token-cost increase

Durable decisions:
- `cf-debug preview-prompts` still reconstructs recipe, knowledge, and line-role prompts only
- embedding accepted tags into final drafts and JSON-LD is output projection work, not a separate prompt builder

Anti-loop note:
- if token accounting changes after a tags edit, prove the recipe prompt changed before blaming the tagging projection

## 2026-03-15 prompt artifact seams and Codex backend map

Problem captured:
- Prompt artifact export was too tightly coupled to the current raw CodexFarm folder layout, and some callers still acted as if the repo had mixed Codex backends.

Durable decisions:
- `prompts/full_prompt_log.jsonl` is the stable downstream prompt artifact.
- Keep discovery and rendering separate in `cookimport/llm/prompt_artifacts.py`:
  - `discover_codexfarm_prompt_run_descriptors(...)`
  - `render_prompt_artifacts_from_descriptors(...)`
  - `build_codex_farm_prompt_response_log(...)`
- The live Codex-backed surfaces are `recipe`, `line_role`, `knowledge`, and `prelabel`; recipe tags are part of the recipe surface rather than a separate Codex lane.
- `cookimport/llm/codex_exec.py` is fail-closed transition only.

Anti-loop note:
- If prompt artifact work requires renderer edits for every new raw layout, the bug is in discovery coupling, not rendering.

## 2026-03-14 merged-repair schema and trace boundary

Problem captured:
- The merged-repair path mixed together three separate failure classes: invalid structured-output schema rules, stale on-wire payload shape, and missing thinking traces that looked like exporter bugs.

Durable decisions:
- Use native nested objects for recipe payload fields on the wire.
- Keep `ingredient_step_mapping` as an array of mapping-entry objects on the wire, then normalize back into the repo's internal dict form.
- Bucket 1 fixed behavior owns first-stage hints, pass pipeline IDs, third-stage skip behavior, and retry attempt count; tests should not expect stale overrides to win.
- Missing thinking traces are usually upstream capture/classification gaps, not a markdown-rendering bug.

Anti-loop note:
- If a merged-repair run fails before useful output, inspect schema validity, fixed-behavior policy, and trace capture before rewriting prompt text.

## 2026-03-14 recipe pipeline versus knowledge-stage

Problem captured:
- `codex-farm-2stage-repair-v1` made it easy to conflate the recipe sub-pipeline with the whole Codex-backed workflow.

Durable decisions:
- `llm_recipe_pipeline` and `llm_knowledge_pipeline` are separate surfaces.
- Switching between `codex-farm-3pass-v1` and `codex-farm-2stage-repair-v1` changes only the recipe extraction path.
- Knowledge extraction remains its own later stage with the same `knowledge` artifact tree.

Anti-loop note:
- If a recipe pipeline rename seems to imply knowledge-stage moved or vanished, inspect `llm_knowledge_pipeline` wiring first.

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

## 2026-03-06 plan mode, compact defaults, and knowledge-stage benchmark enablement

Problem captured:
- Plan mode was initially too shallow to be useful, compact defaults were controlled in too many places, and benchmark prediction generation had dropped knowledge-stage settings.

Durable decisions:
- `--codex-execution-policy plan` runs deterministic prep first, then writes `codex_execution_plan.json` before stopping.
- Compact defaults must stay aligned across:
  - `cookimport/config/run_settings.py`
  - CLI defaults in `cookimport/cli.py`
  - canonical line-role prompt-format resolution
- Benchmark prediction generation now forwards knowledge-stage settings into shared `RunSettings`.
- `knowledge/<workbook_slug>/block_classifications.jsonl` is the primary outside-span contract; `snippets.jsonl` remains transition/reviewer evidence.

Anti-loop note:
- If compact prompts or knowledge-stage behavior look half-enabled, check control-surface alignment and shared `RunSettings` wiring before editing prompts.

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
- Subprocess-backed recipe and knowledge-stage flows validate pipeline IDs up front with `codex-farm pipelines list --root <pack> --json`.
- Runner resolves each pipeline's `output_schema_path` and passes it as `--output-schema`.
- When `process --json` returns a `run_id`, runner can enrich failures with `codex-farm run errors --run-id ... --json`.
- Pass metadata persists `telemetry_report`, `autotune_report`, and compact CSV `telemetry` slices.
- Telemetry/autotune ingestion is non-fatal and stays centralized in the runner.

Anti-loop note:
- Do not duplicate pipeline/schema/telemetry logic in each orchestrator; keep it centralized in `cookimport/llm/codex_farm_runner.py`.

## 2026-02-25 knowledge-stage artifact boundaries

Problem captured:
- Missing knowledge-stage artifacts were often misdiagnosed as prompt-quality problems instead of wiring regressions.

Durable decisions:
- Keep knowledge-stage table hints aligned across single-file, split-merge, and processed-output paths.
- When knowledge extraction is off, deterministic knowledge-lane chunk mapping still backfills stage knowledge labels.
- inline recipe tags now belong to the recipe-correction surface and normal draft outputs, not a separate fifth-stage/tag tree.

Anti-loop note:
- If `KNOWLEDGE=0` appears with knowledge extraction off, debug wiring and run settings before changing prompt assets.

## 2026-03-16 benchmark prompt/export and runner follow-through

Problem captured:
- benchmark single-offline runs exposed several easy-to-misread seams at once:
  - older stderr progress lines looked like terminal corruption
  - missing benchmark-level `prompts/` exports looked like Codex non-execution
  - prompt budgets could lose split-token fields on the single-offline manifest shape
  - reasoning models still produced zero reasoning-summary events in live traces

Durable decisions:
- `SubprocessCodexFarmRunner` should consume legacy stderr progress lines as compatibility progress/control output, not stderr noise
- benchmark prompt/export truth stays split:
  - raw execution truth lives under the linked processed stage run in `data/output`
  - reviewer-facing merged prompt exports live under benchmark `prompts/` when the export step runs
- prompt preview should reuse exact saved recipe/knowledge input payloads when available and only reconstruct locally as fallback
- preview budget output should stay reviewer-blunt: emit a heuristic budget summary plus danger warnings when rendered prompt volume or call fan-out is obviously expensive
- prompt-budget aggregation must support the single-offline top-level telemetry-row layout
- missing reasoning-summary events in `.trace.json` files are usually upstream Codex CLI / CodexFarm transport behavior, not a local prompt-artifact regression

Evidence worth keeping:
- on the 2026-03-16 `saltfatacidheatcutdown` run, live spend was `231` first-pass calls (`175` recipe, `56` knowledge)
- the recipe token spike was not a retry storm; grouped span count and recipe payload inflation were the dominant drivers

Anti-loop note:
- if a benchmark run "looks missing" at the prompt layer, verify the raw processed-output artifacts before changing runner or orchestrator code
