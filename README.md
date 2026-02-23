# Recipe Import (cookimport)

## Full Processing Flowchart (File Types + Label Studio)

```text
START
|-- Put source(s) in `data/input/`
|   |-- Interactive mode: top-level files only
|   `-- `cookimport stage <folder>`: recursive scan
|-- Launch
|   |-- Interactive menu: `C3imp` (or `C3imp <N>` for a test-limit run)
|   `-- Direct CLI: `cookimport <command>`
|
|-- Choose workflow
|   |-- A) Stage/import pipeline (writes cookbook outputs)
|   |   |-- File selection: Import All / one file
|   |   |-- Run settings mode: global defaults / last import / one-run custom
|   |   |-- Optional runtime toggles: warm models, OCR device, EPUB extractor, split sizes/workers, optional codex-farm recipe/knowledge passes
|   |   `-- Per-file execution path
|   |       |-- `.xlsx` / `.xlsm` (Excel importer)
|   |       |   `-- single conversion -> write intermediate/final/tips/chunks/raw/report
|   |       |-- `.txt` / `.md` / `.markdown` / `.docx` (Text importer)
|   |       |   `-- single conversion -> write outputs
|   |       |-- `.paprikarecipes` (Paprika importer)
|   |       |   `-- single conversion -> write outputs
|   |       |-- `.json` with RecipeSage shape (RecipeSage importer)
|   |       |   `-- single conversion -> write outputs
|   |       |-- `.pdf` (PDF importer)
|   |       |   |-- Split eligible? (`pdf_split_workers > 1`, `pdf_pages_per_job > 0`, multi-range plan)
|   |       |   |   |-- yes -> parallel page-range jobs -> merge -> reassign IDs -> merge raw -> write once
|   |       |   |   `-- no  -> single conversion -> write once
|   |       |   `-- OCR path (`auto`/`cpu`/`cuda`/`mps`) used when scanned/image pages need OCR
|   |       `-- `.epub` (EPUB importer)
|   |           |-- Extractor requested: `unstructured` | `legacy` | `markdown` | `auto` | `markitdown`
|   |           |   |-- `auto` -> deterministic pre-selection -> effective extractor + auto artifact
|   |           |   `-- effective extractor runs
|   |           |-- Split eligible?
|   |           |   |-- `unstructured` / `legacy` / `markdown` + split settings -> parallel spine jobs -> merge
|   |           |   `-- `markitdown` -> whole-book conversion (no spine split)
|   |           `-- write outputs + report (auto-selection fields when auto is used)
|   |
|   |-- B) EPUB debug race (EPUB only)
|   |   `-- choose EPUB -> choose output folder -> choose candidate extractors -> race report
|   |
|   |-- C) Label Studio: create labeling tasks (uploads)
|   |   |-- choose file -> project name (blank auto-name) -> overwrite existing project
|   |   |-- choose task scope
|   |   |   |-- `pipeline` -> chunk level: `both` / `structural` / `atomic`
|   |   |   |-- `canonical-blocks` -> context window (`0..N` blocks)
|   |   |   `-- `freeform-spans`
|   |   |       |-- segment size + overlap
|   |   |       `-- AI prelabel mode
|   |   |           |-- off
|   |   |           |-- strict/allow-partial annotations
|   |   |           |-- strict/allow-partial predictions
|   |   |           `-- if enabled: prelabel granularity = `span` (actual freeform) or `block` (legacy)
|   |   |-- conversion under the hood uses the same importer/file-type branches as Stage (including PDF/EPUB split and EPUB extractor logic)
|   |   |-- credentials resolution: env -> `cookimport.json` -> prompt/save
|   |   `-- uploads tasks and writes artifacts (`manifest.json`, tasks JSONL, coverage, extracted files, prelabel reports if used)
|   |
|   |-- D) Label Studio: export completed labels
|   |   |-- choose project (or type project name)
|   |   |-- scope auto-detected when possible; else prompt: `pipeline` / `canonical-blocks` / `freeform-spans`
|   |   `-- write export artifacts by scope
|   |       |-- pipeline -> `labeled_chunks.jsonl`, `golden_set_tip_eval.jsonl`, `summary.json`
|   |       |-- canonical-blocks -> `canonical_block_labels.jsonl`, `canonical_gold_spans.jsonl`, `summary.json`
|   |       `-- freeform-spans -> `freeform_span_labels.jsonl`, `freeform_segment_manifest.jsonl`, `summary.json`
|   |
|   |-- E) Evaluate predictions vs freeform gold
|   |   |-- eval-only: pick existing gold + prediction run -> `labelstudio-eval` (no upload)
|   |   `-- upload path: generate fresh predictions + upload + evaluate
|   |       `-- CLI-only extra permutation: `--no-upload` (fully offline benchmark path)
|   |
|   `-- F) Generate dashboard
|       `-- build lifetime HTML dashboard from output history
|
`-- Output roots
    |-- Stage/import runs: `data/output/<YYYY-MM-DD_HH.MM.SS>/`
    |-- Label Studio import/benchmark prediction runs: `data/golden/<YYYY-MM-DD_HH.MM.SS>/labelstudio/<book_slug>/`
    `-- Label Studio exports: `data/golden/<project_slug>/exports/`
```

