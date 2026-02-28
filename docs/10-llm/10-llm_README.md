---
summary: "Current LLM integration boundaries for codex-farm in stage, prediction-run, and tag flows."
read_when:
  - When changing codex-farm settings or pipeline IDs
  - When debugging pass4 knowledge or pass5 tag artifacts
  - When auditing recipe pipeline policy-lock behavior
  - When reconciling Label Studio prediction-run LLM wiring vs stage wiring
---

# LLM Section Reference

LLM usage in this repo is limited, optional, and explicitly gated.

## Runtime surface

Settings and entrypoints:

- `cookimport/config/run_settings.py` (canonical settings, UI choices, policy lock coercion)
- `cookimport/cli.py` (stage + benchmark + Label Studio command normalization/gating)
- `cookimport/entrypoint.py` (saved settings -> stage defaults pass-through)
- `cookimport/labelstudio/ingest.py` (prediction-run generation + recipe-pass gating)

Stage execution paths:

- `cookimport/cli_worker.py` (single-file stage path recipe/pass4 execution)
- `cookimport/cli.py` (`_merge_split_jobs` split-merge stage path recipe/pass4 execution)
- `cookimport/cli.py` (`run_stage_tagging_pass` trigger for pass5 after stage writes)
- `cookimport/staging/writer.py` (stage block predictions writer receives pass4 snippet path)
- `cookimport/staging/stage_block_predictions.py` (uses knowledge snippets for stage evidence labeling)

Recipe codex-farm pass modules (implementation is present; recipe pass is env-gated via `COOKIMPORT_ALLOW_CODEX_FARM=1`):

- `cookimport/llm/codex_farm_orchestrator.py` (pass1/pass2/pass3 orchestration)
- `cookimport/llm/codex_farm_contracts.py` (strict pass1/2/3 bundle contracts)
- `cookimport/llm/codex_farm_ids.py` (stable slug/id/bundle filename helpers)
- `cookimport/llm/codex_farm_runner.py` (subprocess runner + shared error type)

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

## Policy boundary (current behavior)

- `llm_recipe_pipeline` supports `off` and `codex-farm-3pass-v1`, but enabling Codex Farm requires `COOKIMPORT_ALLOW_CODEX_FARM=1`.
- CLI and Label Studio prediction-run normalizers enforce the env gate (non-`off` values error unless unlocked).
- `RunSettings.from_dict` coerces non-`off` values back to `off` with a warning unless `COOKIMPORT_ALLOW_CODEX_FARM=1` is set.
- Bench all-method permutations include Codex Farm variants only when explicitly requested (for example `cookimport bench ... --include-codex-farm`) and unlocked via env.
- `codex_farm_failure_mode` still controls behavior for active LLM passes (`fail` or `fallback`).

## Active optional passes

### Pass4 knowledge harvesting

Enable with:

- `llm_knowledge_pipeline=codex-farm-knowledge-v1`
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
- `codex_farm_root`
- `codex_farm_workspace_root`
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
- Pass4 knowledge harvesting and pass5 tag suggestions are stage-only flows; prediction-run generation does not execute those passes.
- Benchmark prediction generation (`labelstudio-benchmark`) reuses that same prediction-run recipe-pass boundary.

Recipe pass execution in prediction-run paths is env-gated via normalizers (`COOKIMPORT_ALLOW_CODEX_FARM=1`).

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
- Stage-relevant LLM runtime remains centered on pass4 knowledge and pass5 tags; recipe pass1/2/3 is available but env-gated (`COOKIMPORT_ALLOW_CODEX_FARM=1`) for stage/pred-run use.
- Prediction-run generation currently wires recipe-pass settings only; pass4/pass5 execution remains stage-only.
- LLM docs should keep runtime-adjacent module coverage explicit (prediction wrappers, pass4 helper contracts/writer paths, pass5 provider/validation layer, stage evidence/report consumers).
- Legacy modules (`client.py`, `prompts.py`, `repair.py`) remain non-primary runtime paths and should stay labeled accordingly.

## 2026-02-28 migrated understandings digest (Oracle + Codex Farm ops)

### 2026-02-28_01.58.55 Oracle browser login/session blocker
- Source: `docs/understandings/2026-02-28_01.58.55-oracle-browser-login-session-blocker.md`
- Recurring Oracle browser failures were traced to missing ChatGPT browser auth plus unwritable default session paths under `~/.oracle` in Codex sandbox contexts.
- Local wrapper defaults were moved to writable persistent paths under `/home/mcnal/.local/share/oracle` with `/tmp` fallback and pre-created `sessions/` directories.

### 2026-02-28_03.17.29 Codex Farm opt-in command pattern
- Source: `docs/understandings/2026-02-28_03.17.29-codex-farm-opt-in-command-pattern.md`
- Keep global defaults deterministic (`llm_recipe_pipeline=off`); enable Codex Farm only per-command with explicit env gate and command wrapper.
- Absolute `codex_farm_cmd` paths avoid PATH fragility when Codex Farm is outside shell defaults.

### 2026-02-28_03.19.05 Oracle gpt-5.2-thinking browser blocker
- Source: `docs/understandings/2026-02-28_03.19.05-oracle-gpt52-thinking-browser-blocker.md`
- In this sandbox, gpt-5.2-thinking Oracle browser runs were blocked by browser/auth/session constraints (stuck runs or early chrome-close errors), not prompt/file bundle construction.

### 2026-02-28_03.19.48 interactive Codex Farm gate and launcher
- Source: `docs/understandings/2026-02-28_03.19.48-interactive-codex-farm-gate-and-launcher.md`
- Interactive mode already respects run-settings `llm_recipe_pipeline`; Codex Farm still requires `COOKIMPORT_ALLOW_CODEX_FARM=1`.
- Wrapper launcher pattern (`scripts/interactive-with-codex-farm.sh`) enables opt-in sessions without changing default interactive behavior.
