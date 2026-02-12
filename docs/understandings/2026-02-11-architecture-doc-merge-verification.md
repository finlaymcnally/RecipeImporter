---
summary: "Code-verified architecture facts discovered while merging docs/architecture into architecture_readme.md."
read_when:
  - When updating architecture docs or output path/timestamp conventions
  - When debugging split-job merge behavior across stage and Label Studio flows
---

# Understanding: Architecture Merge Verification

- Stage and Label Studio run-folder timestamps are currently dot-separated (`%Y-%m-%d_%H.%M.%S`), despite one architecture note claiming a colon-separated format.
- Stage conversion reports are written at run root as `<workbook_slug>.excel_import_report.json`, not under a stage `reports/` subfolder.
- Label Studio split-job merges rebase block-index fields across jobs; this is necessary for canonical/freeform task/eval alignment.
