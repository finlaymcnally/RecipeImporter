---
summary: "Offline benchmark-suite documentation for validation, run, sweep, and tuning loops."
read_when:
  - When iterating on parser quality without Label Studio uploads
  - When running or modifying cookimport bench workflows
---

# Bench Section Reference

Offline benchmarking is provided by `cookimport bench ...` commands wired in `cookimport/cli.py`.

## Runbook

- Quick-start and interpretation guide:
  `docs/07-bench/runbook.md`

## Core code

- `cookimport/bench/suite.py`: suite manifest load/validate
- `cookimport/bench/runner.py`: full suite execution
- `cookimport/bench/sweep.py`: parameter sweep
- `cookimport/bench/report.py`: aggregate reporting
- `cookimport/bench/packet.py`: iteration packet generation
