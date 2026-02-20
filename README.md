# Recipe Import

This project is now interactive-first.

## Quick Start (Interactive)

```bash
cd /home/mcnal/projects/recipeimport
. .venv/bin/activate
C3imp
```

Optional: limit output during interactive runs:

```bash
C3imp 10
```

`10` means: at most 10 recipes and 10 tips per imported file.

## Beginner Walkthrough: Import an EPUB with Auto Extractor

This is the easiest path if you have never used this project before.

1. Open a terminal and go to the project:

```bash
cd /home/mcnal/projects/recipeimport
```

2. Activate the virtual environment:

```bash
. .venv/bin/activate
```

3. Put your EPUB file in:

```text
data/input
```

Example:

```bash
cp /path/to/your-book.epub data/input/
```

4. Start interactive mode:

```bash
C3imp
```

5. In the interactive menu:
   1. Choose `Settings`.
   2. Set `epub_extractor` to `auto`.
   3. Leave other values at defaults unless you know you need changes.
   4. Go back to main menu.

6. Choose `Import`, then select your EPUB file.

7. Wait for completion, then check the newest run folder in:

```text
data/output/<YYYY-MM-DD_HH.MM.SS>/
```

Important files to look at:
- Main report:

```text
data/output/<run>/your-book.excel_import_report.json
```

- Auto extractor decision artifact:

```text
data/output/<run>/raw/epub/<source_hash>/epub_extractor_auto.json
```

Inside the main report, look for:
- `runConfig.epub_extractor_requested`
- `runConfig.epub_extractor_effective`
- `epubAutoSelection`
- `epubAutoSelectedScore`

## Optional: Run a One-File Extractor Race (Debug)

After an import, you can run a focused extractor comparison on one EPUB:

```bash
cookimport epub race data/input/your-book.epub --out /tmp/epub-race --force
```

This writes:

```text
/tmp/epub-race/epub_race_report.json
```

Use this when you want a quick, deterministic backend comparison (`unstructured`, `markdown`, `legacy`) without running a full import.

## Interactive Mode Walkthrough

```text
Legend:
  [X] = matching labeled section below
  ~~> = one-level Backspace navigation (only on _menu_select prompts)

[A] Enter interactive mode (`cookimport` with no subcommand)
  |
  v
[B] Startup (load settings + scan top-level data/input files)
  |
  v
[C] Main Menu
  +--> [D] Import -------------------------> stage(...) ------------------> [C]
  |
  +--> [E] Label Studio import
  |       `--> [E] Unified prompt + artifact generation + upload flow -> run_labelstudio_import(...) -> [C]
  |
  +--> [F] Label Studio export ------------> run_labelstudio_export(...) -> [C]
  |
  +--> [G] Benchmark vs freeform gold
  |       +--> [G1] Eval-only -------------> labelstudio-eval -----------> [C]
  |       `--> [G2] Upload ----------------> labelstudio-benchmark ------> [C]
  |
  +--> [H] Generate dashboard -------------> stats-dashboard -------------> [C]
  |
  +--> [I] Settings -----------------------> save `cookimport.json` ------> [C]
  |
  `--> [Z] Exit (user selects Exit)
