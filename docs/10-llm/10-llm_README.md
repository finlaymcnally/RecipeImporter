---
summary: "Current LLM integration boundaries for codex-farm in stage, prediction-run, and tag flows."
read_when:
  - When changing codex-farm settings or pipeline IDs
  - When debugging pass4 knowledge or pass5 tag artifacts
  - When auditing recipe pipeline enablement/default behavior
  - When reconciling Label Studio prediction-run LLM wiring vs stage wiring
---

# LLM Section Reference

LLM usage in this repo is limited and optional.

## Runtime surface

Settings and entrypoints:

- `cookimport/config/run_settings.py` (canonical settings and UI choices)
- `cookimport/cli.py` (stage + benchmark + Label Studio command normalization)
- `cookimport/entrypoint.py` (saved settings -> stage defaults pass-through)
- `cookimport/labelstudio/ingest.py` (prediction-run generation + recipe-pass normalization)

Stage execution paths:

- `cookimport/cli_worker.py` (single-file stage path recipe/pass4 execution)
- `cookimport/cli.py` (`_merge_split_jobs` split-merge stage path recipe/pass4 execution)
- `cookimport/cli.py` (`run_stage_tagging_pass` trigger for pass5 after stage writes)
- `cookimport/staging/writer.py` (stage block predictions writer receives pass4 snippet path)
- `cookimport/staging/stage_block_predictions.py` (uses knowledge snippets for stage evidence labeling)

Recipe codex-farm pass modules:

- `cookimport/llm/codex_farm_orchestrator.py` (pass1/pass2/pass3 orchestration)
- `cookimport/llm/codex_farm_transport.py` (authoritative pass1->pass2 inclusive span selection + audit payload builder)
- `cookimport/llm/codex_farm_contracts.py` (strict pass1/2/3 bundle contracts with guarded JSON-string repair for malformed object payloads)
- `cookimport/llm/evidence_normalizer.py` (deterministic additive pass2 evidence normalization)
- `cookimport/llm/codex_farm_ids.py` (stable slug/id/bundle filename helpers)
- `cookimport/llm/codex_farm_runner.py` (subprocess runner + shared error type)
  - runner now treats `no last agent message` / `nonzero_exit_no_payload` process failures as recoverable partial-output mode; other process failures remain hard errors.

Canonical line-role helper modules:

- `cookimport/llm/codex_exec.py` (shared `codex exec -` invocation helper with json-event parsing and non-interactive fallback)
- `cookimport/llm/canonical_line_role_prompt.py` (structured prompt builder for line-role-only Codex fallback batches)
- `llm_pipelines/prompts/canonical-line-role-v1.prompt.md` (versioned prompt template for canonical line-role fallback)

Pass4 knowledge modules:

- `cookimport/llm/codex_farm_knowledge_orchestrator.py` (pass4 run/manifest/write orchestration)
- `cookimport/llm/codex_farm_knowledge_jobs.py` (job payload construction + context windows)
- `cookimport/llm/codex_farm_knowledge_contracts.py` (pass4 input contract models)
- `cookimport/llm/codex_farm_knowledge_models.py` (pass4 output contract models)
- `cookimport/llm/codex_farm_knowledge_ingest.py` (validated output loading)
- `cookimport/llm/codex_farm_knowledge_writer.py` (snippets + knowledge markdown writer)
- `cookimport/llm/non_recipe_spans.py` (span helpers used by pass4 job building)

Pass5 tags modules:

- `cookimport/tagging/orchestrator.py` (stage-level tag pass orchestration + index writing)
- `cookimport/tagging/llm_second_pass.py` (missing-category shortlist + fallback behavior)
- `cookimport/tagging/codex_farm_tags_provider.py` (pass5 I/O, schema validation, shortlist enforcement)
- `cookimport/tagging/cli.py` (standalone tag-recipes/tag-catalog CLI LLM options)
- `cookimport/llm/codex_farm_runner.py` and `cookimport/llm/codex_farm_ids.py` (shared runner/id helpers)

Report/model plumbing:

- `cookimport/core/models.py` (`ConversionReport.llm_codex_farm` field carried in stage/pred-run reports)
- Codex subprocess metadata is now persisted per pass:
  - recipe pass manifest/report: `process_runs.pass1|pass2|pass3`
  - pass4 knowledge report: `process_run`
  - pass5 tags report: `process_run`
- Stage + benchmark spinners now pass their callback path into codex-farm runners:
  - subprocess runner requests `codex-farm process --progress-events --json` when callback-driven status is active.
  - stderr `__codex_farm_progress__` events are translated into spinner text with `task X/Y` counters, and, when present, active task labels (for running workers) are included as an `active [...]` section.
  - when older codex-farm binaries reject `--progress-events`, runner retries once without that flag and continues with phase-only status.

## Policy boundary (current behavior)

- `llm_recipe_pipeline` supports `off` and `codex-farm-3pass-v1` without env-gate coercion.
- `cookimport/config/codex_decision.py` now carries both surface classification and execution-policy metadata:
  - command decisions still enforce explicit approval in execute mode,
  - prediction/benchmark plan mode writes `codex_execution_plan.json` without live Codex calls.
- `cookimport stage`, `cookimport labelstudio-import`, `cookimport labelstudio-benchmark`, and the `import` entrypoint now share the same `--codex-execution-policy execute|plan` command-boundary behavior.
  - `plan` writes manifests plus `codex_execution_plan.json` and returns before live Codex work.
- `RunSettings.from_dict`, CLI normalizers, and Label Studio prediction-run normalizers accept codex-farm values directly and only reject invalid enum values.
- Interactive import/benchmark run setup asks `Use Codex Farm recipe pipeline for this run?`; default follows global `llm_recipe_pipeline` (`codex-farm-3pass-v1` => `Yes`, otherwise `No`) and `COOKIMPORT_TOP_TIER_PROFILE` can force codexfarm/vanilla. When codex is selected, chooser also prompts for `codex_farm_model` and `codex_farm_reasoning_effort` overrides for that run.
- Interactive benchmark now runs single-offline or single-profile matched-set modes only; codex behavior follows the selected top-tier profile for that session.
- `RunSettings()` defaults and `build_run_settings(...)` helper defaults are now safe/off (`llm_recipe_pipeline=off`, `line_role_pipeline=off`, `atomic_block_splitter=off`) unless a caller explicitly opts into a Codex-backed contract.
- `cookimport/config/codex_decision.py` is now the shared Codex boundary layer. It classifies actual Codex-backed surfaces, applies the interactive top-tier and paired benchmark contracts, and persists explicit decision metadata (`codex_decision_*`, `ai_assistance_profile`, and, when relevant, `benchmark_variant`) into run-config artifacts.
- Direct run commands `cookimport stage`, `cookimport labelstudio-import`, `cookimport labelstudio-benchmark`, and the `import` entrypoint require explicit `--allow-codex` approval only in execute mode when their resolved run settings enable a Codex-backed surface.
- `COOKIMPORT_ALLOW_CODEX_FARM` remains as a legacy no-op compatibility variable.
- `codex_farm_failure_mode` still controls behavior for active LLM passes (`fail` or `fallback`).
- Canonical line-role fallback uses `line_role_pipeline=codex-line-role-v1` with deterministic-first behavior and strict JSON/allowlist validation.
- `RunSettings` now also carries `line_role_guardrail_mode=off|preview|enforce` (default `enforce`) for explicit line-role post-sanitization arbitration behavior.
- Canonical line-role allowlists now auto-offer `RECIPE_TITLE` for title-like lines, and low-confidence deterministic `RECIPE_TITLE` labels are kept on-rule instead of escalated away.
- Canonical line-role prompt few-shots now include an explicit `RECIPE_TITLE` positive example (in addition to `RECIPE_VARIANT`) to reduce title-vs-variant confusion.

## Pass1 Pattern Hints Boundary

- Pass1 recipe chunking input contract supports optional `pattern_hints` (`cookimport/llm/codex_farm_contracts.py`).
- Prompt contract marks `pattern_hints` as advisory only and never a replacement for block evidence (`llm_pipelines/prompts/recipe.chunking.v1.prompt.md`).
- Runtime wiring is controlled by run settings via `codex_farm_pass1_pattern_hints_enabled` (default `false`) in `cookimport/llm/codex_farm_orchestrator.py`.
- This handoff is metadata-only; it does not enable AI parsing/cleaning in EPUB/PDF ingestion.

