from __future__ import annotations

_HTML = """\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>cookimport – Lifetime Stats Dashboard</title>
<meta http-equiv="Cache-Control" content="no-cache, no-store, must-revalidate">
<meta http-equiv="Pragma" content="no-cache">
<meta http-equiv="Expires" content="0">
<link rel="stylesheet" href="assets/style.css?v=__ASSET_VERSION__">
</head>
<body>
<header id="dash-header">
  <h1>cookimport Stats Dashboard</h1>
  <p id="header-subtitle">Latest benchmark diagnostics and history.</p>
  <div id="header-meta"></div>
</header>

<main>
  <section id="diagnostics-section">
    <h2>Diagnostics (Latest Benchmark)</h2>
    <p class="section-note">Deep quality views for the most recent benchmark evaluation. Use these when a score looks off and you want to know why.</p>
    <details class="section-details">
      <summary>Metric help (benchmarks)</summary>
      <section>
        <p class="section-note">Benchmarks compare predicted labeled spans to your labeled gold spans. Higher is better. Scores are 0.0–1.0 (1.0 == 100%).</p>
        <ul class="metric-help-list">
          <li><code>strict_accuracy</code>: strict line/block accuracy from benchmark evaluation.</li>
          <li><code>macro_f1_excluding_other</code>: macro F1 across labels, excluding <code>OTHER</code>.</li>
          <li><code>Gold</code> / <code>Matched</code>: span counts for the benchmark (not recipe totals).</li>
        </ul>
      </section>
    </details>
    <div class="diagnostics-grid">
      <section id="runtime-section" class="diagnostic-card">
        <h2>Benchmark Runtime (Latest)</h2>
        <p class="section-note">AI runtime context for the latest benchmark run group: model, thinking effort, pipeline mode, token totals, and quality-per-token efficiency (including vanilla and peer comparisons).</p>
        <div id="runtime-summary"></div>
      </section>

      <section id="boundary-section" class="diagnostic-card">
        <h2>Boundary Classification (Latest Benchmark)</h2>
        <p class="section-note">How predictions align to gold span boundaries across the latest benchmark run group.</p>
        <div id="boundary-summary"></div>
      </section>

      <section id="per-label-section" class="diagnostic-card">
        <div class="per-label-title-row">
          <h2>Per-Label Breakdown (Latest Benchmark Run)</h2>
          <label class="per-label-run-select-wrap" for="per-label-run-group-select">
            Run
            <select id="per-label-run-group-select">
              <option value="__default_most_recent__">Default - most recent</option>
            </select>
          </label>
        </div>
        <div class="per-label-controls">
          <label class="per-label-rolling-label" for="per-label-rolling-window-size">Rolling N</label>
          <input
            id="per-label-rolling-window-size"
            type="number"
            min="1"
            max="50"
            step="1"
            value="10"
          >
          <label class="per-label-checkbox" for="per-label-comparison-point-value">
            <input id="per-label-comparison-point-value" type="checkbox">
            Point value
          </label>
        </div>
        <p class="section-note">Per label: precision answers false alarms, recall answers misses. Latest-run codex-exec precision/recall columns show raw baseline scores. Use the Point value checkbox to switch the comparison columns between delta-vs-baseline and raw point values (positive/green means codex-exec baseline is higher than the comparison value; negative/red means codex-exec baseline is lower). Rolling metrics use the selected N codex-exec runs without cross-mixing.</p>
        <table id="per-label-table" class="dashboard-resizable-table"><thead>
          <tr class="per-label-header-primary">
            <th title="The label name being scored (for example RECIPE_TITLE)." rowspan="2">Label</th>
            <th data-metric-tooltip-key="gold_total" title="Gold span count for this label." rowspan="2">Gold</th>
            <th data-metric-tooltip-key="pred_total" title="Predicted span count for this label." rowspan="2">Pred</th>
            <th data-metric-tooltip-key="precision" title="Latest-run codex-exec precision for this label (strict scoring baseline)." rowspan="2"><span class="per-label-col-head">Run<br>Precision<br><span class="per-label-col-sub">(codex-exec)</span></span></th>
            <th data-metric-tooltip-key="recall" title="Latest-run codex-exec recall for this label (strict scoring baseline)." rowspan="2"><span class="per-label-col-head">Run<br>Recall<br><span class="per-label-col-sub">(codex-exec)</span></span></th>
            <th class="per-label-comparison-header" data-metric-tooltip-key="precision" data-per-label-comparison-scope="run" data-per-label-comparison-metric="precision" data-per-label-comparison-variant="vanilla" title="Latest-run codex-exec precision minus latest-run vanilla precision for this label." rowspan="2"><span class="per-label-col-head">Run<br><span class="per-label-comparison-mode-value">Delta</span> Precision<br><span class="per-label-col-sub">(vanilla)</span></span></th>
            <th class="per-label-comparison-header" data-metric-tooltip-key="recall" data-per-label-comparison-scope="run" data-per-label-comparison-metric="recall" data-per-label-comparison-variant="vanilla" title="Latest-run codex-exec recall minus latest-run vanilla recall for this label." rowspan="2"><span class="per-label-col-head">Run<br><span class="per-label-comparison-mode-value">Delta</span> Recall<br><span class="per-label-col-sub">(vanilla)</span></span></th>
            <th class="per-label-rolling-group" title="Rolling-window deltas (selected N) for codex-exec columns." colspan="2"><span class="per-label-col-head per-label-rolling-group-head"><span class="per-label-rolling-window-value">10</span>-run Rolling <span class="per-label-comparison-mode-value">Delta</span>:</span></th>
          </tr>
          <tr class="per-label-header-rolling">
            <th class="per-label-comparison-header" data-metric-tooltip-key="precision" data-per-label-comparison-scope="rolling" data-per-label-comparison-metric="precision" data-per-label-comparison-variant="codex-exec" title="Latest-run codex-exec precision minus rolling codex-exec precision over N runs for this label."><span class="per-label-col-head">Precision<br><span class="per-label-col-sub">(codex-exec)</span></span></th>
            <th class="per-label-comparison-header" data-metric-tooltip-key="recall" data-per-label-comparison-scope="rolling" data-per-label-comparison-metric="recall" data-per-label-comparison-variant="codex-exec" title="Latest-run codex-exec recall minus rolling codex-exec recall over N runs for this label."><span class="per-label-col-head">Recall<br><span class="per-label-col-sub">(codex-exec)</span></span></th>
          </tr>
        </thead><tbody></tbody></table>
      </section>
    </div>
  </section>

  <section id="previous-runs-section">
    <h2>Previous Runs</h2>
	    <p class="section-note">Timestamp links to the run artifact folder. Full history is rendered; use horizontal scroll for wide columns.</p>
	    <details class="section-details">
	      <summary>Metric help (table)</summary>
	      <section>
	        <p class="section-note">Previous Runs is a history table of benchmark evaluations. Most quality scores are shown as 0.0–1.0 (1.0 = 100%).</p>
	        <p class="section-note">Span counts (Gold/Pred/Matched/etc) are counts of labeled spans inside the benchmark set, not the number of recipes in your output folders.</p>

	        <p class="section-note"><strong>Quality scores (0.0–1.0; higher is better)</strong></p>
	        <ul class="metric-help-list">
	          <li><code>strict_accuracy</code>: A strict “did we get it exactly right?” score for span boundaries. It only gives credit when the predicted span overlaps enough and the start/end boundaries line up closely. If this drops while the practical scores stay high, you are probably “mostly right” but picking spans that are too long/short.</li>
	          <li><code>macro_f1_excluding_other</code>: An average quality score across labels (excluding the catch-all <code>OTHER</code> label). Each label gets similar weight, so small labels can pull this down even if big labels look fine. This is useful when you care about balance, not just doing well on the most common label.</li>
	          <li><code>precision</code>: Of everything the system predicted, how much was actually correct. High precision means fewer false alarms and less extra junk to clean up. Precision can increase if the system becomes more conservative and predicts fewer spans.</li>
	          <li><code>recall</code>: Of everything that exists in the gold labels, how much the system successfully found. High recall means fewer misses. Recall can increase if the system predicts more spans, even if that also creates more false alarms.</li>
	          <li><code>f1</code>: A single “balance” score that combines precision and recall. It tends to be high only when both precision and recall are reasonably high. Use this when you want one number that punishes both misses and false alarms.</li>
	          <li><code>practical_precision</code>: A more forgiving precision score that gives credit when the prediction is in roughly the right place, even if the boundaries are not perfect. This is helpful when you are iterating and you care more about “did it basically find the right thing?” than perfect spans. Practical precision is usually higher than strict precision when boundary alignment is the main issue.</li>
	          <li><code>practical_recall</code>: A more forgiving recall score that gives credit for near-misses and partial overlaps. If practical recall is high but strict accuracy is low, your model is seeing the right content but the span sizes/boundaries are off. This is a good “directional” signal before you do boundary tuning.</li>
	          <li><code>practical_f1</code>: The balanced F1 score computed from the practical (more forgiving) precision/recall. When this is high but strict accuracy is lower, you likely have a boundary/granularity problem rather than a “wrong label” problem. When both practical and strict are low, the model is missing the content or labeling the wrong things.</li>
	          <li><code>supported_precision</code>: Precision focused on the “supported” labels the app really cares about (a curated subset). This is useful when rare/experimental labels make the overall score look worse than the user-facing quality. If supported precision is much higher than overall precision, your false alarms are mostly coming from non-core labels.</li>
	          <li><code>supported_recall</code>: Recall focused on the supported (core) labels. This helps answer “are we missing the things we actually want to capture?” without being diluted by edge-case labels. If supported recall is low, the output will feel incomplete even if other metrics look decent.</li>
	          <li><code>supported_practical_precision</code>: Practical (forgiving) precision, but only for supported labels. This is a good “rough correctness” signal for the core labels when strict boundaries are still messy. If this is high and strict accuracy is low, you can often fix quality with boundary/segmentation tweaks rather than changing prompts/models.</li>
	          <li><code>supported_practical_recall</code>: Practical recall for supported labels. This tells you whether the pipeline is finding the core things at all, even if the span boundaries are imperfect. If this is low, you are likely missing text entirely (coverage) or the model is not recognizing the right patterns.</li>
	          <li><code>supported_practical_f1</code>: A single balanced score for practical precision/recall on supported labels. Treat this as a “user-facing rough quality” number for the core labels. It can stay stable while strict accuracy moves around due to boundary tuning.</li>
	        </ul>

	        <p class="section-note"><strong>Counts (bigger is not automatically better)</strong></p>
	        <ul class="metric-help-list">
	          <li><code>gold_total</code>: How many gold spans were included in the benchmark for this run. More gold spans generally makes the scores more stable and trustworthy. If <code>gold_total</code> is small, a few mistakes can swing the score a lot.</li>
	          <li><code>pred_total</code>: How many spans the system predicted in total. If this is much larger than <code>gold_total</code>, it often means the system is over-predicting and precision may suffer. If it is much smaller, the system may be under-predicting and recall may suffer.</li>
	          <li><code>gold_matched</code>: How many gold spans were successfully matched under the strict rules. This is the “numerator” behind strict-style accuracy/recall. Watching <code>gold_matched</code> alongside <code>gold_total</code> helps you see whether a score change is real or just a data-size change.</li>
	          <li><code>gold_recipe_headers</code>: How many “recipe header/title” spans exist in the gold set for this benchmark. This is a useful reference point for “how many recipes are truly in this benchmark set.” If your predicted <code>recipes</code> is far above/below this, recipe segmentation is likely off.</li>
	          <li><code>recipes</code>: The pipeline’s predicted recipe count (when available). This is not part of the span-matching score, so it can be wrong even when span scores are good. When this is off, the output can feel broken (missing recipes, merged recipes, or extra fake recipes) even if label metrics look fine.</li>
	          <li><code>task_count</code>: How many Label Studio tasks/items were evaluated in that benchmark run (when available). Higher counts usually mean the scores are less “random” and more representative. Very small task counts can make the metrics jump around from run to run.</li>
	        </ul>

	        <p class="section-note"><strong>Boundary and “shape” diagnostics (helps explain strict vs practical gaps)</strong></p>
	        <ul class="metric-help-list">
	          <li><code>boundary_correct</code>: Number of matched spans where the predicted start and end boundaries exactly match the gold boundaries. A high value means the model is not only finding the right thing, but also cutting it to the right size. If this is low while matches exist, you are mostly fighting boundary alignment rather than label recognition.</li>
	          <li><code>boundary_over</code>: Number of matched spans where the prediction fully contains the gold span (the model highlighted too much text). This usually happens when the model “grabs extra lines” before/after the correct content. If <code>boundary_over</code> is high, tightening segmentation rules often helps.</li>
	          <li><code>boundary_under</code>: Number of matched spans where the prediction is fully inside the gold span (the model highlighted too little text). This can happen when the model only captures the core phrase and misses surrounding lines that gold includes. If <code>boundary_under</code> is high, you may need larger span windows or different chunking.</li>
	          <li><code>boundary_partial</code>: Number of matched spans that overlap but neither fully contain the other (a partial boundary mismatch). This is the messy middle case: the model is near the right spot, but the boundaries are shifted. High partial counts usually mean you should inspect examples because multiple failure modes can produce it.</li>
	          <li><code>pred_width_p50</code>: The median (typical) predicted span width, measured in text blocks/lines. This tells you whether predictions are usually short “snippets” or larger chunks. If this is much bigger than <code>gold_width_p50</code>, strict metrics will often suffer because boundaries are too wide.</li>
	          <li><code>gold_width_p50</code>: The median gold span width in text blocks/lines. This is the “target” span size the benchmark expects. Comparing it to <code>pred_width_p50</code> helps you see if the system is labeling at the right granularity.</li>
	          <li><code>granularity_mismatch_likely</code>: A warning flag that the system and the gold labels are using different “chunk sizes” (for example, gold marks small spans while predictions mark whole paragraphs). When this is true, strict scores can look worse than the output feels because you are mostly mis-sizing spans. Use the boundary breakdown and span widths to confirm.</li>
	        </ul>

	        <p class="section-note"><strong>Coverage (did the pipeline feed the model the text?)</strong></p>
	        <ul class="metric-help-list">
	          <li><code>extracted_chars</code>: How much text was extracted from the source file for this run (in characters). Bigger sources usually cost more and take longer to process. If this unexpectedly drops, extraction may have failed or skipped content.</li>
	          <li><code>chunked_chars</code>: How much of the extracted text was actually chunked and sent through the pipeline. If this is much smaller than <code>extracted_chars</code>, a lot of content was filtered out (headers/footers removal, skip rules, etc). Low chunked text can directly hurt recall because the model cannot label what it never sees.</li>
	          <li><code>coverage_ratio</code>: A simple ratio of <code>chunked_chars / extracted_chars</code>. Low coverage means you are throwing away lots of extracted text before the model sees it, which can cause missing labels and missing recipes. Coverage does not guarantee quality, but very low coverage is a strong “something is wrong upstream” signal.</li>
	        </ul>

	        <p class="section-note"><strong>Tokens (cost proxy; present when run telemetry is available)</strong></p>
	        <ul class="metric-help-list">
		          <li><code>all_token_use</code>: A single “quick scan” token number that combines input and output tokens, with cached input discounted. Cached tokens are treated as cheaper by counting them at 10% weight. Use this to compare overall cost between runs without staring at multiple token columns.</li>
		          <li><code>quality_per_million_tokens</code>: Quality efficiency (preferred quality metric per 1,000,000 discounted tokens). Higher is better. Use this to compare whether token spend translated into score gains across runs.</li>
		          <li><code>tokens_input</code>: How many input tokens were sent to the model across the run. More input tokens often means more context, which can help quality, but it also costs more and can slow things down. If this spikes, check whether chunk sizes or prompts got larger.</li>
	          <li><code>tokens_cached_input</code>: Input tokens that came from cache (reused context) rather than being fully “paid for” again. This helps explain why a run can have high input tokens but lower effective cost. If cache tokens go up, cost can drop even if quality stays the same.</li>
	          <li><code>tokens_output</code>: How many tokens the model produced in its responses. Higher output usually means higher cost and can increase latency. If this grows a lot, it can mean the model is being too verbose or returning extra structure.</li>
	          <li><code>tokens_reasoning</code>: Tokens used for the model’s internal reasoning (when the provider reports it). Higher reasoning can improve hard cases, but it usually increases cost and time. If you raise “effort” settings, this is often the first token bucket to grow.</li>
	          <li><code>tokens_total</code>: Total tokens reported for the run (when available). This can be useful for rough comparisons across runs, but different providers/models can count tokens differently. When in doubt, compare runs using the same model and settings.</li>
	        </ul>

	        <p class="section-note"><strong>Run metadata (helps compare apples-to-apples)</strong></p>
	        <ul class="metric-help-list">
	          <li><code>run_timestamp</code>: When the benchmark run happened. The timestamp cell links to the artifact folder for that run. Use it to open the exact logs/reports behind a row.</li>
	          <li><code>source_label</code>: A human-friendly label for the source being evaluated (for example, a book name). This is the fastest way to make sure you are comparing the same source across runs. Different sources can have very different difficulty, so mixing them can mislead.</li>
	          <li><code>source_file</code>: The raw source filename/path from the benchmark manifest (when available). This helps you track exactly what file the run came from. It is mainly for troubleshooting when a label looks “impossible” and you want to confirm the input.</li>
	          <li><code>source_file_basename</code>: Just the filename portion of <code>source_file</code> (no folders). This is easier to scan in the table and works well for filtering. It does not change the metrics directly, but it helps you slice the history correctly.</li>
	          <li><code>importer_name</code>: Which importer/pipeline generated the predictions used in the benchmark. Importer differences can change the text structure (blocks/lines) and therefore affect boundary-based metrics. When comparing runs, try to keep the importer the same unless you are explicitly testing an importer change.</li>
	          <li><code>ai_model</code>: The model name used for the run (best-effort from metadata). Different models can have very different quality and cost profiles. When a metric changes, check this column first to make sure you are not comparing different models by accident.</li>
	          <li><code>ai_effort</code>: A label for the model “thinking effort” used (best-effort from metadata). Higher effort can improve tricky cases but usually costs more and runs slower. If quality improves and tokens rise, effort is often the reason.</li>
	          <li><code>run_config_hash</code>: A fingerprint of the run configuration (when available). If two rows share the same hash, they should be using the same settings. This is useful for grouping runs and spotting accidental config drift.</li>
	          <li><code>run_config_summary</code>: A compact, human-readable summary of the run configuration (when available). Use it to quickly understand what was different between two runs without opening artifacts. This is especially helpful when you are iterating on pipeline knobs.</li>
	          <li><code>run_config.model</code>: The exact model field from the recorded run config (when present). This is often more precise than <code>ai_model</code> when you are debugging metadata. It matters because changing models can change both quality and token usage.</li>
	          <li><code>run_config.reasoning_effort</code>: The exact reasoning-effort setting from the run config (when present). This setting often trades cost/time for quality. If you see a step-change in tokens or quality, this is a likely cause.</li>
	          <li><code>run_config.codex_model</code>: The codex model recorded in the run config (when present). This matters when your pipeline can use different models for different passes or modes. If this changes, treat the runs as different variants.</li>
	          <li><code>run_config.codex_reasoning_effort</code>: The codex reasoning-effort recorded in the run config (when present). Higher values tend to use more reasoning tokens and run slower. Use it to explain “why did this run get expensive?” changes.</li>
	          <li><code>artifact_dir</code>: The artifact directory path for the run. The dashboard uses this to create the clickable link from the timestamp to the run folder. If it is missing, the run row may be an older record without a stable artifact path.</li>
	          <li><code>artifact_dir_basename</code>: Just the folder name part of <code>artifact_dir</code>. This is handy for quick filtering when you remember a run folder name. It is purely a convenience field.</li>
	          <li><code>report_path</code>: The path to the benchmark report JSON that produced the row (when available). This is useful when you want to open the exact raw evaluation output. If it is missing, the dashboard may be using CSV history without a directly linked report file.</li>
	          <li><code>processed_report_path</code>: Path to a processed/derived report for the run (when available). This can include extra enrichment not present in the raw report. Use it when you need deeper diagnostics and the raw report is not enough.</li>
	          <li><code>all_method_record</code>: True/false indicating whether a row came from an “all-method” benchmark sweep. This is useful for filtering because all-method runs can have different patterns than single-book runs. If you want clean apples-to-apples trending, you may want to exclude these.</li>
	          <li><code>speed_suite_record</code>: True/false indicating whether a row is part of the speed benchmark suite. Speed runs may be optimized for runtime rather than max quality. Filter these out when you are focused purely on label quality.</li>
	        </ul>
	      </section>
	    </details>
	    <div class="previous-runs-sections">
	      <section id="previous-runs-history-panel" class="previous-runs-subsection">
	        <h3>History Table &amp; Trend</h3>
	        <p class="section-note">Use this section for row filtering, trend review, and table-level drilldown.</p>
	        <div class="trend-chart-wrap">
	          <h4>Benchmark Score Trend</h4>
	          <p class="section-note">Interactive time-series view of benchmark quality metrics (same chart tech as the git-stats dashboards).</p>
	          <div class="benchmark-trend-fields">
	            <div class="benchmark-trend-fields-head">
	              <h5>Trend fields</h5>
	              <div class="benchmark-trend-fields-actions">
	                <button id="benchmark-trend-select-all" type="button">Select all</button>
	                <button id="benchmark-trend-clear" type="button">Clear</button>
	              </div>
	            </div>
	            <p class="section-note">Add/remove any numeric benchmark field. The chart supports any number of selected fields.</p>
	            <div id="benchmark-trend-field-checklist" class="benchmark-trend-field-checklist"></div>
	            <p id="benchmark-trend-fields-status" class="section-note"></p>
	          </div>
	          <div id="benchmark-trend-chart" class="highcharts-host" aria-label="Benchmark score trend chart"></div>
	          <p id="benchmark-trend-fallback" class="empty-note" hidden></p>
	        </div>
    <section id="quick-filters-panel" class="quick-filters-panel">
	      <h3>Quick Filters</h3>
      <div class="quick-filters-actions">
        <div class="quick-filters-list">
          <label for="quick-filter-official-only">
            <input id="quick-filter-official-only" type="checkbox" checked>
            Official benchmarks only (single-book vanilla/codex-exec)
          </label>
          <label for="quick-filter-exclude-ai-tests">
            <input id="quick-filter-exclude-ai-tests" type="checkbox">
            Exclude AI test/smoke benchmark runs
          </label>
        </div>
        <button id="previous-runs-clear-all-filters" type="button">Clear all filters</button>
      </div>
      <section class="previous-runs-presets-panel">
        <h4>View presets</h4>
        <div class="previous-runs-presets-controls">
          <label for="previous-runs-preset-select">Preset</label>
          <select id="previous-runs-preset-select">
            <option value="">(none)</option>
          </select>
        </div>
        <div class="previous-runs-presets-actions">
          <button id="previous-runs-preset-load" type="button">Load</button>
          <button id="previous-runs-preset-save-current" type="button">Save current view</button>
          <button id="previous-runs-preset-delete" type="button">Delete</button>
        </div>
        <p id="previous-runs-preset-status" class="section-note"></p>
      </section>
	      <p id="quick-filters-status" class="section-note"></p>
	    </section>
	    <div class="table-wrap table-scroll">
      <div class="previous-runs-columns-control">
        <button
          id="previous-runs-columns-toggle"
          class="previous-runs-columns-toggle"
          type="button"
          aria-haspopup="true"
          aria-expanded="false"
          aria-controls="previous-runs-columns-popup"
          title="Show or hide table columns"
        >+/-</button>
        <div id="previous-runs-columns-popup" class="previous-runs-columns-popup" hidden>
          <p class="section-note">Check fields to include them in Previous Runs. Drag table headers to reorder and drag edges to resize.</p>
          <div id="previous-runs-columns-checklist"></div>
          <div class="previous-runs-columns-popup-actions">
            <div class="previous-runs-global-filter-mode">
              <label for="previous-runs-global-filter-mode">Across columns</label>
              <select id="previous-runs-global-filter-mode">
                <option value="and">AND</option>
                <option value="or">OR</option>
              </select>
            </div>
            <button id="previous-runs-clear-filters" type="button">Clear column filters</button>
            <button id="previous-runs-column-reset" type="button">Reset defaults</button>
          </div>
        </div>
      </div>
	      <table id="previous-runs-table">
        <colgroup></colgroup>
        <thead>
          <tr class="previous-runs-header-row"></tr>
          <tr class="previous-runs-active-filters-row"></tr>
          <tr class="previous-runs-filter-spacer-row"></tr>
        </thead>
        <tbody></tbody>
	      </table>
	    </div>
      </section>
      <section id="compare-control-analysis-section" class="previous-runs-subsection">
        <h3>Compare &amp; Control Analysis</h3>
        <p class="section-note">Analyze benchmark history independently from the Previous Runs table/filters. Group subsets here stay local to Compare &amp; Control only.</p>
        <div class="compare-control-global-actions">
          <button id="compare-control-toggle-second-set" type="button">Expand set 2 from right</button>
          <label for="compare-control-chart-layout">Chart layout</label>
          <select id="compare-control-chart-layout">
            <option value="stacked">stacked</option>
            <option value="side_by_side">side by side</option>
            <option value="combined">combined</option>
          </select>
          <label for="compare-control-combined-axis-mode">Combined Y axis</label>
          <select id="compare-control-combined-axis-mode">
            <option value="single">single y-axis</option>
            <option value="dual">dual y-axis (left/right)</option>
          </select>
        </div>
        <div id="compare-control-workspace" class="compare-control-workspace">
          <div id="compare-control-column-primary" class="compare-control-set-column compare-control-set-column-primary">
            <section id="compare-control-panel" class="compare-control-panel compare-control-set-panel">
              <h3>Set 1</h3>
              <div class="compare-control-controls">
                <label for="compare-control-view-mode">View</label>
                <select id="compare-control-view-mode">
                  <option value="discover">discover</option>
                  <option value="raw">raw</option>
                  <option value="controlled">controlled</option>
                </select>
                <label for="compare-control-outcome-field">Outcome</label>
                <select id="compare-control-outcome-field"></select>
                <label for="compare-control-compare-field">Compare by</label>
                <select id="compare-control-compare-field"></select>
                <label for="compare-control-split-field">Split by</label>
                <select id="compare-control-split-field"></select>
              </div>
              <div class="compare-control-hold">
                <span class="compare-control-hold-label">Hold constant</span>
                <div id="compare-control-hold-fields" class="compare-control-hold-fields"></div>
              </div>
              <div id="compare-control-group-selection" class="compare-control-group-selection"></div>
              <div class="compare-control-actions">
                <button id="compare-control-filter-subset" type="button">Apply local subset</button>
                <button id="compare-control-clear-selection" type="button">Clear groups</button>
                <button id="compare-control-reset" type="button">Reset set 1</button>
              </div>
            </section>
            <section id="compare-control-results-card-primary" class="compare-control-results-card compare-control-results-card-primary">
              <h4>Set 1 table</h4>
              <p id="compare-control-status" class="section-note"></p>
              <div id="compare-control-results" class="compare-control-results"></div>
            </section>
            <section id="compare-control-chart-card-primary" class="compare-control-chart-card compare-control-chart-card-primary">
              <h5>Set 1 chart</h5>
              <p class="section-note">Auto-built from Compare &amp; Control scope and settings only (numeric compare: scatter, categorical compare: bars).</p>
              <div id="compare-control-trend-chart" class="highcharts-host" aria-label="Compare and control score trend chart"></div>
              <p id="compare-control-trend-fallback" class="empty-note" hidden></p>
            </section>
          </div>
          <div id="compare-control-column-secondary" class="compare-control-set-column compare-control-set-column-secondary" hidden>
            <section id="compare-control-panel-secondary" class="compare-control-panel compare-control-set-panel compare-control-set-panel-secondary" hidden>
              <h3>Set 2</h3>
              <div class="compare-control-controls">
                <label for="compare-control-view-mode-secondary">View</label>
                <select id="compare-control-view-mode-secondary">
                  <option value="discover">discover</option>
                  <option value="raw">raw</option>
                  <option value="controlled">controlled</option>
                </select>
                <label for="compare-control-outcome-field-secondary">Outcome</label>
                <select id="compare-control-outcome-field-secondary"></select>
                <label for="compare-control-compare-field-secondary">Compare by</label>
                <select id="compare-control-compare-field-secondary"></select>
                <label for="compare-control-split-field-secondary">Split by</label>
                <select id="compare-control-split-field-secondary"></select>
              </div>
              <div class="compare-control-hold">
                <span class="compare-control-hold-label">Hold constant</span>
                <div id="compare-control-hold-fields-secondary" class="compare-control-hold-fields"></div>
              </div>
              <div id="compare-control-group-selection-secondary" class="compare-control-group-selection"></div>
              <div class="compare-control-actions">
                <button id="compare-control-filter-subset-secondary" type="button">Apply local subset</button>
                <button id="compare-control-clear-selection-secondary" type="button">Clear groups</button>
                <button id="compare-control-reset-secondary" type="button">Reset set 2</button>
              </div>
            </section>
            <section id="compare-control-results-card-secondary" class="compare-control-results-card compare-control-results-card-secondary" hidden>
              <h4>Set 2 table</h4>
              <p id="compare-control-status-secondary" class="section-note"></p>
              <div id="compare-control-results-secondary" class="compare-control-results"></div>
            </section>
            <section id="compare-control-chart-card-secondary" class="compare-control-chart-card compare-control-chart-card-secondary" hidden>
              <h5>Set 2 chart</h5>
              <p class="section-note">Auto-built from Compare &amp; Control scope and settings only (numeric compare: scatter, categorical compare: bars).</p>
              <div id="compare-control-trend-chart-secondary" class="highcharts-host" aria-label="Compare and control score trend chart set 2"></div>
              <p id="compare-control-trend-fallback-secondary" class="empty-note" hidden></p>
            </section>
          </div>
        </div>
        <section id="compare-control-chart-card-combined" class="compare-control-chart-card compare-control-chart-card-combined" hidden>
          <h5>Combined chart</h5>
          <p class="section-note">Use combined mode only when you want one merged chart instead of the default left/right split.</p>
          <div id="compare-control-trend-chart-combined" class="highcharts-host" aria-label="Combined compare and control score trend chart"></div>
          <p id="compare-control-trend-fallback-combined" class="empty-note" hidden></p>
        </section>
      </section>
    </div>
	  </section>
</main>

<footer>Generated by <code>cookimport stats-dashboard</code></footer>

<script id="dashboard-data-inline" type="application/json">__DASHBOARD_DATA_INLINE__</script>
<script src="https://code.highcharts.com/stock/highstock.js"></script>
<script>
if (!window.Highcharts || typeof window.Highcharts.stockChart !== 'function') {
  document.write('<script src="https://cdn.jsdelivr.net/npm/highcharts/highstock.js"><\\/script>');
}
</script>
<script src="https://code.highcharts.com/highcharts-more.js"></script>
<script>
if (!window.Highcharts || !window.Highcharts.seriesTypes || typeof window.Highcharts.seriesTypes.arearange !== 'function') {
  document.write('<script src="https://cdn.jsdelivr.net/npm/highcharts/highcharts-more.js"><\\/script>');
}
</script>
<script src="assets/dashboard.js?v=__ASSET_VERSION__"></script>
</body>
</html>
"""
