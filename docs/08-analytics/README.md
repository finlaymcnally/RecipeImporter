---
summary: "Performance, observability, and lifetime metrics documentation for stage and benchmark workflows."
read_when:
  - When changing performance reporting, history CSV writes, or dashboard generation
  - When tuning throughput and validating optimization tradeoffs
---

# Analytics Section Reference

This section documents runtime metrics and performance tooling.

## Core code

- `cookimport/analytics/perf_report.py`: per-run summaries and history CSV writes
- `cookimport/analytics/dashboard_collect.py`: dashboard data collection
- `cookimport/analytics/dashboard_render.py`: static HTML dashboard renderer
- `cookimport/analytics/dashboard_schema.py`: dashboard data contracts

## Primary docs

- Metrics artifact map:
  `docs/08-analytics/2026-02-12_11.31.47-metrics-observability-map.md`
- Throughput/resource tuning report:
  `docs/08-analytics/resource_usage_report.md`
- Performance optimization ExecPlan history:
  `docs/08-analytics/SPEED_UP.md`
