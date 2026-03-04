---
summary: "INSTRUCITONS FOR HUMANS"
read_when:
  - "dont waste ur tokens"
---
ENSURE EVERYTHING IS WRITTEN SUCH THAT A NON CODER NON STATS PERSON CAN UNDERSTAND AND ACTION UNDERSTANDING FROM THIS TOOL 

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

### Example: when to trust `raw` vs `controlled`

Imagine you compare **model** and your outcome is quality score:

- `raw` says: `codexfarm` beats `vanilla` by +0.05.
- `controlled` says: almost no difference (+0.01), and maybe shows a coverage warning.

How to read that:

1. Trust `raw` as a quick signal only ("there might be something here").
2. Trust `controlled` more for decision-making **if coverage is decent** (because it is comparing more similar runs).
3. If controlled coverage is weak, treat it as a hint and simplify controls (fewer **Hold constant** fields), then re-check.

Simple decision rule:
- If `raw` and `controlled` agree: confidence goes up.
- If they disagree: prefer `controlled`, but check coverage before final decisions.

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

## Terminal mode (no browser)

You can run the same analysis from terminal:

1. One-shot JSON:
`cookimport compare-control run --action analyze --view controlled --outcome-field strict_accuracy --compare-field ai_model`
2. One-shot auto-learn summary:
`cookimport compare-control run --action insights --outcome-field strict_accuracy`
3. Keep a session open for repeated requests:
`cookimport compare-control agent`

Agent mode reads one JSON request per line and writes one JSON response per line, so external tools can loop quickly without reopening the dashboard.

## QualitySuite friend mode (AI-agent shortcut)

After running `cookimport bench quality-run` or `cookimport bench quality-compare`, open the generated `agent_compare_control/` folder in that run/comparison directory.

Use this order:

1. Read `qualitysuite_compare_control_index.json` (what scopes are available).
2. Read the precomputed insight JSON for the scope/outcome you care about.
3. If you need deeper detail, run:
`cookimport compare-control agent --output-root data/output --golden-root data/golden < agent_requests.jsonl > agent_responses.jsonl`