## Pass2 Transport Audit + Evidence Normalization

- Pass2 input now carries additive normalized evidence fields:
  - `normalized_evidence_text`
  - `normalized_evidence_lines`
  - `normalization_stats`
- Pass1->pass2 transport now uses explicit inclusive end-index semantics (`start <= idx <= end`) through `codex_farm_transport.py`, and transport audits include `end_index_semantics=\"inclusive\"`.
- Pass1 clamp behavior is overlap-focused: when recipe spans overlap, boundaries are split across the overlap window midpoint to reduce evidence loss while still preventing overlap.
- Pass1 now applies an eligibility do-no-harm gate before pass2:
  - score `+2` ingredient-like evidence, `+2` instruction-like evidence, `+1` heading/yield context, `-2` high prose dominance, `-2` high chapter/page metadata negative evidence (chapter-intro/front-matter/mixed-content style tags).
  - action bands: `score >= 3 => proceed`, `score 1-2 => clamp to heuristic bounds`, `score <= 0 => drop before pass2`.
  - per-recipe manifest fields: `eligibility_status`, `eligibility_action`, `eligibility_score`, `eligibility_score_components`, `eligibility_reasons`.
- Eligibility diagnostics are persisted at `raw/llm/<workbook_slug>/pass1_recipe_eligibility_diagnostics.json`.
- Authoritative pass2 evidence remains `canonical_text` + `blocks`; normalized evidence is helper-only.
- Recipe-level pass1/pass2 handoff audits are persisted under:
  - `raw/llm/<workbook_slug>/transport_audit/*.json` (sanitized recipe-id keyed)
- Recipe-level evidence normalization provenance is persisted under:
  - `raw/llm/<workbook_slug>/evidence_normalization/*.json` (sanitized recipe-id keyed)
- Transport mismatches now set recipe-level status according to failure mode:
  - `codex_farm_failure_mode=fallback` marks the recipe as pass3 fallback with reason `transport mismatch`,
  - `codex_farm_failure_mode=fail` keeps recipe-level error status without process-wide crash.
- `llm_manifest.json` now records:
  - transport audit rows and mismatch counts,
  - per-recipe `pass1_span_loss_metrics` (raw span vs midpoint-clamped span, with block-loss count/ratio),
  - pass2 degradation counts/reasons (`pass2_degraded`, per-recipe `pass2_degradation_reasons`),
  - evidence-normalization row summaries/counts,
  - pass3 fallback counts (when deterministic fallback replaces low-quality pass3 output).
- Pass2 degradation is now severity-scoped before pass3 routing:
  - hard degradation (`missing_instructions`, placeholder-only instruction evidence, or non-soft warning buckets) still fail-closes to deterministic fallback (`pass3_status=fallback`);
  - soft degradation (`warning_bucket:page_or_layout_artifact` only) stays `pass2_status=degraded` but is eligible for selective pass3 routing.
- Pass3 routing now records additive metadata per recipe in `llm_manifest`:
  - `pass2_degradation_severity`, `pass2_promotion_policy`,
  - `pass3_execution_mode`, `pass3_routing_reason`.
- Pass2-ok rows now also record `pass3_utility_signal` in per-recipe `llm_manifest` rows
  (instruction/ingredient/schema/warning evidence snapshot + conservative
  `deterministic_low_risk` flag).
- Pass2-ok deterministic promotion now defaults to enabled and skips pass3 only
  when the utility signal is low-risk
  (`pass3_routing_reason=pass2_ok_high_confidence_deterministic`).
- Override control is run-settings only:
  - `run_settings.codex_farm_pass3_skip_pass2_ok` (default `true`) controls pass2-ok
    deterministic skip behavior.
- Manifest counts now include pass2-ok routing utility counters:
  `pass3_pass2_ok_utility_rows`, `pass3_pass2_ok_skip_candidates`,
  `pass3_pass2_ok_deterministic_skips`, `pass3_pass2_ok_llm_calls`.
- Selective soft-degradation routing defaults to deterministic promotion for low-risk rows (non-placeholder instruction evidence present), producing `pass3_status=ok` with `pass3_execution_mode=deterministic` and no pass3 LLM call.
- Pass2 degradation warning bucket naming is now layout-specific for page-marker noise (`warning_bucket:page_or_layout_artifact`) instead of OCR-specific wording.
- Deterministic fallback now starts from the existing `state.recipe` candidate, then applies guarded pass2 enrichments when instruction/ingredient evidence is non-empty and non-placeholder.
- When pass3 returns placeholder-only steps but pass2 contains non-placeholder extracted instructions, orchestrator now repairs steps from pass2 evidence before low-quality rejection.
- Pass2/Pass3 contract loaders now attempt bounded repair for malformed object strings (control-byte cleanup, null-hex artifact cleanup, bracket rebalance, and first-object extraction) before raising validation errors.
- Pass3 draft normalization now coerces legacy `draft_v1` object shapes (for example `name`/`instructions`, schema.org-only, or pass2-like objects) into valid `RecipeDraftV1` (`schema_v`, `recipe.title`, `steps`) before final validation.
- Recipe-pass block extraction now falls back to `full_text.lines` when `full_text.blocks` is missing/empty (common in some cached prediction payloads), synthesizing minimal block rows by line index so codexfarm can still execute pass1/pass2/pass3.

## 2026-02-28 merged task specs (`docs/tasks` batch)

### 2026-02-28_02.31.09 enable codex-farm in benchmarks (historical gate phase)

- Source task: `docs/tasks/2026-02-28_02.31.09-enable-codex-farm-in-benchmarks.md`
- Added `--include-codex-farm` coverage in bench speed/quality all-method flows and made codex variants a real all-method dimension.
- Historical note: this task used an env-gated rollout (`COOKIMPORT_ALLOW_CODEX_FARM=1`); that gating was later removed by `2026-02-28_04.05.00`.
- Durable behavior that remains relevant:
  - all-method codex variants are explicit/opt-in (`--include-codex-farm`),
  - bench speed/quality runs persist command-level Codex decision metadata alongside the existing confirmation-token contract,
  - deterministic sweeps remain independent from codex inclusion choices.

### 2026-02-28_02.48.43 codex-farm CLI setup for EPUB benchmark runs

- Source task: `docs/tasks/2026-02-28_02.48.43-setup-codex-farm-cli-for-epub-benchmarks.md`
- Captured operational dependency that benchmark/stage codex paths shell out to external `codex-farm`.
- Recommended durable setup:
  - prefer absolute `codex_farm_cmd` paths,
  - set `codex_farm_root` to this repo’s `llm_pipelines` when using local packs,
  - keep pass pipeline IDs aligned (`recipe.chunking.v1`, `recipe.schemaorg.v1`, `recipe.final.v1`).
- Failure semantics:
  - missing/unresolvable `codex-farm` should fail fast with explicit invocation errors.

### 2026-02-28_03.37.51 unlock interactive llm recipe pipeline option

- Source task: `docs/tasks/2026-02-28_03.37.51-unlock-interactive-llm-recipe-pipeline-option.md`
- Historical note: this was tied to the retired full-screen run-settings editor path.
- Current interactive control point is the two-profile top-tier chooser (`CodexFarm`/`Vanilla`).

### 2026-02-28_04.05.00 codex-farm always-on in interactive and normalizers

- Source task: `docs/tasks/2026-02-28_04.05.00-codex-farm-always-on-in-interactive-and-normalizers.md`
- Recipe codex-farm normalization is ungated in `RunSettings`, CLI, and Label Studio ingest paths.
- Interactive defaults now bias to codex-enabled runs:
  - per-run chooser prompt default `Yes`,
  - Vanilla remains one explicit prompt choice away.
- Bench/stage behavior remains explicit opt-in at command/profile level (`--include-codex-farm` and run-settings choices); no implicit global always-on execution.

### 2026-02-28_09.26.29 codex-farm connection contract alignment

- Merged from former `docs/tasks/2026-02-28_09.26.29-codex-farm-connection-contract-alignment.md` (file removed after merge).
- Interactive model discovery now follows caller contract via `codex-farm models list --json` (best-effort fallback if unavailable).
- Subprocess-backed pass orchestration prevalidates configured pipeline ids via `codex-farm pipelines list --root <pack> --json`.
- Subprocess failure diagnostics now parse `process --json` and, when `run_id` is present, append `codex-farm run errors --run-id <run_id> --json` context.
- Boundary note:
  - strict pipeline prevalidation is scoped to subprocess-backed execution and does not block fake/injected test runners.

