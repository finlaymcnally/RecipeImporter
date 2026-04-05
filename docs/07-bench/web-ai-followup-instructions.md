---
summary: "Instructions for external web AI reviewers on how to request narrow follow-up data from an upload_bundle_v1 benchmark handoff."
read_when:
  - When preparing or answering web-AI follow-up requests against benchmark upload bundles
  - When explaining how upload_bundle_v1 row locators map back to richer local follow-up artifacts
---

# Web AI Instructions For Benchmark Follow-Up Requests

This note is for a web AI that is reviewing a benchmark handoff rooted at `upload_bundle_v1` and wants to ask for narrower, better-targeted local follow-up data.

## What You Already Have
The `upload_bundle_v1` contract is always three files:

- `upload_bundle_overview.md`: human summary and quick-start.
- `upload_bundle_index.json`: machine-readable navigation, topline metrics, default views, row locators, and run diagnostics.
- `upload_bundle_payload.jsonl`: lossless payload store. One JSON object per line. Use `path` as the join key and `payload_row` as the locator field.

Important implication: most follow-up requests should ask for new derived artifacts or specific row-locator-backed slices, not a duplicate copy of the bundle.

## The Full Run Data Layout

The upload bundle is a compact handoff layer built from a larger benchmark session folder. 

The session root typically contains:

- one directory per benchmarked source book or run, such as `01_amatteroftastecutdown/`
- a top-level `upload_bundle_v1/` directory for multi-run handoff
- `processing_timeseries.jsonl`
- sometimes housekeeping state such as `.split_phase_slots/`

Each per-run directory typically contains:

- `run_manifest.json`: run identity, config, and artifact registry
- `eval_report.json`: aggregate evaluation metrics
- `wrong_label_lines.jsonl`, `wrong_label_blocks.jsonl`
- `missed_gold_lines.jsonl`, `missed_gold_blocks.jsonl`
- `aligned_prediction_blocks.jsonl`, `alignment_gaps.jsonl`, `unmatched_pred_blocks.jsonl`
- `prompt_budget_summary.json`: post-run cost/runtime rollup when available
- `stage_observability.json`: stage status / observability summary when available
- `.prediction-record-replay/`: replayable scored prediction snapshots when available
- `prompts/`: prompt, response, and parsed prompt-linked artifacts
- sometimes `prediction-run/` or `raw/llm/...` stage outputs, depending on how the run was produced
- `line-role-pipeline/`: line-role stage artifacts
- sometimes a per-run `upload_bundle_v1/`

The larger cutdown pipeline can also create or derive these higher-level artifacts, which may appear physically in the session root or only as payload rows inside the upload bundle:

- `README.md`
- `run_index.json`
- `comparison_summary.json`
- `codex_vs_vanilla_comparison.json`
- `process_manifest.json`
- `changed_lines.codex_vs_vanilla.jsonl`
- `per_recipe_or_per_span_breakdown.json`
- `targeted_prompt_cases.md`
- `label_policy_adjudication_notes.md`
- `starter_pack_v1/...`

Important detail: `starter_pack_v1` may be represented logically in the bundle even when it is not physically present beside the bundle. If `upload_bundle_index.json` says `starter_pack_present: true` but `starter_pack_physical_dir_present: false`, treat that as expected. The starter-pack rows may exist under `_upload_bundle_derived/...` inside the payload.

## How To Read The Bundle First

Read in this order:

1. `upload_bundle_overview.md`
2. `upload_bundle_index.json`
3. `upload_bundle_index.json.topline`
4. `upload_bundle_index.json.self_check`
5. `upload_bundle_index.json.navigation.default_initial_views`
6. `upload_bundle_index.json.navigation.row_locators`
7. referenced rows in `upload_bundle_payload.jsonl`

The most important fields in `upload_bundle_index.json` are:

- `topline`: run count, pair count, changed-lines totals, prompt-log status, generalization readiness
- `self_check`: whether counts and critical row locators were recomputed successfully
- `run_diagnostics`: one row per run with status of prompt logs, projection traces, wrong-line context, and preprocess traces
- `navigation.default_initial_views`: recommended triage order
- `navigation.root_paths`: important logical artifacts
- `navigation.per_run_summary_paths`: per-run summary entrypoints
- `navigation.row_locators`: exact payload rows for important artifacts

