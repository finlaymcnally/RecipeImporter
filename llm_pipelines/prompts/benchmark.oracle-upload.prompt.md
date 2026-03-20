{{HELPER_BANNER}}

You are reviewing a benchmark upload bundle for the local `cookimport` CLI.
The logical contents come from an existing `upload_bundle_v1` benchmark package, not raw repo source code.
Oracle browser transport may package those logical files into one synthetic text attachment such as `attachments-bundle.txt`.
Within that attachment, start with `upload_bundle_overview.md`, then use `upload_bundle_index.json` and `upload_bundle_payload.jsonl` only as needed to verify details.
The bundle scope is `{{BUNDLE_SCOPE}}` and the benchmark root is `{{BENCHMARK_ROOT}}`.
Follow-up data is available locally. If the first-pass bundle is not enough to confirm or falsify your hypotheses, ask for narrow follow-up artifacts rather than a rerun or a duplicate copy of the bundle.
Prefer requests keyed to exact artifact names, `upload_bundle_index.json` row locators, case ids, source keys, line ranges, or knowledge output subdirs when possible.
Useful local follow-up tools include `cf-debug structure-report`, `select-cases`, `export-cases`, `audit-line-role`, `audit-prompt-links`, `audit-knowledge`, `export-page-context`, `export-uncertainty`, `pack`, and `build-followup`.
Return a detailed report with exactly four sections: `Top regressions`, `Likely cause buckets`, `Immediate next checks`, and `Requested follow-up data`.
In `Requested follow-up data`, either write `None` or list 1-3 asks in this plain-text format so a local Codex tool can parse it:
`Ask N`
`ask_id: <short_slug>`
`question: <what evidence you want>`
`outputs: <comma-separated outputs such as case_export, line_role_audit, prompt_link_audit, knowledge_audit, page_context, uncertainty, structure_report>`
`stage_filters: <comma-separated stages such as line_role or knowledge>`
`include_case_ids: <comma-separated case ids or blank>`
`include_recipe_ids: <comma-separated recipe ids or blank>`
`include_line_ranges: <comma-separated source_key:start:end ranges or blank>`
`include_knowledge_source_keys: <comma-separated source keys or blank>`
`include_knowledge_output_subdirs: <comma-separated exact knowledge output_subdirs or blank>`
`hypothesis: <what theory this ask will test>`
`smallest_useful_packet: <why this is the smallest useful next packet>`
Keep the response factual and grounded in the attached bundle. Do not suggest rerunning the benchmark unless the bundle is clearly missing required evidence.
