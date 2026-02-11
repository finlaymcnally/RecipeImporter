---
summary: "How default Label Studio project naming is resolved during import."
read_when:
  - Extending Label Studio import naming or resume behavior
---

# Label Studio Project Name Dedupe (Discovery)

- `cookimport labelstudio-import` now resolves the default project title from `Path(input).stem` when `--project-name` is omitted.
- Name collision handling happens before project lookup: if a title already exists in Label Studio, the importer tries `base-1`, then `base-2`, etc. until it finds an unused title.
- Explicit `--project-name` still bypasses dedupe and uses the provided value directly, preserving existing resume/overwrite behavior for named projects.
