---
summary: "How to run the optional codex-farm pass4 knowledge harvesting workflow and where its artifacts live."
read_when:
  - "When enabling or debugging pass4 knowledge harvesting outputs"
  - "When editing the recipe.knowledge.v1 codex-farm pipeline prompt/schema assets"
---

# Pass 4: Knowledge Harvesting (codex-farm)

Pass 4 is an **optional** codex-farm pipeline that extracts **general cooking knowledge** (tips, techniques, definitions, substitutions, do/don’t guidance) from the **non-recipe text** in a block-first cookbook source (EPUB/PDF/text extractors that emit `full_text` blocks and `nonRecipeBlocks`).

It is **off by default** and does nothing unless explicitly enabled.

## How to run

From repo root:

    source .venv/bin/activate
    cookimport stage <path> --llm-knowledge-pipeline codex-farm-knowledge-v1

Optional knobs:

- `--codex-farm-pipeline-pass4-knowledge recipe.knowledge.v1`
- `--codex-farm-knowledge-context-blocks 12`
- `--codex-farm-root <pack_root>` and `--codex-farm-workspace-root <dir>`

## Output locations

Per staged workbook (`<workbook_slug>`):

- Raw codex-farm IO:
  - `data/output/<ts>/raw/llm/<workbook_slug>/pass4_knowledge/in/*.json`
  - `data/output/<ts>/raw/llm/<workbook_slug>/pass4_knowledge/out/*.json`
  - `data/output/<ts>/raw/llm/<workbook_slug>/pass4_knowledge_manifest.json`
- User-facing artifacts:
  - `data/output/<ts>/knowledge/<workbook_slug>/snippets.jsonl`
  - `data/output/<ts>/knowledge/<workbook_slug>/knowledge.md`

Run-level index (if any knowledge artifacts were written):

- `data/output/<ts>/knowledge/knowledge_index.json`

## Pipeline assets

Local default pack files:

- `llm_pipelines/pipelines/recipe.knowledge.v1.json`
- `llm_pipelines/prompts/recipe.knowledge.v1.prompt.md`
- `llm_pipelines/schemas/recipe.knowledge.v1.output.schema.json`
