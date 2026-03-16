---
summary: "AI onboarding for the current post-refactor cookimport architecture."
read_when:
  - When an AI agent or new developer needs the current mental model for the repo
  - When you need a high-level map before diving into the numbered subsystem docs
---

# AI Context: `cookimport` (code-verified on 2026-03-16)

This is the fast orientation doc for the current repo.

Use this file to understand the product shape, the current authority boundaries, and which deeper docs own each subsystem. For detailed contracts, read the numbered docs in `docs/01-architecture` through `docs/12-testing`.

## 1. What this project is now

`cookimport` is a deterministic-first local recipe-import pipeline with optional Codex-backed stages, freeform Label Studio workflows, and benchmark/analytics tooling built around the same staged artifacts.

The post-refactor mental model is:

1. importer gets source material into normalized recipe/non-recipe candidates and raw artifacts
2. label-first staging becomes the authority for recipe vs non-recipe ownership
3. deterministic recipe building produces intermediate and final drafts
4. optional Codex stages can correct labels, recipes, or knowledge outputs
5. downstream Label Studio, benchmark, and analytics flows reuse those staged artifacts instead of inventing a second architecture

Primary roots:

- `data/input` for incoming source files
- `data/output/<YYYY-MM-DD_HH.MM.SS>/` for staged runs
- `data/golden/` for Label Studio exports, benchmark runs, and review artifacts
- `.history/` for cross-run analytics and dashboard state

## 2. Current runtime architecture

### 2.1 Source conversion still starts with importers

Importers are selected by score through `cookimport/plugins/registry.py` and implement the shared contract from `cookimport/plugins/base.py`.

Active importer families:

- Excel
- text / markdown / DOCX
- PDF
- EPUB
- Paprika
- RecipeSage
- webschema

Importer conversion returns a `ConversionResult` with recipe candidates, tips, topic candidates, non-recipe material, raw artifacts, and a conversion report.

### 2.2 Label-first staging is now the authority boundary

The central runtime seam is `cookimport/staging/import_session.py`.

Every stage/prediction run now starts by building authoritative labels via `build_label_first_stage_result(...)`, then writing:

- `label_det/<workbook_slug>/...`
- `label_llm_correct/<workbook_slug>/...` when line-role Codex correction runs
- `group_recipe_spans/<workbook_slug>/...`

Those artifacts are the current source of truth for recipe ownership. Authoritative rows publish:

- `decided_by`
- `reason_tags`
- `escalation_reasons`

Important rule:

- if importer candidates existed but authoritative regrouping yields zero recipes, the run stays on the label-first result and writes `group_recipe_spans/<workbook_slug>/authority_mismatch.json` instead of silently reverting to importer-owned recipe candidates

### 2.3 Recipe building is deterministic-first, with one main recipe Codex seam

Current semantic recipe stage keys are:

- `build_intermediate_det`
- `recipe_llm_correct_and_link`
- `build_final_recipe`

The current public recipe pipeline id is:

- `codex-farm-single-correction-v1`

Current recipe flow:

1. deterministic code builds an intermediate `RecipeCandidate`
2. optional Codex correction updates that candidate and emits `ingredient_step_mapping` plus raw selected tags
3. deterministic code rebuilds final cookbook drafts locally

Inline recipe tagging is not a standalone subsystem anymore. Tags ride on the recipe-correction contract and are normalized into:

- `final drafts/.../r*.json` as `recipe.tags`
- `intermediate drafts/.../r*.jsonld` as `keywords`

### 2.4 Non-recipe ownership and knowledge are stage-backed too

Outside-recipe ownership is now handled by deterministic Stage 7 classification in `cookimport/staging/nonrecipe_stage.py`.

Run-level non-recipe artifacts:

- `08_nonrecipe_spans.json`
- `09_knowledge_outputs.json`

Optional knowledge extraction writes under:

- `knowledge/<workbook_slug>/...`
- `raw/llm/<workbook_slug>/knowledge/...`
- `raw/llm/<workbook_slug>/knowledge_manifest.json`

`08_nonrecipe_spans.json` is the authoritative `knowledge` vs `other` machine-readable seam. Reviewer-facing snippets are downstream evidence, not the main ownership contract.

### 2.5 Stage observability is semantic now

Run-level stage indexing lives in `stage_observability.json` and uses semantic keys from `cookimport/runs/stage_observability.py`.

Current stage families include:

- `label_det`
- `label_llm_correct`
- `group_recipe_spans`
- `classify_nonrecipe`
- `build_intermediate_det`
- `recipe_llm_correct_and_link`
- `build_final_recipe`
- `extract_knowledge_optional`
- `write_outputs`

If you are reading old docs, tests, or artifacts that still imply numbered pass slots, treat them as historical noise, not the current architecture.

## 3. Entrypoints and command surface

`pyproject.toml` currently defines these scripts:

- `cookimport` -> main Typer app
- `cf-debug` -> follow-up/debug CLI for existing benchmark `upload_bundle_v1` bundles
- `import` and `C3import` -> stage-on-default-input wrappers
- `C3imp` -> interactive wrapper

`cookimport --help` currently exposes:

- `stage`
- `perf-report`
- `stats-dashboard`
- `benchmark-csv-backfill`
- `inspect`
- `labelstudio-import`
- `labelstudio-export`
- `labelstudio-eval`
- `debug-epub-extract`
- `labelstudio-benchmark`
- `bench`
- `compare-control`
- `epub`

