from __future__ import annotations

_CSS = """\
:root {
  --bg: #eef2f6;
  --bg-accent: #dde7f1;
  --card: #ffffff;
  --border: #d4dde7;
  --accent: #1f5ea8;
  --accent2: #127a52;
  --accent3: #bb3a2f;
  --text: #18222c;
  --muted: #546372;
  --font: 'IBM Plex Sans', 'Avenir Next', 'Segoe UI', Arial, sans-serif;
  --mono: 'SF Mono', SFMono-Regular, Consolas, 'Liberation Mono', Menlo, monospace;
  --focus: #0b72ff;
  --previous-runs-header-row-height: 2.18rem;
  --previous-runs-filter-row-height: 2.18rem;
  --previous-runs-spacer-row-height: 2.18rem;
  --previous-runs-body-row-height: 1.85rem;
  --previous-runs-visible-body-rows: 10;
}
*, *::before, *::after { box-sizing: border-box; }
body {
  font-family: var(--font);
  color: var(--text);
  background: linear-gradient(180deg, var(--bg-accent) 0%, var(--bg) 220px, var(--bg) 100%);
  margin: 0;
  padding: 0 1rem 2rem;
  line-height: 1.5;
  min-height: 100vh;
}
a {
  color: var(--accent);
}
a:focus-visible,
button:focus-visible,
select:focus-visible,
input:focus-visible,
summary:focus-visible {
  outline: 2px solid var(--focus);
  outline-offset: 2px;
}
header {
  padding: 1.5rem 0 0.65rem;
  border-bottom: 2px solid var(--border);
  margin-bottom: 0.8rem;
}
header h1 {
  margin: 0;
  font-size: 1.7rem;
  letter-spacing: 0.015em;
}
main {
  min-width: 0;
  max-width: 100%;
}
#header-subtitle {
  margin: 0.25rem 0 0.45rem;
  color: var(--muted);
  font-size: 0.95rem;
}
#header-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 0.5rem 1rem;
  font-size: 0.83rem;
  color: var(--muted);
}
#header-meta span {
  display: inline-flex;
  align-items: center;
  border: 1px solid var(--border);
  border-radius: 999px;
  background: var(--card);
  padding: 0.1rem 0.55rem;
}

#kpi-strip {
  background: transparent;
  border: 0;
  padding: 0;
  margin-bottom: 1rem;
}
#kpi-strip h2 {
  margin: 0 0 0.45rem;
  font-size: 0.96rem;
  letter-spacing: 0.06em;
  color: var(--muted);
  text-transform: uppercase;
}
#kpi-cards {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
  gap: 0.65rem;
}
.kpi-card {
  border: 1px solid var(--border);
  border-radius: 10px;
  background: var(--card);
  padding: 0.7rem 0.8rem;
}
.kpi-label {
  color: var(--muted);
  font-size: 0.72rem;
  text-transform: uppercase;
  letter-spacing: 0.07em;
}
.kpi-value {
  display: block;
  margin-top: 0.2rem;
  font-family: var(--mono);
  font-size: 1.15rem;
  font-weight: 600;
}
.kpi-detail {
  display: block;
  margin-top: 0.12rem;
  font-size: 0.75rem;
  color: var(--muted);
}

#controls-bar {
  display: flex;
  flex-wrap: wrap;
  align-items: flex-end;
  gap: 0.7rem;
  margin-bottom: 1.2rem;
}
#filters {
  display: flex;
  gap: 0.65rem;
  flex-wrap: wrap;
  flex: 1 1 auto;
}
fieldset {
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 0.35rem 0.65rem;
  background: rgba(255, 255, 255, 0.85);
}
legend {
  font-size: 0.73rem;
  color: var(--muted);
  text-transform: uppercase;
  letter-spacing: 0.07em;
  padding: 0 0.28rem;
}
fieldset label {
  margin-right: 0.65rem;
  font-size: 0.83rem;
  cursor: pointer;
}
fieldset button {
  background: var(--card);
  border: 1px solid var(--border);
  border-radius: 999px;
  padding: 0.18rem 0.58rem;
  margin-right: 0.22rem;
  cursor: pointer;
  font-size: 0.78rem;
}
fieldset button.active { background: var(--accent); color: #fff; border-color: var(--accent); }

section {
  background: var(--card);
  border: 1px solid var(--border);
  border-radius: 10px;
  padding: 1.1rem;
  margin-bottom: 1rem;
}
section h2 {
  margin: 0 0 0.6rem;
  font-size: 1.12rem;
}
section h3 {
  margin: 1rem 0 0.4rem;
  font-size: 0.93rem;
  color: var(--muted);
}
.section-note { margin: 0 0 0.75rem; color: var(--muted); font-size: 0.85rem; }
.metric-help-list {
  margin: 0.15rem 0 0.4rem 1.1rem;
  color: var(--muted);
  font-size: 0.83rem;
}
.metric-help-list li { margin: 0.2rem 0; }
.metric-hover-tooltip {
  position: fixed;
  z-index: 1200;
  max-width: min(440px, calc(100vw - 1.4rem));
  padding: 0.48rem 0.58rem;
  border-radius: 8px;
  border: 1px solid #2a3b4d;
  background: #172430;
  color: #f2f7fb;
  font-size: 0.78rem;
  line-height: 1.35;
  box-shadow: 0 8px 24px rgba(14, 22, 30, 0.35);
  pointer-events: none;
}
.metric-hover-tooltip[hidden] {
  display: none;
}
[data-metric-tooltip-key] {
  transition:
    color 150ms ease,
    fill 150ms ease;
}
[data-metric-tooltip-key]:hover,
th[data-metric-tooltip-key]:hover,
td[data-metric-tooltip-key]:hover {
  color: #1a5684;
}
svg [data-metric-tooltip-key]:hover {
  fill: #1a5684 !important;
}
svg [data-metric-tooltip-key]:hover * {
  fill: #1a5684 !important;
}
#previous-runs-clear-filters,
#previous-runs-clear-all-filters,
#previous-runs-column-reset {
  border: 1px solid var(--border);
  border-radius: 999px;
  background: #f6f9fc;
  color: var(--text);
  cursor: pointer;
  font-size: 0.78rem;
  padding: 0.18rem 0.62rem;
}
#previous-runs-clear-filters:hover,
#previous-runs-clear-all-filters:hover,
#previous-runs-column-reset:hover {
  border-color: #c7d0d9;
}
#previous-runs-section {
  overflow-x: hidden;
}
.previous-runs-sections {
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  gap: 0.75rem;
  margin: 0.5rem 0 0.9rem;
  min-width: 0;
}
.previous-runs-subsection {
  border: 1px solid var(--border);
  border-radius: 10px;
  background: #fbfcff;
  padding: 0.62rem 0.72rem;
  min-width: 0;
  overflow-x: hidden;
}
.previous-runs-subsection > h3 {
  margin: 0 0 0.35rem;
  color: #355471;
}
.previous-runs-subsection > .section-note {
  margin: 0 0 0.55rem;
}
#all-method-summary-section {
  background: #fdfcf7;
  border-color: #e8dec7;
}
#all-method-summary-section > h3 {
  color: #6d5430;
}
.all-method-summary-wrap {
  border: 1px solid var(--border);
  border-radius: 8px;
  background: #fffef9;
}
.all-method-summary-table td.num {
  white-space: nowrap;
}
.all-method-summary-empty {
  margin: 0;
}
#compare-control-analysis-section {
  background: #f8fbf6;
  border-color: #d7e3cf;
}
#compare-control-analysis-section > h3 {
  color: #4a6438;
}
.compare-control-global-actions {
  display: grid;
  grid-template-columns: auto auto minmax(150px, 180px) auto minmax(170px, 230px);
  align-items: center;
  gap: 0.35rem 0.48rem;
  margin-bottom: 0.6rem;
}
.compare-control-global-actions label {
  color: var(--muted);
  font-size: 0.73rem;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.05em;
}
#compare-control-toggle-second-set {
  border: 1px solid #c7d9b8;
  border-radius: 999px;
  background: #eef7e7;
  color: #2f4a1e;
  cursor: pointer;
  font-size: 0.77rem;
  padding: 0.22rem 0.68rem;
  white-space: nowrap;
}
#compare-control-toggle-second-set:hover {
  border-color: #aac293;
  background: #e7f3de;
}
#compare-control-chart-layout,
#compare-control-combined-axis-mode {
  width: 100%;
  min-width: 0;
  border: 1px solid var(--border);
  border-radius: 6px;
  background: #fff;
  color: var(--text);
  font-size: 0.8rem;
  padding: 0.28rem 0.4rem;
}
.compare-control-x-axis-toggle-wrap {
  display: flex;
  align-items: center;
  gap: 0.45rem;
  margin-top: 0.55rem;
  flex-wrap: wrap;
}
.compare-control-x-axis-toggle-label {
  color: var(--muted);
  font-size: 0.73rem;
  font-weight: 600;
  letter-spacing: 0.04em;
  text-transform: uppercase;
}
.compare-control-x-axis-toggle {
  display: inline-flex;
  align-items: stretch;
  border: 1px solid #cfd9c5;
  border-radius: 999px;
  overflow: hidden;
  background: #f5f8ef;
}
.compare-control-x-axis-toggle button {
  border: 0;
  background: transparent;
  color: #516047;
  cursor: pointer;
  font-size: 0.78rem;
  font-weight: 600;
  padding: 0.3rem 0.72rem;
}
.compare-control-x-axis-toggle button:hover {
  background: #e8f0dd;
}
.compare-control-x-axis-toggle button.is-active {
  background: #d8e8c6;
  color: #274112;
}
.compare-control-controls-split {
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  gap: 0.58rem;
  align-items: stretch;
}
.compare-control-workspace {
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  gap: 0.7rem;
  align-items: start;
}
.compare-control-set-column {
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  gap: 0.58rem;
  min-width: 0;
  align-content: start;
}
.compare-control-panel {
  margin: 0;
  background: #fbfcf7;
  border: 1px solid #dde5cf;
  min-width: 0;
  max-width: 100%;
}
.compare-control-set-panel {
  min-height: 380px;
}
#compare-control-panel-secondary {
  background: #f7fbff;
  border-color: #d6e4f2;
  transform: translateX(22px);
  opacity: 0;
  transition: transform 180ms ease, opacity 180ms ease;
}
#compare-control-analysis-section.compare-control-dual-enabled .compare-control-controls-split {
  grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
}
#compare-control-analysis-section.compare-control-dual-enabled .compare-control-workspace {
  grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
}
#compare-control-analysis-section.compare-control-dual-enabled .compare-control-set-panel {
  min-height: 460px;
}
#compare-control-analysis-section.compare-control-dual-enabled #compare-control-panel-secondary {
  transform: translateX(0);
  opacity: 1;
}
.compare-control-panel h3 {
  margin: 0 0 0.5rem;
  color: #4a6438;
}
.compare-control-panel.compare-control-set-panel-secondary h3 {
  color: #355471;
}
.compare-control-controls {
  display: grid;
  grid-template-columns: minmax(78px, auto) minmax(0, 1fr);
  gap: 0.32rem 0.45rem;
  align-items: center;
}
.compare-control-controls label,
.compare-control-hold-label {
  color: var(--muted);
  font-size: 0.73rem;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.05em;
}
#compare-control-view-mode,
#compare-control-outcome-field,
#compare-control-compare-field,
#compare-control-split-field,
#compare-control-view-mode-secondary,
#compare-control-outcome-field-secondary,
#compare-control-compare-field-secondary,
#compare-control-split-field-secondary {
  width: 100%;
  min-width: 0;
  border: 1px solid var(--border);
  border-radius: 6px;
  background: #fff;
  color: var(--text);
  font-size: 0.8rem;
  padding: 0.28rem 0.4rem;
}
#compare-control-filter-subset,
#compare-control-clear-selection,
#compare-control-reset,
#compare-control-filter-subset-secondary,
#compare-control-clear-selection-secondary,
#compare-control-reset-secondary {
  border: 1px solid var(--border);
  border-radius: 999px;
  background: #f6f9fc;
  color: var(--text);
  cursor: pointer;
  font-size: 0.77rem;
  padding: 0.18rem 0.62rem;
}
#compare-control-filter-subset:hover,
#compare-control-clear-selection:hover,
#compare-control-reset:hover,
#compare-control-filter-subset-secondary:hover,
#compare-control-clear-selection-secondary:hover,
#compare-control-reset-secondary:hover {
  border-color: #c7d0d9;
}
#compare-control-filter-subset:disabled,
#compare-control-clear-selection:disabled,
#compare-control-reset:disabled,
#compare-control-filter-subset-secondary:disabled,
#compare-control-clear-selection-secondary:disabled,
#compare-control-reset-secondary:disabled {
  opacity: 0.65;
  cursor: not-allowed;
}
#compare-control-status.error,
#compare-control-status-secondary.error {
  color: var(--accent3);
}
.compare-control-hold {
  margin-top: 0.5rem;
}
.compare-control-hold-fields {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 0.24rem 0.5rem;
  margin-top: 0.24rem;
}
.compare-control-hold-item {
  display: inline-flex;
  align-items: center;
  gap: 0.32rem;
  font-size: 0.76rem;
  color: var(--text);
}
.compare-control-hold-item input[type="checkbox"] {
  margin: 0;
}
.compare-control-group-selection {
  margin-top: 0.5rem;
}
.compare-control-group-selection-list {
  display: grid;
  gap: 0.21rem;
  max-height: 150px;
  overflow-y: auto;
  padding-right: 0.2rem;
}
.compare-control-group-option {
  display: inline-flex;
  align-items: center;
  gap: 0.36rem;
  font-size: 0.76rem;
  color: var(--text);
}
.compare-control-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 0.4rem;
  margin-top: 0.52rem;
}
.compare-control-results-stack {
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  gap: 0.52rem;
  margin-top: 0.58rem;
}
#compare-control-analysis-section.compare-control-dual-enabled .compare-control-results-stack {
  grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
  align-items: start;
}
.compare-control-results-card {
  border: 1px solid #dde7d2;
  border-radius: 9px;
  padding: 0.5rem 0.56rem;
}
.compare-control-results-card > h4 {
  margin: 0 0 0.25rem;
  font-size: 0.86rem;
  color: #4a6438;
}
.compare-control-results-card-primary {
  background: linear-gradient(180deg, #fcfef9 0%, #f8fdf2 100%);
}
.compare-control-results-card-secondary {
  background: linear-gradient(180deg, #fbfdff 0%, #f3f9ff 100%);
  border-color: #d5e3f0;
}
.compare-control-results {
  border: 1px dashed #ccd9c1;
  border-radius: 8px;
  background: #fff;
  padding: 0.48rem 0.62rem;
  min-width: 0;
  max-width: 100%;
  overflow-x: auto;
  overflow-wrap: anywhere;
  word-break: break-word;
}
.compare-control-results p {
  margin: 0.2rem 0;
  font-size: 0.81rem;
  overflow-wrap: anywhere;
  word-break: break-word;
}
.compare-control-results ul {
  margin: 0.25rem 0 0.05rem 1rem;
  padding: 0;
}
.compare-control-results li {
  margin: 0.15rem 0;
  font-size: 0.79rem;
  overflow-wrap: anywhere;
  word-break: break-word;
}
.compare-control-groups-table-wrap {
  margin-top: 0.24rem;
  max-width: 100%;
  overflow-x: auto;
}
.compare-control-groups-table {
  width: max-content;
  min-width: 100%;
  border-collapse: collapse;
}
.compare-control-groups-table th,
.compare-control-groups-table td {
  border-bottom: 1px solid #e5ecda;
  padding: 0.22rem 0.36rem;
  font-size: 0.77rem;
  white-space: nowrap;
}
.compare-control-groups-table th {
  text-transform: none;
  letter-spacing: 0;
  color: var(--muted);
  background: #f8fbf2;
  white-space: normal;
  overflow-wrap: anywhere;
  word-break: break-word;
  line-height: 1.12;
  height: 2.5rem;
  vertical-align: top;
}
.compare-control-groups-table tbody tr:last-child td {
  border-bottom: 0;
}
.compare-control-groups-table td:first-child {
  min-width: 14rem;
  white-space: normal;
  overflow-wrap: anywhere;
  word-break: break-word;
}
.compare-control-discovery-list {
  display: grid;
  gap: 0.26rem;
}
.compare-control-discovery-card {
  border: 1px solid #d8e2cb;
  border-radius: 7px;
  background: #f9fcf3;
  text-align: left;
  padding: 0.34rem 0.48rem;
  cursor: pointer;
  color: var(--text);
  overflow-wrap: anywhere;
  word-break: break-word;
}
.compare-control-discovery-card:hover {
  border-color: #b4c59f;
}
.compare-control-discovery-card .score {
  color: #466832;
  font-weight: 600;
}
.compare-control-split-list {
  margin-top: 0.36rem;
}
.compare-control-inline-note {
  color: var(--muted);
  font-size: 0.78rem;
}
.compare-control-warning {
  color: #8a5b07;
  font-size: 0.79rem;
}
.compare-control-chart-grid {
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  gap: 0.58rem;
}
.compare-control-chart-grid.layout-side-by-side {
  grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
}
.compare-control-chart-grid.layout-combined {
  grid-template-columns: minmax(0, 1fr);
}
.compare-control-chart-card {
  border: 1px solid #d6e3ce;
  border-radius: 9px;
  background: #f9fcf6;
  padding: 0.42rem 0.48rem;
  min-width: 0;
}
.compare-control-chart-card > h5 {
  margin: 0 0 0.24rem;
  font-size: 0.82rem;
  color: #476137;
}
.compare-control-chart-card-secondary {
  border-color: #d2e1ee;
  background: #f5faff;
}
.compare-control-chart-card-secondary > h5 {
  color: #355471;
}
.compare-control-chart-card-combined {
  border-color: #d2ddd2;
  background: #f9fbf9;
  margin-top: 0.65rem;
}
.compare-control-chart-card-combined > h5 {
  color: #42513f;
}

.chart-container { width: 100%; overflow-x: auto; min-height: 120px; }
.chart-container svg { display: block; }
.chart-legend {
  display: flex;
  flex-wrap: wrap;
  gap: 0.65rem;
  margin: 0.2rem 0 0.45rem;
}
.chart-legend-item {
  font-size: 0.78rem;
  color: var(--muted);
}
.chart-legend-dot {
  display: inline-block;
  width: 0.62rem;
  height: 0.62rem;
  border-radius: 999px;
  margin-right: 0.28rem;
  vertical-align: middle;
}
.trend-chart-wrap {
  margin: 0.4rem 0 0.7rem;
  min-width: 0;
}
.trend-chart-wrap h4 {
  margin: 0;
  color: #355471;
  font-size: 0.94rem;
}
.benchmark-trend-fields {
  margin: 0.2rem 0 0.52rem;
  padding: 0.48rem 0.55rem;
  border: 1px solid #d4e1ef;
  border-radius: 8px;
  background: #f8fbff;
}
.benchmark-trend-fields-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.45rem;
}
.benchmark-trend-fields-head h5 {
  margin: 0;
  font-size: 0.82rem;
  color: #2b557d;
}
.benchmark-trend-fields-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 0.32rem;
}
.benchmark-trend-fields-actions button {
  font-size: 0.71rem;
  padding: 0.12rem 0.42rem;
}
.benchmark-trend-field-checklist {
  margin-top: 0.28rem;
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(210px, 1fr));
  gap: 0.25rem 0.5rem;
  max-height: 9.2rem;
  overflow: auto;
  padding-right: 0.18rem;
}
.benchmark-trend-field-option {
  display: inline-flex;
  align-items: center;
  gap: 0.34rem;
  font-size: 0.76rem;
  color: var(--text);
}
.benchmark-trend-field-option input[type="checkbox"] {
  width: 0.9rem;
  height: 0.9rem;
  accent-color: var(--accent2);
}
#benchmark-trend-fields-status {
  margin: 0.35rem 0 0;
}
.compare-control-trend-wrap h4 {
  color: #4a6438;
}
.quick-filters-panel {
  margin: 0.5rem 0 0.62rem;
  background: #f9fcf8;
  border: 1px solid #d6e2ce;
}
.quick-filters-panel h3 {
  margin: 0 0 0.24rem;
  color: #435c3b;
}
.quick-filters-list {
  display: flex;
  flex-wrap: wrap;
  gap: 0.32rem 0.9rem;
  flex: 1 1 420px;
  min-width: min(420px, 100%);
}
.quick-filters-list label {
  display: inline-flex;
  align-items: center;
  gap: 0.38rem;
  font-size: 0.82rem;
  color: var(--text);
  cursor: pointer;
}
.quick-filters-list input[type="checkbox"] {
  width: 0.95rem;
  height: 0.95rem;
  accent-color: var(--accent2);
}
.quick-filters-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 0.36rem 0.7rem;
  align-items: center;
  justify-content: space-between;
  margin-top: 0.12rem;
}
#previous-runs-clear-all-filters {
  font-size: 0.78rem;
  align-self: center;
  margin-left: auto;
  white-space: nowrap;
}
#quick-filters-status {
  margin: 0.34rem 0 0;
  font-size: 0.74rem;
}
.highcharts-host {
  width: 100%;
  max-width: 100%;
  min-width: 0;
  height: 800px;
  min-height: 720px;
  border: 1px solid var(--border);
  border-radius: 8px;
  background: #fbfdff;
}

.table-wrap {
  overflow-x: auto;
  position: relative;
  min-width: 0;
  max-width: 100%;
}
.previous-runs-columns-control {
  position: absolute;
  top: 0.4rem;
  right: 0.45rem;
  z-index: 5;
  display: inline-block;
}
.previous-runs-columns-toggle {
  border: 1px solid var(--border);
  border-radius: 999px;
  background: #f4f8fd;
  color: var(--text);
  cursor: pointer;
  font-size: 0.72rem;
  font-weight: 700;
  letter-spacing: 0.03em;
  padding: 0.14rem 0.5rem;
  min-width: 2.6rem;
}
.previous-runs-columns-toggle:hover,
.previous-runs-columns-toggle.open {
  border-color: #8ab0d8;
  background: #e7f1ff;
  color: #174d84;
}
.previous-runs-columns-popup {
  position: absolute;
  top: calc(100% + 0.25rem);
  right: 0;
  width: min(310px, calc(100vw - 1.6rem));
  max-height: min(65vh, 460px);
  overflow-y: auto;
  border: 1px solid var(--border);
  border-radius: 8px;
  background: #fbfdff;
  box-shadow: 0 10px 24px rgba(21, 34, 48, 0.14);
  padding: 0.55rem 0.6rem;
}
#previous-runs-columns-checklist {
  display: grid;
  gap: 0.28rem;
}
.previous-runs-columns-check-item {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr);
  gap: 0.42rem;
  align-items: start;
  color: var(--text);
  font-size: 0.78rem;
}
.previous-runs-columns-check-item code {
  color: var(--muted);
  font-size: 0.72rem;
}
.previous-runs-presets-panel {
  margin: 0.4rem 0 0;
  padding: 0.44rem 0.55rem;
  border: 1px solid #cfdfc7;
  border-radius: 7px;
  background: #fcfefb;
  box-shadow: none;
  width: min(560px, 100%);
  max-width: 100%;
  flex: 0 1 auto;
}
.previous-runs-presets-panel h4 {
  margin: 0 0 0.24rem;
  font-size: 0.76rem;
  color: #245273;
}
.previous-runs-presets-controls {
  display: grid;
  grid-template-columns: auto minmax(180px, 280px);
  align-items: center;
  gap: 0.2rem 0.46rem;
}
.previous-runs-presets-controls label {
  font-size: 0.72rem;
  color: var(--muted);
}
#previous-runs-preset-select {
  width: min(280px, 100%);
  min-height: 1.72rem;
}
.previous-runs-presets-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 0.3rem;
  margin-top: 0.24rem;
}
.previous-runs-presets-actions button {
  font-size: 0.74rem;
}
#previous-runs-preset-status {
  margin: 0.24rem 0 0;
  font-size: 0.72rem;
}
#previous-runs-preset-status.error {
  color: #ad2e24;
}
.previous-runs-columns-popup-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 0.36rem;
  align-items: flex-end;
  margin-top: 0.48rem;
}
.previous-runs-columns-popup-actions button {
  font-size: 0.74rem;
}
.previous-runs-global-filter-mode {
  display: grid;
  gap: 0.18rem;
}
.previous-runs-global-filter-mode label {
  font-size: 0.72rem;
  color: var(--muted);
}
#previous-runs-global-filter-mode {
  min-height: 1.9rem;
}

.table-scroll {
  min-height: calc(
    var(--previous-runs-header-row-height)
    + var(--previous-runs-filter-row-height)
    + var(--previous-runs-spacer-row-height)
    + (var(--previous-runs-visible-body-rows) * var(--previous-runs-body-row-height))
  );
  max-height: calc(
    var(--previous-runs-header-row-height)
    + var(--previous-runs-filter-row-height)
    + var(--previous-runs-spacer-row-height)
    + (var(--previous-runs-visible-body-rows) * var(--previous-runs-body-row-height))
  );
  overflow-x: auto;
  overflow-y: auto;
  border: 1px solid var(--border);
  border-radius: 8px;
}
.table-scroll thead th {
  position: sticky;
  background: var(--card);
  z-index: 1;
}
#previous-runs-table thead tr.previous-runs-header-row th {
  top: 0;
  z-index: 3;
}
#previous-runs-table thead tr.previous-runs-active-filters-row th {
  top: var(--previous-runs-header-row-height);
  background: #f7fbff;
  z-index: 2;
  text-transform: none;
  letter-spacing: 0;
  font-weight: 500;
  padding-top: 0.46rem;
  padding-bottom: 0.46rem;
}
#previous-runs-table thead tr.previous-runs-filter-spacer-row th {
  top: calc(var(--previous-runs-header-row-height) + var(--previous-runs-filter-row-height));
  background: #fcfdff;
  z-index: 1;
  text-transform: none;
  letter-spacing: 0;
  font-weight: 500;
  padding-top: 0.06rem;
  padding-bottom: 0.06rem;
  border-bottom: 0;
}

table { width: 100%; border-collapse: collapse; font-size: 0.85rem; }
.dashboard-resizable-table {
  width: max-content;
  min-width: 100%;
}
.dashboard-resizable-table th,
.dashboard-resizable-table td {
  position: relative;
}
th, td { text-align: left; padding: 0.37rem 0.55rem; border-bottom: 1px solid var(--border); }
#previous-runs-table {
  border-collapse: separate;
  border-spacing: 0;
  width: max-content;
  min-width: clamp(880px, 100%, 1600px);
  max-width: none;
}
#previous-runs-table thead th {
  background-clip: padding-box;
}
#previous-runs-table th,
#previous-runs-table td {
  white-space: nowrap;
}
#previous-runs-table th {
  padding-right: 0.9rem;
}
#previous-runs-table .previous-runs-header-title {
  display: inline-flex;
  align-items: center;
  gap: 0.2rem;
}
#previous-runs-table thead tr.previous-runs-header-row th:not(:last-child),
.dashboard-resizable-table thead tr:first-child th:not(:last-child) {
  border-right: 1px solid #d6e0ea;
}
.previous-runs-column-filter {
  position: relative;
}
.previous-runs-column-filter-summary-wrap {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 0.35rem;
  align-items: center;
}
.previous-runs-column-filter-summary {
  min-height: 1.22rem;
  display: flex;
  flex-direction: column;
  gap: 0.24rem;
  color: var(--muted);
  font-size: 0.77rem;
  line-height: 1.28;
}
.previous-runs-column-filter-summary.filter-active {
  color: #174d84;
  font-weight: 600;
}
.previous-runs-column-filter-summary-item {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  align-items: center;
  gap: 0.34rem;
}
.previous-runs-column-filter-summary-edit {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  border: 0;
  border-radius: 0;
  background: transparent;
  color: inherit;
  cursor: pointer;
  display: block;
  font: inherit;
  line-height: inherit;
  margin: 0;
  padding: 0;
  text-align: left;
}
.previous-runs-column-filter-summary-edit:hover {
  text-decoration: underline;
}
.previous-runs-column-filter-summary-remove {
  border: 0;
  border-radius: 0;
  background: transparent;
  color: #6f8091;
  cursor: pointer;
  width: auto;
  height: auto;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  line-height: 1;
  padding: 0.02rem;
  min-width: 13px;
  min-height: 13px;
}
.previous-runs-column-filter-summary-remove:hover {
  color: #556778;
}
.previous-runs-column-filter-toggle {
  width: auto;
  height: auto;
  border: 0;
  border-radius: 0;
  background: transparent;
  color: #174d84;
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  padding: 0.08rem 0.16rem;
  font-weight: 700;
  letter-spacing: 0.03em;
  line-height: 1;
  min-width: 1rem;
  min-height: 1rem;
  align-self: center;
}
.previous-runs-icon-svg {
  display: block;
  width: 12px;
  height: 12px;
}
.previous-runs-column-filter-toggle:hover {
  color: #123a63;
}
.previous-runs-column-filter-toggle.filter-active {
  color: #174d84;
}
.previous-runs-column-filter-popover {
  position: absolute;
  top: calc(100% + 0.24rem);
  right: 0;
  min-width: 230px;
  max-width: min(340px, 85vw);
  border: 1px solid #cfd9e4;
  border-radius: 8px;
  background: #ffffff;
  box-shadow: 0 8px 18px rgba(15, 23, 42, 0.12);
  padding: 0.5rem;
  z-index: 20;
  white-space: normal;
}
.previous-runs-column-filter-popover-title {
  font-size: 0.72rem;
  font-weight: 700;
  letter-spacing: 0.04em;
  text-transform: uppercase;
  color: var(--muted);
  margin: 0 0 0.35rem;
}
.previous-runs-column-filter-mode {
  display: grid;
  grid-template-columns: auto 1fr;
  align-items: center;
  gap: 0.32rem;
  margin: 0 0 0.42rem;
}
.previous-runs-column-filter-mode-label {
  font-size: 0.68rem;
  color: var(--muted);
}
.previous-runs-column-filter-mode-buttons {
  display: inline-flex;
  justify-content: flex-end;
  gap: 0.24rem;
}
.previous-runs-column-filter-mode-btn {
  border: 1px solid var(--border);
  border-radius: 999px;
  background: #f6f9fc;
  color: var(--text);
  cursor: pointer;
  font-size: 0.66rem;
  padding: 0.08rem 0.42rem;
}
.previous-runs-column-filter-mode-btn.active {
  border-color: #8ab0d8;
  background: #e7f1ff;
  color: #174d84;
}
.previous-runs-column-filter-mode-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
.previous-runs-column-filter-mode-btn:hover:not(:disabled) {
  border-color: #c7d0d9;
}
.previous-runs-column-filter-active-list {
  display: flex;
  flex-direction: column;
  gap: 0.22rem;
  margin: 0 0 0.45rem;
}
.previous-runs-column-filter-active-item {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  align-items: center;
  gap: 0.28rem;
  font-size: 0.71rem;
  color: var(--text);
  border: 1px solid #dde6f0;
  border-radius: 6px;
  background: #f8fbff;
  padding: 0.15rem 0.22rem 0.15rem 0.34rem;
}
.previous-runs-column-filter-active-item span {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.previous-runs-column-filter-active-remove {
  border: 1px solid #d7e0ea;
  border-radius: 999px;
  background: #ffffff;
  color: #4a5b6b;
  cursor: pointer;
  width: 1.1rem;
  height: 1.1rem;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  font-size: 0.75rem;
  line-height: 1;
  padding: 0;
}
.previous-runs-column-filter-active-remove:hover {
  border-color: #c6d0dc;
}
.previous-runs-column-filter-active-empty {
  font-size: 0.7rem;
  color: var(--muted);
}
.previous-runs-column-filter-popover-controls {
  display: grid;
  grid-template-columns: minmax(86px, 1fr) minmax(120px, 1.2fr);
  gap: 0.3rem;
  align-items: center;
  margin-bottom: 0.4rem;
}
.previous-runs-column-filter-popover-controls select,
.previous-runs-column-filter-popover-controls input {
  width: 100%;
  border: 1px solid var(--border);
  border-radius: 6px;
  background: #fff;
  color: var(--text);
  font-size: 0.75rem;
  padding: 0.18rem 0.32rem;
}
.previous-runs-column-filter-suggestions {
  margin: 0 0 0.42rem;
}
.previous-runs-column-filter-suggestions-title {
  color: var(--muted);
  font-size: 0.68rem;
  margin-bottom: 0.2rem;
}
.previous-runs-column-filter-suggestions-list {
  display: flex;
  flex-wrap: wrap;
  gap: 0.22rem;
  max-height: 6.8rem;
  overflow-y: auto;
}
.previous-runs-column-filter-suggestion {
  border: 1px solid var(--border);
  border-radius: 999px;
  background: #f8fbff;
  color: var(--text);
  cursor: pointer;
  font-size: 0.68rem;
  line-height: 1.2;
  padding: 0.12rem 0.42rem;
}
.previous-runs-column-filter-suggestion.best {
  border-color: #8ab0d8;
  background: #e7f1ff;
  color: #174d84;
}
.previous-runs-column-filter-suggestion:hover {
  border-color: #c7d0d9;
}
.previous-runs-column-filter-popover-actions {
  display: flex;
  gap: 0.3rem;
  justify-content: flex-end;
}
.previous-runs-column-filter-clear {
  border: 1px solid var(--border);
  border-radius: 999px;
  background: #f6f9fc;
  color: var(--text);
  cursor: pointer;
  font-size: 0.68rem;
  padding: 0.12rem 0.48rem;
}
.previous-runs-column-filter-clear:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}
.previous-runs-column-filter-clear:hover:not(:disabled) {
  border-color: #c7d0d9;
}
.previous-runs-column-filter-save,
.previous-runs-column-filter-close {
  border: 1px solid var(--border);
  border-radius: 999px;
  background: #f6f9fc;
  color: var(--text);
  cursor: pointer;
  font-size: 0.68rem;
  padding: 0.12rem 0.48rem;
}
.previous-runs-column-filter-save {
  border-color: #8ab0d8;
  background: #e7f1ff;
  color: #174d84;
}
.previous-runs-column-filter-save:hover,
.previous-runs-column-filter-close:hover {
  border-color: #c7d0d9;
}
#previous-runs-table th.previous-runs-draggable {
  cursor: grab;
}
#previous-runs-table th.previous-runs-draggable:active {
  cursor: grabbing;
}
#previous-runs-table th.previous-runs-drag-source {
  opacity: 0.65;
}
#previous-runs-table th.previous-runs-drag-target {
  box-shadow: inset 0 -2px 0 var(--focus);
}
.previous-runs-resize-handle,
.dashboard-table-resize-handle {
  position: absolute;
  top: 0;
  right: -0.28rem;
  width: 0.62rem;
  height: 100%;
  cursor: col-resize;
}
body.previous-runs-resizing,
body.dashboard-table-resizing {
  cursor: col-resize;
  user-select: none;
}
th {
  font-weight: 600;
  color: var(--muted);
  font-size: 0.73rem;
  text-transform: uppercase;
  letter-spacing: 0.045em;
}
td.num { text-align: right; font-family: var(--mono); }
td.delta-better { color: #0d5b37; font-weight: 600; }
td.delta-worse { color: #8a261f; font-weight: 600; }
td a { color: var(--accent); text-decoration: none; word-break: break-all; }
td a:hover { text-decoration: underline; }
td.warn-note { color: #b45309; font-weight: 600; }
.empty-note-cell {
  text-align: center;
  color: var(--muted);
  font-style: italic;
  padding: 0.8rem;
}
.mismatch-tag {
  color: #b45309;
  font-size: 0.72rem;
  font-weight: 600;
  margin-left: 0.35rem;
}

.inline-controls {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  margin: 0.25rem 0 0.75rem;
  flex-wrap: wrap;
}
.inline-controls label {
  color: var(--muted);
  font-size: 0.85rem;
}
.inline-controls select {
  min-width: 240px;
  max-width: 100%;
  border: 1px solid var(--border);
  border-radius: 4px;
  padding: 0.25rem 0.4rem;
  background: var(--card);
  color: var(--text);
}
.control-label {
  color: var(--muted);
  font-size: 0.82rem;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.05em;
}
.chart-mode-controls button {
  border: 1px solid var(--border);
  background: #f6f9fc;
  color: var(--text);
  border-radius: 999px;
  padding: 0.2rem 0.55rem;
  font-size: 0.78rem;
}
.chart-mode-controls button.active {
  border-color: var(--accent);
  background: var(--accent);
  color: #fff;
}

.table-collapse-global {
  display: flex;
  align-items: center;
  gap: 0.45rem;
  margin: 0;
  margin-left: auto;
}

.table-collapse-controls {
  display: flex;
  align-items: center;
  gap: 0.6rem;
  margin: 0.1rem 0 0.55rem;
}
.table-collapse-toggle {
  background: #f6f9fc;
  border: 1px solid var(--border);
  border-radius: 999px;
  color: var(--text);
  cursor: pointer;
  font-size: 0.78rem;
  padding: 0.2rem 0.62rem;
}
.table-collapse-toggle:hover {
  border-color: #c7d0d9;
}
.table-collapse-status {
  color: var(--muted);
  font-size: 0.78rem;
}

.empty-note { color: var(--muted); font-style: italic; padding: 1rem 0; }

.all-method-quick-nav {
  display: flex;
  flex-wrap: wrap;
  gap: 0.45rem;
  margin-bottom: 0.7rem;
  position: sticky;
  top: 0.35rem;
  z-index: 4;
  background: rgba(255, 255, 255, 0.94);
  backdrop-filter: blur(3px);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 0.35rem 0.45rem;
}
.all-method-quick-nav a {
  text-decoration: none;
  font-size: 0.76rem;
  border: 1px solid var(--border);
  border-radius: 999px;
  padding: 0.1rem 0.42rem;
  color: var(--muted);
}
.all-method-quick-nav a:hover {
  border-color: var(--accent);
  color: var(--accent);
}
.section-details {
  border: 1px solid var(--border);
  border-radius: 8px;
  margin-bottom: 0.7rem;
  background: #f8fbfe;
}
.section-details > summary {
  cursor: pointer;
  list-style: none;
  font-size: 0.82rem;
  font-weight: 600;
  color: var(--muted);
  padding: 0.42rem 0.6rem;
}
.section-details > summary::-webkit-details-marker {
  display: none;
}
.section-details > summary::before {
  content: "+";
  display: inline-block;
  margin-right: 0.34rem;
}
.section-details[open] > summary::before {
  content: "-";
}
.section-details > section {
  margin: 0;
  border: 0;
  border-top: 1px solid var(--border);
  border-radius: 0;
  background: transparent;
}

.summary-compact th,
.summary-compact td {
  padding: 0.3rem 0.5rem;
}
.summary-compact th {
  font-size: 0.74rem;
}

.metric-chart-block {
  margin-top: 0.85rem;
}
.metric-chart-block h3 {
  margin: 0 0 0.45rem;
  color: var(--text);
  font-size: 0.92rem;
}
.metric-chart-grid {
  display: grid;
  gap: 0.28rem;
}
.metric-bar-row {
  display: grid;
  grid-template-columns: 3.5rem minmax(220px, 1fr) 4.5rem;
  align-items: center;
  gap: 0.5rem;
}
.metric-bar-label {
  color: var(--muted);
  font-size: 0.76rem;
  font-family: var(--mono);
}
.metric-bar-track {
  display: block;
  width: 100%;
  background: #edf0f2;
  border-radius: 6px;
  height: 0.65rem;
  overflow: hidden;
}
.metric-bar-fill {
  display: block;
  height: 100%;
  background: var(--accent);
}
.metric-bar-fill-missing {
  background: #c5cdd5;
}
.metric-bar-value {
  text-align: right;
  font-family: var(--mono);
  font-size: 0.75rem;
}

.metric-radar-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
  gap: 0.75rem;
}
.metric-radar-card {
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 0.55rem;
  background: var(--card);
}
.metric-radar-card h4 {
  margin: 0 0 0.4rem;
  color: var(--text);
  font-size: 0.78rem;
  font-family: var(--mono);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.metric-radar-svg {
  width: 100%;
  height: auto;
  display: block;
}
.metric-radar-ring {
  fill: none;
  stroke: #d5dde5;
  stroke-width: 1;
}
.metric-radar-axis {
  stroke: #c2ccd7;
  stroke-width: 1;
}
.metric-radar-axis-label {
  fill: var(--muted);
  font-size: 7px;
  font-family: var(--mono);
}
.metric-radar-shape {
  fill: rgba(37, 99, 235, 0.22);
  stroke: var(--accent);
  stroke-width: 2;
}
.metric-radar-point {
  fill: var(--accent);
}
.metric-radar-values {
  margin-top: 0.45rem;
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 0.15rem 0.55rem;
}
.metric-radar-value-label {
  color: var(--muted);
  font-size: 0.72rem;
}
.metric-radar-value-number {
  text-align: right;
  font-family: var(--mono);
  font-size: 0.72rem;
}

.diagnostics-grid {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
  gap: 0.7rem;
}
.diagnostic-card {
  margin: 0;
  background: #f8fbfe;
}
#runtime-summary table,
#boundary-summary table {
  margin: 0;
  width: 100%;
  min-width: 0;
  table-layout: fixed;
}
#runtime-summary td:first-child {
  color: var(--muted);
  width: 42%;
}
#runtime-summary,
#boundary-summary {
  overflow-x: hidden;
}
#per-label-section {
  grid-column: 1 / -1;
  overflow-x: auto;
}
.per-label-title-row {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 0.4rem 0.6rem;
  margin: 0 0 0.45rem;
}
#per-label-section .per-label-title-row h2 {
  margin: 0;
}
.per-label-run-select-wrap {
  display: inline-flex;
  align-items: center;
  gap: 0.35rem;
  color: var(--muted);
  font-size: 0.74rem;
  font-weight: 600;
  letter-spacing: 0.03em;
  text-transform: uppercase;
}
.per-label-run-select-wrap select {
  min-width: 15.5rem;
  max-width: min(60vw, 25rem);
  border: 1px solid var(--border);
  border-radius: 6px;
  padding: 0.15rem 0.35rem;
  background: #fff;
  color: var(--text);
  font-size: 0.76rem;
  font-family: var(--mono);
  text-transform: none;
  letter-spacing: 0;
  font-weight: 500;
}
.per-label-controls {
  display: inline-flex;
  align-items: center;
  gap: 0.35rem;
  margin: 0 0 0.45rem;
  padding: 0.2rem 0.35rem;
  border: 1px solid #d5e0ea;
  border-radius: 6px;
  background: #f9fcff;
}
.per-label-controls .per-label-rolling-label {
  color: var(--muted);
  font-size: 0.74rem;
  font-weight: 600;
  letter-spacing: 0.03em;
  text-transform: uppercase;
}
.per-label-controls input[type="number"] {
  width: 3.6rem;
  border: 1px solid var(--border);
  border-radius: 6px;
  padding: 0.1rem 0.3rem;
  background: #fff;
  color: var(--text);
  font-size: 0.78rem;
  font-family: var(--mono);
}
.per-label-controls .per-label-checkbox {
  display: inline-flex;
  align-items: center;
  gap: 0.28rem;
  margin-left: 0.25rem;
  color: var(--muted);
  font-size: 0.72rem;
  font-weight: 600;
  letter-spacing: 0.02em;
  text-transform: uppercase;
  cursor: pointer;
}
.per-label-controls .per-label-checkbox input[type="checkbox"] {
  width: 0.88rem;
  height: 0.88rem;
  margin: 0;
}
#per-label-table {
  width: max-content;
  min-width: max-content;
}
#per-label-table th:first-child,
#per-label-table td:first-child {
  width: 25.5ch;
  min-width: 25.5ch;
}
#per-label-table th {
  white-space: normal;
  text-align: left;
  padding-top: 0.16rem;
  padding-bottom: 0.16rem;
}
#per-label-table th,
#per-label-table td {
  padding-left: 2px;
  padding-right: 2px;
}
#per-label-table th:first-child,
#per-label-table td:first-child {
  padding-left: 0.24rem;
  padding-right: 0.24rem;
}
#per-label-table td.num {
  text-align: left;
}
#per-label-table td:nth-child(n+2):nth-child(-n+3),
#per-label-table thead tr.per-label-header-primary th:nth-child(n+2):nth-child(-n+3) {
  width: calc(6ch + 10px);
  min-width: calc(6ch + 10px);
}
#per-label-table td:nth-child(n+4):nth-child(-n+11),
#per-label-table thead tr.per-label-header-primary th:nth-child(n+4):nth-child(-n+7),
#per-label-table thead tr.per-label-header-rolling th {
  width: calc(10ch + 10px);
  min-width: calc(10ch + 10px);
}
#per-label-table thead tr.per-label-header-primary th.per-label-rolling-group {
  text-align: center;
  vertical-align: bottom;
  padding-bottom: 0.04rem;
}
#per-label-table thead tr.per-label-header-primary th.per-label-rolling-group .per-label-col-head {
  text-align: center;
}
.per-label-rolling-group-head {
  white-space: nowrap;
}
#per-label-table thead tr.per-label-header-rolling th {
  vertical-align: top;
}
.per-label-col-head {
  display: block;
  line-height: 1.06;
  text-align: left;
  font-size: 0.92em;
}
.per-label-col-sub {
  font-size: 0.74em;
  letter-spacing: 0.01em;
}

footer { text-align: center; color: var(--muted); font-size: 0.78rem; margin-top: 1.3rem; }

@media (max-width: 1100px) {
  #controls-bar {
    align-items: stretch;
  }
  .table-collapse-global {
    margin-left: 0;
  }
  #previous-runs-table {
    min-width: 1100px;
  }
  .highcharts-host {
    height: 680px;
    min-height: 620px;
  }
}

@media (max-width: 900px) {
  .diagnostics-grid {
    grid-template-columns: 1fr;
  }
  body {
    padding: 0 0.55rem 1.4rem;
  }
  header h1 {
    font-size: 1.38rem;
  }
  #header-subtitle {
    font-size: 0.88rem;
  }
  section {
    padding: 0.82rem;
  }
  #recent-runs th:nth-child(7),
  #recent-runs td:nth-child(7),
  #recent-runs th:nth-child(8),
  #recent-runs td:nth-child(8),
  #recent-runs th:nth-child(9),
  #recent-runs td:nth-child(9),
  #recent-runs th:nth-child(10),
  #recent-runs td:nth-child(10),
  #file-trend-table th:nth-child(6),
  #file-trend-table td:nth-child(6),
  #file-trend-table th:nth-child(7),
  #file-trend-table td:nth-child(7),
  #file-trend-table th:nth-child(8),
  #file-trend-table td:nth-child(8),
  #file-trend-table th:nth-child(9),
  #file-trend-table td:nth-child(9),
  #benchmark-table th:nth-child(6),
  #benchmark-table td:nth-child(6),
  #benchmark-table th:nth-child(7),
  #benchmark-table td:nth-child(7),
  #benchmark-table th:nth-child(11),
  #benchmark-table td:nth-child(11),
  #benchmark-table th:nth-child(12),
  #benchmark-table td:nth-child(12) {
    display: none;
  }
  .all-method-quick-nav {
    position: static;
  }
  .previous-runs-column-filter {
    min-width: 120px;
  }
  .previous-runs-column-filter-popover {
    right: auto;
    left: 0;
    min-width: 210px;
  }
  .previous-runs-column-filter-popover-controls {
    grid-template-columns: 1fr;
  }
  .previous-runs-columns-control {
    top: 0.35rem;
    right: 0.35rem;
  }
  .previous-runs-columns-popup {
    width: min(280px, calc(100vw - 1.3rem));
  }
  .compare-control-global-actions {
    grid-template-columns: 1fr;
    justify-items: start;
  }
  #compare-control-chart-layout,
  #compare-control-combined-axis-mode {
    width: 100%;
  }
  .compare-control-controls-split,
  #compare-control-analysis-section.compare-control-dual-enabled .compare-control-controls-split {
    grid-template-columns: minmax(0, 1fr);
  }
  .compare-control-workspace,
  #compare-control-analysis-section.compare-control-dual-enabled .compare-control-workspace {
    grid-template-columns: minmax(0, 1fr);
  }
  #compare-control-analysis-section.compare-control-dual-enabled .compare-control-results-stack {
    grid-template-columns: minmax(0, 1fr);
  }
  #compare-control-analysis-section.compare-control-dual-enabled .compare-control-set-panel {
    min-height: 0;
  }
  .compare-control-controls {
    grid-template-columns: 1fr;
  }
  #compare-control-view-mode,
  #compare-control-outcome-field,
  #compare-control-compare-field,
  #compare-control-split-field,
  #compare-control-view-mode-secondary,
  #compare-control-outcome-field-secondary,
  #compare-control-compare-field-secondary,
  #compare-control-split-field-secondary {
    width: 100%;
  }
  .compare-control-hold-fields {
    grid-template-columns: 1fr;
  }
  .compare-control-chart-grid.layout-side-by-side {
    grid-template-columns: minmax(0, 1fr);
  }
  .quick-filters-list {
    flex-direction: column;
    align-items: flex-start;
    min-width: 0;
    flex: 1 1 100%;
  }
  .quick-filters-actions {
    align-items: flex-start;
  }
  #previous-runs-clear-all-filters {
    margin-left: 0;
  }
  .previous-runs-presets-controls {
    grid-template-columns: 1fr;
  }
  #previous-runs-preset-select {
    width: 100%;
    min-width: 0;
  }
  #previous-runs-table {
    min-width: 100%;
  }
  #previous-runs-table th,
  #previous-runs-table td {
    white-space: normal;
    word-break: break-word;
    overflow-wrap: anywhere;
    vertical-align: top;
  }
  #previous-runs-table td.num {
    white-space: nowrap;
    word-break: normal;
    overflow-wrap: normal;
  }
  .highcharts-host {
    height: 560px;
    min-height: 500px;
  }
  .per-label-controls {
    flex-wrap: wrap;
  }
  .per-label-run-select-wrap {
    width: 100%;
    justify-content: space-between;
  }
  .per-label-run-select-wrap select {
    width: 100%;
    min-width: 0;
    max-width: 100%;
  }
}

@media (max-width: 620px) {
  #kpi-cards {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
  .metric-bar-row {
    grid-template-columns: 3.2rem minmax(90px, 1fr) 3.8rem;
  }
  .highcharts-host {
    height: 460px;
    min-height: 420px;
  }
  #per-label-table th:first-child,
  #per-label-table td:first-child {
    width: 16ch;
    min-width: 16ch;
  }
}
"""
