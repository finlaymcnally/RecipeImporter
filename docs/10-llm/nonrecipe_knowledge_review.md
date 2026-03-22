---
summary: "How the optional shard-runtime non-recipe knowledge review stage refines seed non-recipe spans and writes its artifacts."
read_when:
  - "When enabling or debugging optional non-recipe knowledge review outputs"
  - "When editing the compact knowledge-stage codex-farm pipeline prompt/schema assets"
---

# Optional Non-Recipe Knowledge Review

The knowledge stage is an **optional** shard-worker CodexFarm phase that reviews Stage 7 review-eligible non-recipe spans, is the only semantic authority for review-eligible outside-recipe `knowledge` versus `other`, and extracts **general cooking knowledge** (tips, techniques, definitions, substitutions, do/don't guidance) from the spans that remain knowledge.

The deterministic classifier runs first and always writes:

- `08_nonrecipe_spans.json`
- `09_knowledge_outputs.json`

Those files are the authoritative outside-recipe ownership boundary. They now preserve the Stage 7 routing split, the fallback block-category map, the explicit final-authority block indices/categories that downstream projection is allowed to trust, and the refinement report that explains which review-eligible rows remained unreviewed. The LLM stage no longer publishes `block_classifications.jsonl`; instead it returns `block_decisions` that merge into the final authority recorded in those artifacts while keeping richer internal reviewer categories inside the refinement seam.

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
- knowledge-stage inputs now come from the review-eligible subset of Stage 7 non-recipe spans. Obvious-junk `OTHER` blocks excluded by line-role stay visible in `08_nonrecipe_spans.json` / `08_nonrecipe_review_exclusions.jsonl`, but they are pruned before `knowledge/in/*.json` is written.
- Stage 7 no longer grants semantic authority to review-eligible rows by itself. If the knowledge stage does not review a row, downstream scoring and Label Studio projection must treat it as unreviewed seed-kept fallback rather than reviewed semantic `other`.
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
  - `data/output/<ts>/raw/llm/<workbook_slug>/knowledge/stage_status.json`
  - `data/output/<ts>/raw/llm/<workbook_slug>/knowledge/phase_manifest.json`
  - `data/output/<ts>/raw/llm/<workbook_slug>/knowledge/shard_manifest.jsonl`
  - `data/output/<ts>/raw/llm/<workbook_slug>/knowledge/task_manifest.jsonl`
  - `data/output/<ts>/raw/llm/<workbook_slug>/knowledge/task_status.jsonl`
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
  - `data/output/<ts>/08_nonrecipe_review_exclusions.jsonl`
  - `data/output/<ts>/09_knowledge_outputs.json`
- Reviewer-facing extraction artifacts:
  - `data/output/<ts>/knowledge/<workbook_slug>/snippets.jsonl`
  - `data/output/<ts>/knowledge/<workbook_slug>/knowledge.md`

Run-level index (if any knowledge artifacts were written):

- `data/output/<ts>/knowledge/knowledge_index.json`

Manifest/runtime note:
- `knowledge_manifest.json` now advertises `input_mode = "stage7_review_eligible_nonrecipe_spans"` and reports whether the stage changed or confirmed final authority for reviewed rows.
- manifest `counts` now distinguish shard count (`shards_written`) from surviving chunk count (`chunks_written`).
- manifest and `review_summary` now also report how many Stage 7 blocks stayed review-eligible versus how many were excluded upstream, so missing blocks in `knowledge/in/*.json` are explainable from repo artifacts alone.
- If Stage 7 finds zero non-recipe spans, the manifest is still written as a successful no-op with zero shards.
- Live execution and prompt/debug reconstruction both read immutable shard payloads from `knowledge/in/*.json` and validated proposal wrappers from `knowledge/proposals/*.json`; there is no `knowledge/out/*.json` compatibility copy anymore.
- `stage_status.json` is the canonical machine-readable operator summary for stage wrap-up, interruption attribution, and normalized artifact state. It records `stage_state`, `termination_cause`, `finalization_completeness`, `pre_kill_failure_counts`, and normalized `artifact_states`.
- `task_status.jsonl` is the packet-level runtime ledger. Each task packet starts `pending`, moves to `leased` when the repo assigns it to the worker's ordered queue, can record `main_output_written` once the main worker drops its local result file, tracks follow-up attempt types (`main_worker`, `watchdog_retry`, `retry_split`, `repair`), and ends in one explicit terminal state such as `validated`, `retry_failed`, `repair_recovered`, `missing_output`, or `cancelled_due_to_interrupt`.
- promotion is now packet-aware: if a parent shard wrapper is invalid only because some owned packets never validated (`missing_owned_chunk_results`), accepted sibling task packets can still promote and refine final authority while the missing or semantic-invalid packet subset stays explicitly unreviewed.
- `phase_manifest.json.runtime_metadata` now also records the worker blast-radius summary for the run: `bundle_policy`, `task_packet_total`, `worker_task_packet_counts`, and min/max task packets per worker.
- knowledge worker roots carry an authoritative ordered `assigned_tasks.json` queue plus repo-written batch sidecars (`current_batch.json`, `CURRENT_BATCH.md`, `CURRENT_BATCH_FEEDBACK.md`), compatibility single-task fallback sidecars for the first active task (`current_task.json`, `CURRENT_TASK.md`, `CURRENT_TASK_FEEDBACK.md`), `OUTPUT_CONTRACT.md`, `examples/`, `tools/knowledge_worker.py`, `hints/`, and `scratch/`. The happy path is batch-first: `CURRENT_BATCH.md` is the cheap first read, `current_batch.json` keeps only batch-local task facts, and `assigned_tasks.json` is fallback/debug inventory rather than the ordinary first surface. Each task row still advertises `metadata.input_path`, `metadata.hint_path`, `metadata.result_path`, and its ordered queue position, so the live worker loop does not depend on repo-side lease-file mutation mid-session.
- the main worker writes one semantic packet-result object to each task row's declared `metadata.result_path`, using semantic keys such as `packet_id`, `chunk_results`, `chunk_id`, `is_useful`, `block_decisions`, `snippets`, and optional `reason_code`. Repo code then serializes the canonical compact `v` / `bid` / `r` packet payload before proposal validation and promotion.
- a validated leased packet result is authoritative even if the workspace session ends with no final assistant message or only a prose closing note. `final_agent_message_state` stays in telemetry/live-status for debugging, but repair and retry should only follow file-level validation failure.
- retry / repair child status files now keep explicit `reason_code` / `reason_detail` fields for skips, cancellation, and supersession. Follow-up wrappers normalize stage-interrupt cleanup to `cancelled_stage_interrupt`, while the task ledger keeps the packet terminal state as `cancelled_due_to_interrupt`.
- `cookimport/llm/knowledge_runtime_replay.py` is the zero-token replay seam for this artifact tree. It reads a saved `knowledge/` root plus the paired benchmark root and rebuilds packet totals, worker output/malformed counts, follow-up counts, stale follow-up counts, worker outcome buckets, and missing expected artifacts from repo evidence alone.
- A missing stage wrap-up file is only evidence of a bug when `stage_status.json` says finalization should have been complete. If `finalization_completeness` is `interrupted_before_finalization`, the missing wrap-up files are expected kill fallout and should classify as `skipped_due_to_interrupt`.
- Interrupted runs now still flush partial `phase_manifest.json`, `promotion_report.json`, `telemetry.json`, and `failures.json` before the stage reraises, then mark any still-running retry / repair live-status files as `cancelled_due_to_interrupt`.
- structured progress for this stage is now packet-based: `task_current/task_total` counts task packets rather than parent shards, worker labels show local packet progress, and detail lines call out configured workers, completed shards, queued task packets, and any live retry/repair follow-up calls.
- post-run cost summaries now also copy the compact knowledge counters into `prediction-run/prompt_budget_summary.json` under the knowledge stage row, including packet outcome counts, worker outcome buckets, salvage counts, circuit-breaker counts, and an execution split between main workspace-worker rows and structured follow-up calls.

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
- that compact bundle is now repo-owned on the main workspace-worker path. The worker's normal job is to return the smaller semantic packet-result object; canonical compact bundle fields are a compatibility concern for structured follow-up attempts, not the mainline authority seam.
- the semantic packet worker contract is intentionally narrow: final `category` values are only `knowledge` or `other`, `reviewer_category` carries any richer internal reason, and `snippets[*].body` should be a short grounded extraction rather than a whole-chunk echo or long verbatim copy of its cited evidence surface.
- the knowledge worker prompt now also explicitly says to open `worker_manifest.json`, then the batch sidecars, then the repo-named `tasks[*].input_path` / `tasks[*].hint_path` files directly only when the batch packet is insufficient; use `python3 tools/knowledge_worker.py` for the paved-road `complete-batch`, `check-batch`, and `install-batch` loop (with `current-batch`, `next-batch`, `show-batch`, the older single-task verbs, and lower-level `overview|show|scaffold|check|install` still available for recovery/debugging); avoid broad queue dumps or ad hoc shell schedulers; and keep any helper files in `scratch/` or short-lived local temp roots such as `/tmp`. Strong-cue scaffolds are now visibly prewritten as `strong_cue_review_required`, `install-batch` accepts the longest valid prefix in order, direct writes to `out/` without a passing checker are incomplete work, and both snippet-copy failures and `semantic_all_false_empty_shard` failures now name the narrow chunk-local reason in worker language instead of forcing rediscovery through helper-source inspection.
- the knowledge main-worker watchdog now also fails closed on batch-bypass commands that the bad benchmark run exposed: direct `assigned_tasks.json` dumps, helper-source reads of `tools/knowledge_worker.py`, `install-current`-style single-task helper detours while a batch is active, ad hoc shell schedulers over queue/output files, and inline queue-control rewrites. Those are now explicit runtime violations, not just discouraged prompt wording.
- the knowledge main-worker watchdog now also tolerates absolute paths only when they resolve under that worker session's assigned sterile execution root; sibling workspaces, repo paths, home paths, and other outside-root absolute paths still remain forbidden.
- prompt contract is intentionally strict: when input `c` is non-empty, output `r` must contain exactly one row per input chunk in input order, must echo the same `cid` values, and must not collapse to `r: []` or a synthetic fallback row.
- each result row must cover every owned block in order. `u=true` now requires at least one `knowledge` block decision plus at least one grounded snippet, while `u=false` requires only `other` decisions and no snippets.
- `promotion_report.json` and the review rollups now distinguish fully validated shards from `partially_promoted_shards`, so packet-level progress no longer collapses into a whole-shard failure count.
- ingest now rejects the March 19 empty-collapse shape explicitly: if a shard with strong deterministic knowledge cues comes back as blanket `u=false` with zero snippets and zero `knowledge` decisions, the shard stays seed-kept but is reported as semantically rejected/unreviewed rather than reviewed-empty success.
- ingest also fails closed on two newer low-trust shapes: snippet bodies with no grounded text at all, and snippets that effectively copy either the full owned chunk text or a long cited evidence surface back into the answer instead of extracting a smaller grounded claim. Those snippet-copy-only failures now get one narrow snippet-body-only repair attempt before poisoned-worker skip logic can win. Deterministic salvage stays narrow and only trims trailing `EOF` or obvious shell-wrapper suffix noise after an otherwise valid JSON object.
