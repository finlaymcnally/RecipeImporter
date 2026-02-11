---
summary: "How freeform eval can be forced to compare spans despite source identity mismatches."
read_when:
  - Debugging freeform eval runs that return all-zero overlap due to source hash/file mismatch
  - Comparing full-vs-cutdown or renamed source variants in benchmark mode
---

# Freeform Eval Forced Source Matching

- Default freeform evaluation requires source compatibility (matching source hash, hash-prefix compatibility, or file-name fallback).
- When prediction and gold refer to different source identities (for example `thefoodlab.epub` vs `thefoodlabCUTDOWN.epub`), matches can collapse to zero even with aligned block ranges.
- Use `--force-source-match` on `cookimport labelstudio-eval freeform-spans` or `cookimport labelstudio-benchmark` to bypass source identity checks and evaluate overlap/label quality anyway.
- Reports include `source_matching_mode` (`strict` or `forced`) so downstream interpretation is explicit.