Treat `row_locators` as the canonical bridge from the index into `upload_bundle_payload.jsonl`.

If the question is "is recipe structure mostly solved, and are the remaining losses coming from non-recipe labels instead?", start with `analysis.structure_label_report` before looking at raw changed lines.

## The Most Useful Logical Artifacts

When present, these are the highest-value things to reason from before asking for more data:

- `analysis.turn1_summary`: one-screen severity/span/blame/runtime summary
- `analysis.benchmark_pair_inventory`
- `analysis.active_recipe_span_breakout`
- `analysis.net_error_blame_summary`: where net regressions seem to originate
- `analysis.top_confusion_deltas`
- `analysis.changed_lines_stratified_sample`
- `analysis.triage_packet`: JSONL-first per-case triage rows
- `analysis.config_version_metadata`: whether comparisons are config-compatible
- `analysis.stage_observability_summary`
- `analysis.structure_label_report`
- `analysis.per_label_metrics`
- `analysis.per_recipe_breakdown`
- `analysis.stage_separated_comparison`
- `analysis.failure_ledger`
- `analysis.regression_casebook`
- `analysis.explicit_escalation_changed_lines_packet`
- `analysis.call_inventory_runtime`
- `analysis.line_role_escalation`
- `analysis.knowledge`
- `analysis.group_high_level`, `analysis.book_scorecard`, `analysis.ablation_summary`, `analysis.outside_span_by_book`, `analysis.runtime_by_book` for multi-book sessions

If you need to jump into raw artifacts, use the payload rows referenced by:

- `run_index.json`
- `comparison_summary.json`
- `process_manifest.json`
- `changed_lines.codex_vs_vanilla.jsonl`
- `per_recipe_or_per_span_breakdown.json`
- `targeted_prompt_cases.md`
- `label_policy_adjudication_notes.md`
- `starter_pack_v1/01_recipe_triage.packet.jsonl`
- `navigation.row_locators.knowledge_by_run` when the question is specifically about knowledge-harvest/knowledge artifacts

## Follow-Up Tooling You Can Ask The User To Run

The local follow-up CLI is `cf-debug`. It is a deterministic helper layer on top of `upload_bundle_v1`.

### `cf-debug request-template`

Purpose: create a starter request manifest for a web AI.

Input:

- `--bundle <upload_bundle_v1 dir>`
- `--out <json file>`

Output:

- a `cf.followup_request.v1` JSON document

Use this when you want to fill in one or more precise asks but do not want to hand-author the whole manifest schema.
It now pre-seeds one line-role-oriented ask and, when the bundle exposes knowledge evidence, one knowledge-oriented ask.
The default line-role ask prefers a negative-delta recipe regression when one exists, otherwise it falls back to an `outside_span_window_*` case, then to the strongest remaining recipe-signal case.

### `cf-debug select-cases`

Purpose: choose stable case selectors from the bundle.

Input knobs:

- `--stage <stage>` repeated
- `--top-neg <N>`
- `--top-pos <N>`
- `--outside-span <N>`
- `--include-case-id <case_id>` repeated
- `--include-recipe-id <recipe_id>` repeated
- `--include-line-range <source_key>:<start>:<end>` repeated
- `--include-knowledge-source-key <source_key or bundle-local knowledge key>` repeated
- `--include-knowledge-output-subdir <exact output_subdir from the bundle or request-template>` repeated

Output:

- a selector manifest with schema `cf.selector.v1`

Use this when you know which cases or ranges you want, or when you want the top regressions/wins chosen deterministically.
For knowledge-specific asks, prefer `--stage knowledge` plus `--include-knowledge-output-subdir` when you already have an exact value from `request-template` or `navigation.row_locators.knowledge_by_run`.
Use `--include-knowledge-source-key` when you only know the source identity and want the bundle to resolve the matching knowledge run.

### `cf-debug structure-report`

Purpose: emit one bundle-wide summary that separates core recipe-structure labels from non-recipe labels and includes boundary exactness.

Input:

- `--bundle <upload_bundle_v1 dir>`
- `--out <json file>`

Output:

- `structure_report.json`

Use this when you need to answer questions like:

