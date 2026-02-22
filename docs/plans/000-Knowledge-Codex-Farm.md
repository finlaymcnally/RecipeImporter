---
summary: "Implementation-complete record for codex-farm 3-pass recipe/knowledge boundary integration on recipeimport side, including external pack configurability."
read_when:
  - "When wiring cookimport to an external codex-farm pipeline pack"
  - "When changing codex-farm run settings, pass pipeline IDs, or workspace-root behavior"
---

# ExecPlan: Integrate codex-farm 3-pass knowledge-aware extraction into cookimport (recipeimport side)

IT IS INCREDIBLY IMPORTANT TO NOTE THAT YOU MUST NOT RUN THE CODEX FARM INTEGRAITON. BUILD THIS BUT DO NOT TEST IT "LIVE" BY ACTUALLY SUMMONING CODEX INSTANCES UNTIL I HAVE HAD A TIME TO THINK ABOUT HOW I WANT TO MANAGE TOKEN USE. DO NOT TEST THIS IN A WAY THAT CAUSES THE CODEX FARM PROGRAM TO USE TOKENS PLEASE!!!

This ExecPlan is a living document. The sections `Progress`, `Surprises & Discoveries`, `Decision Log`, and `Outcomes & Retrospective` are maintained in accordance with `docs/PLANS.md`.

## Purpose / Big Picture

Enable an opt-in codex-farm 3-pass recipe correction path that also improves knowledge chunk quality by recomputing non-recipe blocks after pass1 boundary corrections. Keep deterministic behavior as default (`llm_recipe_pipeline=off`), and support external codex-farm pipeline packs without editing cookimport code.

## Progress

- [x] (2026-02-22_14.43.25) Core 3-pass codex-farm orchestration shipped on recipeimport side (contracts, runner, orchestrator, stage + pred-run wiring, manifest/report surfacing, deterministic fallback behavior).
- [x] (2026-02-22_14.43.25) Split-merge path integration shipped, including merged full-text reconstruction/rebasing before codex-farm pass1 on split EPUB/PDF runs.
- [x] (2026-02-22_14.43.25) Baseline test coverage shipped for contracts/orchestrator/CLI flags/run-manifest parity without live codex-farm calls.
- [x] (2026-02-22_15.31.00) Added external-pack configurability: run settings + CLI/pred-run threading for `codex_farm_workspace_root` and pass pipeline IDs (`codex_farm_pipeline_pass1/2/3`).
- [x] (2026-02-22_15.31.00) Updated subprocess runner/orchestrator to pass explicit codex-farm `--root` and optional `--workspace-root`; manifest now records effective pass pipeline IDs.
- [x] (2026-02-22_15.31.00) Added local `llm_pipelines/` skeleton placeholder so default root contract exists (`pipelines/`, `prompts/`, `schemas/`).
- [x] (2026-02-22_15.31.00) Updated docs/tests for new codex-farm knobs and parity guarantees; verified with offline pytest suite only.

## Surprises & Discoveries

- Observation: Hardcoded pass pipeline IDs prevented clean integration with external codex-farm packs that may use different pipeline IDs.
  Evidence: orchestrator previously always invoked `recipe.chunking.v1`, `recipe.schemaorg.v1`, and `recipe.final.v1` constants.

- Observation: Missing local `llm_pipelines/` folder caused default-root validation failures when codex-farm mode was enabled without explicit `--codex-farm-root`.
  Evidence: `_resolve_pipeline_root(...)` requires `pipelines/`, `prompts/`, and `schemas/` directories.

## Decision Log

- Decision: Keep deterministic pipeline as default and require explicit opt-in (`llm_recipe_pipeline=codex-farm-3pass-v1`).
  Rationale: preserves existing behavior and avoids silent token spend.
  Date/Author: 2026-02-22 / ChatGPT

- Decision: Keep 3-pass architecture (pass1 boundaries -> pass2 schema.org -> pass3 final draft) and retain pass1-driven recomputation of `non_recipe_blocks`.
  Rationale: this is the minimal working lane that improves recipe extraction while directly improving downstream knowledge chunk boundaries.
  Date/Author: 2026-02-22 / ChatGPT

- Decision: Add run-configurable pass pipeline IDs and workspace root instead of only hardcoded/default-root behavior.
  Rationale: external codex-farm pipeline packs must be swappable without code changes.
  Date/Author: 2026-02-22 / GPT-5 Codex

