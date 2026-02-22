Label Studio benchmark mode helpers.

- `ingest.py` builds a full extracted text archive and uploads chunk tasks (pipeline), block tasks (canonical), or freeform span tasks.
- `label_config_blocks.py` defines the block-classification labeling UI.
- `label_config_freeform.py` defines text-span highlighting labels for freeform projects.
- `block_tasks.py` generates canonical block tasks with stable block IDs and context windows.
- `freeform_tasks.py` builds segment-based freeform tasks with stable segment IDs and block offset mappings.
- `prelabel.py` adds Codex-CLI prelabel support: block-index suggestions -> deterministic span offsets, plus merge/idempotence helpers for decorate mode. Default command is non-interactive (`codex exec -`) and plain `codex` auto-retries with `exec -` on TTY errors.
- `export.py` pulls annotations back and converts them into JSONL (pipeline tip eval + canonical block labels + freeform spans).
- `eval_canonical.py` compares pipeline structural chunks to canonical gold spans.
- `eval_freeform.py` compares pipeline chunk predictions to freeform span gold labels via block-range overlap.
- `eval_freeform.py` now also emits an `app_aligned` summary (deduped predictions, supported-label-only metrics, relaxed overlap, and any-overlap coverage) alongside strict span metrics.
- `eval_freeform.py` also emits `classification_only` diagnostics focused on label agreement/coverage with boundary-insensitive overlap.
- `labelstudio-benchmark` now also writes stage-style processed cookbook output to `data/output` (override via `--processed-output-dir`) while still writing benchmark artifacts to `data/golden`.
- `labelstudio-import --prelabel` can upload completed freeform annotations (with fallback to post-import per-task annotation create if inline annotation import is rejected).
- Prelabel/decorate progress callbacks now emit `task X/Y` counters for spinner visibility during long AI-label loops.
- Interactive freeform import now exposes prelabel modes (`off`, strict/allow-partial annotations, plus predictions variants) that map directly to `--prelabel-upload-as` and `--prelabel-allow-partial`.
- Freeform prelabel/decorate now support explicit `--codex-model` selection (or Codex CLI default discovery), and token usage totals are always captured into `prelabel_report.json` / `decorate_report.json`.
- `labelstudio-decorate` re-annotates existing freeform projects additively (new annotation, original preserved), with `--no-write` dry-run reporting.
