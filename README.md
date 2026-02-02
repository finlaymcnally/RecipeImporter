# Recipe Import + Label Studio Quick Start

Note to future AI editors: write for a non-technical, step-by-step audience. Use simple words, numbered steps, and “copy/paste this” instructions. Assume the reader has never used Python or Docker.

This repo lets you import cookbooks (Excel/PDF/EPUB/etc.) and optionally build Label Studio projects for human labeling. The normal and Label Studio flows both run through the **C3imp** interactive menu.

## One-time setup (do this once)

Copy/paste each line, in order:

```bash
cd /home/mcnal/projects/recipeimport
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e ".[dev]"
```

## Put your files here (input folder)

```
/home/mcnal/projects/recipeimport/data/input
```

## Run the app (normal import or Label Studio) - one command

Copy/paste:

```bash
cd /home/mcnal/projects/recipeimport
. .venv/bin/activate
C3imp
```

In the menu, choose:

- **Import files from data/input** for normal recipe outputs, or
- **Label Studio benchmark import** for labeling tasks.

## Label Studio (set variables once, then run C3imp)

Start Label Studio (Docker):

```bash
docker run -it -p 8080:8080 --name labelstudio heartexlabs/label-studio:latest
```

In the Label Studio UI (http://localhost:8080), create an API key. Then set these once per terminal session:

```bash
export LABEL_STUDIO_URL=http://localhost:8080
export LABEL_STUDIO_API_KEY=your_api_key_here
```

Now just run `C3imp` and choose **Label Studio benchmark import**.

---

# Canonical Label Studio Workflow (block-based, step-by-step)

This is the **new** workflow that labels every extracted block (so you can measure recall and missed recipes). Follow these steps exactly.

## 1) Start Label Studio (Docker)

Open a terminal and run:

```bash
docker run -it -p 8080:8080 --name labelstudio heartexlabs/label-studio:latest
```

Leave this running.

## 2) Create a Label Studio API key

1. Open your browser to http://localhost:8080
2. Create an account (if asked).
3. Go to the user menu → **Account & Settings** → **Access Token**.
4. Copy the token.

## 3) Set the Label Studio environment variables (every new terminal)

Open a **new** terminal and copy/paste:

```bash
export LABEL_STUDIO_URL=http://localhost:8080
export LABEL_STUDIO_API_KEY=your_api_key_here
```

Replace `your_api_key_here` with the token you copied.

## 4) Put a book in the input folder

Copy your file into:

```
/home/mcnal/projects/recipeimport/data/input
```

Example file: `sample.epub` or `sample.pdf`.

## 5) Create the **pipeline** Label Studio project (old, chunk-based)

This keeps the existing benchmark flow for fast regression tests.

Copy/paste:

```bash
cd /home/mcnal/projects/recipeimport
. .venv/bin/activate
cookimport labelstudio-import data/input/sample.epub \
  --project-name "Sample Benchmark (pipeline)" \
  --chunk-level both
```

## 6) Create the **canonical** Label Studio project (new, block-based)

Copy/paste:

```bash
cd /home/mcnal/projects/recipeimport
. .venv/bin/activate
cookimport labelstudio-import data/input/sample.epub \
  --project-name "Sample Canonical (blocks)" \
  --task-scope canonical-blocks \
  --context-window 1
```

## 7) Label some blocks in the browser

1. In Label Studio, open the project **Sample Canonical (blocks)**.
2. Label ~20 blocks with a mix of:
   - RECIPE_TITLE
   - INGREDIENT_LINE
   - INSTRUCTION_LINE
   - TIP
   - NARRATIVE
   - OTHER

## 8) Export the canonical labels

Copy/paste:

```bash
cd /home/mcnal/projects/recipeimport
. .venv/bin/activate
cookimport labelstudio-export \
  --project-name "Sample Canonical (blocks)" \
  --export-scope canonical-blocks \
  --output-dir data/golden/sample/canonical
```

You should now have:

```
data/golden/sample/canonical/canonical_block_labels.jsonl
data/golden/sample/canonical/canonical_gold_spans.jsonl
```

## 9) Run the evaluation (pipeline vs canonical)

First, find your latest Label Studio run folder in:

```
data/output/<timestamp>/labelstudio/<book_slug>/
```

Then run:

```bash
cd /home/mcnal/projects/recipeimport
. .venv/bin/activate
cookimport labelstudio-eval canonical-blocks \
  --pred-run data/output/<timestamp>/labelstudio/<book_slug>/ \
  --gold-spans data/golden/sample/canonical/canonical_gold_spans.jsonl \
  --output-dir data/golden/sample/eval
```

You should now have:

```
data/golden/sample/eval/eval_report.json
data/golden/sample/eval/eval_report.md
data/golden/sample/eval/missed_gold_spans.jsonl
data/golden/sample/eval/false_positive_preds.jsonl
```

## Important notes

- Keep the **pipeline** project and **canonical** project separate.
- Re-running imports is safe; existing tasks are skipped.
- If you see “No text extracted,” the PDF likely needs OCR first.

## Performance & Settings

You can configure performance settings via the **Settings** menu in `C3imp` or via CLI flags.

**Key Features:**
*   **Parallel Processing:** Process multiple files at once (`--workers 4`).
*   **OCR Optimization:** Choose between `auto`, `cuda` (GPU), `mps` (Mac), or `cpu`.
*   **Batching:** Process multiple pages per OCR call (`--ocr-batch-size`).
*   **Model Warming:** Pre-load heavy AI models (`--warm-models`) to speed up processing.

**Interactive Configuration:**
1.  Run `C3imp`.
2.  Select **Settings**.
3.  Adjust workers, OCR device, etc.
4.  Settings are saved to `data/config.json`.

**CLI Usage:**
```bash
cookimport stage data/input --workers 8 --ocr-device cuda --warm-models
```

## Where outputs go

Each run writes a timestamped folder under:

```
data/output/<timestamp>/
```

Normal imports:

- `intermediate drafts/<workbook>/` (RecipeSage JSON-LD)
- `final drafts/<workbook>/` (Draft V1)
- `tips/<workbook>/` (tips + topic candidates)
- `<workbook>.excel_import_report.json` (report at run root)

Label Studio runs:

```
data/output/<timestamp>/labelstudio/<book_slug>/
```

Key files:

- `extracted_archive.json` (full extracted text archive)
- `label_studio_tasks.jsonl` (uploaded tasks)
- `coverage.json` (coverage report)
- `exports/labeled_chunks.jsonl` (full fidelity labels)
- `exports/golden_set_tip_eval.jsonl` (tip eval harness input)
- `exports/canonical_block_labels.jsonl` (canonical block labels)
- `exports/canonical_gold_spans.jsonl` (derived recipe spans)

## Troubleshooting

If `C3imp` is not found, activate the virtualenv first:

```bash
cd /home/mcnal/projects/recipeimport
. .venv/bin/activate
```

If Label Studio reports no text extracted, the PDF is likely scanned. Run OCR first, then re-import.
