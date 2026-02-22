---
summary: "ExecPlan (implementation-complete record) for adding optional codex-farm pass4 knowledge harvesting in cookimport (recipeimport side)."
read_when:
  - "When enabling or debugging pass4 knowledge harvesting artifacts"
  - "When editing recipe.knowledge.v1 pipeline pack assets or run settings"
---

# ExecPlan: Add Pass 4 “Knowledge Harvesting” for cookimport (recipeimport side)

This ExecPlan is a living document. The sections `Progress`, `Surprises & Discoveries`, `Decision Log`, and `Outcomes & Retrospective` must be kept up to date as work proceeds.

This plan must be maintained in accordance with `docs/PLANS.md` at the repository root.

## Purpose / Big Picture

After this change, `cookimport stage ...` can optionally run a **fourth codex-farm pass** that extracts **general cooking knowledge** from the **non-recipe text** of a block-first cookbook (introductions, technique notes, ingredient guides, equipment notes, etc.), after recipes have already been delineated/processed.

When enabled, cookimport:

- takes the final `nonRecipeBlocks` block stream,
- builds **job bundles** for a codex-farm pipeline,
- runs codex-farm,
- validates the structured outputs strictly,
- writes stable, human-auditable artifacts (`snippets.jsonl` + `knowledge.md`) into the run directory.

All deterministic defaults remain unchanged: the pass is **off unless explicitly enabled**.

## Definitions (plain language)

- **Block**: one extracted unit of text from a source document (PDF/EPUB/etc). Blocks are ordered and have stable indices in the full stream (`full_text`).
- **Recipe span**: a contiguous region of the full block stream that the system considers “this is the recipe”, represented as `[start_block_index, end_block_index)` (end is exclusive).
- **Non-recipe blocks**: all blocks that are not in any accepted recipe span (after any boundary corrections/exclusions are applied).
- **Chunk**: a contiguous set of non-recipe blocks grouped for analysis; cookimport already has deterministic chunking + lane assignment + highlight extraction.
- **Lane**: a heuristic label for a chunk (for example `knowledge` vs `noise`). It is a hint, not a filter.
- **Knowledge snippet**: structured, reusable non-recipe information (tip/technique/substitution/definition/do/don’t), with evidence pointers back to original block indices.
- **Job bundle**: a single JSON input file written by cookimport containing everything the model needs for one task. codex-farm consumes directories of these.
- **codex-farm pipeline**: a named prompt + output schema contract run by `codex-farm process --pipeline ...`. cookimport treats it as “directory in → directory out”.

## Scope and non-scope

In scope (recipeimport side only):

- Build pass4 knowledge job bundles from final non-recipe blocks (heuristics are hints only; no filtering by lane).
- Run codex-farm for pass4 (subprocess runner) and ingest outputs.
- Write stable artifacts under the run directory (JSONL + Markdown preview + run-level index).
- Keep everything opt-in and safe (do nothing unless user enabled the knowledge pass).

Out of scope:

- Implementing codex-farm itself.
- Designing prompts beyond shipping editable local pack assets under `llm_pipelines/`.

## Contract with the codex-farm side

Assumed codex-farm pipeline:

- Pipeline id: `recipe.knowledge.v1` (default, configurable via run settings).
- Input: one JSON job bundle per non-recipe chunk.
- Output: one JSON file per job, schema-validated, containing:
  - `chunk_id` (echo of input chunk id)
  - `is_useful` (boolean)
  - `snippets` (array)
  - each snippet includes `evidence` pointers (`block_index` + short verbatim `quote`)

Local default pack assets shipped in this repo:

- `llm_pipelines/pipelines/recipe.knowledge.v1.json`
- `llm_pipelines/prompts/recipe.knowledge.v1.prompt.md` (prompt text is `.md`)
- `llm_pipelines/schemas/recipe.knowledge.v1.output.schema.json`

## User-visible behavior and how to verify it

After implementation, a human can:

1. Stage a block-first source with pass4 enabled:

       cookimport stage <path> --llm-knowledge-pipeline codex-farm-knowledge-v1

2. Observe per-workbook outputs under the stage run directory:

