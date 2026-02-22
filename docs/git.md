---
summary: "Simple English changelog summarizing what is implemented from docs/plans."
read_when:
  - When you want a quick recap of what has shipped from docs/plans
---

# Simple Changelog (from docs/plans)

Snapshot date: 2026-02-20

- Added per-run settings selection/editing, with saved last-used settings for `import` and `benchmark` flows.
- Added stable run-config hash/summary fields and propagated them through reports, benchmark outputs, CSV history, and dashboard data.
- Unified stage/benchmark semantics with shared `run_manifest.json` artifacts and an offline benchmark mode (`labelstudio-benchmark --no-upload`).
- Added EPUB backend expansion work: MarkItDown support, deterministic markdown-to-block parsing, and split-safe wiring.
- Tuned Unstructured EPUB extraction with explicit options, BR normalization, improved adapter behavior, and richer diagnostics artifacts.
- Added EPUB debugging tooling under `cookimport epub`: `inspect`, `dump`, `unpack`, `blocks`, `candidates`, `validate`, and `race`.
- Added EPUB cleanup and hardening layers: shared normalization/postprocess, extraction health metrics/warnings, and stronger nav/pagebreak/table handling.
- Shipped deterministic multi-backend EPUB auto-selection wiring (`legacy`, `unstructured`, `markdown`, `markitdown`, `auto`) into stage, benchmark, reports, perf CSV, and dashboard.
- Shipped the major I-series foundations: stats dashboard, offline benchmark suite, unstructured extraction path, and deterministic catalog-driven auto-tagging.
- Added freeform Label Studio AI assist workflows:
  - `labelstudio-import --prelabel` (Codex CLI block-labeling -> deterministic span annotations),
  - inline-annotation upload fallback to post-import annotation creation,
  - `labelstudio-decorate` additive re-annotation command with dry-run reporting.

Still open / partial:

- `I5.1` is partial by design: `YIELD_LINE`/`TIME_LINE` support shipped, but most dataset campaign tasks remain open.
- `I6.1` LLM repair integration is still deferred/planning-only.
- OG `06` schema names (`qualityScoreV1` / `qualitySignalsV1`) were not adopted; current equivalent is `epubAutoSelectedScore` plus detailed auto-selection artifacts.
- `08` Milestone 0 real-book baseline evidence is documented as partial.
