---
summary: "CLI and interactive-menu reference, including command surfaces and settings behavior."
read_when:
  - When changing command wiring, defaults, or interactive menu flows
  - When adding a new CLI command or command group
---

# CLI Section Reference

Primary command wiring lives in `cookimport/cli.py`.

## Entry points

- `cookimport/entrypoint.py`: batch-first default behavior
- `cookimport/c3imp_entrypoint.py`: interactive-first behavior
- `cookimport/cli.py`: Typer app, commands, interactive menu handlers, settings

## Command surfaces

- Stage pipeline: `cookimport stage`
- Inspection: `cookimport inspect`
- Label Studio flows: `cookimport labelstudio-*`
- Offline bench suite: `cookimport bench *`
- Metrics: `cookimport perf-report`, `cookimport stats-dashboard`
- Tagging: `cookimport tag-catalog *`, `cookimport tag-recipes *`

## Settings and interaction

- Persistent settings file: `cookimport.json`
- Backspace-based one-level menu navigation details:
  `docs/02-cli/2026-02-11-c3imp-menu-backspace-navigation.md`

## Related stage docs

- Import flow details: `docs/03-ingestion/README.md`
- Output/staging behavior: `docs/05-staging/README.md`
- Labeling/eval workflows: `docs/06-label-studio/README.md`
