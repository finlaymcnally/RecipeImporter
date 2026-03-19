You are reviewing a benchmark upload bundle for the local `cookimport` CLI.
The logical contents come from an existing `upload_bundle_v1` benchmark package, not raw repo source code.
Oracle browser transport may package those logical files into one synthetic text attachment such as `attachments-bundle.txt`.
Within that attachment, start with `upload_bundle_overview.md`, then use `upload_bundle_index.json` and `upload_bundle_payload.jsonl` only as needed to verify details.
The bundle scope is `{{BUNDLE_SCOPE}}` and the benchmark root is `{{BENCHMARK_ROOT}}`.
Return a detailed report with exactly three sections: `Top regressions`, `Likely cause buckets`, and `Immediate next checks`.
Keep the response factual and grounded in the attached bundle. Do not suggest rerunning the benchmark unless the bundle is clearly missing required evidence.
