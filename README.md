# Recipe Import + Label Studio Quick Start

This repo lets you import cookbooks (Excel/PDF/EPUB/etc.) and optionally build Label Studio projects for human labeling. The normal and Label Studio flows both run through the **C3imp** interactive menu.

## One-time setup

Copy/paste:

```bash
cd /home/mcnal/projects/recipeimport
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e ".[dev]"
```

## Put your files here

```
/home/mcnal/projects/recipeimport/data/input
```

## Run (normal import or Label Studio) - one command

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

## Troubleshooting

If `C3imp` is not found, activate the virtualenv first:

```bash
cd /home/mcnal/projects/recipeimport
. .venv/bin/activate
```

If Label Studio reports no text extracted, the PDF is likely scanned. Run OCR first, then re-import.
