# Recipe Import (Excel) Quick Start

This tool reads Excel files and writes RecipeSage JSON-LD outputs plus a per-file report. You do not need to code.

## 1) Put your Excel files here

Copy `.xlsx` files into:
`/home/mcnal/projects/recipeimport/data/input`

## 2) Run the tool

```bash
cd /home/mcnal/projects/recipeimport
. .venv/bin/activate
cookimport
```

The tool will guide you through the rest:

1. Choose what to do (convert files or inspect a single file)
2. Select which file(s) to process
3. Confirm and run

## Where the outputs go

The tool creates a timestamped folder for each run (e.g., `2026-01-21-153000`) inside the output directory.

- **JSON recipes (Draft V1)**: `data/output/<timestamp>/drafts/<workbook>/<sheet>/r<row>.json`
- **Reports**: `data/output/<timestamp>/reports/<workbook>.excel_import_report.json`
- **Mapping files**: `data/output/mappings/<workbook>.mapping.yaml` (when using `inspect`)

## Troubleshooting

If `cookimport` is not found, activate the virtual environment:

```bash
. .venv/bin/activate
```

## Advanced: Manual commands

You can also run commands directly without the interactive menu:

```bash
# Inspect a single file (guesses layout and optionally writes a mapping stub)
cookimport inspect data/input/yourfile.xlsx --write-mapping --out data/output

# Convert all files in a folder into timestamped drafts
cookimport stage data/input --out data/output
```