- Decision: Keep both env (`CODEX_FARM_ROOT`) and explicit CLI root/workspace arguments for subprocess calls.
  Rationale: explicit `--root`/`--workspace-root` makes the subprocess contract unambiguous and aligns with codex-farm integration contracts.
  Date/Author: 2026-02-22 / GPT-5 Codex

## Outcomes & Retrospective

- Outcome: knowledge-aware recipe correction pipeline is fully wired and configurable in both stage and benchmark prediction-generation paths, with offline-safe tests and deterministic fallback semantics.
- What remains: no live codex-farm/token-spending validation was run in this implementation pass by explicit request.
- Lessons learned: external-pipeline integration stability depends on surfacing pipeline IDs/workspace/root as first-class run settings, not hardcoded constants.

## Context and Orientation

Primary runtime files:

- `cookimport/config/run_settings.py` (canonical run-setting schema + summary/hash)
- `cookimport/llm/codex_farm_contracts.py` (pass contracts)
- `cookimport/llm/codex_farm_runner.py` (subprocess boundary)
- `cookimport/llm/codex_farm_orchestrator.py` (3-pass orchestration, manifest/report payloads, pass1 non-recipe recomputation)
- `cookimport/cli_worker.py` and `cookimport/cli.py` (stage + split-merge integration)
- `cookimport/labelstudio/ingest.py` (prediction-run generation integration)

## Implemented Work

This implementation pass completed the remaining external-pack integration pieces on top of the shipped recipe-side codex-farm lane:

- Added run settings and CLI support for:
  - `codex_farm_workspace_root`
  - `codex_farm_pipeline_pass1`
  - `codex_farm_pipeline_pass2`
  - `codex_farm_pipeline_pass3`
- Threaded those settings across:
  - `cookimport stage`
  - interactive import/benchmark run-settings paths
  - Label Studio import and benchmark prediction generation (`generate_pred_run_artifacts` path)
- Updated orchestrator to:
  - resolve effective pipeline IDs from run settings
  - pass `root_dir` and optional `workspace_root` into runner invocations
  - persist effective pipeline IDs and workspace root in `llm_manifest.json`
- Added local placeholder pack root at `llm_pipelines/` with required subdirectories.

## Concrete Steps

Commands run from repository root:

    source .venv/bin/activate
    python -m py_compile \
      cookimport/config/run_settings.py \
      cookimport/llm/codex_farm_runner.py \
      cookimport/llm/fake_codex_farm_runner.py \
      cookimport/llm/codex_farm_orchestrator.py \
      cookimport/cli.py \
      cookimport/labelstudio/ingest.py

    source .venv/bin/activate
    pytest -q \
      tests/test_run_settings.py \
      tests/test_cli_llm_flags.py \
      tests/test_codex_farm_orchestrator.py \
      tests/test_run_manifest_parity.py \
      tests/test_labelstudio_benchmark_helpers.py

Result:

- `52 passed, 2 warnings` (offline only)

## Validation and Acceptance

Automated acceptance completed without live codex-farm/token usage.

- Stage/help surfaces new codex-farm options (workspace root + pass pipeline IDs).
- Run settings and manifest parity now include pass pipeline ID knobs.
- Orchestrator tests verify configured pipeline IDs and workspace/root propagation to runner interface.
- Label Studio benchmark helper tests pass with new option threading.

## Idempotence and Recovery

- Changes are additive and backward compatible:
  - Existing defaults preserve previous behavior and pipeline IDs.
  - `llm_recipe_pipeline=off` remains deterministic and bypasses codex-farm.
- Operational rollback:
  - disable via `--llm-recipe-pipeline off`.
- Code rollback:
  - revert this task’s run-setting/runner/orchestrator wiring changes.

## Artifacts and Notes

- Added local placeholder pipeline-pack root: `llm_pipelines/`.
- Updated docs and tests for the new codex-farm knobs.

## Interfaces and Dependencies

New/expanded interface contract:

- Run settings fields:
  - `codex_farm_workspace_root: str | None`
  - `codex_farm_pipeline_pass1: str`
  - `codex_farm_pipeline_pass2: str`
  - `codex_farm_pipeline_pass3: str`
- Runner interface:
  - `run_pipeline(..., root_dir: Path | None = None, workspace_root: Path | None = None)`
- Orchestrator manifest/report now includes effective per-pass pipeline IDs.

Plan update note: this file was converted from planning-draft state (unchecked milestones, missing front matter, stale assumptions) into an implementation-complete operational record aligned with shipped behavior.