> README goal (for humans and future AIs editing this file)
>
> Keep this README as a simple, step-by-step, non-coder walkthrough for setting up, running, and tweaking an import pipeline.
> Put deep reference material in `docs/` (especially `docs/02-cli/02-cli_README.md`) and link to it from here.

## Choice Tree (Start Here)

```text
Start
|-- Step 1) Put your file(s) in `data/input/`
|   `-- Important: interactive mode only shows top-level files in `data/input/`
|-- Step 2) Every time: launch the tool
|   |-- `cd /home/mcnal/projects/recipeimport`
|   |-- . .venv/bin/activate
|   `-- C3imp (or `C3imp 10` for a small test run)
`-- Step 3) In the menu, pick a workflow
    |-- Import: stage files -> outputs in `data/output/<YYYY-MM-DD_HH.MM.SS>/`
    |-- Settings: change defaults (saved in `cookimport.json`)
    |-- EPUB debug: race extractors on one file (EPUB only)
    |-- Label Studio: create labeling tasks (optional)
    |-- Label Studio: export completed labels (optional)
    |-- Label Studio: decorate with AI spans (optional)
    |-- Evaluate predictions vs freeform gold (optional)
    `-- Generate dashboard (optional)
```

## What This Tool Does (Plain English)

You drop recipe sources into `data/input/` (EPUB/PDF/Excel/Word/text exports). Then you run the tool.

Each import run creates a new timestamped folder under `data/output/` like:

```text
data/output/2026-02-20_21.45.00/
```

That run folder contains:
- Converted recipe outputs (intermediate + final)
- Tips/knowledge snippets (when found)
- Raw extraction artifacts (useful for debugging)
- A JSON report that summarizes what happened

## Step 1: Put Your Source File(s) in `data/input/`

1. Copy your file into:

```text
data/input/
```

2. Keep it top-level (no subfolders).
   - Interactive mode only lists files directly inside `data/input/`.
   - Batch mode (`cookimport stage <folder>`) scans folders recursively.

Common inputs this project recognizes:
- Excel workbooks: `.xlsx`, `.xlsm`
- EPUB books: `.epub`
- PDFs: `.pdf`
- Word docs: `.docx`
- Plain text: `.txt`, `.md`, `.markdown`
- Paprika: `.paprikarecipes`
- RecipeSage export: `.json` (expects a `recipes` array)

## Step 2: Launch the Tool (Every Time)

Run:

```bash
cd /home/mcnal/projects/recipeimport
. .venv/bin/activate
C3imp
```

Optional: do a small "test run" first:

```bash
C3imp 10
```

That limits each imported file to at most 10 recipes and 10 tips (faster, less output).

Optional check (shows help instead of starting the menu):

```bash
cookimport --help
```

## Step 3: Pick a Workflow (What Each Menu Option Means)

