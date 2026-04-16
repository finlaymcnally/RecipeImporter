# cookimport

This package provides the local CLI and shared pipeline modules for staging
recipe sources into schema.org Recipe JSON (intermediate) and cookbook3 (final).
Durable orchestration and CLI rules live in `cookimport/CONVENTIONS.md`.
CLI entrypoints live in
`cookimport/cli.py`, core models live in `cookimport/core/`, and staging output
helpers live in `cookimport/staging/`.
CLI entrypoints include `cookimport` plus the short aliases `C3imp` and `C4imp`.
`C3imp 30` preserves the full interactive flow while limiting output to the first
30 recipes. `C4imp` launches the separate `cookimport bitter-recipe` corpus-first
lane for building reviewed row-gold through Label Studio. For non-interactive batch
runs, use `cookimport stage`; for example, `cookimport stage --limit 30` processes
the first 30 recipes from `data/input` to `data/output`.

`cookimport bitter-recipe` is intentionally much smaller than the main product. It
reuses source-row extraction plus Label Studio import/export, writes under
`data/bitter-recipe/`, and treats reviewed `row_gold_labels.jsonl` as the main output.

RecipeCandidate supports optional schema.org Recipe fields like `image`,
`recipeCategory`, `datePublished`, `creditText`, `isBasedOn`, `comment`, and
`aggregateRating`, plus `recipeInstructions` as strings or HowToStep objects.

Run `cookimport inspect <workbook>` to print layout guesses. Run `cookimport stage <folder>`
to scan a folder and write schema.org Recipe JSON under
`data/output/<timestamp>/intermediate drafts/` and cookbook3 under
`data/output/<timestamp>/final drafts/`, plus sections/chunks/tables under the
matching staging folders, raw artifacts under `data/output/<timestamp>/raw/`, and
report JSON files at the run root (`data/output/<timestamp>/<workbook>.excel_import_report.json`).
During `cookimport stage`, the CLI shows a per-worker status panel that refreshes
about every 5 seconds with the latest progress message.
Callback-driven spinners (Label Studio import, benchmark import, bench
run/sweep) now append elapsed seconds after about 10 seconds on the same phase
message so long-running steps remain visibly active. When callback messages
include `X/Y` counters, these spinners also show ETA using average
seconds-per-item throughput.
Live boxed spinner panels now clamp to a terminal-aware max width so long
worker task labels do not stretch the panel across the full terminal.
When stdout is not a real terminal (for example, when output is captured), the
status spinner falls back to plain progress prints on change to avoid log
floods; multi-line dashboard statuses also throttle tick refreshes. Agent-run
environments (for example `CODEX_CI=1`, `CODEX_THREAD_ID`, or
`CLAUDE_CODE_SSE_PORT`) also default to plain progress to avoid spinner-frame
noise in polled PTY logs. Use `COOKIMPORT_PLAIN_PROGRESS=1` to force plain
progress everywhere, or `COOKIMPORT_PLAIN_PROGRESS=0` to keep live spinner
status even in those agent envs.
`C3imp` and `C4imp` both set `COOKIMPORT_PLAIN_PROGRESS=0` by default so their
interactive menu runs keep the animated spinner unless you override it.
Codex-farm `task X/Y` callback messages intentionally omit per-file `active ...`
tails so plain-progress mode only emits meaningful counter/error changes.
Interactive all-method benchmark runs now keep one persistent dashboard-style
spinner that shows the source queue, overall source/config progress, and the
current per-config task line while suppressing per-config benchmark summary
dumps.
Interactive `C3imp`/`cookimport` prompts now use `Esc` for one-level back/cancel
navigation across both menu `select` prompts and typed text/confirm/password prompts.
Interactive Label Studio import is freeform-only (`freeform-spans`) and asks
for freeform segment sizing plus optional AI prelabel settings.
Interactive menus now print short purpose blurbs and include concise per-option
descriptions to make each branch easier to choose without external docs.

Performance can be tuned with:
- `--workers <N>`: Parallelize file processing (default: 7).
- `--ocr-device <auto|cuda|mps|cpu>`: Select OCR hardware acceleration.
- `--ocr-batch-size <N>`: Process N pages per OCR call.
- `--pdf-pages-per-job <N>`: Target pages per PDF job when splitting large PDFs.
- `--epub-spine-items-per-job <N>`: Target spine items per EPUB job when splitting large EPUBs.
- `--pdf-split-workers <N>`: Cap PDF job splitting by worker count (default: 7).
- `--epub-split-workers <N>`: Cap EPUB job splitting by worker count (default: 7).
- `--warm-models`: Pre-load models to reduce per-file latency.

When a run contains only EPUB files, the CLI will automatically raise the worker
pool to `--epub-split-workers` if it is higher than `--workers`, so EPUB imports
default to 6 concurrent workers unless you explicitly lower them.

Large PDFs can be split into page-range jobs when `--workers > 1`, then merged into a
single workbook output with sequential recipe IDs. Large EPUBs can be split into
spine-range jobs with `--epub-spine-items-per-job` and merged the same way.

The text importer treats .docx tables with recognized headers as structured
recipe rows, so Word docs that store recipes in tables retain ingredients and
instructions instead of flattening to plain text.

For text/docx content without explicit "Ingredients" headers, the text importer
can split on "Serves/Yield" lines and infer ingredient vs. instruction blocks
using line-level heuristics.

Parsing overrides can be supplied with `--overrides` or a `<workbook>.overrides.yaml`
sidecar to extend header/tip detection and enable optional spaCy signals.

EPUB segmentation treats all-caps section headers (including single-word chapter
labels) embedded in intro paragraphs or emitted as heading blocks as hard recipe
boundaries to avoid greedy spillover into chapter text.
