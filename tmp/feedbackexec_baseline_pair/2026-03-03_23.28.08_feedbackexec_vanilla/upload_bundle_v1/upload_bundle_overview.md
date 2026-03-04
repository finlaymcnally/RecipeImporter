# External AI Upload Bundle (3 files)

- Generated at: `2026-03-03_23.28.21`
- Source folder: `/home/mcnal/projects/recipeimport/data/golden/benchmark-vs-golden/2026-03-03_23.28.08_feedbackexec_vanilla`
- Bundle folder: `/home/mcnal/projects/recipeimport/data/golden/benchmark-vs-golden/2026-03-03_23.28.08_feedbackexec_vanilla/upload_bundle_v1`

## Files

- `upload_bundle_overview.md`: human quick-start + topline diagnostics.
- `upload_bundle_index.json`: navigation index, topline metrics, artifact lookup.
- `upload_bundle_payload.jsonl`: full artifact payload rows (lossless source data).

## Quick Start

1. Read `topline` and `self_check` in `upload_bundle_index.json`.
2. Start with `analysis.triage_packet` (JSONL-first triage rows).
3. Open `navigation.default_initial_views` in order for first-pass triage.
4. Use `navigation.row_locators` to jump into `upload_bundle_payload.jsonl` rows.

## Topline

- run_count: 1
- pair_count: 0
- changed_lines_total: 0
- pair_count_sufficient_for_generalization: false
- additional_pairs_needed_for_generalization: 2
- full_prompt_log_status: unknown
- full_prompt_log_rows: 0

## Self-Check

- starter_pack_present: true
- starter_pack_physical_dir_present: false
- pair_count_verified: true
- changed_lines_verified: true
- topline_consistent: true

## Included Views

- triage packet (JSONL-first row navigation; CSV remains legacy-compatible)
- net-error blame summary (line-role / pass2 / pass3 / routing-fallback buckets)
- config/version parity metadata
- per-label metrics + confusion deltas
- per-recipe breakdown
- stage-separated comparison (baseline / line-role / pass2 / pass3 / final-fallback)
- failure ledger (recipe x pass rows)
- compact regression casebook
- changed-lines stratified sample
- low-confidence changed-lines packet
- call inventory with latency/tokens/cost
- line-role confidence (and candidate-label signal when present)

## Availability Notes

- call_cost_available: false
- call_cost_coverage_ratio: 0.000000
- call_cost_estimated_available: false
- call_cost_estimated_coverage_ratio: 0.000000
- line_role_candidate_labels_available: false
- triage_packet_rows: 0
- low_confidence_changed_lines_rows: 0
- critical_row_locator_coverage_ratio: 0.916667

## Net-Error Blame Summary

- new_error_lines: 0
- fixed_error_lines: 0
- net_error_delta_lines: 0
- line_role: count=0 (share_of_net_error=0.000000)
- pass2_extraction: count=0 (share_of_net_error=0.000000)
- pass3_mapping: count=0 (share_of_net_error=0.000000)
- routing_or_fallback: count=0 (share_of_net_error=0.000000)

## Config / Version Parity

- config_compatible_pair_count: 0
- pair_count: 0
- config_compatible_pair_ratio: 1.000000
- non_comparable_keys: none

### Targeted Regression IDs

- requested: `c6`, `c9`, `c12`, `c3`
- found: none

## Run Diagnostics

| run_id | prompt_log | prompt_warning | projection_trace | wrong_context | preprocess_trace |
|---|---|---|---|---|---|
| 2026-03-03_23.28.08_feedbackexec_vanilla | not_applicable | not_applicable | not_applicable | written | not_applicable |

## Data Integrity

Each artifact row carries `sha256` and `bytes`. Text/structured files are embedded directly for easy browsing, while compressed/binary payloads are embedded as base64.
Heavy artifacts (full prompt logs, raw manifests, transport traces, split-cache blobs) are retained in payload but deprioritized in default navigation.
