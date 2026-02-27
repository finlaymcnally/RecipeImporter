Label Studio helpers for freeform span workflows.
Durable import/export/prelabel rules live in `cookimport/labelstudio/CONVENTIONS.md`.

- `ingest.py` builds extracted archives, freeform span tasks, prediction-run artifacts, and handles upload/resume.
- `archive.py` contains shared archive/normalization helpers used by freeform ingest and stage-block prediction flows, including `prepare_extracted_archive(...)` for one-pass archive preparation and serialization reuse.
- `freeform_tasks.py` builds segment-based freeform tasks (`segment_id`, `source_map`, focus/context metadata).
- `label_config_freeform.py` defines the freeform labeling UI and label normalization rules.
- `prelabel.py` runs optional Codex-CLI prelabeling for freeform tasks.
- `export.py` exports freeform annotations only (`freeform_span_labels.jsonl`, `freeform_segment_manifest.jsonl`, `summary.json`) and rejects legacy project scopes.
- `eval_freeform.py` evaluates predicted freeform labels against exported freeform gold.
- `labelstudio-benchmark` scores stage evidence (`stage_block_predictions.json`) against freeform gold.
