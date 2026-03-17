---
summary: "How the optional codex-farm knowledge stage reviews seed non-recipe spans, refines final authority, and writes its artifacts."
read_when:
  - "When enabling or debugging optional knowledge extraction outputs"
  - "When editing the compact knowledge-stage codex-farm pipeline prompt/schema assets"
---

# Optional Knowledge Refinement And Extraction (codex-farm)

The knowledge stage is an **optional** codex-farm pipeline that reviews seed Stage 7 non-recipe spans, can refine final `knowledge` versus `other` ownership, and extracts **general cooking knowledge** (tips, techniques, definitions, substitutions, do/don't guidance) from the spans that remain knowledge.

The deterministic classifier runs first and always writes:

- `08_nonrecipe_spans.json`
- `09_knowledge_outputs.json`

Those files are the authoritative outside-recipe ownership boundary. They now preserve both the deterministic seed and the final post-knowledge authority. The LLM stage no longer publishes `block_classifications.jsonl`; instead it returns `block_decisions` that merge into the final authority recorded in those artifacts.

It is **off by default** and does nothing unless explicitly enabled.

## How to run

From repo root:

    source .venv/bin/activate
    cookimport stage <path> --llm-knowledge-pipeline codex-farm-knowledge-v1

Optional knobs:

- `--codex-farm-pipeline-knowledge recipe.knowledge.compact.v1`
- `--codex-farm-knowledge-context-blocks 0`
- `--codex-farm-root <pack_root>` and `--codex-farm-workspace-root <dir>`
- `--table-extraction on` (recommended for table-heavy books; compact knowledge bundles then include `chunk.blocks[*].table_hint`)

Chunking note:
- knowledge-stage inputs now come from seed Stage 7 non-recipe spans, then apply the existing adjacent-chunk consolidation logic inside each seed span.
- compact knowledge jobs now bundle surviving chunks across neighboring seed spans when they stay local, including small bridged gaps up to 10 blocks, so prompt count tracks broader outside-recipe regions instead of one chunk per prompt.
- standalone heading fragments and tiny bridge chunks are collapsed before bundling so decorative section seams do not become their own Codex jobs.
- table chunks are intentionally excluded from consolidation and remain isolated.
- deterministic `noise` routing is intentionally stricter for obvious junk such as blurbs, navigation fragments, attribution-only lines, and ad copy; explanatory cooking prose should still survive into bundled review.
- a second deterministic savings pass now drops tiny low-signal knowledge chunks (`<=240` chars with no heading context, no highlights, and no table content) before Codex job writing.

## Output locations

Per staged workbook (`<workbook_slug>`):

- Raw codex-farm IO:
  - `data/output/<ts>/raw/llm/<workbook_slug>/knowledge/in/*.json`
  - `data/output/<ts>/raw/llm/<workbook_slug>/knowledge/out/*.json`
  - `data/output/<ts>/raw/llm/<workbook_slug>/knowledge_manifest.json`
- Canonical stage artifacts:
  - `data/output/<ts>/08_nonrecipe_spans.json`
  - `data/output/<ts>/09_knowledge_outputs.json`
- Reviewer-facing extraction artifacts:
  - `data/output/<ts>/knowledge/<workbook_slug>/snippets.jsonl`
  - `data/output/<ts>/knowledge/<workbook_slug>/knowledge.md`

Run-level index (if any knowledge artifacts were written):

- `data/output/<ts>/knowledge/knowledge_index.json`

Manifest/runtime note:
- `knowledge_manifest.json` now advertises `input_mode = "stage7_seed_nonrecipe_spans"` and reports whether the stage changed final authority.
- manifest `counts` now distinguish bundle count (`jobs_written`) from surviving chunk count (`chunks_written`).
- If Stage 7 finds zero non-recipe spans, the manifest is still written as a successful no-op with zero jobs.

## Pipeline assets

Local default pack files:

- `llm_pipelines/pipelines/recipe.knowledge.compact.v1.json`
- `llm_pipelines/prompts/recipe.knowledge.compact.v1.prompt.md`
- `llm_pipelines/schemas/recipe.knowledge.v1.output.schema.json`

`table_hint` contract note:
- When table extraction is enabled, compact knowledge input can include `chunk.blocks[*].table_hint` (`table_id`, `caption`, `row_index_in_table`) to help structural interpretation.
- Evidence still must quote verbatim from `chunk.blocks[*].text`.

Bundle contract note:
- compact knowledge input is now `bundle_version = "2"` with `bundle_id`, shared local context, and `chunks[*]`.
- compact knowledge output is now `bundle_version = "2"` with short keys `v`, `bid`, and `r`; nested results also use short keys to cut structured-output overhead.
