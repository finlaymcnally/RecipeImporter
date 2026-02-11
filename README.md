# Recipe Import

This project is now interactive-first.

## Quick Start (Interactive)

```bash
cd /home/mcnal/projects/recipeimport
. .venv/bin/activate
C3imp
```

Optional: limit output during interactive runs:

```bash
C3imp 10
```

`10` means: at most 10 recipes and 10 tips per imported file.

## Non-Interactive CLI (Agent Reference)

Main command:

```bash
cookimport <command> [options]
```

If you need Label Studio commands, set auth first (or pass flags each time):

```bash
export LABEL_STUDIO_URL=http://localhost:8080
export LABEL_STUDIO_API_KEY=<your_token>
```

### Commands

1. `stage` - Run import pipeline directly (no interactive menu)
2. `perf-report` - Summarize run timing/perf
3. `inspect` - Inspect one input file and guessed layout
4. `labelstudio-import` - Create/import labeling tasks
5. `labelstudio-export` - Export labels into JSONL artifacts
6. `labelstudio-eval` - Evaluate predictions vs gold labels
7. `labelstudio-benchmark` - One-shot benchmark flow for freeform labels

---

## `cookimport stage`

Usage:

```bash
cookimport stage [OPTIONS] PATH
```

Arguments:

- `PATH` (required): file or folder containing source files.

Options:

- `--out PATH` (default: `data/output`)
- `--mapping PATH`
- `--overrides PATH`
- `--limit, -n INTEGER` (min 1)
- `--ocr-device TEXT` (default: `auto`; values used by tool: `auto`, `cpu`, `cuda`, `mps`)
- `--ocr-batch-size INTEGER` (min 1, default: `1`)
- `--pdf-pages-per-job INTEGER` (min 1, default: `50`)
- `--epub-spine-items-per-job INTEGER` (min 1, default: `10`)
- `--warm-models`
- `--workers, -w INTEGER` (min 1, default: `7`)
- `--pdf-split-workers INTEGER` (min 1, default: `7`)
- `--epub-split-workers INTEGER` (min 1, default: `7`)

---

## `cookimport perf-report`

Usage:

```bash
cookimport perf-report [OPTIONS]
```

Options:

- `--run-dir PATH`
- `--out-dir PATH` (default: `data/output`)
- `--write-csv` / `--no-csv` (default: `--write-csv`)

---

## `cookimport inspect`

Usage:

```bash
cookimport inspect [OPTIONS] PATH
```

Arguments:

- `PATH` (required): file to inspect.

Options:

- `--out PATH` (default: `data/output`)
- `--write-mapping`

---

## `cookimport labelstudio-import`

Usage:

```bash
cookimport labelstudio-import [OPTIONS] PATH
```

Arguments:

- `PATH` (required): cookbook file to import for labeling.

Options:

- `--output-dir PATH` (default: `data/golden`)
- `--pipeline TEXT` (default: `auto`)
- `--project-name TEXT`
- `--chunk-level TEXT` (default: `both`; expected: `structural`, `atomic`, `both`)
- `--task-scope TEXT` (default: `pipeline`; expected: `pipeline`, `canonical-blocks`, `freeform-spans`)
- `--context-window INTEGER` (min 0, default: `1`)
- `--segment-blocks INTEGER` (min 1, default: `40`)
- `--segment-overlap INTEGER` (min 0, default: `5`)
- `--overwrite` / `--resume` (default: `--resume`)
- `--label-studio-url TEXT`
- `--label-studio-api-key TEXT`
- `--allow-labelstudio-write` (required to upload tasks)
- `--limit, -n INTEGER` (min 1)
- `--sample INTEGER` (min 1)

---

## `cookimport labelstudio-export`

Usage:

```bash
cookimport labelstudio-export [OPTIONS]
```

Options:

- `--project-name TEXT` (required)
- `--output-dir PATH` (default: `data/golden`)
- `--run-dir PATH`
- `--export-scope TEXT` (default: `pipeline`; expected: `pipeline`, `canonical-blocks`, `freeform-spans`)
- `--label-studio-url TEXT`
- `--label-studio-api-key TEXT`

---

## `cookimport labelstudio-eval`

Usage:

```bash
cookimport labelstudio-eval [OPTIONS] SCOPE
```

Arguments:

- `SCOPE` (required): `canonical-blocks` or `freeform-spans`.

Options:

- `--pred-run PATH` (required)
- `--gold-spans PATH` (required)
- `--output-dir PATH` (required)
- `--overlap-threshold FLOAT` (`0.0` to `1.0`, default: `0.5`)

---

## `cookimport labelstudio-benchmark`

Usage:

```bash
cookimport labelstudio-benchmark [OPTIONS]
```

Options:

- `--gold-spans PATH` (prompts if omitted)
- `--source-file PATH` (prompts if omitted)
- `--output-dir PATH` (default: `data/golden`)
- `--eval-output-dir PATH`
- `--overlap-threshold FLOAT` (`0.0` to `1.0`, default: `0.5`)
- `--pipeline TEXT` (default: `auto`)
- `--chunk-level TEXT` (default: `both`; expected: `structural`, `atomic`, `both`)
- `--project-name TEXT`
- `--allow-labelstudio-write` (required to upload prediction tasks)
- `--overwrite` / `--resume` (default: `--resume`)
- `--label-studio-url TEXT`
- `--label-studio-api-key TEXT`
- `--workers INTEGER` (min 1, default: `7`)
- `--pdf-split-workers INTEGER` (min 1, default: `7`)
- `--epub-split-workers INTEGER` (min 1, default: `7`)
- `--pdf-pages-per-job INTEGER` (min 1, default: `50`)
- `--epub-spine-items-per-job INTEGER` (min 1, default: `10`)

---

## CLI Help Shortcuts

Use these to get current help text directly from the installed version:

```bash
cookimport --help
cookimport stage --help
cookimport perf-report --help
cookimport inspect --help
cookimport labelstudio-import --help
cookimport labelstudio-export --help
cookimport labelstudio-eval --help
cookimport labelstudio-benchmark --help
```