- Raw codex-farm IO:
  - `raw/llm/<workbook_slug>/pass4_knowledge/in/*.json`
  - `raw/llm/<workbook_slug>/pass4_knowledge/out/*.json`
  - `raw/llm/<workbook_slug>/pass4_knowledge_manifest.json`
- User-facing artifacts:
  - `knowledge/<workbook_slug>/snippets.jsonl`
  - `knowledge/<workbook_slug>/knowledge.md`
- Run-level index (if any knowledge artifacts were written):
  - `knowledge/knowledge_index.json`

3. Spot-check that `chunk.blocks[*].block_index` in a job bundle does not overlap recipe spans (context blocks may overlap; evidence must point to chunk blocks only by prompt contract).

## Progress

- [x] (2026-02-22_16.40.05) Added half-open span utilities + unit tests (`cookimport/llm/non_recipe_spans.py`, `tests/test_non_recipe_spans.py`).
- [x] (2026-02-22_16.40.05) Implemented pass4 job bundle schema + deterministic job writer + idempotence test (`cookimport/llm/codex_farm_knowledge_{contracts,jobs}.py`, `tests/test_knowledge_job_bundles.py`).
- [x] (2026-02-22_16.40.05) Added pass4 output models + ingestion + writer + tests (`cookimport/llm/codex_farm_knowledge_{models,ingest,writer}.py`, `tests/test_knowledge_output_ingest.py`, `tests/test_knowledge_writer.py`).
- [x] (2026-02-22_16.40.05) Wired pass4 into stage (single-file + split-merge) with new run settings + CLI flags; stage writes `knowledge_index.json`.
- [x] (2026-02-22_16.40.05) Shipped local codex-farm pipeline assets for `recipe.knowledge.v1` and updated pack-asset tests.
- [x] (2026-02-22_16.40.05) Added operator docs (`docs/10-llm/knowledge_harvest.md`) and updated conventions (`docs/IMPORTANT CONVENTIONS.md`, `docs/05-staging/05-staging_readme.md`).

## Surprises & Discoveries

- Observation: `KnowledgeChunk.blockIds` are relative indices into the input list passed to the chunker, not absolute `full_text` indices.
  Evidence: chunker appends `i` from the local loop; pass4 job writing must map `relative_id -> sequence[relative_id]["index"]`.

- Observation: chunking the full `nonRecipeBlocks` list can accidentally bridge across recipe-span gaps (because recipe blocks are removed).
  Evidence: pass4 job builder splits `nonRecipeBlocks` into contiguous sequences of absolute indices before chunking so each chunk maps cleanly back to the original stream.

## Decision Log

- Decision: Store pass4 codex-farm IO under `raw/llm/<workbook_slug>/pass4_knowledge/{in,out}` and write user-facing artifacts under `knowledge/<workbook_slug>/`.
  Rationale: matches existing recipe codex-farm artifact conventions and keeps outputs easy to browse.
  Date/Author: 2026-02-22 / GPT-5.2 Codex

- Decision: Gate pass4 behind a dedicated run setting (`llm_knowledge_pipeline`) and keep defaults deterministic (`off`).
  Rationale: prevents silent token spend; aligns with existing `llm_recipe_pipeline` gating.
  Date/Author: 2026-02-22 / GPT-5.2 Codex

- Decision: Embed pass4 report metadata under `ConversionReport.llmCodexFarm["knowledge"]`.
  Rationale: avoids schema churn on `ConversionReport` while keeping LLM metadata auditable in the report.
  Date/Author: 2026-02-22 / GPT-5.2 Codex

## Outcomes & Retrospective

- Outcome: cookimport can now optionally run a codex-farm pass4 knowledge harvesting step, producing validated snippet artifacts with evidence pointers and a human-readable preview.
- Outcome: local pipeline-pack assets for `recipe.knowledge.v1` are shipped under `llm_pipelines/` and covered by tests.
- Verification: offline pytest suite only; no live codex-farm/token-spending execution was performed in verification.

Plan update note: This file was updated from a draft plan into an implementation-complete record, removing stale assumptions (separate `llm_jobs/` + `llm_out/` layout and standalone CLI subcommands) and aligning paths/contracts to the shipped stage-integrated implementation.
