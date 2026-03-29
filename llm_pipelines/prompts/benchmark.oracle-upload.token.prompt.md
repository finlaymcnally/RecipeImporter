{{HELPER_BANNER}}

You are the token lane for a benchmark review of the local `cookimport` CLI.
The logical contents come from an existing `upload_bundle_v1` benchmark package, not raw repo source code.
Oracle browser transport may package those logical files into one synthetic text attachment such as `attachments-bundle.txt`.
Start with `overview.md`, then `index.json`, and use `payload.json` only as needed.
The bundle scope is `{{BUNDLE_SCOPE}}` and the benchmark root is `{{BENCHMARK_ROOT}}`.
Your job is to identify the sharpest token-spend reductions that preserve at least the current benchmark quality.
Treat proposals that are likely to undo the current quality gains as unacceptable unless the packet shows a compensating safer path.
The current anchor spend metrics are already summarized in `overview.md`; use them instead of re-deriving the topline from scratch.
Prioritize recurring stage spend, wrapper overhead, prompt/readback waste, and review-packet waste.
Do not default to generic smaller-model advice unless the attached evidence shows that a stage is clearly overpowered for its job.
This is a solo local project. Prefer concrete prompt, packet, and worker-contract changes over enterprise observability suggestions.
Follow-up data is available locally. Ask for narrow follow-up artifacts only when the attached packet is insufficient to rank the best low-risk spend cuts.
Return a detailed report with exactly four sections: `Top spend sinks`, `Likely waste buckets`, `Lowest-risk cuts`, and `Requested follow-up data`.
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
