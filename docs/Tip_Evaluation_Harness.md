---
summary: "How to label topic candidates and score tip extraction precision/recall."
read_when:
  - When building or using the tip evaluation harness
  - When creating a golden set of topic candidates
---

# Tip Evaluation Harness

This document explains how to build a small **golden set** of topic candidates and measure whether the heuristic tip extractor is improving.

## What is a “topic candidate”?

A topic candidate is an atom-level snippet of standalone cookbook text (paragraphs or list items) captured before tip classification, with container headers and adjacent-atom context stored in provenance. These are written to:

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

If you generated a golden set from Label Studio, use the exported file:

```
python tools/tip_eval.py score \
  --labels data/output/<timestamp>/labelstudio/<book_slug>/exports/golden_set_tip_eval.jsonl
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

---

## Simplified Guide for Non-Coders

If the steps above look complicated, don't worry! Here is the exact same process broken down into simple tasks.

### 1. Run an Import First
Before you can evaluate anything, you need to import a cookbook or file so the system can find potential tips.
1. Run your normal import command (e.g., `python -m cookimport.cli ...`).
2. Look at the output folder it created. It will be something like `data/output/2026-01-27-103000/`.
3. Inside that folder, look for a `tips` folder, then a `topic_candidates.json` file. **Copy the full path to this file.**

### 2. Create the "Homework Sheet" (The Template)
We need to turn that list of candidates into a form you can fill out.
1. Open your terminal/command prompt.
2. Paste this command, but **replace the `[PATH_TO_CANDIDATES]` part** with the path you found in Step 1:
   ```bash
   python tools/tip_eval.py template --input [PATH_TO_CANDIDATES] --out my_golden_set.jsonl
   ```
3. Press Enter. This creates a file named `my_golden_set.jsonl` in your current folder.

### 3. Fill in the Answers
Now you decide what is a tip and what isn't.
1. Open `my_golden_set.jsonl` in any text editor (VS Code, Notepad, TextEdit).
2. You will see lines of text with data. Look for `"label": ""`.
3. Change `""` to `"tip"` if it's a good tip, or `"not_tip"` if it isn't.
   - Example: Change `"label": ""` to `"label": "tip"`
   - **IMPORTANT:** Keep the quotes `""` around the word!
4. Save the file.

### 4. Check Your Score
Now see how well the computer did compared to your answers.
1. Go back to your terminal.
2. Run this command:
   ```bash
   python tools/tip_eval.py score --labels my_golden_set.jsonl
   ```
3. It will print out a score (Precision and Recall). Higher numbers are better!