The menu shows different options depending on what is in `data/input/`:
- **Stage files...** and **Label Studio: create labeling tasks...** only appear when at least one supported top-level file exists in `data/input/`.
- **EPUB debug: race extractors...** only appears when at least one top-level `.epub` exists in `data/input/`.

After you complete any workflow, the tool returns to the main menu. It only exits when you choose **Exit**.

Tip: On list-style menus (where you pick from a list), Backspace goes back one level.

### Choice Tree: Main Menu + Sub-Prompts

```text
Main Menu ("What would you like to do?")
|-- Stage files from data/input - produce cookbook outputs
|   |-- Which file(s) would you like to import?
|   |   |-- Import All - process every supported file
|   |   `-- <pick one file>
|   |-- Run settings
|   |   |-- Run with global defaults (...)
|   |   |-- Run with last import settings (...) (disabled until you have a successful import)
|   |   `-- Change run settings... (one-run editor; does not change global defaults)
|   `-- Outputs written to: <output_dir>/<YYYY-MM-DD_HH.MM.SS>/
|
|-- Label Studio: create labeling tasks (uploads)
|   |-- Select a file to import into Label Studio
|   |-- Project name (leave blank to auto-name)
|   |-- Task scope:
|   |   |-- pipeline chunks -> Chunk level: both / structural only / atomic only
|   |   |-- canonical blocks -> Canonical context window (blocks): 0,1,2,...
|   |   `-- freeform spans -> Segment size + overlap (+ optional AI prelabel)
|   `-- Label Studio URL + API key (prompted if missing)
|
|-- EPUB debug: race extractors on one file
|   |-- Select an EPUB file for extractor race
|   |-- Race output folder (default: data/output/EPUBextractorRace/<book>)
|   |-- Output folder not empty? -> confirm overwrite
|   `-- Candidate extractors (comma-separated) (default: unstructured,markdown,legacy)
|
|-- Label Studio: export completed labels to golden artifacts
|   |-- Label Studio URL + API key (prompted if missing)
|   |-- Select Label Studio project to export:
|   |   |-- Type project name manually
|   |   `-- <pick a project from the list (shows detected type when possible)>
|   `-- Export scope (only if type is unknown): pipeline / canonical-blocks / freeform-spans
|
|-- Label Studio: decorate existing freeform project with AI spans
|   |-- Label Studio URL + API key (prompted if missing)
|   |-- Select Label Studio project (same picker as export)
|   |-- Select label types to add (checkbox; defaults include YIELD_LINE, TIME_LINE)
|   |-- Dry run only? (recommended first)
|   `-- If writing: confirm creating new annotations in Label Studio
|
|-- Evaluate predictions vs freeform gold (re-score or generate)
|   |-- If both gold exports and prediction runs exist: choose mode
|   |   |-- Eval-only: pick gold export + pick prediction run (no upload)
|   |   `-- Upload: generate predictions + evaluate (uploads to Label Studio)
|   `-- Writes evaluation artifacts under data/golden/eval-vs-pipeline/<YYYY-MM-DD_HH.MM.SS>/
|
|-- Generate dashboard - build lifetime stats dashboard HTML
|   |-- Open dashboard in your browser after generation?
|   `-- Writes to <output_dir>/.history/dashboard/
|
|-- Settings - tune worker/OCR/output defaults
|   `-- Settings Configuration
|       |-- Workers / PDF Split Workers / EPUB Split Workers
|       |-- EPUB Extractor + Unstructured tuning
|       |-- OCR Device + OCR Batch Size
|       |-- Output Folder
|       |-- PDF Pages/Job + EPUB Spine Items/Job
|       |-- Warm Models
|       `-- Back to Main Menu
|
`-- Exit - close the tool
```

### Stage Files from `data/input/` (Import Pipeline)

This is the main workflow. It reads file(s) from `data/input/` and writes a new run folder under your configured `output_dir`.

Sub-prompts you will see:
1. **Which file(s) would you like to import?**
   - **Import All**: processes every supported file in `data/input/`
   - Or pick one file: runs the import for that file only
2. **Run settings**
   - **Run with global defaults**: uses your saved defaults (from `cookimport.json`)
   - **Run with last import settings**: repeats the settings from your last successful import
   - **Change run settings...**: lets you experiment for this run only (it does not change your global defaults)
3. If you choose **Change run settings...**, a full-screen editor opens.
   - Up/Down moves between settings.
   - Left/Right changes a value.
   - Enter lets you type an exact value.
   - `S` saves and starts the run; `Q`/Esc cancels.

### Settings (Change Your Defaults)

This edits your saved defaults and writes them to `cookimport.json`. It affects future imports and future benchmark "upload" runs.

Sub-menu options (Settings Configuration):
- **Workers**: how many files/jobs to process in parallel (higher = faster, but uses more CPU/RAM)
- **PDF Split Workers**: how much parallelism is used to split one large PDF into parts
- **EPUB Split Workers**: how much parallelism is used to split one large EPUB into parts
- **EPUB Extractor**: how text is extracted from EPUBs (`auto` is a good first choice if you're unsure)
- **Unstructured HTML Parser** / **Skip Headers/Footers** / **EPUB Preprocess**: extra knobs for the `unstructured` EPUB extractor
- **OCR Device** / **OCR Batch Size**: only matters for scanned/image PDFs that need OCR
- **Output Folder**: where new run folders are written (this is your `output_dir`)
- **PDF Pages/Job** / **EPUB Spine Items/Job**: how large each split job is (smaller jobs can parallelize more)
- **Warm Models**: pre-load heavy models before work starts (slower startup, sometimes faster overall)

### EPUB Debug: Race Extractors on One File (EPUB Only)

Use this when an EPUB import looks wrong and you want to compare extractors on that one book without running a full import.

Sub-prompts you will see:
- Pick an EPUB file.
- Choose an output folder (default: `data/output/EPUBextractorRace/<book>`).
- If the folder is not empty, confirm overwrite behavior.
- Enter a comma-separated list of candidate extractors (default: `unstructured,markdown,legacy`).

### Label Studio: Create Labeling Tasks (Uploads)

Use this only if you want to do manual labeling in Label Studio.

Important behavior:
- This interactive flow always recreates the project if it already exists (it overwrites).
- It uploads tasks immediately (there is no extra "are you sure?" prompt after you pick options).

Sub-prompts you will see:
1. Pick a source file (from `data/input/`).
2. Pick a project name (or leave blank to auto-name it).
3. Pick a **task scope**:
   - **pipeline chunks**: label pipeline "chunks" (bigger or smaller units, depending on chunk level)
   - **canonical blocks**: label every extracted block (with optional context around it)
   - **freeform spans**: highlight arbitrary spans of text
4. Scope-specific prompts:
   - pipeline chunks: choose **Chunk level** (`both`, `structural`, `atomic`)
   - canonical blocks: choose **Context window** (how many blocks of context to show)
   - freeform spans: choose **Segment size** + **Overlap**, then choose **AI prelabel mode**
5. Enter Label Studio URL + API key if you have not already.
6. During task generation/upload, a spinner shows live phase updates and `task X/Y` progress when the total work count is known (including AI prelabeling).

Choice tree (Label Studio upload):

```text
Label Studio: create labeling tasks (uploads)
|-- Select a file
|-- Project name (blank = auto-name)
`-- Task scope
    |-- pipeline chunks
    |   `-- Chunk level: both / structural only / atomic only
    |-- canonical blocks
    |   `-- Context window (blocks): 0,1,2,...
    `-- freeform spans
        |-- Segment size (blocks per task): 1,2,3,...
        |-- Segment overlap (blocks): 0,1,2,...
        `-- AI prelabel mode (off / strict / allow-partial; requires local Codex CLI with `exec` support)
```

