---
summary: "How the optional shard-runtime non-recipe knowledge review stage refines seed non-recipe spans and writes its artifacts."
read_when:
  - "When enabling or debugging optional non-recipe knowledge review outputs"
  - "When editing the compact knowledge-stage codex-farm pipeline prompt/schema assets"
---

# Optional Non-Recipe Knowledge Review

The knowledge stage is an **optional** shard-worker CodexFarm phase that reviews seed Stage 7 non-recipe spans, can refine final `knowledge` versus `other` ownership, and extracts **general cooking knowledge** (tips, techniques, definitions, substitutions, do/don't guidance) from the spans that remain knowledge.

The deterministic classifier runs first and always writes:

- `08_nonrecipe_spans.json`
- `09_knowledge_outputs.json`

Those files are the authoritative outside-recipe ownership boundary. They now preserve both the deterministic seed and the final post-knowledge authority. The LLM stage no longer publishes `block_classifications.jsonl`; instead it returns `block_decisions` that merge into the final authority recorded in those artifacts while keeping richer internal reviewer categories inside the refinement seam.

It is **off by default** and does nothing unless explicitly enabled.

## How to run

From repo root:

    source .venv/bin/activate
    cookimport stage <path> --llm-knowledge-pipeline codex-knowledge-shard-v1

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
- deterministic semantic lane judgments no longer decide whether a chunk reaches the LLM reviewer, and the old low-signal prefilter is gone too. If deterministic chunking produces a non-recipe chunk at all, the reviewer now sees its raw chunk text.
- the model-facing payload now avoids deterministic semantic chunk hints entirely; it carries raw block text plus mechanically true structure only.
- `knowledge_prompt_target_count` is now a literal shard-count override. When set, the planner partitions the ordered non-recipe chunk list into that many contiguous non-empty shards whenever enough chunks exist.
- if a forced shard exceeds the old chunk, char, locality, or table-isolation heuristics, the planner now records warnings instead of silently increasing shard count.
- if the operator requests more shards than there are chunks, the planner emits one non-empty shard per chunk and warns that the exact count could not be achieved without empty shards.

## Output locations

Per staged workbook (`<workbook_slug>`):

- Runtime artifacts:
  - `data/output/<ts>/raw/llm/<workbook_slug>/knowledge/phase_manifest.json`
  - `data/output/<ts>/raw/llm/<workbook_slug>/knowledge/shard_manifest.jsonl`
  - `data/output/<ts>/raw/llm/<workbook_slug>/knowledge/worker_assignments.json`
  - `data/output/<ts>/raw/llm/<workbook_slug>/knowledge/promotion_report.json`
  - `data/output/<ts>/raw/llm/<workbook_slug>/knowledge/telemetry.json`
  - `data/output/<ts>/raw/llm/<workbook_slug>/knowledge/failures.json`
  - `data/output/<ts>/raw/llm/<workbook_slug>/knowledge/proposals/*.json`
- Authoritative input + validated proposals:
  - `data/output/<ts>/raw/llm/<workbook_slug>/knowledge/in/*.json`
  - `data/output/<ts>/raw/llm/<workbook_slug>/knowledge/proposals/*.json`
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
- manifest `counts` now distinguish shard count (`shards_written`) from surviving chunk count (`chunks_written`).
- If Stage 7 finds zero non-recipe spans, the manifest is still written as a successful no-op with zero shards.
- Live execution and prompt/debug reconstruction both read immutable shard payloads from `knowledge/in/*.json` and validated proposal wrappers from `knowledge/proposals/*.json`; there is no `knowledge/out/*.json` compatibility copy anymore.

## Pipeline assets

Local default pack files:

- `llm_pipelines/pipelines/recipe.knowledge.compact.v1.json`
- `llm_pipelines/prompts/recipe.knowledge.compact.v1.prompt.md`
- `llm_pipelines/schemas/recipe.knowledge.v1.output.schema.json`

`table_hint` contract note:
- When table extraction is enabled, compact knowledge input can include `chunk.blocks[*].table_hint` (`table_id`, `caption`, `row_index_in_table`) to help structural interpretation.
- Evidence still must quote verbatim from `chunk.blocks[*].text`.

Bundle contract note:
- shard-owned compact knowledge input is now `bundle_version = "2"` with short keys `v`, `bid`, and `c`, plus optional `x` local context and optional `g` guardrails.
- each chunk now carries only `cid` and `b` in the billed payload, with optional mechanically true block-level structure such as `hl` and `th`.
- the model-facing payload no longer emits chunk-level semantic hint objects. Deterministic routing and provenance remain local runtime concerns, not reviewer-model guidance.
- compact knowledge output is now `bundle_version = "2"` with short keys `v`, `bid`, and `r`; nested results also use short keys to cut structured-output overhead. Snippets now carry only grounded body text plus evidence pointers, while `block_decisions[*].rc` carries the internal reviewer category and `block_decisions[*].c` stays the final `knowledge|other` authority that staging writes out.
- prompt contract is intentionally strict: when input `c` is non-empty, output `r` must contain exactly one row per input chunk in input order, must echo the same `cid` values, and must not collapse to `r: []` or a synthetic fallback row.
- each result row must cover every owned block in order. `u=true` now requires at least one `knowledge` block decision plus at least one grounded snippet, while `u=false` requires only `other` decisions and no snippets.
- ingest now rejects the March 19 empty-collapse shape explicitly: if a shard with strong deterministic knowledge cues comes back as blanket `u=false` with zero snippets and zero `knowledge` decisions, the shard stays seed-kept but is reported as semantically rejected/unreviewed rather than reviewed-empty success.
