---
summary: "How to run Label Studio benchmark imports and export golden sets."
read_when:
  - When labeling cookbook chunks in Label Studio
  - When exporting golden sets for the tip evaluation harness
---

# Label Studio Benchmarking

You can run Label Studio imports from the interactive menu by running `C3imp` and choosing "Label Studio benchmark import".

This guide explains how to start Label Studio locally, import a cookbook for labeling, and export a golden set for evaluation.

## Run Label Studio Locally

If you already have Label Studio running, skip this section. For a quick local run with Docker:

```
docker run -it -p 8080:8080 --name labelstudio heartexlabs/label-studio:latest
```

Then open the web UI at `http://localhost:8080` and create an API key from your user profile. Export it in your shell:

```
export LABEL_STUDIO_URL=http://localhost:8080
export LABEL_STUDIO_API_KEY=your_api_key_here
```

## Import a Cookbook for Labeling

From the repo root:

```
cd /home/mcnal/projects/recipeimport
. .venv/bin/activate
C3imp labelstudio-import data/input/your_cookbook.pdf \
  --project-name "your-benchmark" \
  --chunk-level both
```

This will:

- auto-select the importer pipeline for the file type
- write a full extracted text archive
- create a Label Studio project and upload chunked tasks

Optional flags:

- `--overwrite` to delete and recreate the project
- `--limit` or `--sample` to cap the number of chunks uploaded

Artifacts are written under:

```
data/output/<timestamp>/labelstudio/<book_slug>/
```

## Labeling Tips

Each task shows both `text_display` (cleaned) and `text_raw` (verbatim) plus metadata like `chunk_level` and location. You must choose a Content Type and Value / Usefulness. Optional tags help categorize the tip type (technique, timing, etc.).

Use `mixed` when boundaries are unclear and avoid forcing a tip vs fluff choice.

## Export Golden Sets

Once labels are applied:

```
cd /home/mcnal/projects/recipeimport
. .venv/bin/activate
C3imp labelstudio-export --project-name "your-benchmark"
```

If no manifest is found, the exporter will look up the project by name and create a new export folder under `data/output/<timestamp>/labelstudio/<project_slug>/exports/`.

Outputs are written to:

```
data/output/<timestamp>/labelstudio/<book_slug>/exports/
```

You will see:

- `labeled_chunks.jsonl` (full fidelity)
- `golden_set_tip_eval.jsonl` (tip evaluation harness input)

## Run the Tip Evaluation Harness

```
python tools/tip_eval.py score \
  --labels data/output/<timestamp>/labelstudio/<book_slug>/exports/golden_set_tip_eval.jsonl
```

## Recommended Benchmark Strategy

- Pick 2-3 books total
- Label ~200-500 atomic chunks per book
- Include at least one "chatty" book, one dense reference book, and one messy/formatting-heavy book
