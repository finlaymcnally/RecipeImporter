---
summary: "Label Studio uploads now require explicit consent in both CLI and interactive flows."
read_when:
  - Changing Label Studio import/benchmark command behavior
  - Investigating why uploads did or did not occur
---

# Label Studio Write Consent Gate

- `run_labelstudio_import(...)` enforces `allow_labelstudio_write=True` before creating projects or importing tasks.
- `cookimport labelstudio-import` and `cookimport labelstudio-benchmark` now require `--allow-labelstudio-write` in non-interactive use.
- Interactive menu flows prompt for explicit upload confirmation before invoking import/benchmark uploads.
- Interactive benchmark now supports an eval-only fallback when upload is declined: it can score an existing prediction run against gold without pushing new tasks.