Two practical distinctions matter:

- `cookimport` with no subcommand enters interactive mode
- `cf-debug` is a separate CLI for benchmark follow-up packets and prompt/knowledge audits, not a subcommand of `cookimport`

## 4. LLM boundary

LLM usage is optional and all live Codex-backed surfaces run through CodexFarm.

Current live surfaces:

- `llm_recipe_pipeline`: `off` or `codex-farm-single-correction-v1`
- `line_role_pipeline`: `off`, `deterministic-v1`, or `codex-line-role-v1`
- `llm_knowledge_pipeline`: `off` or `codex-farm-knowledge-v1`
- freeform prelabel: CodexFarm pipeline `prelabel.freeform.v1`

Default posture is safe/off:

- deterministic-first behavior is the baseline
- execute mode requires explicit approval at the command boundary
- plan mode writes a Codex execution plan without running live Codex work

## 5. Label Studio and benchmark model

### 5.1 Label Studio is freeform-only now

The active Label Studio scope is:

- `freeform-spans`

Current commands:

- `labelstudio-import`
- `labelstudio-export`
- `labelstudio-eval`
- `labelstudio-benchmark`

Import/export/eval/benchmark flows are all built around freeform span artifacts and their canonicalized projections.

### 5.2 Benchmarking has three active surfaces

- `cookimport bench ...` for speed/quality suites and artifact retention
- `cookimport labelstudio-benchmark` for single-run prediction/eval/compare flows
- `cf-debug ...` for deterministic follow-up packets on top of `upload_bundle_v1`

Current benchmark scoring modes:

- `stage-blocks`
- `canonical-text`

Primary scored prediction artifact:

- `stage_block_predictions.json`

That artifact is generated from staged outputs and is the benchmark evidence seam downstream tools are expected to trust.

## 6. Output and path conventions

Timestamp format is critical and repo-wide:

- `YYYY-MM-DD_HH.MM.SS`

Important roots and artifacts:

- stage runs: `data/output/<timestamp>/`
- Label Studio import runs: `data/golden/sent-to-labelstudio/<timestamp>/labelstudio/<book_slug>/`
- Label Studio exports: `data/golden/pulled-from-labelstudio/<source_or_project_slug>/exports/`
- benchmark/eval runs: `data/golden/benchmark-vs-golden/<timestamp>/`
- stage benchmark evidence: `.bench/<workbook_slug>/stage_block_predictions.json`
- run traceability: `run_manifest.json`
- run stage index: `stage_observability.json`
- stage summaries: `run_summary.json` and optional `run_summary.md`
- analytics history: `.history/performance_history.csv`
- dashboard output: `.history/dashboard/`

Tables are now always extracted for stage/prediction runs. The old `table_extraction` toggle is not part of the ordinary current product surface.

## 7. Current directory map

```text
cookimport/
├── cli.py                    # Main command surface
├── c3imp_entrypoint.py       # Interactive wrapper
├── entrypoint.py             # import / C3import wrapper
├── cf_debug_cli.py           # Benchmark follow-up CLI
├── cli_worker.py             # Worker-side stage execution
├── plugins/                  # Importers and registry
├── parsing/                  # Label-first logic, sectioning, ingredients, EPUB helpers
├── staging/                  # Import session, draft shaping, writers, stage evidence
├── labelstudio/              # Freeform task import/export/eval/prelabel
├── bench/                    # Offline benchmark tooling
├── analytics/                # History, dashboard, compare/control
├── llm/                      # CodexFarm orchestration and prompt artifacts
├── config/                   # Run settings and persistence
├── runs/                     # run_manifest and stage_observability
├── core/                     # Shared models, IDs, reporting, timing
├── cli_ui/                   # Interactive run-settings flow
├── epubdebug/                # EPUB debugging utilities
└── ocr/                      # OCR backends
```

## 8. Recommended docs map

Read these after this file, depending on the task:

- architecture and module boundaries: `docs/01-architecture/01-architecture_README.md`
- command surface and interactive mode: `docs/02-cli/02-cli_README.md`
- importer behavior and split-job merge: `docs/03-ingestion/03-ingestion_readme.md`
- parsing details: `docs/04-parsing/04-parsing_readme.md`
- staging/output contracts: `docs/05-staging/05-staging_readme.md`
- Label Studio flows: `docs/06-label-studio/06-label-studio_README.md`
- benchmark workflows: `docs/07-bench/07-bench_README.md`
- analytics/dashboard/compare-control: `docs/08-analytics/08-analytics_readme.md`
- inline recipe tagging: `docs/09-tagging/09-tagging_README.md`
- CodexFarm boundaries: `docs/10-llm/10-llm_README.md`
- reference schemas and inventories: `docs/11-reference/11-reference_README.md`
- test layout and low-noise test commands: `docs/12-testing/12-testing_README.md`

## 9. Practical guidance for future agents

- Start from the numbered doc for the subsystem you are touching, not from old task notes or historical plans.
- When a runtime question is really about truth ownership, inspect the label-first artifacts first.
- When a downstream tool disagrees with staged output, check `stage_observability.json`, `run_manifest.json`, and the canonical artifact pointers before assuming scoring or export code is wrong.
- Do not invent a second tagging, benchmark, or Label Studio architecture. The current repo is intentionally converging those surfaces onto the staged artifact model.