### 2026-02-28_09.49.32 codex-farm caller output-schema enforcement

- Merged from former `docs/tasks/2026-02-28_09.49.32-codex-farm-output-schema-enforcement.md` (file removed after merge).
- Recipe/pass4/pass5 subprocess calls now resolve each pipeline `output_schema_path` from pack pipeline definitions and pass it explicitly as `--output-schema`.
- Fail-fast guards now trigger before subprocess execution for:
  - missing/duplicate pipeline definition for requested `pipeline_id`,
  - missing `output_schema_path`,
  - missing schema file on disk.
- When `process --json` payload is present, runner now requires `output_schema_path` and validates parity with caller-expected schema path.
- Runtime auditability:
  - recipe pass manifest/report: `output_schema_paths`,
  - pass4/pass5 reports: `output_schema_path`.

### 2026-02-28_10.15.00 codex-exec telemetry contract ingest

- Merged from former `docs/tasks/2026-02-28_10.15.00-codex-farm-telemetry-contract-ingest.md` (file removed after merge).
- Runner now returns structured process metadata plus:
  - `telemetry_report` copied from `process --json.telemetry_report` (CodexFarm caller contract, schema v2),
  - `autotune_report` from `run autotune --run-id <id> --json` (flag overrides, command preview, and optional prompt/pipeline diffs),
  - compact best-effort telemetry slices from `codex_exec_activity.csv` keyed by `run_id` + `pipeline_id` under `telemetry`.
- Persisted telemetry surfaces:
  - recipe pass manifest/report: `process_runs.pass1|pass2|pass3`,
  - pass4 knowledge report: `process_run`,
  - pass5 tags report: `process_run`.
- Telemetry ingestion remains non-fatal:
  - missing/unreadable telemetry CSV adds warnings in payload and does not fail conversion runs,
  - missing embedded `telemetry_report` (older codex-farm or `--no-telemetry-report`) is tolerated,
  - missing/unsupported `run autotune` command is tolerated (payload key remains null).
- CSV resolution follows codex-farm process semantics:
  - `--data-dir` override when present,
  - otherwise `<cwd>/var`.

## Active optional passes

### Pass4 knowledge harvesting

Enable with:

- `llm_knowledge_pipeline=codex-farm-knowledge-v1`

## 2026-03-06 merged understandings digest (Codex decision + line-role telemetry)

Current LLM contracts reinforced:
- Codex decision logic is layered and must stay aligned across three surfaces:
  - interactive top-tier profile selection,
  - paired benchmark variant contracts,
  - analytics/runtime classification persisted into run-config artifacts.
- `cookimport/config/codex_decision.py` is the shared boundary:
  - command-entry validation,
  - explicit decision metadata stamping,
  - runtime surface classification reused by analytics.
- Anti-loop note on defaults:
  - `RunSettings()` is now safe/off,
  - if a command still behaves Codex-on by default, inspect constructor/helper bypasses and command-boundary validators before changing the base model again.
- Line-role telemetry is now captured locally through `prediction-run/line-role-pipeline/telemetry_summary.json`; the remaining gap is unified reporting, not raw telemetry capture.
- Prompt/provenance surfaces for line-role and prompt-budget work are:
  - `prediction-run/line-role-pipeline/prompts/prompt_*.txt`
  - `prediction-run/line-role-pipeline/prompts/response_*.txt`
  - `prediction-run/line-role-pipeline/prompts/parsed_*.json`
  - `prediction-run/line-role-pipeline/extracted_archive.json`
- Prompt-budget reduction work should target:
  - unified prompt-budget summary artifacts across recipe passes plus line-role,
  - pass2 duplicate evidence payloads,
  - pass3 duplicated structured content rather than already-removed raw block windows.
  - pipeline-id-based compaction for pass2/pass3 and a line-role prompt-format selector are the intended rollout seams; new global prompt-mode settings are unnecessary.
- Separate Codex-backed surface reminder:
  - `labelstudio-import --prelabel` is not the same surface as recipe/line-role run-settings pipelines and needs its own approval/metadata review whenever Codex decision policy changes.
- Prompt-sample thinking traces are only as good as upstream trace capture. If trace files exist but `reasoning_event_count` is zero, recipeimport should report the absence rather than fabricate excerpts.
- `codex_farm_pipeline_pass4_knowledge`
- `codex_farm_knowledge_context_blocks`

Writes:

- `data/output/<ts>/raw/llm/<workbook_slug>/pass4_knowledge/{in,out}/`
- `data/output/<ts>/raw/llm/<workbook_slug>/pass4_knowledge_manifest.json`
- `data/output/<ts>/knowledge/<workbook_slug>/snippets.jsonl`
- `data/output/<ts>/knowledge/<workbook_slug>/knowledge.md`
- `data/output/<ts>/knowledge/knowledge_index.json`

### Pass5 tag suggestions

Enable with:

- `llm_tags_pipeline=codex-farm-tags-v1`
- `tag_catalog_json`
- `codex_farm_pipeline_pass5_tags`

Writes:

- `data/output/<ts>/raw/llm/<workbook_slug>/pass5_tags/{in,out}/`
- `data/output/<ts>/raw/llm/<workbook_slug>/pass5_tags_manifest.json`
- `data/output/<ts>/tags/<workbook_slug>/r{index}.tags.json`
- `data/output/<ts>/tags/<workbook_slug>/tagging_report.json`
- `data/output/<ts>/tags/tags_index.json`

## Shared codex-farm controls

These settings remain part of run settings and stage execution:

- `llm_recipe_pipeline`
- `llm_knowledge_pipeline`
- `llm_tags_pipeline`
- `codex_farm_cmd`
- `codex_farm_model` (optional override passed to codex-farm)
- `codex_farm_reasoning_effort` (optional override passed to codex-farm as reasoning/thinking effort)
  - when unset in benchmark prediction metadata, runtime metadata backfill resolves concrete effort from Codex config/model-cache defaults when possible so downstream benchmark CSV/dashboard rows can retain both model and effort.
- `codex_farm_root`
- `codex_farm_workspace_root`
- `codex_farm_recipe_mode` (`extract` default, `benchmark` for benchmark-native line-label flow)
- `codex_farm_failure_mode`
- `codex_farm_pipeline_pass1`
- `codex_farm_pipeline_pass2`
- `codex_farm_pipeline_pass3`
- `codex_farm_pipeline_pass4_knowledge`
- `codex_farm_pipeline_pass5_tags`
- `codex_farm_context_blocks`
- `codex_farm_knowledge_context_blocks`
- `tag_catalog_json`

## Prediction-run boundary

- Label Studio prediction-run generation (`generate_pred_run_artifacts`) currently wires recipe-pass settings only (pass1/2/3 + codex-farm command/root/workspace/context/failure mode).
- Prediction-run manifests now carry `codex_farm_recipe_mode`, and subprocess-backed recipe passes export `COOKIMPORT_CODEX_FARM_RECIPE_MODE` so codex-farm can receive `--benchmark-mode ...` where supported.
- Pass4 knowledge harvesting and pass5 tag suggestions are stage-only flows; prediction-run generation does not execute those passes.
- Benchmark prediction generation (`labelstudio-benchmark`) reuses that same prediction-run recipe-pass boundary.
- When `llm_recipe_pipeline` is active, Codex Farm prompt payloads are persisted as:
  - `prompt_inputs_manifest.txt` (pass1/2/3 `in` payloads)
  - `prompt_outputs_manifest.txt` (pass1/2/3 `out` payloads)
- Prompt/debug artifacts are also auto-generated when Codex Farm pass manifests exist:
  - benchmark eval output: `<eval_root>/prompts/`
  - stage run output: `<stage_run_root>/prompts/`
  - labelstudio-import run output: `<labelstudio_run_root>/prompts/`
  - key files: `prompt_request_response_log.txt`, `full_prompt_log.jsonl`, `prompt_type_samples_from_full_prompt_log.md`
