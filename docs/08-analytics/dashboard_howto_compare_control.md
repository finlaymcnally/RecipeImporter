---
summary: "INSTRUCITONS FOR HUMANS"
read_when:
  - "dont waste ur tokens"
---
ENSURE EVERYTHING IS WRITTEN SUCH THAT A NON CODER NON STATS PERSON CAN UNDERSTAND AND ACTION UNDERSTANDING FROM THIS TOOL 

# How To Use: Compare & Control

This tool lives in the **Previous Runs** section of the dashboard. It runs on its own benchmark analysis scope and is independent from the table filters in the `History Table & Trend` card.

## Compare & Control (compare fairly, in its own scope)

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

### What the chart shows (dynamic)

The chart under Compare & Control is auto-generated from Compare & Control scope + current control settings:

0. It starts blank when the dashboard loads unless a valid Compare + View selection is already saved; with a saved valid selection it renders automatically.
1. Numeric **Compare by**: scatter of run-level points (`Compare by` on X, `Outcome` on Y).
2. Categorical **Compare by**: bar chart of group outcome means (each group gets a soft pastel color so bars are easier to scan, and each group keeps the same color across local subsets and changing row mixes).
3. If you set **Split by**, each split becomes its own series.
4. In `discover`, the chart waits for a selected compare field.

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

### Step 6 (optional): Run two comparisons at once

If you want to compare two different hypotheses side by side:

1. Click **Expand set 2 from right**.
2. Configure Set 2 independently (its own Outcome, Compare by, Hold constant, Split by, and groups).
3. Keep Set 1 as your baseline and use Set 2 as your alternate.

Both control panels are shown left/right in a taller workspace.

When Set 2 opens, the analysis area also splits left/right the whole way down by default:

- Set 1 controls, table, and chart stay in the left column.
- Set 2 controls, table, and chart stay in the right column.

If you want a merged chart instead, switch **Chart layout** to `combined`.

### Reading group results quickly (table view)

When **Compare by** is categorical, `Group outcome means` is shown as a table:

- `Group`
- `Rows`
- `Avg`
- one column per available side metric (for example token/runtime/cost-style fields)

The number of side-metric columns is dynamic and depends on what metrics are available in your current Compare & Control scope.
Column headers wrap in a two-line header row, and labels use normal human-readable names (not internal field keys).
Numeric table cells use readability formatting: values above `5` show as comma-separated whole numbers, while small ratio-like values keep decimals.
Rows are display-sorted for readability: missing/placeholder labels (like `-`) appear at the bottom, and `AI Effort` follows `low` -> `medium` -> `high` -> `xhigh` -> `AI off` order.
For `AI Effort`, `AI off` and `-` are separate categories: `AI off` means vanilla/pipeline-off runs or codex runtime failure, while `-` means effort is unknown/missing.

### Filtering to a subset (categorical fields only)

If **Compare by** is a categorical field (a small set of named groups), you can:

1. Check one or more groups in the group list.
2. Click **Apply local subset**.

This limits Compare & Control analysis/chart to those groups only.
It does **not** write into the Previous Runs table filters.

To undo it:
Click **Clear groups** (or uncheck the selected groups).

### Chart layout options for two sets

When Set 2 is open, use **Chart layout**:

1. `stacked`: Set 1 chart on top, Set 2 chart below.
2. `side by side`: Set 1 chart left, Set 2 chart right.
3. `combined`: one shared chart (when compatible).

For `combined`, you can choose:

1. `single y-axis`: both sets share one Y scale.
2. `dual y-axis (left/right)`: Set 1 uses left axis and Set 2 uses right axis.

If chart types are not compatible for combination (for example one numeric scatter and one categorical bar), the combined chart will show a clear fallback message instead of forcing a bad merge.

## Terminal mode (no browser)

You can run the same analysis from terminal:

1. One-shot JSON:
`cookimport compare-control run --action analyze --view controlled --outcome-field strict_accuracy --compare-field ai_model`
2. One-shot auto-learn summary:
`cookimport compare-control run --action insights --outcome-field strict_accuracy`
3. Keep a session open for repeated requests:
`cookimport compare-control agent`

Agent mode reads one JSON request per line and writes one JSON response per line, so external tools can loop quickly without reopening the dashboard.

## Live browser control from CLI

If the dashboard is open from `cookimport stats-dashboard --serve`, you can also push visible Compare & Control changes into the browser:

1. Show Set 1 live:
`cookimport compare-control dashboard-state --compare-field ai_model --view raw --outcome-field strict_accuracy`
2. Show Set 2 live:
`cookimport compare-control dashboard-state --set secondary --compare-field ai_effort --view controlled --enable-second-set --chart-layout combined`

The browser polls `assets/dashboard_ui_state.json`, so the panel and chart update a few seconds after each write.

## Tune discovery cards from CLI (backend-driven)

If discovery keeps surfacing noisy path/hash fields, you can tune card ranking from CLI:

1. Persist dashboard discovery preferences:
`cookimport compare-control discovery-preferences --exclude-field processed_report_path --exclude-field run_config_hash --prefer-field ai_model --prefer-field ai_effort --demote-pattern path --demote-pattern hash --max-cards 8`
2. Refresh/reopen dashboard (`cookimport stats-dashboard` if needed).
3. Compare & Control `discover` cards will now follow those preferences.

## QualitySuite friend mode (AI-agent shortcut)

After running `cookimport bench quality-run` or `cookimport bench quality-compare`, open the generated `agent_compare_control/` folder in that run/comparison directory.

Use this order:

1. Read `qualitysuite_compare_control_index.json` (what scopes are available).
2. Read the precomputed insight JSON for the scope/outcome you care about.
3. If you need deeper detail, run:
`cookimport compare-control agent --output-root data/output --golden-root data/golden < agent_requests.jsonl > agent_responses.jsonl`