- is the benchmark still failing on segmentation/boundaries?
- are titles / ingredient lines / instruction lines already mostly solved?
- are `KNOWLEDGE` and `OTHER` dominating the remaining score loss?

This is the fastest artifact for the "structure should be near 100 percent" discussion because it puts:

- `structure_core` labels (`RECIPE_TITLE`, `INGREDIENT_LINE`, `INSTRUCTION_LINE`, `HOWTO_SECTION`, `YIELD_LINE`, `TIME_LINE`)
- `recipe_context_auxiliary` labels (`RECIPE_NOTES`, `RECIPE_VARIANT`)
- `nonrecipe_core` labels (`KNOWLEDGE`, `OTHER`)
- boundary exact-match ratios

into one summary instead of requiring manual reconstruction from `per_label_metrics`, `stage_separated_comparison`, and raw `eval_report.json` files.

### `cf-debug export-cases`

Purpose: emit case-level evidence for selected cases only.

Input:

- `--bundle`
- `--selectors`
- `--out <directory>`

Output:

- `index.json`
- `case_export.jsonl`
- `file_manifest.jsonl`

Use this when you want the minimum case-centered packet.

### `cf-debug audit-line-role`

Purpose: inspect line-role predictions, candidate labels, prompt-linked files, trust/escalation metadata, and simple invariants for selected lines/cases.

Output:

- `line_role_audit.jsonl`

Use this when the likely failure is around label selection, candidate lists, postprocess changes, or codex-vs-baseline disagreement at the line role stage.

### `cf-debug audit-prompt-links`

Purpose: verify whether the prompt, response, and parsed prompt artifacts are properly linked back to the selected atomic line indices.

Output:

- `prompt_link_audit.jsonl`

Use this when you suspect prompt provenance gaps, broken prompt joins, or missing prompt-side evidence for a regression.

### `cf-debug audit-knowledge`

Purpose: inspect run-level knowledge-stage evidence, bundle row locators, and local artifact presence for selected knowledge runs.

Output:

- `knowledge_audit.jsonl`

Use this when the question is specifically about knowledge-stage prompts, manifests, snippet-writing status, or whether the knowledge-harvest pass ran and produced usable evidence.

### `cf-debug export-page-context`

Purpose: emit local page or nearby-line context around the selected cases or ranges.

Output:

- `page_context.jsonl`

Use this when the error smells like layout bleed, heading confusion, page marker contamination, or outside-span contamination.

### `cf-debug export-uncertainty`

Purpose: emit low-trust or explicit-escalation signal around the selected cases.

Output:

- `uncertainty.jsonl`

Use this when you want trust/escalation-driven evidence rather than prompt provenance.

### `cf-debug pack`

Purpose: create one compact all-in-one follow-up evidence pack from a selector manifest.

Output directory contents:

- `structure_report.json`
- `index.json`
- `selectors.json`
- `case_export/`
- `line_role_audit.jsonl`
- `prompt_link_audit.jsonl`
- `knowledge_audit.jsonl`
- `page_context.jsonl`
- `uncertainty.jsonl`
- optionally `README.md`

Use this when one selector set should produce a complete local packet without multiple separate commands.

### `cf-debug build-followup`

Purpose: create a multi-ask packet for iterative back-and-forth with a web AI.

Input:

- `--bundle`
- `--request <cf.followup_request.v1 json>`
- `--out <directory>`

Output directory contents:

- `index.json`
- `request_manifest.json`
- `asks/<ask_id>/selectors.json`
- `asks/<ask_id>/index.json`
- only the requested outputs for each ask
- optionally `README.md`

Use this when you have several distinct questions and want each question packaged separately.

### `cf-debug ablate`

Purpose: export the benchmark variant matrix so the web AI can reason about baseline-only, line-role-only, recipe-only, and full-stack comparisons.

Output:

- a `cf.ablation_matrix.v1` JSON file

Use this when the question is about which subsystem is responsible for wins or regressions across variants.

## What A Good Follow-Up Ask Looks Like

A good ask is narrow, references stable identifiers from the bundle, and requests only the evidence needed to answer the question.

Prefer these selector strategies, in order:

