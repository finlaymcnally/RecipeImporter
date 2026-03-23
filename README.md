# Recipe Import (`cookimport`)

> README goal
> Keep this file as the simple current walkthrough for running the tool. If deeper behavior needs explanation, link to the owning doc instead of re-teaching old flows here.

## What This Tool Does

Put recipe sources in `data/input/`, run the CLI, and it writes a fresh timestamped run under `data/output/`.

Main input types:
- Excel: `.xlsx`, `.xlsm`
- EPUB: `.epub`
- PDF: `.pdf`
- Word/text: `.docx`, `.txt`, `.md`, `.markdown`
- Paprika: `.paprikarecipes`
- RecipeSage-style JSON: `.json`
- Web recipe/schema sources: `.html`, `.htm`, `.jsonld`, some `.json`

Main outputs from a stage run:
- `intermediate drafts/` for schema.org-style recipe JSON-LD
- `final drafts/` for cookbook outputs
- `sections/`, `tips/`, `chunks/`, and `tables/` when present
- `raw/` debug artifacts
- `stage_observability.json`
- `run_manifest.json`
- per-source report JSON at the run root

Timestamp format everywhere is:

```text
YYYY-MM-DD_HH.MM.SS
```

## Quick Start

### 1. Put files in `data/input/`

Interactive mode scans only the top level of `data/input/`.

```text
data/input/
```

### 2. Activate the project venv

```bash
cd /home/mcnal/projects/recipeimport
. .venv/bin/activate
```

### 3. Start the interactive menu

```bash
C3imp
```

Useful shortcut:

```bash
C3imp 10
```

That keeps the interactive flow, but limits each imported file to the first 10 recipes and 10 tips.

You can also use:
- `cookimport` to enter interactive mode
- `import` or `C3import` to immediately run `stage data/input`

## Main Workflows

### Stage

This is the normal path.

Interactive path:
1. Choose `Stage: Convert files from data/input into cookbook outputs`
2. Pick one file or `Import all`
3. Choose `Vanilla / no Codex` or `CodexFarm`
4. If you choose `CodexFarm`, the next screen lets you toggle:
   - recipe correction
   - non-recipe knowledge review
   - prompt counts for enabled Codex steps
5. Wait for the run to finish

Direct CLI examples:

```bash
cookimport stage data/input
```

```bash
cookimport stage data/input/my-book.epub --limit 20
```

```bash
cookimport stage data/input/some-folder --out data/output
```

Important behavior:
- interactive mode scans only top-level files in `data/input`
- `cookimport stage <folder>` scans that folder recursively
- large PDFs and EPUBs can split into worker jobs and merge back into one run

### Label Studio Upload

Current Label Studio task generation is freeform-only.

Interactive path:
1. Choose `Label Studio upload: Create labeling tasks (uploads)`
2. Pick a source file
3. Pick a project name, or leave blank
4. Set freeform segment sizing
5. Optionally enable AI prelabeling
6. The interactive flow uploads directly after credential resolution

Current interactive rules:
- task scope is `freeform-spans` only
- interactive upload uses overwrite behavior for the target project
- there is no second upload confirmation prompt

Direct CLI example:

```bash
cookimport labelstudio-import data/input/my-book.epub \
  --project-name my-book \
  --allow-labelstudio-write
```

If you want AI prelabels too:

```bash
cookimport labelstudio-import data/input/my-book.epub \
  --project-name my-book \
  --prelabel \
  --prelabel-granularity span \
  --allow-labelstudio-write \
  --allow-codex
```

### Label Studio Export

Use this after labeling to pull your gold data back to disk.

Interactive path:
1. Choose `Label Studio export: Export completed labels into golden artifacts`
2. Pick the project
3. Export

Current export scope:
- `freeform-spans` only

Direct CLI example:

```bash
cookimport labelstudio-export --project-name my-book
```

### Evaluate / Benchmark Against Gold

Use this when you already have exported freeform gold and want to score predictions.

Interactive benchmark flow stays offline and compares predictions against freeform gold.

Direct CLI examples:

```bash
cookimport labelstudio-benchmark \
  --source-file data/input/my-book.epub \
  --gold-spans data/golden/pulled-from-labelstudio/my-book/exports/freeform_span_labels.jsonl \
  --eval-mode canonical-text \
  --no-upload
```

```bash
cookimport labelstudio-eval \
  --pred-run data/golden/benchmark-vs-golden/some-run/prediction_run \
  --gold-spans data/golden/pulled-from-labelstudio/my-book/exports/freeform_span_labels.jsonl \
  --output-dir data/golden/benchmark-vs-golden/manual-eval
```

For direct control, `labelstudio-benchmark` supports both:
- `--eval-mode stage-blocks`
- `--eval-mode canonical-text`

### Dashboard

Build the lifetime dashboard here:

```bash
cookimport stats-dashboard
```

Default output:

```text
.history/dashboard/
```

#### Compare & Control

This lives inside the dashboard's `Previous Runs` section.
It has its own analysis scope and does not use the table filters from `History Table & Trend`.

Use it when you want to answer:
- what seems to move quality, runtime, or cost
- whether that result still holds when you compare more similar runs