If you enable **AI prelabel**:
- It tries to generate initial AI annotations before upload.
- If you do not have the Codex CLI available (`codex exec -`), choose **No** to avoid errors.

### Label Studio: Export Completed Labels to Golden Artifacts

Use this after you have labeled tasks in Label Studio and want the labeled data downloaded to files.

Sub-prompts you will see:
- Enter Label Studio URL + API key (if needed).
- Pick a project from a list (or choose "Type project name manually").
- If the tool cannot detect the project type, choose an export scope (pipeline vs canonical-blocks vs freeform-spans).

Choice tree (Export):

```text
Label Studio: export completed labels to golden artifacts
|-- Label Studio URL + API key (if needed)
|-- Select project:
|   |-- Pick from list (shows detected type when possible)
|   `-- Type project name manually
`-- Export scope (only if unknown): pipeline / canonical-blocks / freeform-spans
```

### Label Studio: Decorate Existing Freeform Project with AI Spans

Use this to add new AI labels to an existing freeform project without deleting your existing human work.

Sub-prompts you will see:
- Pick a project (same picker as export).
- If the project type does not look like `freeform-spans`, you will be warned and asked if you want to try anyway.
- Choose which label types to add (checkbox list; defaults include `YIELD_LINE` and `TIME_LINE`).
- Choose dry-run (recommended) or write mode.
- If you choose write mode, it asks for a final confirmation before creating annotations in Label Studio.