- The prompt sample markdown now covers pass1/pass2/pass3 and also pass4/pass5 when those manifests are present.
- `full_prompt_log.jsonl` rows now also carry Codex trace metadata in `request_telemetry` (`trace_path`, resolved path, action/reasoning counts/types), plus `thinking_trace` payloads with reasoning events when trace files are available.
- Local recipe pipeline pack prompts now run with `prompt_input_mode=inline` and embed full input JSON via `{{INPUT_TEXT}}`; recipe pass templates should not depend on file-read instructions.
- `run_manifest.json` includes `prompt_inputs_manifest_txt` and `prompt_outputs_manifest_txt` artifact pointers for active Codex Farm runs.

Recipe pass execution in prediction-run paths follows selected run settings with no env gate.

## Test support + legacy modules

- `cookimport/llm/fake_codex_farm_runner.py` provides deterministic fake outputs for tests.

Legacy modules (not on current stage/pred-run/tag runtime path):

- `cookimport/llm/client.py`
- `cookimport/llm/prompts.py`
- `cookimport/llm/repair.py`

These modules remain for older/manual experimentation and tests; current import pipeline behavior is governed by codex-farm modules and run settings above.

## Related docs

- `docs/10-llm/10-llm_log.md`
- `docs/10-llm/knowledge_harvest.md`
- `docs/10-llm/tags_pass.md`

## 2026-02-27 Merged Understandings: Runtime Scope and Coverage Parity

Merged source notes:
- `docs/understandings/2026-02-27_19.45.57-llm-docs-runtime-scope-cleanup.md`
- `docs/understandings/2026-02-27_19.51.50-llm-docs-parity-runtime-surface-map.md`

Current-contract additions:
- Stage-relevant LLM runtime remains centered on pass4 knowledge and pass5 tags; recipe pass1/2/3 is available for stage/pred-run use via run settings.
- Prediction-run generation currently wires recipe-pass settings only; pass4/pass5 execution remains stage-only.
- LLM docs should keep runtime-adjacent module coverage explicit (prediction wrappers, pass4 helper contracts/writer paths, pass5 provider/validation layer, stage evidence/report consumers).
- Legacy modules (`client.py`, `prompts.py`, `repair.py`) remain non-primary runtime paths and should stay labeled accordingly.

## 2026-02-28 migrated understandings digest (Codex Farm ops)

### 2026-02-28_03.17.29 Codex Farm opt-in command pattern
- Source: `docs/understandings/2026-02-28_03.17.29-codex-farm-opt-in-command-pattern.md`
- Historical note (superseded): global defaults were previously deterministic (`llm_recipe_pipeline=off`) before top-tier defaults were promoted.
- Absolute `codex_farm_cmd` paths avoid PATH fragility when Codex Farm is outside shell defaults.

### 2026-02-28_03.19.48 interactive Codex Farm gate and launcher
- Source: `docs/understandings/2026-02-28_03.19.48-interactive-codex-farm-gate-and-launcher.md`
- Interactive mode already respects run-settings `llm_recipe_pipeline`; no additional interactive-only gate path is required.
- Wrapper launcher pattern (`scripts/interactive-with-codex-farm.sh`) remains useful when you want codex-enabled sessions with preset command/model flags.

## 2026-02-28 migrated understandings batch (03:47-04:01)

The items below were merged from `docs/understandings` in timestamp order and folded into LLM current-state guidance.

### 2026-02-28_03.47.42 codex-farm prompt-tightening priorities
- External review found deterministic/schema-safety under-specification across pass prompts.
- Priority order for highest-impact tightening was:
  1. pass2 (`recipe.schemaorg.v1`)
  2. pass3 (`recipe.final.v1`)
  3. pass1 (`recipe.chunking.v1`)
  4. pass4/pass5 (medium impact)
- High-value wording improvements: explicit omit-vs-guess policy, tie-break rules, strict evidence language, stable ordering, and no-extra-properties constraints.

### 2026-02-28_04.01.52 codex toggle vs effective run settings
- Prompt-time codex selection can diverge from persisted effective run settings when normalization/gating code changes around run time.
- For run `2026-02-28_03.54.15`, artifacts showed `llm_recipe_pipeline=off` and `llm_codex_farm.enabled=false`; nearby file edits around `04:00` explain likely normalization drift during that session.
- For incident triage, trust persisted run artifacts (`run_manifest`, run settings snapshot) over assumptions from current head code.

## 2026-02-28 migrated understandings batch (04:05-10:08 Codex gate surfaces and connection contract)

### 2026-02-28_04.05.20 codex-farm gate surface map
- Source: `docs/understandings/2026-02-28_04.05.20-codex-farm-gate-surface-map.md`
- Codex behavior can drift when only one surface is edited.
- Four runtime surfaces must stay aligned:
  1. `RunSettings.from_dict(...)` coercion/normalization.
  2. `cookimport/cli_ui/run_settings_flow.py` interactive top-tier chooser.
  3. `cookimport/cli.py:_normalize_llm_recipe_pipeline(...)`.
  4. `cookimport/cli.py:_resolve_all_method_codex_choice(...)`.
- Prompt defaults are independent from those normalization surfaces.

### 2026-02-28_04.11.09 docs-task merge codex gating drift
- Source: `docs/understandings/2026-02-28_04.11.09-docs-task-merge-codex-gating-drift.md`
- During docs consolidation, stale env-gated wording appeared alongside current ungated runtime behavior.
- Current authoritative runtime remains ungated in run-settings parser + CLI + Label Studio ingest normalizers.
- `COOKIMPORT_ALLOW_CODEX_FARM` is legacy compatibility surface (no active gate); keep old gated behavior only as historical `_log` context.

### 2026-02-28_09.26.29 codex-farm connection contract alignment
- Source: `docs/understandings/2026-02-28_09.26.29-codex-farm-connection-contract-aligned.md`
- Shared run-settings Codex model picker now discovers choices via `codex-farm models list --json` (best-effort fallback when unavailable).
- Recipe/pass4/pass5 subprocess paths now validate configured pipeline ids up front via `codex-farm pipelines list --root <pack> --json`.
- Subprocess failure diagnostics now parse `process --json` output and, when `run_id` is available, append first-error context from `codex-farm run errors --run-id <run_id> --json`.

### 2026-02-28_09.49.32 caller output-schema enforcement wiring
- Recipe/pass4/pass5 subprocess calls now resolve each pipeline's declared `output_schema_path` from the selected pack and pass it explicitly as `--output-schema` to `codex-farm process`.
- This keeps caller-side schema contract enforcement aligned with Codex Farm's structured-output retry gate.
- If pipeline definitions are missing/duplicated, or the resolved schema file is missing, subprocess invocation now fails fast before work starts.
- When `process --json` returns payload JSON, runner now expects `output_schema_path` and verifies it matches the caller-expected schema path.
- Runtime manifests/reports now surface schema paths for auditing:
  - recipe pass manifest/report: `output_schema_paths`
  - pass4/pass5 reports: `output_schema_path`

### 2026-02-28_10.08.00 codex-exec telemetry ingestion in recipeimport
- Recipe/pass4/pass5 runner calls now retain per-process metadata (`run_id`, `process_exit_code`, `subprocess_exit_code`, `process_payload`) and also surface:
  - `telemetry_report` from `process --json` (CodexFarm schema-v2 caller contract with `insights` and `tuning_playbook`),
  - `autotune_report` from `run autotune --json` (non-mutating override/diff suggestions),
  - `telemetry` CSV slices keyed by `run_id` + `pipeline_id` for compact per-row context.
- Telemetry slices are read from Codex Farm `codex_exec_activity.csv` and persisted into recipe artifacts (`process_runs` / `process_run`) with compact rows + summary counts for:
  - retry context and previous-error hashes,
  - Heads Up tip ids/texts/scores and usage flags,
  - normalized failures and suspected rate limits,
  - output hashes/previews/presence stats,
  - codex event count/type summaries and token counters.

## 2026-02-28 merged understandings (09:26-10:13 codex-farm subprocess and telemetry boundary)

The items below were merged from `docs/understandings` in source timestamp order.

### 2026-02-28_09.26.29 codex-farm connection contract aligned
- Source: `docs/understandings/2026-02-28_09.26.29-codex-farm-connection-contract-aligned.md`
- Interactive model discovery now uses `codex-farm models list --json` via runner helper so choices reflect live CLI discovery.
- Subprocess-backed recipe/pass4/pass5 flows validate pipeline IDs using `codex-farm pipelines list --root <pack> --json` before execution.
- Failure paths parse `process --json` and pull first-error details from `codex-farm run errors --run-id <run_id> --json` when available.