Simple workflow:
1. Set `Outcome` to the number you care about.
2. Set `Compare by` to the thing you want to test, like model, effort, or importer.
3. Choose a `View`:
   - `discover`: helps you find a good compare field
   - `raw`: quick direct comparison
   - `controlled`: fairer comparison that tries to hold other fields constant
4. Optionally add `Hold constant` fields if you want more apples-to-apples comparisons.
5. Optionally use `Split by` to repeat the same comparison inside buckets, like by importer.

Rule of thumb:
- start with `discover` if you do not know what field to test
- start with `raw` for a quick signal
- switch to `controlled` when the result might be explained by other differences
- if `controlled` shows weak coverage, remove some controls and re-check

How to read results:
- if `raw` and `controlled` agree, confidence goes up
- if they disagree, prefer `controlled`, but only if coverage looks decent

Useful dashboard behaviors:
- categorical `Compare by` fields show a group table with rows, averages, and any available side metrics
- you can limit compare/control to selected groups with `Apply local subset`
- that local subset does not change the main history table filters
- you can open `Set 2` to compare two hypotheses side by side
- when `Set 2` is open, chart layout can be `side by side` or `combined`

Terminal versions of the same analysis:

```bash
cookimport compare-control run --action analyze --view controlled --outcome-field strict_accuracy --compare-field ai_model
```

```bash
cookimport compare-control run --action insights --outcome-field strict_accuracy
```

```bash
cookimport compare-control agent
```

If the dashboard is open with `--serve`, you can also push live Compare & Control state into the browser:

```bash
cookimport compare-control dashboard-state --compare-field ai_model --view raw --outcome-field strict_accuracy
```

```bash
cookimport compare-control dashboard-state --set secondary --compare-field ai_effort --view controlled --enable-second-set --chart-layout combined
```

If `discover` keeps surfacing noisy fields, tune the suggested cards:

```bash
cookimport compare-control discovery-preferences --exclude-field processed_report_path --exclude-field run_config_hash --prefer-field ai_model --prefer-field ai_effort --demote-pattern path --demote-pattern hash --max-cards 8
```

QualitySuite shortcut:
- after `cookimport bench quality-run` or `cookimport bench quality-compare`, open that run's `agent_compare_control/` folder
- read `qualitysuite_compare_control_index.json` first
- if you need deeper follow-up, run:

```bash
cookimport compare-control agent --output-root data/output --golden-root data/golden < agent_compare_control/agent_requests.jsonl > agent_responses.jsonl
```

## Where Files Go

### Stage runs

```text
data/output/<YYYY-MM-DD_HH.MM.SS>/
```

Typical contents:
- `intermediate drafts/`
- `final drafts/`
- `sections/`
- `tips/`
- `chunks/`
- `tables/`
- `raw/`
- `stage_observability.json`
- `run_manifest.json`
- `<source>.excel_import_report.json`

### Label Studio task-generation runs

```text
data/golden/sent-to-labelstudio/<YYYY-MM-DD_HH.MM.SS>/labelstudio/<book_slug>/
```

### Label Studio exports

```text
data/golden/pulled-from-labelstudio/<source_slug_or_project_slug>/exports/
```

Common export files:
- `freeform_span_labels.jsonl`
- `freeform_segment_manifest.jsonl`
- `canonical_text.txt`
- `canonical_span_labels.jsonl`
- `summary.json`

### Benchmark runs

```text
data/golden/benchmark-vs-golden/<YYYY-MM-DD_HH.MM.SS>/
```

## Settings You Can Tweak Without Coding

Use the interactive `Settings` screen when you want defaults saved to `cookimport.json`.

Common saved defaults:
- `output_dir`
- `workers`
- `pdf_split_workers`
- `epub_split_workers`
- `pdf_pages_per_job`
- `epub_spine_items_per_job`
- `epub_extractor`
- `pdf_ocr_policy`
- `warm_models`
- Label Studio URL and API key
- Codex command/path/model defaults

Rule of thumb:
- use `Settings` when you want the default to stick
- use per-run prompts or CLI flags when you are just experimenting

## Handy Extras

### Inspect a workbook and write a mapping stub

```bash
cookimport inspect data/input/your-workbook.xlsx --write-mapping
```

That writes a stub under:

```text
data/output/mappings/
```

### EPUB debugging

If an EPUB import looks wrong, compare extraction output directly:

```bash
cookimport epub blocks data/input/your-book.epub --extractor unstructured --out /tmp/epub-blocks --force
```

```bash
cookimport epub candidates data/input/your-book.epub --extractor unstructured --out /tmp/epub-candidates --force
```

### Performance regression checks

When you are changing runtime performance, use the bench speed tools:

```bash
cookimport bench speed-discover
```

```bash
cookimport bench speed-run
```

```bash
cookimport bench speed-compare
```

## Deeper Docs

For current source-of-truth docs, start here:
- `docs/02-cli/02-cli_README.md`
- `docs/03-ingestion/03-ingestion_readme.md`
- `docs/06-label-studio/06-label-studio_README.md`
- `docs/07-bench/07-bench_README.md`
- `docs/08-analytics/08-analytics_readme.md`

## One-Time Setup If `.venv` Is Missing

```bash
cd /home/mcnal/projects/recipeimport
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e .[dev]
```