Choice tree (Decorate):

```text
Label Studio: decorate existing freeform project with AI spans
|-- Select project
|-- Select label types to add (checkbox list)
|-- Dry run only? (recommended first)
|   `-- Yes -> writes a report only
`-- No -> confirm write -> creates new annotations in Label Studio
```

### Evaluate Predictions vs Freeform Gold (Re-Score or Generate)

Use this to compare pipeline predictions against your freeform "gold" labels.

Sub-prompts you may see:
- If both gold exports and prior prediction runs exist, you can choose:
  - **Eval-only**: re-score an existing prediction run (no upload)
  - **Upload**: generate fresh predictions and evaluate them (uploads to Label Studio)
- In eval-only mode, you pick:
  - a freeform gold export file
  - a prediction run folder
- In upload mode, you pick benchmark run settings (similar editor to import), then it uploads tasks + evaluates them.

Choice tree (Evaluate):

```text
Evaluate predictions vs freeform gold
|-- Eval-only (no upload)
|   |-- Select gold export
|   `-- Select prediction run
`-- Upload (generates predictions + uploads + evaluates)
    |-- Choose benchmark run settings
    `-- Label Studio URL + API key (if needed)
```

### Generate Dashboard

This builds a static HTML dashboard of run history under `<output_dir>/.history/dashboard/`.

Sub-prompt you will see:
- "Open dashboard in your browser after generation?" (Yes/No)

## Step 4: Run an Import (The Common Path)

1. Put at least one supported file in `data/input/` (Step 1).
2. Start `C3imp` (Step 2).
3. Choose **Stage files from data/input**.
4. Choose **Import All** or pick a single file.
5. Choose which settings to use for this run:
   - Use global defaults
   - Reuse the last run's settings
   - Change run settings (recommended when experimenting)
6. Wait for completion.
7. At the end, the tool prints an "Outputs written to:" path.

## Step 5: Find and Understand the Output Folder

Output root:

```text
data/output/
```

Each run creates a new timestamp folder:

```text
data/output/<YYYY-MM-DD_HH.MM.SS>/
```

Inside a run folder you will typically see:
- `intermediate drafts/` (schema.org-style Recipe JSON)
- `final drafts/` (cookbook outputs)
- `tips/` (tip/knowledge snippets)
- `raw/` (debug artifacts, including EPUB extraction artifacts)
- `*.excel_import_report.json` (the main report for a source file)

If you used `epub_extractor=auto`, look for the auto-selection artifact:

```text
data/output/<run>/raw/epub/<source_hash>/epub_extractor_auto.json
```

In the report JSON, search for:
- `runConfig` (the settings used)
- `runConfig.epub_extractor_requested` / `runConfig.epub_extractor_effective`

## Step 6: Tweak the Pipeline (Without "Coding")

### A) Change global defaults (saved in `cookimport.json`)

Use **Settings** in the interactive menu when you want a default to stick for future runs.

Common defaults to tweak:
- `output_dir`: where new run folders are written
- `workers`: how much parallelism to use (higher = faster, but uses more CPU)
- `epub_extractor`: how EPUB text is extracted
- `ocr_device`: only matters for scanned/image PDFs (auto/cpu/cuda/mps)

### B) Change settings for just one run (recommended for experiments)

When you start an import, choose the "Change run settings" option. This lets you try settings without permanently changing your defaults.

### C) Choose an EPUB extractor (simple guidance)

If you are importing an EPUB and results look messy, this is usually the first knob to try:
- `auto`: recommended first; it runs a deterministic comparison and picks an extractor
- `unstructured`: semantic extraction (often good, can be slower)
- `legacy`: older HTML parsing approach (sometimes better for specific books)
- `markdown`: converts HTML to Markdown before parsing
- `markitdown`: whole-book EPUB->markdown mode (legacy)

Tip: use the "EPUB debug: race extractors" menu item (next step) to compare extractors on one file.

### D) Excel mappings (optional, but powerful)

If an Excel workbook doesn't import correctly because the columns/headers don't match expectations:

1. Generate a mapping stub:

```bash
cookimport inspect data/input/your-workbook.xlsx --write-mapping
```

This writes:

```text
data/output/mappings/your-workbook.mapping.yaml
```

2. Use it in one of two ways:
   - Batch mode: pass it directly with `--mapping`.
   - Interactive mode: copy/rename it next to your workbook as `data/input/your-workbook.mapping.yaml` so the importer can discover it automatically.

## Step 7 (Optional): Compare EPUB Extractors (Debug)

Interactive path:
1. Run `C3imp`.
2. Choose **EPUB debug: race extractors on one file**.
3. Pick an EPUB, an output folder, and a candidate list.

Direct command path:

```bash
cookimport epub race data/input/your-book.epub --out data/output/EPUBextractorRace/your-book --force
```

This writes:

```text
data/output/EPUBextractorRace/your-book/epub_race_report.json
```

## Step 8 (Optional): Label Studio (Manual Labeling + Evaluation)

You only need this if you want to build a "golden set" of labels, add AI spans, or evaluate predictions.

### A) Start Label Studio (Docker)

If you already have a container:

```bash
docker start labelstudio
```

First-time setup:

```bash
docker run -d \
  --name labelstudio \
  --restart unless-stopped \
  -p 8080:8080 \
  -v labelstudio_data:/label-studio/data \
  heartexlabs/label-studio:latest