### 2026-02-28_09.50.17 codex-farm output schema resolution point
- Source: `docs/understandings/2026-02-28_09.50.17-codex-farm-output-schema-resolution-point.md`
- Correct caller-side insertion point for schema enforcement is `SubprocessCodexFarmRunner.run_pipeline(...)` command assembly.
- This single boundary guarantees consistent `--output-schema` handling across recipe pass1/2/3, pass4 knowledge, and pass5 tags.
- Process payload contract check also belongs here: validate returned `output_schema_path` against caller-expected schema path.

### 2026-02-28_10.03.37 codex-exec telemetry consumption boundary (historical snapshot)
- Source: `docs/understandings/2026-02-28_10.03.37-codex-exec-telemetry-consumption-boundary.md`
- Snapshot finding at that time: repo runtime did not yet ingest `codex_exec_activity.csv` rich telemetry fields; analytics consumed performance history contracts instead.
- This historical boundary is intentionally kept to prevent false assumptions when reading older artifacts or logs.
- Superseded by the implementation captured in `2026-02-28_10.13.48` and task merge entry `2026-02-28_10.08.00`.

### 2026-02-28_10.13.48 codex-farm run-id telemetry ingestion path
- Source: `docs/understandings/2026-02-28_10.13.48-codex-farm-runid-telemetry-ingestion-path.md`
- `run_id` from `process --json` is the join key into Codex Farm telemetry rows for the exact pipeline run.
- Runner now persists compact pass-level telemetry slices in:
  - recipe pass manifests/reports: `process_runs.pass1|pass2|pass3`
  - pass4/pass5 reports: `process_run`
- Telemetry ingestion remains non-fatal and warnings are carried in payloads when CSV data is missing/unreadable.
- CSV path discovery follows codex-farm semantics: explicit `--data-dir` if present, otherwise `<cwd>/var/codex_exec_activity.csv`.

### Known bad or easy-to-repeat mistakes
- Do not inject schema enforcement separately in each orchestrator; keep it centralized at subprocess runner command assembly.
- Do not treat missing telemetry CSV as conversion failure; current contract is warn-and-continue with bounded payload slices.
- When behavior differs between UI choices and runtime, verify live CLI discovery and persisted run artifacts before changing prompts or enums.

## 2026-02-28 merged understandings (10:28-10:35 telemetry report v2 + autotune boundary)

The items below were merged from `docs/understandings` in source timestamp order.

### 2026-02-28_10.28.23 codex-farm telemetry-report v2 alignment
- Source: `docs/understandings/2026-02-28_10.28.23-codex-farm-telemetry-report-v2-alignment.md`
- `process --json.telemetry_report` (schema v2) is preserved as first-class `telemetry_report` on pass metadata.
- Existing `telemetry` CSV slices remain intentionally retained as compact row-level fallback/context.
- Keep both surfaces:
  - `telemetry_report` for caller contract (`insights`, `tuning_playbook`),
  - `telemetry` for row-level diagnostics and backward compatibility.

### 2026-02-28_10.35.22 codex-farm autotune consumption boundary
- Source: `docs/understandings/2026-02-28_10.35.22-codex-farm-run-autotune-consumption-boundary.md`
- Runner performs best-effort `run autotune --run-id <id> --json` after successful `process` calls and stores result as `autotune_report`.
- `autotune_report` is non-fatal metadata (null when unavailable) and does not trigger automatic runtime mutation.
- Keep metadata layers distinct:
  - `telemetry_report`: structured caller telemetry contract.
  - `autotune_report`: concrete suggested overrides/diffs.
  - `telemetry`: compact activity slices.

## 2026-02-28 task consolidation (`docs/tasks` CodexFarm telemetry ingest batch)

Merged task files (source creation order):
- `2026-02-28_10.08.00-codex-farm-telemetry-contract-ingest.md`
- `2026-02-28_10.22.31-codex-farm-telemetry-implementation-summary.md`
- `2026-02-28_10.28.23-codex-farm-telemetry-v2-alignment.md`
- `2026-02-28_10.35.22-codex-farm-autotune-payload-ingest.md`

Current contract distilled from this task batch:
- Runner boundary (`cookimport/llm/codex_farm_runner.py`) is the only place that parses and normalizes Codex Farm process metadata for recipe/pass4/pass5 callers.
- `run_pipeline(...)` returns structured process metadata including:
  - `telemetry_report` from `process --json` (schema-v2 caller contract)
  - `autotune_report` from best-effort `run autotune --run-id <id> --json`
  - compact CSV `telemetry` slices from `codex_exec_activity.csv` keyed by `run_id + pipeline_id`
- Serialized pass metadata persists this shape consistently:
  - recipe pass manifests/reports: `process_runs.pass1|pass2|pass3`
  - pass4/pass5 reports/manifests: `process_run`
- Missing telemetry CSV, missing schema-v2 report, or missing autotune support are non-fatal by design; conversion correctness must not depend on observability payload availability.

Known anti-loop boundary:
- Do not duplicate telemetry parsing/wiring in each orchestrator; keep ingest/normalization centralized in the runner and only serialize shared runner payload downstream.

## 2026-03-01 to 2026-03-02 docs/tasks merge (codex progress callback surface)

Merged task files (source creation order):
- `2026-03-01_21.37.45-codex-farm-spinner-progress-bridge.md`
- `2026-03-02_01.02.14-codex-farm-progress-active-noise.md`

Current-contract additions:
- Stage and benchmark codex flows now pass progress callbacks through orchestrators into `SubprocessCodexFarmRunner`.
- Runner requests `codex-farm process --progress-events --json` when callback status is enabled and translates event payloads into stable status lines (`task X/Y`, running count, error count).
- Unsupported `--progress-events` is handled via one fallback retry without the flag; codex pass execution still continues.
- Volatile per-file `active ...` suffixes are intentionally removed from callback status text so plain-progress mode remains readable and dedupe remains effective.

Anti-loop reminder:
- If codex progress looks noisy or stalls, inspect runner event parsing and emitted status strings before changing higher-level spinner UI behavior.

## 2026-03-02 merged understandings digest (schemaorg failure triage + pass2/pass3 payload contract)

Merged sources (chronological):
- `docs/understandings/2026-03-02_00.37.59-codex-farm-schemaorg-403-forbidden.md`
- `docs/understandings/2026-03-02_07.03.58-recipeimport-pass2-pass3-json-string-contracts.md`

Current-contract additions:
- When codex-farm pass2 (`recipe.schemaorg.v1`) fails broadly with exit code `1`, one observed root cause is upstream Codex websocket auth failure (`403 Forbidden`) rather than local schema/prompt bugs.
- `codex-farm run errors` may show only trailing warnings; high-fidelity failure cause is usually in run forensics bundles (`stderr_tail.txt`, `metadata.json`) for each failed task attempt.
- Recipe pass2/pass3 schema contract is stringified nested payloads at top level (`additionalProperties: false` object with string fields):
  - pass2: `schemaorg_recipe`, `field_evidence`
  - pass3: `draft_v1`, `ingredient_step_mapping`
- Contract resilience in recipeimport should continue accepting either Python objects or JSON strings and coercing to canonical JSON-string form before strict validation.
- Prompt assets and fake runner defaults should stay aligned with the JSON-string top-level contract so stage and benchmark codex paths behave consistently.

Triage shortcut for recurring pass2/pass3 failures:
1. Verify Codex Farm process payload + run_id in runner metadata.
2. Inspect codex-farm forensics bundle stderr/metadata for auth/network failures before editing schemas.
3. If auth is healthy, then inspect JSON-string contract alignment (prompt outputs, coercion path, schema constraints).

## 2026-03-02 docs/tasks merge (inline CodexFarm prompt inputs)

### 2026-03-02_08.18.23-codexfarm-self-contained-inline-prompts.md

Why this matters:
- The user goal was to make CodexFarm prompts 100% self-contained, eliminating reliance on instructions like "read JSON from a file path".

What was implemented:
- Inline placeholder support was added in CodexFarm runtime (`src/codex_farm/pipeline_spec.py`) as `{{INPUT_TEXT}}` while preserving `{{INPUT_PATH}}` compatibility.
- Prompt lints now support a `prompt_input_mode` contract (`path` default, `inline` for self-contained mode).
- Recipe packs were migrated to inline prompts where active in this repo: `recipe.chunking.v1`, `recipe.schemaorg.v1`, `recipe.final.v1`, plus associated pass4/pass5 prompts.
- LLM pack tests now validate inline substitution behavior and path-mode backward compatibility.