1. `include_case_ids` when the bundle already exposes a stable case ID such as `regression_c6`, `win_c10`, or `outside_span_window_628_657`
2. `include_recipe_ids` when the issue is recipe-scoped but case IDs are not stable enough
3. `include_line_ranges` when the problem is a specific span or contamination window
4. `include_knowledge_output_subdirs` when the issue is specifically a knowledge-stage run and you already have an exact run locator
5. `include_knowledge_source_keys` when the issue is knowledge-stage but you only know the source identity
6. `top_neg`, `top_pos`, or `outside_span` when you want deterministic triage picks without choosing exact IDs yourself

Prefer these output combinations:

- Root-cause on a single regression: `case_export`, `line_role_audit`, `prompt_link_audit`
- Knowledge question: `case_export`, `knowledge_audit`
- Suspected layout or span contamination: `page_context`, `uncertainty`
- Full small packet for a handful of cases: `pack`
- Several separate questions in one round-trip: `build-followup`
- Stack attribution question: `ablate`

## What Not To Ask For

Avoid low-signal asks like:

- "send the whole payload again"
- "dump every prompt artifact for every run"
- "send all raw files"
- "explain the whole benchmark"

Those waste bandwidth and make later reasoning worse.

Instead, ask for:

- specific case IDs
- specific recipe IDs
- specific line ranges
- a deterministic top-N slice
- only the evidence family needed for the hypothesis you are testing

## Recommended Reasoning Workflow

1. Read `topline` and `self_check`.
2. Check `run_diagnostics` to see whether prompt and trace artifacts exist.
3. Read the triage packet and regression casebook.
4. Decide whether the problem looks like line-role, prompt linkage, knowledge-stage harvest, page/layout contamination, or general stack attribution.
5. Ask for the smallest follow-up artifact that can prove or falsify that hypothesis.

If the bundle already contains a row locator for the needed artifact, cite that row instead of asking for new material.

## Example Follow-Up Request Manifest

```json
{
  "schema_version": "cf.followup_request.v1",
  "bundle_dir": "data/golden/benchmark-vs-golden/2026-03-06_00.44.16/single-profile-benchmark/upload_bundle_v1",
  "bundle_sha256": "<copy from request-template output>",
  "request_id": "followup_request_01",
  "request_summary": "Answer three targeted follow-up asks from the web AI.",
  "requester_context": {
    "already_has_upload_bundle_v1": true,
    "prefer_new_local_artifacts_over_bundle_repeats": true,
    "duplicate_bundle_payloads_only_when_needed_for_context": true
  },
  "default_stage_filters": ["line_role"],
  "asks": [
    {
      "ask_id": "ask_regression_c6",
      "question": "Why is regression_c6 bad? Show line-role provenance and prompt linkage.",
      "outputs": ["case_export", "line_role_audit", "prompt_link_audit"],
      "selectors": {
        "top_neg": 0,
        "top_pos": 0,
        "outside_span": 0,
        "stage_filters": ["line_role"],
        "include_case_ids": ["regression_c6"],
        "include_recipe_ids": [],
        "include_line_ranges": []
      }
    },
    {
      "ask_id": "ask_outside_span",
      "question": "Show context for the outside-span weird window.",
      "outputs": ["page_context", "uncertainty"],
      "selectors": {
        "top_neg": 0,
        "top_pos": 0,
        "outside_span": 0,
        "stage_filters": ["line_role"],
        "include_case_ids": ["outside_span_window_628_657"],
        "include_recipe_ids": [],
        "include_line_ranges": [],
        "include_knowledge_source_keys": [],
        "include_knowledge_output_subdirs": []
      }
    },
    {
      "ask_id": "ask_knowledge_saltfat",
      "question": "Show the knowledge-stage evidence for Salt Fat Acid Heat.",
      "outputs": ["case_export", "knowledge_audit"],
      "selectors": {
        "top_neg": 0,
        "top_pos": 0,
        "outside_span": 0,
        "stage_filters": ["knowledge"],
        "include_case_ids": [],
        "include_recipe_ids": [],
        "include_line_ranges": [],
        "include_knowledge_source_keys": [],
        "include_knowledge_output_subdirs": ["<copy exact output_subdir from request-template or navigation.row_locators.knowledge_by_run>"]
      }
    }
  ]
}
```