```

Open `http://localhost:8080` in your browser and create/get your API token.

### B) Create tasks (upload)

1. Run `C3imp`.
2. Choose **Label Studio: create labeling tasks (uploads)**.
3. Pick your source file.
4. Choose the task type (pipeline vs canonical-blocks vs freeform-spans).
5. Follow the prompts.

The tool writes local artifacts under:

```text
data/golden/
```

Note: Label Studio URL and API key can be saved in `cookimport.json`. Treat the API key like a password.

### C) Export "gold" labels

Use **Label Studio: export completed labels to golden artifacts** when you want your labeled data downloaded into files for evaluation.

### D) Add AI spans (decorate)

Use **Label Studio: decorate existing freeform project with AI spans** to add additional AI labels without deleting existing human work.

### E) Evaluate predictions vs gold

Use **Evaluate predictions vs freeform gold** to score pipeline predictions against your exported "gold" labels.

## Advanced Reference

Full command/flag/environment documentation lives in:
- `docs/02-cli/02-cli_README.md`

Cross-cutting "hidden rules" and conventions live in:
- `docs/IMPORTANT CONVENTIONS.md`

## Optional: One-Time Setup (Only If Needed)

Most of the time, this repo already has a working `.venv/`. Only use this section if:
- `.venv/` is missing (fresh clone, new machine, or your PC was wiped)
- You activated the venv but `C3imp` / `cookimport` says "command not found"

### Create `.venv` (one-time)

```bash
cd /home/mcnal/projects/recipeimport
python3 -m venv .venv
```

### Install the tool (one-time, or after dependency changes)

"Install the tool" means: install this project into your virtual environment so the CLI commands (`cookimport`, `C3imp`) exist inside that venv.

```bash
cd /home/mcnal/projects/recipeimport
. .venv/bin/activate
python -m pip install -e .
```