Current contract:
- For inline prompts, generated prompt text should include `BEGIN_INPUT_JSON`/`END_INPUT_JSON` blocks containing full input payloads.
- Both placeholder styles remain supported during transition to avoid breaking older packs.
- Full end-to-end log proof should still be collected for confidence after runtime updates in external CodexFarm repository.

Known limitations:
- Runtime proof depends on CodexFarm executable/pack versions aligned to the inline contract; recipeimport-side prompt/template changes alone are not sufficient.
- Cross-repo edits are required; this repo documents both the contract and run-time dependency boundary.

## 2026-03-03 merged understanding digest (full prompt log payload provenance)

Merged source note:
- `docs/understandings/2026-03-02_23.30.23-codexfarm-full-prompt-log-payload-source.md`

Current LLM contract to keep:
- `prompts/full_prompt_log.jsonl` is the source-of-truth prompt artifact for benchmark codex runs (one row per pass call, no sampling/truncation).
- Rows include `request_payload_source` so provenance is explicit:
  - `telemetry_csv` for exact prompt/model/runtime fields from codex telemetry,
  - `reconstructed_from_prompt_template` as fallback reconstruction path.
- `request_telemetry` should remain attached for per-call auditability (task/worker ids, attempt indexes, token usage fields, transport/hash context).
- Cutdown/report tooling should treat this JSONL as canonical and sampled text logs as convenience-only views.


## 2026-03-03 merged understandings digest (codexfarm transport/prompt-plan alignment)

- `2026-03-03_09.19.33` `codexfarm-prompt-log-layout`: Where CodexFarm literal prompt text is stored and how to sample by pass
- `2026-03-03_09.27.30` `codexfarm-prompt-samples-autogen-hook`: Benchmark CodexFarm prompt sample markdown is best generated in the existing prompt-log builder
- `2026-03-03_09.58.02` `codexfarm-nonbenchmark-prompt-log-hook`: CodexFarm prompt logs/samples are now generated for stage and labelstudio-import, with pass-specific manifest resolution for pass1..pass5.
- `2026-03-03_10.19.30` `proplan2-vs-runtime-surface-audit`: Audit notes for Proplan2 against current codex-farm/line-role runtime contracts.
- `2026-03-03_10.41.10` `codexfarm-transport-mismatch-and-pass3-fallback-boundary`: CodexFarm orchestrator now records pass1/pass2 transport drift explicitly and uses deterministic pass3 fallback for low-quality bundles.
- `2026-03-03_10.54.45` `execplan-audit-og-vs-implemented`: Audit notes comparing OG Proplan2 intent, implemented codex-farm changes, and completed execplan claims.
- `2026-03-03_11.01.27` `ogplan-non-m5-alignment-pass`: Non-milestone-5 OG Proplan2 alignment pass updated transport failure-mode semantics, artifact keying, and pred-run token-field compatibility.
- `2026-03-03_11.06.42` `ogplan-vs-runtime-gap-review`: Review findings for Proplan2 OG intent vs implemented codex-farm runtime and completed execplan claims.
- `2026-03-03_11.11.55` `transport-audit-block-id-value-comparison`: Transport audit now compares effective vs payload block-id values, not just counts and index alignment.
- `2026-03-03_11.20.30` `seaandsmoke-code-packet-runtime-seams`: Code packet seam map for pass1->pass2 handoff, EPUB unstructured preprocessing, canonical projection/join, and pass3 mapping/override boundaries.
- `2026-03-03_12.16.08` `ogplan-proplan2-code-alignment-review`: Gap check between OG Proplan2 intent, current code, and completed Proplan2 claims.
- `2026-03-03_12.43.42` `pro3-execplan-codebase-fit-gaps`: Pro3 ExecPlan aligns with active codex-farm seams but has stale milestone state and unresolved path placeholders that reduce self-contained execution reliability.
- `2026-03-03_13.05.30` `pro3-transport-gating-outside-span-policy`: Pro3 implementation seam note: inclusive transport helper + pass2 degradation gating + outside-span prompt-join policy.

## 2026-03-03 docs/tasks merge digest (Proplan2 milestone outcome)

Merged source task file:
- `docs/tasks/Proplan2.md`

Current contract additions/reminders:
- Proplan2 milestones 1/2/4 are implemented in runtime and tests: recipe-scoped pass1/pass2 transport audits, additive evidence normalization sidecars, and deterministic pass3 fallback from pass2 structured outputs when pass3 output is missing/invalid/low quality.
- Benchmark-facing label measurement remains on the existing line-role path (`cookimport/parsing` + `cookimport/labelstudio`) rather than adding a separate taxonomy path under `cookimport/llm`.
- Latest recorded Sea paired replay used for Proplan2 milestone-5 decision:
  - `data/golden/benchmark-vs-golden/2026-03-03_12.12.49/single-offline-benchmark/seaandsmokecutdown/codex_vs_vanilla_comparison.json`
  - `strict_accuracy` delta: `-0.102521` (codex lower)
  - `macro_f1_excluding_other` delta: `-0.057421` (codex lower)
  - dev-slice (`c0,c6,c8,c9`) aggregate accuracy delta: `-0.123288`
- Current promotion decision remains `no promotion` and no default flip to Codex recipe correction.


## 2026-03-03 merged understandings digest (docs/understandings cleanup)

This section consolidates notes that were previously in `docs/understandings`.
Detailed chronology and preserved deep notes are in `10-llm_log.md`.

Merged source notes (chronological):
- `2026-03-03_13.10.03-pro3-ogplan-vs-code-audit.md`: Audit note for Pro3 OG plan vs runtime implementation and completed ExecPlan claims.
- `2026-03-03_13.22.30-pro3-pass1-span-loss-metrics-surface.md`: Pro3 span-loss observability now records raw-vs-clamped pass1 span metrics per recipe.
- `2026-03-03_13.51.55-pro3-overlap-clamp-and-pass3-placeholder-repair.md`: Quality-first Pro3 follow-up: overlap-only pass1 clamp and pass3 placeholder-step repair from pass2 evidence.
- `2026-03-03_14.27.12-seaandsmoke-codexfarm-failure-root-causes.md`: Root-cause diagnosis of codexfarm fallback-heavy behavior in SeaAndSmokeCUTDOWN single-offline run 2026-03-03_13.37.54.
- `2026-03-03_14.57.52-codex-contract-json-repair-for-stringified-objects.md`: Codex farm contract parsing can fail on malformed stringified JSON objects; bounded repair recovers common artifacts.
- `2026-03-03_15.25.41-pass3-schema-v-missing-legacy-draft-shapes.md`: Pass3 schema_v validation fallbacks were driven by legacy draft_v1 object shapes, not empty evidence.
- `2026-03-03_15.40.00-pass2-missing-instructions-root-cause-report.md`: Root-cause report for pass2 missing_instructions degradation in SeaAndSmokeCUTDOWN codexfarm run (2026-03-03_13.37.54).
- `2026-03-03_15.44.35-pass2-warning-bucket-page-layout-naming.md`: Pass2 warning bucket label was renamed to page/layout-specific wording while preserving legacy compatibility in cutdown tooling.
- `2026-03-03_17.12.05-single-offline-codexfarm-pass2-timeout-failure.md`: Single-offline codexfarm variant failed in pass2 because three tasks hit the 180s codex timeout across all retries.
- `2026-03-03_18.09.09-single-offline-codexfarm-pass3-timeout-failure.md`: Single-offline codexfarm variant failed in pass3 because every task hit the 180s codex timeout across retries.
- `2026-03-03_18.18.54-llm-timeout-default-surfaces-expanded.md`: LLM timeout defaults include prelabel preflight, line-role fallback, and optional pass4/pass5 pipeline specs in addition to benchmark pass settings.
- `2026-03-03_20.07.02-feedback-relevance-after-canonical-guards.md`: Post-18.31 feedback relevance check after canonical guard updates: line-role bucket critique is partially outdated, while fallback gating and runtime-cost concerns remain active.
- `2026-03-03_20.31.33-codexfarm-soft-gating-plan-rebaseline.md`: ExecPlan rebaseline discovery: current codex-farm seams still hard-gate degraded pass2 rows, while latest SeaAndSmoke artifacts shifted fallback reasons and model/runtime profile.
- `2026-03-03_20.46.18-codexfarm-soft-gating-pass3-routing-contract.md`: Soft-gated codex-farm pass3 routing now separates hard fallback from low-risk deterministic promotion while preserving pass status enums.
- `2026-03-03_21.17.56-profeedback-relevance-audit.md`: Audit of ProFeedback suggestions against current runtime code and 2026-03-03_20.49.14 artifacts.
- `2026-03-03_21.25.37-profeedback-plan-rebuild-scope-check.md`: ProFeedback plan rebuild check: active plan already matched OG scope and only needed working-copy refresh.
- `2026-03-03_21.33.21-profeedback-ogplan-implementation-gap-audit.md`: Audit finding: ProFeedback OG plan remains partially unimplemented despite related runtime improvements.

