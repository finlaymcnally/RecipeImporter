---
summary: "INSTRUCITONS FOR HUMANS"
read_when:
  - "dont waste ur tokens"
---

# How To Use: Compare & Control

This tool lives in the **Previous Runs** section of the dashboard. It works on whatever rows are currently showing (after Quick Filters and table filters).

## Compare & Control (compare fairly, using visible rows)

Use this when you want to answer: "What seems to move my outcome (quality, runtime, cost), and is that still true if I compare apples-to-apples?"

### Step 1: Pick the goal (Outcome)

1. Set **Outcome** to the number you care about (usually a quality metric).

### Step 2: Pick what to compare (Compare by)

1. Set **Compare by** to the field you suspect matters (model, effort, importer, etc.).

If you are not sure what to compare:
1. Set **View** to `discover` (field-finding mode).
2. Leave **Compare by** empty.
3. Click one of the suggested field cards.

### Step 3: Choose analysis mode (View)

`discover` is for finding candidate **Compare by** fields. It does not run the direct raw/controlled comparison table.

`raw` is a quick comparison. It compares groups directly, without trying to correct for other differences.

`controlled` is a more careful comparison. It tries to compare runs that match on the **Hold constant** fields (so you are comparing "similar runs" to "similar runs"). If you see coverage warnings, treat the results as directional hints, not a final answer.

Rule of thumb: use `discover` to pick a field, start analysis in `raw`, then switch to `controlled` if you think the result might be explained by other changes (different source files, different importers, different benchmark setup).

### Step 4 (optional): Hold constant (controls)

Pick one or more **Hold constant** checkboxes to keep those fields the same while comparing.

Tips:
More controls means more "fair", but it also means less data is usable. If controlled coverage is low, remove some controls.

### Step 5 (optional): Split by

Use **Split by** to repeat the same comparison inside a few buckets (for example: compare by model, split by importer).

### Filtering to a subset (categorical fields only)

If **Compare by** is a categorical field (a small set of named groups), you can:

1. Check one or more groups in the group list.
2. Click **Filter to subset**.

This writes those selected groups into the table filters, so the table (and chart) only shows that subset.

To undo it:
Remove the table filter for that column, or use **Clear all filters**.
