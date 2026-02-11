---
summary: "Root cause of unexpected Label Studio task uploads and how to identify the triggering flow."
read_when:
  - Investigating why tasks appear in Label Studio unexpectedly
  - Auditing benchmark/import side effects
---

# Label Studio Unexpected Push Root Cause

- Task uploads happen only through `run_labelstudio_import(...)` -> `LabelStudioClient.import_tasks(...)`.
- `cookimport labelstudio-benchmark` always calls `run_labelstudio_import(...)` to generate prediction tasks before eval.
- Benchmark-created imports are identifiable by artifacts under `data/golden/eval-vs-pipeline/<timestamp>/prediction-run/manifest.json`.
- The manifest includes `uploaded_task_count`, `task_scope`, `source_file`, and `label_studio_url`, which can be used to confirm exactly what was uploaded.
- Current Label Studio tests in `tests/test_labelstudio_benchmark_helpers.py` monkeypatch `run_labelstudio_import` and do not perform real network uploads.