## 2026-03-03 docs/tasks consolidation batch (transport/fallback hardening, pass3 routing, diagnostics)

Merged source task files (timestamp/file order):
- `docs/tasks/Pro3.md` (task file had no timestamp prefix; mtime-ordered with the 2026-03-03 batch)
- `docs/tasks/2026-03-03_15.25.18-pass3-schema-v-fallback-reduction.md`
- `docs/tasks/2026-03-03_15.44.46-pass2-page-layout-warning-bucket-rename.md`
- `docs/tasks/2026-03-03_20.13.22-codexfarm-soft-gating-runtime-outside-span-precision.md`
- `docs/tasks/2026-03-03_21.42.59 - profeedback-ogplan-gap-implementation.md`

Current LLM contracts added/confirmed:
- Pass1->pass2 transport/audit semantics are centralized and inclusive-end; transport mismatches are explicit invariant failures instead of silent shrinkage.
- Deterministic fallback anchor stays `state.recipe` (not pass2-mutated output), with pass2 enrichments gated on evidence quality.
- Pass3 acceptance rejects placeholder/empty structures; empty mapping rejection is conditional on missing step/instruction evidence.
- Pass3 `draft_v1` normalization coerces legacy object families into valid `RecipeDraftV1` shape when usable evidence exists, reducing schema_v-triggered fallback churn.
- Pass2 warning bucket naming is `warning_bucket:page_or_layout_artifact`; cutdown/reporting canonicalizes legacy `ocr_or_page_artifact` to the new name for compatibility.
- Pass2 degradation classification is severity-aware (`soft` vs `hard`) with additive routing metadata:
  - `pass2_degradation_severity`
  - `pass2_promotion_policy`
  - `pass3_execution_mode`
  - `pass3_routing_reason`
- Soft-degraded low-risk rows can deterministically promote without pass3 LLM calls while preserving existing pass status enums.
- ProFeedback OG-gap work adds pass2-ok utility/skip instrumentation policy and candidate-label propagation into line-role artifacts; pass2-ok skip is default-on via run settings (`codex_farm_pass3_skip_pass2_ok=true`).

Validation/evidence highlights preserved from merged tasks:
- `Pro3` merged verification transcript includes replayed SeaAndSmoke transport cases (`c0,c6,c7,c8,c9,c12`) with exact-match transport and zero outside-span fallback prompt joins.
- Pass3 legacy-shape normalization task recorded:
  - orchestrator targeted tests (`2 passed`) and full orchestrator suite (`29 passed`) plus contracts suite (`10 passed`).
- ProFeedback OG gap implementation task recorded:
  - `python -m pytest tests/llm/test_codex_farm_orchestrator.py tests/parsing/test_canonical_line_roles.py tests/bench/test_cutdown_export_consistency.py tests/bench/test_benchmark_cutdown_for_external_ai.py` -> `84 passed, 1 warning`.

Known pending/runtime-follow-up captured in merged tasks:
- `2026-03-03_20.13.22` marked paired benchmark rerun and required speed-suite baseline/candidate comparison as remaining validation steps after code/tests/docs implementation.

Anti-loop reminders from this task batch:
- If fallback spikes return, inspect transport audit + pass2 severity/routing metadata before editing prompts.
- If candidate-label diagnostics stay unavailable, inspect line-role prediction payload fields before changing upload-bundle summarizers.
- Keep pass status enums stable for compatibility; prefer additive metadata fields when extending routing observability.

## 2026-03-03 docs/tasks merge digest (ProFeedback rebaseline and closure)

Merged source task file:
- `docs/tasks/ProFeedback.md`

Current LLM-side contracts to keep:
- ProFeedback follow-up scope was benchmark/evaluation only (no default-ingestion enablement changes).
- Pass3 ROI controls now include pass2-ok utility instrumentation plus deterministic skip policy via run settings (`codex_farm_pass3_skip_pass2_ok`); task evidence showed substantial pass3 load reduction when enabled, with no quality regression in cited SeaAndSmoke reruns.
- Routing observability should remain additive and explicit in manifests (`pass2_degradation_severity`, `pass2_promotion_policy`, `pass3_execution_mode`, `pass3_routing_reason` plus pass2-ok utility fields).
- Candidate-label surfacing is now expected end-to-end:
  - line-role predictions include candidate-label payloads,
  - cutdown/export propagates candidate fields,
  - upload bundle `candidate_label_signal` should become available when those artifacts are present.
- Upload-bundle codex diagnostics completeness expectation:
  - when source artifacts exist, codex `run_diagnostics` statuses should resolve to written artifacts rather than blanket `missing`.
- Validation workflow used in this cycle remains the contract for runtime-sensitive LLM changes:
  - targeted llm/parsing/bench tests in `.venv`,
  - paired vanilla/codex benchmark reruns with model/effort locked,
  - required speed regression flow (`bench speed-discover`, `bench speed-run`, `bench speed-compare`).

Anti-loop reminders:
- Do not assume old upload bundles reflect current script behavior; regenerate bundles before concluding diagnostics are still missing.
- If standalone upload bundles show empty call-inventory runtime, check prediction-run manifest telemetry fallback before changing runtime accounting.
- `labelstudio-benchmark --compare-vanilla` is not a valid path now; paired evidence requires separate vanilla and codex runs.

## 2026-03-04 docs/understandings merge digest (codexfarm reliability + feedback gap closure)

Merged source notes (timestamp order):
- `2026-03-03_22.21.36-profeedback-ogplan-vs-completed-audit.md`: Audit note: ProFeedback OG plan milestones are implemented; pass3 token-share evidence comes from prediction-run telemetry when standalone upload-bundle call inventory is empty.
- `2026-03-03_22.32.51-profeedback-ogplan-audit-refresh.md`: Refresh audit: ProFeedback OG milestones are implemented; existing evidence bundles may predate runtime-telemetry fallback regeneration.
- `2026-03-03_23.08.45-saltfat-codex-single-offline-collapse.md`: SaltFat cutdown codex single-offline collapse: atomic split fragmentation + strict chunk parse fallback + outside-span title/howto rule overfire.
- `2026-03-03_23.48.18-feedback-ogplan-code-audit-gaps.md`: Audit result: feedback OG plan is mostly implemented, but deterministic line-role refinements and Milestone-5 validation remain partially incomplete.
- `2026-03-03_23.50.30-codex-farm-no-last-agent-message-recovery-seam.md`: Codex-farm runner seam for recovering from no-last-agent-message chunk failures without aborting full pass runs.
- `2026-03-03_23.53.16-feedback-og-gap-closure-routing-and-line-role.md`: Gap-closure implementation note: canonical line-role sanitizer adds TIME_LINE demotion + neighbor ingredient rescue; pass2-ok selective pass3 skip is now default-on.
- `2026-03-03_23.55.30-codex-no-last-agent-message-content-filter-root-cause.md`: Root cause of codex-farm `no last agent message` on DinnerFor2 pass2: provider `content_filter` stream failures prevent final assistant message emission.
- `2026-03-03_23.58.37-single-offline-codexfarm-full-text-block-guard.md`: Single-offline codexfarm variant can fail immediately when cached conversion payload has `full_text` lines/text but no `blocks` list.
- `2026-03-04_00.01.53-codexfarm-content-filter-terminal-classification.md`: [missing frontmatter summary]
- `2026-03-04_00.03.20-feedback-ogplan-vs-code-audit-refresh.md`: Refresh audit: OG feedback plan is mostly implemented, with remaining gaps in deterministic title/yield constraints and Milestone-5 validation evidence.
- `2026-03-04_00.03.32-codexfarm-full-text-lines-fallback.md`: Codex-farm recipe pass now synthesizes minimal full-text blocks from `full_text.lines` when `full_text.blocks` is missing.

