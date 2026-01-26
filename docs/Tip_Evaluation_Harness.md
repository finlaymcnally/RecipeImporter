---
summary: "How to label topic candidates and score tip extraction precision/recall."
read_when:
  - When building or using the tip evaluation harness
  - When creating a golden set of topic candidates
---

# Tip Evaluation Harness

This document explains how to build a small **golden set** of topic candidates and measure whether the heuristic tip extractor is improving.

## What is a “topic candidate”?

A topic candidate is a chunk of standalone cookbook text (usually multiple paragraphs) captured before tip classification. These are written to:

- `data/output/<timestamp>/tips/<workbook>/topic_candidates.json`
- `data/output/<timestamp>/tips/<workbook>/topic_candidates.md`

Use these chunks to label what is a real, reusable cooking tip versus narrative or reference text.

## Step 1 — Create a labeling template

From the repo root:

```
python tools/tip_eval.py template \
  --input data/output/<timestamp>/tips/<workbook>/topic_candidates.json \
  --out data/output/<timestamp>/tips/<workbook>/topic_labels.jsonl
```

This produces a JSONL file where each line includes:

- `id`
- `text`
- `anchors` (tags)
- `label` (empty)
- `notes` (empty)

## Step 2 — Label a golden set

Edit `topic_labels.jsonl` and fill in `label` with one of:

- `tip` (actionable advice)
- `not_tip` (not actionable)
- `narrative` (story, memoir, commentary)
- `reference` (definitions, background facts)
- `recipe_specific` (only useful inside a single recipe)

Start small (30–50 labels). This becomes your “golden set.”

## Step 3 — Score the current heuristics

```
python tools/tip_eval.py score \
  --labels data/output/<timestamp>/tips/<workbook>/topic_labels.jsonl
```

If you use parsing overrides:

```
python tools/tip_eval.py score \
  --labels data/output/<timestamp>/tips/<workbook>/topic_labels.jsonl \
  --overrides data/input/<workbook>.overrides.yaml
```

Output includes:

- Precision (how many predicted tips were correct)
- Recall (how many real tips were found)

## Why this helps

Without a golden set, it’s easy to “feel” like the parser improves while it actually just trades one error type for another. This harness gives you a measurable way to tune heuristics before adding LLMs.