```

### [A] Enter Interactive Mode

Interactive mode is entered when `cookimport` is run without a subcommand.

### [B] Startup

Startup behavior:

1. Loads settings from `cookimport.json` (or defaults if missing/invalid).
2. Sets `input_folder = data/input`.
3. Scans only top-level files in `data/input` for importer support (not recursive).
4. Builds the main menu choices.
5. Uses Backspace as one-level "go back" in prompts wired through `_menu_select`.

Important divergence to remember:
- interactive file selection is top-level only, but `cookimport stage <folder>` is recursive when a folder path is passed directly.

### [C] Main Menu

Menu options:

- `Stage files from data/input - produce cookbook outputs`
- `Label Studio: create labeling tasks (uploads)`
- `Label Studio: export completed labels to golden artifacts`
- `Evaluate predictions vs freeform gold (re-score or generate)`
- `Generate dashboard - build lifetime stats dashboard HTML`
- `Settings - tune worker/OCR/output defaults`
- `Exit - close the tool`

Availability rule:

- `Import` and `Label Studio task upload` only appear when at least one supported top-level file exists in `data/input`.
- `inspect` remains available as a direct command (`cookimport inspect <path>`), not as an interactive menu action.

Menu numbering and shortcuts:

- `_menu_select` now shows Questionary shortcut labels on all select-style menus (for example `1)`, `2)`, ...).
- Numeric shortcuts (`1-9`, `0`) select immediately in interactive menus; non-numeric shortcuts still move focus and can be confirmed with Enter.

### [I] Settings

`Settings` edits global defaults in `cookimport.json`.

Interactive `Import` and benchmark upload runs now include a per-run chooser (`global defaults` / `last run` / `change run settings`) so experiments do not mutate these global defaults.

Config keys and defaults:

- `workers` (default `7`)
- `pdf_split_workers` (default `7`)
- `epub_split_workers` (default `7`)
- `epub_extractor` (default `unstructured`)
- `epub_unstructured_html_parser_version` (default `v1`)
- `epub_unstructured_skip_headers_footers` (default `false`)
- `epub_unstructured_preprocess_mode` (default `br_split_v1`)
- `ocr_device` (default `auto`)
- `ocr_batch_size` (default `1`)
- `output_dir` (default `data/output`)
- `label_studio_url` (default unset; populated after first interactive Label Studio prompt)
- `label_studio_api_key` (default unset; populated after first interactive Label Studio prompt)
- `pdf_pages_per_job` (default `50`)
- `epub_spine_items_per_job` (default `10`)
- `warm_models` (default `false`)

What each setting affects:

- `workers`, split workers, page/spine split size: `stage` and benchmark import parallelism/sharding.
- `epub_extractor`: runtime extractor choice (`unstructured`, `legacy`, `markdown`, `auto`, or `markitdown`) via `C3IMP_EPUB_EXTRACTOR`.
- `epub_unstructured_html_parser_version`: parser version (`v1` or `v2`) passed into Unstructured HTML partitioning.
- `epub_unstructured_skip_headers_footers`: enables Unstructured `skip_headers_and_footers` for EPUB HTML partitioning.
- `epub_unstructured_preprocess_mode`: HTML pre-normalization mode before Unstructured (`none`, `br_split_v1`, or `semantic_v1` alias).
- `ocr_device`, `ocr_batch_size`: OCR path for PDFs.
- `output_dir`: interactive `stage` target output root.
- `label_studio_url`, `label_studio_api_key`: interactive Label Studio import/export credential defaults.
- `warm_models`: preloads SpaCy, ingredient parser, and OCR model before staging.

Developer note:
- Per-run toggle definitions live in `cookimport/config/run_settings.py`. Add new fields there with `ui_*` metadata so the interactive editor picks them up automatically.

### [D] Import Flow

`Import` steps:

1. Prompt for `Import All` or one selected file from top-level `data/input`.
2. Show `Run settings` mode picker:
   - `Run with global defaults (...)`
   - `Run with last import settings (...)` when available
   - `Change run settings...` (full-screen arrow-key editor)
3. Applies selected EPUB env vars:
   - `C3IMP_EPUB_EXTRACTOR`
   - `C3IMP_EPUB_UNSTRUCTURED_HTML_PARSER_VERSION`
   - `C3IMP_EPUB_UNSTRUCTURED_SKIP_HEADERS_FOOTERS`
   - `C3IMP_EPUB_UNSTRUCTURED_PREPROCESS_MODE`
4. Calls `stage(...)` using selected per-run workers/OCR/split/warm-model values.
5. Saves selected settings to `<output_dir>/.history/last_run_settings_import.json` after a successful run.
6. Uses `limit` only if `C3IMP_LIMIT` was set before entering interactive mode.
7. Prints `Outputs written to: <run_folder>`.
8. Returns to the main menu after successful import.

### [E] Label Studio Import Flow

1. Choose a source file.
   - The menu shows supported files from `data/input`.
   - Pick the file you want to create labeling tasks from.
2. Enter a project name (or leave it blank).
   - If blank, the tool uses a name based on the file name.
   - If a project with that final name already exists, this flow replaces it.
3. Choose task type (`task_scope`).
   - You are choosing what kind of labeling jobs the program will create.
   - There are 5 practical choices:
   - `pipeline` + `structural`:
   - Creates bigger recipe-section tasks.
   - Use this when you want a faster, higher-level labeling pass.
   - `pipeline` + `atomic`:
   - Creates smaller, line-like tasks.
   - Use this when you want detailed labels on fine-grained chunks.
   - `pipeline` + `both`:
   - Creates both structural and atomic tasks in one run.
   - Use this when you want broad coverage and can label more tasks.
   - `canonical-blocks`:
   - Creates one task per extracted text block, with one label per block.
   - Asks for `context_window` (number `>= 0`), which controls how much nearby text is shown for context.
   - Use this when you want complete block-by-block classification.
   - `freeform-spans`:
   - Creates segment tasks where you highlight exact text ranges (spans).
   - Asks for `segment_blocks` (number `>= 1`) and `segment_overlap` (number `>= 0`) to control segment size and overlap.
   - Use this when you need precise span annotations for downstream freeform export/eval.
   - In all 5 cases, the output is a set of Label Studio tasks that gets uploaded and later exported/evaluated with the matching scope.
4. Enter Label Studio URL and API key if needed.
   - If `LABEL_STUDIO_URL` and `LABEL_STUDIO_API_KEY` are set, prompts are skipped.
   - Otherwise, interactive mode uses saved `cookimport.json` values when present.
   - If still missing, you are prompted once and the entered values are saved to `cookimport.json` for future interactive runs.
5. The tool builds tasks on your machine.
   - It prepares text/chunk or block/segment tasks based on your scope choice.
   - It writes run files under `data/golden`:
   - `label_studio_tasks.jsonl`
   - `coverage.json`
   - `extracted_archive.json`
   - `extracted_text.txt`
   - `manifest.json`
6. The tool uploads tasks to Label Studio automatically.
   - No extra "are you sure?" prompt in this interactive flow.
   - Upload is batched in groups of 200 tasks.
   - `manifest.json` is updated with project ID, upload count, and project URL.
7. Review the summary shown in terminal.
   - You get a quick recap of project/tasks/run location.
8. Interactive mode returns to the main menu after the flow completes.

### [F] Label Studio Export Flow

`Label Studio export` steps:

1. Uses `LABEL_STUDIO_URL` / `LABEL_STUDIO_API_KEY` env vars when present; otherwise prompts for them.
   - If env vars are unset, interactive mode reuses saved `cookimport.json` values before prompting.
   - Newly prompted values are saved to `cookimport.json`.
2. Fetches Label Studio projects and shows a project picker.
   - In plain English: choose an existing project title instead of typing it.
   - The picker shows each project with a detected type tag (for example `pipeline`, `canonical-blocks`, `freeform-spans`) when available.
   - Includes a manual-entry option when needed.
3. Falls back to manual project-name entry when project discovery fails (or no projects exist).
4. Uses the selected project's detected type as `export_scope` when available.
   - If the selected project type is `unknown` (or project name is typed manually), interactive mode prompts for `export_scope` (`pipeline`, `canonical-blocks`, `freeform-spans`).
5. Calls `run_labelstudio_export(...)` with `output_dir=data/golden`.
   - By default, export writes to: `data/golden/<project_slug>/exports/`.
   - If `--run-dir` is supplied in non-interactive mode, export writes to that run directory.
6. Prints export summary path and returns to the main menu.

### [G] Benchmark vs Freeform Gold Flow

`Evaluate predictions vs freeform gold` supports two paths:

- `eval-only` when both gold exports and prediction runs exist.
- `upload` mode (default/fallback) for generating fresh predictions.
- If either artifact set is missing, interactive mode skips the mode picker and goes straight to upload mode.

Why both paths exist:

1. Benchmark always needs two inputs:
- labeled `gold` spans (`freeform_span_labels.jsonl`)
- pipeline `predictions` (`label_studio_tasks.jsonl` run directory)
2. `eval-only` is the "re-score" path:
- no new upload
- no new prediction generation
- fastest way to compare an existing prediction run against updated gold labels or updated eval settings.
3. `upload` is the "make predictions first" path:
- creates a fresh prediction run
- uploads tasks to Label Studio
- then evaluates those fresh predictions against gold.

Typical reasons to use `eval-only` again on an old run:

- You corrected or expanded freeform gold labels and want updated scores.
- You changed eval settings (`overlap_threshold` or `force_source_match`) and want a fresh report on the same predictions.
- You changed evaluator/report formatting and want regenerated artifacts without creating new predictions.

### [G1] Eval-Only Branch

1. Select freeform gold export (`**/exports/freeform_span_labels.jsonl`).
2. Select prediction run (`**/label_studio_tasks.jsonl` run directory).
3. Prints `Eval-only mode: no pipeline run settings applied.`
4. Runs `labelstudio-eval scope=freeform-spans` into `data/golden/eval-vs-pipeline/<timestamp>`.
5. Returns to the main menu.

### [G2] Upload Branch

1. Shows benchmark `Run settings` mode picker (`global` / `last benchmark` / `change`), using the same editor flow as Import.
2. Resolves Label Studio credentials from env (`LABEL_STUDIO_URL` / `LABEL_STUDIO_API_KEY`) or saved interactive settings; if still missing, prompts and saves values to `cookimport.json`.
3. Calls `labelstudio-benchmark(...)` with selected per-run settings (extractor, workers/split controls, OCR options, warm-model flag).
4. Saves selected settings to `<output_dir>/.history/last_run_settings_benchmark.json` after a successful upload/eval run.
5. Returns to the main menu on completion.

### [H] Generate Dashboard Flow

1. Prompts `Open dashboard in your browser after generation?`.
2. Runs `stats-dashboard` using the interactive `output_dir` setting as `--output-root`.
3. Writes dashboard files to `<output_dir>/.history/dashboard`.
4. Opens `index.html` automatically when you answer `Yes`.
5. Returns to the main menu on completion.

### [Z] Exit Conditions

Interactive mode exits when:

- user selects `Exit` from the main menu.

## Label Studio Setup (Optional)

```bash
cd /home/mcnal/projects/recipeimport
docker start labelstudio
```

If this is your first run and the container does not exist yet:

```bash
docker run -d \
  --name labelstudio \
  --restart unless-stopped \
  -p 8080:8080 \
  -v labelstudio_data:/label-studio/data \
  heartexlabs/label-studio:latest
```

Then open `http://localhost:8080` and create/get your API token.

## Advanced CLI Reference (Coding/Agent)

Full command/flag/environment documentation lives in:

- `docs/02-cli/02-cli_README.md`
