Label Studio benchmark mode helpers.

- `ingest.py` builds a full extracted text archive and uploads chunk tasks (pipeline), block tasks (canonical), or freeform span tasks.
- `label_config_blocks.py` defines the block-classification labeling UI.
- `label_config_freeform.py` defines text-span highlighting labels for freeform projects.
- `block_tasks.py` generates canonical block tasks with stable block IDs and context windows.
- `freeform_tasks.py` builds segment-based freeform tasks with stable segment IDs and block offset mappings.
- `export.py` pulls annotations back and converts them into JSONL (pipeline tip eval + canonical block labels + freeform spans).
- `eval_canonical.py` compares pipeline structural chunks to canonical gold spans.
- `eval_freeform.py` compares pipeline chunk predictions to freeform span gold labels via block-range overlap.
