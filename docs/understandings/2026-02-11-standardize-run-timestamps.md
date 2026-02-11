---
summary: "Run-folder timestamps are now standardized to YYYY-MM-DD_HH:MM:SS."
read_when:
  - Changing output folder naming for stage or Label Studio runs
  - Debugging mismatched timestamp folder formats across golden/output trees
---

# Standardized Run Timestamp Format

- Stage output runs, Label Studio import/export runs, and benchmark eval runs now use the same timestamp format: `YYYY-MM-DD_HH:MM:SS`.
- This replaces mixed formats like `YYYY-MM-DD-HHMMSS` and `YYYY-MM-DD-HH-MM-SS`.
- Example folder name: `2026-02-10_23:21:33`.