Current LLM contracts reinforced by this batch:
- ProFeedback/feedback gap audits should be interpreted against fresh artifacts; historical bundle snapshots can lag behind runner/generator fixes.
- Codexfarm terminal failure classes (`no last agent message`, `content_filter`, missing full_text blocks) now have explicit recovery/fallback seams and should be debugged through those contracts first.
- Pass3 routing/skip policy and canonical line-role hardening changes are coupled; treat them as one system when evaluating quality/runtime tradeoffs.
- Single-offline codex failures that do not reproduce in vanilla should first check block/payload shape guardrails before prompt/pipeline rewrites.

## 2026-03-04 merged understandings digest (top-tier profile vs pass3-skip control plane)

Merged source note:
- `2026-03-04_01.06.17-top-tier-profile-vs-pass3-skip-env-boundary.md`
- `2026-03-04_01.31.25-top-tier-pass3-skip-profile-baseline-boundary.md`

Current LLM contracts reinforced:
- Interactive top-tier profile selection controls pipeline/splitter settings (`llm_recipe_pipeline`, `line_role_pipeline`, `atomic_block_splitter`) through `RunSettings`.
- Built-in codex and vanilla top-tier baselines explicitly pin `codex_farm_pass1_pattern_hints_enabled=false`.
- Built-in codex and vanilla top-tier baselines explicitly pin `codex_farm_pass3_skip_pass2_ok=true`.
- Codex winner-run harmonization intentionally does not overwrite winner-provided `codex_farm_pass1_pattern_hints_enabled`.
- Codex winner-run harmonization intentionally does not overwrite winner-provided `codex_farm_pass3_skip_pass2_ok`.
- Pass3 pass2-ok skip policy is a persisted run-settings field (`codex_farm_pass3_skip_pass2_ok`) and is now profile/QualitySuite-tunable.
- Pass1 pattern hints policy is a persisted run-settings field (`codex_farm_pass1_pattern_hints_enabled`) and is profile/QualitySuite-tunable.

Anti-loop reminder:
- If pass3 volume changes unexpectedly while profiles stay fixed, inspect run-settings values before editing profile patches.

## 2026-03-04 merged understandings digest (pass-policy control plane + top-tier baseline boundaries)

Merged source notes (timestamp order):
- `docs/understandings/2026-03-04_01.21.40-pass3-skip-settings-first-qualitysuite-surface.md`
- `docs/understandings/2026-03-04_01.24.50-orchestrator-env-benchmark-control-plane.md`
- `docs/understandings/2026-03-04_01.31.25-top-tier-pass3-skip-profile-baseline-boundary.md`
- `docs/understandings/2026-03-04_01.32.00-codexfarm-policy-knobs-settings-only.md`
- `docs/understandings/2026-03-04_01.35.09-pass1-pattern-hints-top-tier-baseline-boundary.md`

Current LLM contracts reinforced:
- Pass-policy knobs are RunSettings-first controls:
  - `codex_farm_pass3_skip_pass2_ok`
  - `codex_farm_pass1_pattern_hints_enabled`
- Orchestrator policy toggles should not reintroduce separate env-only routing for those knobs; QualitySuite/profile tuning should patch RunSettings directly.
- `orchestrator/env` references in docs are shorthand for env-aware logic in `cookimport/llm/codex_farm_orchestrator.py`, not a standalone module.
- Automatic top-tier built-in baselines pin:
  - `codex_farm_pass3_skip_pass2_ok=true`
  - `codex_farm_pass1_pattern_hints_enabled=false`
- Winner harmonization must preserve winner-provided values for both policy knobs while still enforcing codex pipeline trio normalization.

Anti-loop reminder:
- If pass1 hinting or pass3 volume changes while profile choice appears unchanged, inspect resolved RunSettings payload values before editing orchestrator routing logic.

## 2026-03-04 merged understandings digest (Profeedback gap scan, gating hardening, Milestone-5 blockers)

Merged source notes (timestamp order):
- `2026-03-04_09.59.00-profeedback-execplan-code-gap-scan.md`
- `2026-03-04_10.28.11-profeedback2-vs-execplan-coverage-map.md`
- `2026-03-04_10.31.54-profeedback-line-role-pass1-gates-implementation-findings.md`
- `2026-03-04_11.11.52-pass1-eligibility-chapter-page-negative-evidence.md`
- `2026-03-04_11.14.01-profeedback-og-vs-completed-code-gap-audit.md`

Current LLM/line-role contracts reinforced:
- Runtime line-role guardrail arbitration for codex line-role is active post-sanitization, with explicit outside-span containment rules and diagnostics artifacts (`guardrail_report.json`, `guardrail_changed_rows.jsonl`).
- Legacy compatibility copies remain available as `do_no_harm_diagnostics.json` and `do_no_harm_changed_rows.jsonl` when guardrail diagnostics are emitted.
- Outside-span low-confidence escalation is default-off; opt-in remains `COOKIMPORT_LINE_ROLE_OUTSIDE_SPAN_LOW_CONFIDENCE_ESCALATION`.
- Pass1 eligibility is an explicit score-gated pre-pass2 contract, with persisted score/reason/component telemetry and diagnostics artifact output.
- Pass1 eligibility now treats chapter/page metadata as explicit negative evidence (`chapter_page_negative_score=-2` when triggered).
- Profeedback2 coverage check result: core safety milestones are represented in OG plan; telemetry naming cleanup and some finalizer naming topics were intentionally out of scope.

Open-context reminder from this batch:
- Historical audit at `2026-03-04_11.14.01` captured a transient gap state (`toast` imperative miss and compare-root acceptance gap) before the follow-up fix pass landed in later docs/tests.

Anti-loop reminders:
- If pass1 clamp/drop behavior regresses, inspect `eligibility_score_components` and chapter/page metadata fields before modifying prompt/schema layers.
- If outside-span contamination resurfaces, inspect do-no-harm artifacts first rather than retuning benchmark gates.

## 2026-03-04 to 2026-03-06 docs/tasks merge digest (safe defaults, decision boundary, telemetry, and reasoning traces)

Merged source task files (timestamp order):
- `docs/tasks/2026-03-04_22.15.00-fix-codexfarm-reasoning-trace-capture.md`
- `docs/tasks/2026-03-05_22.24.41-fix-safe-deterministic-defaults.md`
- `docs/tasks/2026-03-05_22.25.41-fix-line-role-token-telemetry-gap.md`
- `docs/tasks/2026-03-05_22.43.31-human-owned-codexfarm-decision-boundary.md`

Current LLM contracts reinforced:
- Shared defaults are now deterministic and safe:
  - `RunSettings()` defaults to `llm_recipe_pipeline=off`, `line_role_pipeline=off`, `atomic_block_splitter=off`,
  - helper-based settings construction must match that safe posture rather than silently reintroducing codex-enabled defaults,
  - explicit codex-enabled modes still exist and must opt in deliberately.
- Codex-backed behavior now has one explicit decision layer:
  - `cookimport/config/codex_decision.py` classifies codex surfaces, resolves benchmark/profile contracts, validates command context, and emits manifest metadata,
  - ordinary command surfaces should fail loudly when Codex is implicitly requested without explicit approval,
  - `labelstudio-import --prelabel` counts as its own Codex surface and is not exempt just because recipe parsing is deterministic.
- Line-role Codex usage must produce durable telemetry even when recipe Codex is off:
  - line-role retries are counted,
  - `prediction-run/line-role-pipeline/telemetry_summary.json` is the durable local artifact,
  - benchmark history and analytics must aggregate line-role telemetry with codex-farm telemetry rather than treating them as mutually exclusive.
- Reasoning-trace availability is an upstream-capture contract, not only an exporter contract:
  - prompt sample markdown should include reasoning excerpts when traces exist,
  - `_No thinking trace captured for this sample._` usually means upstream trace capture/classification failed,
  - fix nested capture and trace ingestion before rewriting prompt-sample rendering.

Known bad / anti-loop reminders carried forward:
- `build_run_settings(...)` was a historical bypass seam. If safe-default behavior regresses, inspect helper defaults and decision-layer routing before adding more approval flags.
- Prompt-byte estimates can prove hidden work happened, but they are not a replacement for durable telemetry once the repo now writes telemetry artifacts directly.
