---
summary: "Archived original ExecPlan draft for unifying stage vs benchmark semantics."
read_when:
  - When comparing this archived draft against docs/plans/02-UnifyBenchSemantics.md
---

https://chatgpt.com/c/69933a59-5110-832f-bfda-0a62f6dc298f

# Unify “stage vs benchmark” semantics with clearer naming, shared run manifests, and parity checks

This ExecPlan is a living document. The sections `Progress`, `Surprises & Discoveries`, `Decision Log`, and `Outcomes & Retrospective` must be kept up to date as work proceeds.

This plan must be maintained in accordance with `docs/PLANS.md` from the repository root.

Reference snapshot of the current documented system (architecture + CLI + Label Studio + bench + analytics): :contentReference[oaicite:0]{index=0}


## Purpose / Big Picture

Right now, the system is conceptually sound but easy to misunderstand because the words “import”, “benchmark import/export”, and “benchmark” refer to different layers: (a) generating product outputs (cookbook3), (b) generating labeling tasks for humans in Label Studio, (c) exporting human labels as “gold”, and (d) scoring predictions vs gold.

After this change, a user should be able to:

1) Understand (from CLI names, help text, and folder manifests) which operation they are doing: producing cookbook outputs, producing labeling tasks, exporting gold, or evaluating/benchmarking.

2) Trust that “benchmark predictions” and “regular stage outputs” are based on the same conversion pipeline and configuration (or, if intentionally different, that the difference is explicit and recorded).

3) Re-run evaluation without re-uploading to Label Studio (non-interactive, not only via the interactive menu) so the system supports both “online Label Studio loops” and “offline reproducible benchmarks” without surprising side effects.

You can see it working when:

- Every run folder contains a small `run_manifest.json` that explicitly links inputs, config, and produced artifacts.
- CLI help and interactive menu text no longer use “benchmark import/export” for what is actually “Label Studio task upload” and “Label export”.
- There is an explicit offline “no upload” benchmark path for a single source+gold pair.
- A new parity test (or small suite of tests) proves that stage and benchmark use the same core conversion settings and produce the same source hash / block coordinate system.


## Progress

- [ ] (2026-02-16 ET) Create a new run-manifest model + writer utilities, and write manifests for `cookimport stage`, `labelstudio-import`, `labelstudio-benchmark`, `labelstudio-eval`, and offline `bench` pred runs.
- [ ] (2026-02-16 ET) Add an explicit non-interactive “eval-only / no-upload” pathway for benchmarking a single source against gold (without requiring the interactive menu).
- [ ] (2026-02-16 ET) Rename/retitle interactive menu items and CLI help strings to match the real mental model (tasks vs gold vs eval), while keeping command names backward compatible.
- [ ] (2026-02-16 ET) Add a parity test that fails before / passes after: stage vs pred-run generation agree on source identity + block coordinate space and share the same config snapshot fields.
- [ ] (2026-02-16 ET) Fix the two analytics sharp edges that amplify confusion during iteration: run-dir auto-detect timestamp mismatch and `--out` history path mismatch (so dashboards and perf-report match the actual output root).
- [ ] (2026-02-16 ET) Update docs in the smallest relevant places so the docs match the new CLI semantics and manifest behavior.


## Surprises & Discoveries

(Empty at plan start. As you implement, record unexpected behavior here with short evidence: failing tests, surprising artifact locations, performance regressions, etc.)


## Decision Log

- Decision: Treat “stage outputs” and “benchmark predictions” as different artifact products that must be linked by manifests, not forced to be identical files.
  Rationale: Benchmarks are scored in a span/block coordinate system; stage outputs are normalized cookbook objects. Forcing them to be identical is the wrong abstraction, but ensuring they are derived from the same conversion inputs/config is the right one.
  Date/Author: 2026-02-16 / ExecPlan author

- Decision: Keep existing CLI command names for backward compatibility, but change user-facing menu labels and help strings, and add new explicit flags/aliases for offline benchmarking.
  Rationale: This reduces confusion immediately without breaking existing workflows or scripts.
  Date/Author: 2026-02-16 / ExecPlan author

- Decision: Add `run_manifest.json` as the cross-cutting “source of truth” that ties together (source file, source hash, config knobs, and artifact paths).
  Rationale: This is the simplest reliable way to make runs explainable and reproducible without requiring a database.
  Date/Author: 2026-02-16 / ExecPlan author

- Decision: Fix the known analytics mismatches as part of this effort rather than deferring.
  Rationale: Those mismatches cause misleading dashboards and broken “latest run” behavior, which directly undermines iteration and user trust.
  Date/Author: 2026-02-16 / ExecPlan author


## Outcomes & Retrospective

(Empty at plan start. At the end of each milestone, summarize what changed, what remains, and what you learned.)


## Context and Orientation

This repository is a deterministic-first recipe ingestion pipeline with optional Label Studio integration and an offline bench suite.

There are four relevant “concepts” that currently get conflated in naming:

1) Stage import (product output): `cookimport stage …` converts sources to intermediate schema.org JSON and final cookbook3 outputs, plus tips/chunks/raw artifacts and a per-file report JSON.

2) Label Studio task generation (human labeling): `cookimport labelstudio-import …` converts a source and generates Label Studio tasks (pipeline chunks, canonical blocks, or freeform segments), writes task artifacts locally, and optionally uploads tasks to Label Studio (write-consent gated).

3) Label export (gold creation): `cookimport labelstudio-export …` pulls completed annotations from Label Studio and shapes them into golden-set JSONL artifacts (including freeform spans for benchmark scoring).

4) Evaluation / benchmarking (scoring): evaluation compares predicted labeled ranges (from task artifacts) vs gold spans (from export artifacts) and writes a report. The “benchmark” command is currently a convenience wrapper that also generates/ uploads predictions first in the CLI flow.

Key modules (repository-relative paths) that a novice should locate immediately:

- `cookimport/cli.py`: Typer CLI commands and interactive menu wiring.
- `cookimport/cli_worker.py`: worker-side stage execution and split job execution.
- `cookimport/staging/writer.py`: canonical output writing (intermediate, final drafts, tips, chunks, raw artifacts, report JSON).
- `cookimport/labelstudio/ingest.py`: task generation + prediction-run artifacts + optional upload; split merge reindexing for block indices.
- `cookimport/labelstudio/export.py`: export pulling and golden JSONL shaping.
- `cookimport/labelstudio/eval_freeform.py` and `cookimport/labelstudio/eval_canonical.py`: scoring logic and report writing.
- `cookimport/bench/*`: offline benchmark suite and pred-run generation.
- `cookimport/analytics/perf_report.py`: perf-report behavior and history CSV append.
- `cookimport/analytics/dashboard_collect.py`: dashboard scan and aggregation.

Important invariants to preserve (do not regress these):

- Determinism first: core pipeline should not require an LLM to function.
- Split-job behavior must preserve a single global block coordinate space (reindexing / rebasing is required).
- Label Studio writes remain explicitly gated in non-interactive flows (a user must opt in).
- Existing output folder structure is relied on by scripts/tests; avoid breaking changes unless you provide compatibility shims and update tests/docs together.


## Plan of Work

### Milestone 1: Introduce a run manifest that links stage, task-generation, gold export, and eval artifacts

At the end of this milestone, every run-producing command writes a `run_manifest.json` at its run root. The manifest is small, human-readable, stable, and includes explicit pointers to key artifacts.

What will exist that didn’t before:

- A new Pydantic model describing `RunManifest` (or similarly named) plus a helper to write it atomically.
- `cookimport stage` run directory contains `run_manifest.json`.
- `cookimport labelstudio-import` run directory contains `run_manifest.json`.
- `cookimport labelstudio-eval` output directory contains `run_manifest.json`.
- `cookimport labelstudio-benchmark` eval directory contains `run_manifest.json` that links:
  - the prediction run directory (often under `prediction-run/`)
  - the processed output run directory (if written)
  - the gold spans path used
  - the eval report paths produced

Commands to run and what to observe:

- From repo root:

    source .venv/bin/activate
    cookimport stage data/input/<a small fixture file> --out /tmp/cookimport_out

  Expect:
  - A new timestamped run directory under `/tmp/cookimport_out/…/`
  - `run_manifest.json` exists at that run root, containing:
    - run_kind = "stage"
    - source_path and source_hash (or source identity fields)
    - run_config snapshot (workers/ocr/split knobs)
    - pointers to per-file report JSON and output subfolders

Acceptance:

- Manifests are created without changing existing artifact paths.
- Manifest writing is best-effort but not silent: if writing fails, the command should warn clearly (and tests should cover expected behavior in a temp dir).


### Milestone 2: Make “benchmark without upload” a first-class, non-interactive workflow

At the end of this milestone, a user can run a single-file benchmark comparison (predictions vs freeform gold) entirely offline, without needing the interactive menu and without uploading anything to Label Studio.

What will exist that didn’t before:

- A CLI flag or subcommand that triggers “pred-run generation + eval” with no upload side effects.
- A clear name in help text that communicates “offline” vs “upload”.

Recommended design (pick one and implement fully):

Option A (minimal change): extend `cookimport labelstudio-benchmark` with a flag

- Add `--no-upload` (default false).
- When `--no-upload` is set:
  - still generates prediction-run artifacts locally
  - does not call Label Studio APIs
  - runs eval and writes eval artifacts
  - still honors `--allow-labelstudio-write` only when upload is requested

Option B (cleaner mental model): add a new command alias dedicated to offline benchmarking

- Add `cookimport benchmark` (or `cookimport eval-freeform`) as a new Typer command.
- Internally call the same `generate_pred_run_artifacts` + eval functions used by bench suite.

The milestone is complete when:

- The offline path is usable from the CLI with no Label Studio credentials present.
- The output directory contains `eval_report.json`, `eval_report.md`, and a `run_manifest.json` that records:
  - gold spans path used
  - pred-run artifact directory used
  - overlap threshold and source matching settings

Commands to run and what to observe:

- From repo root (with a known gold export path):

    source .venv/bin/activate
    cookimport labelstudio-benchmark \
      --gold-spans data/golden/<project_slug>/exports/freeform_span_labels.jsonl \
      --source-file data/input/<matching source> \
      --no-upload \
      --eval-output-dir /tmp/cookimport_eval

  Expect:
  - No network calls; no need for `LABEL_STUDIO_URL` or `LABEL_STUDIO_API_KEY`
  - `/tmp/cookimport_eval/` contains eval report artifacts and a manifest


### Milestone 3: Fix the naming confusion in the interactive menu and help text without breaking compatibility

At the end of this milestone, the interactive menu and help text teach the correct mental model:

- “Stage / Import” = produce cookbook outputs.
- “Label Studio task upload” = generate tasks for humans to label (gold creation workflow).
- “Label export” = pull gold labels out of Label Studio.
- “Evaluate / Benchmark” = compare predictions vs gold; upload is optional and explicit.

What will exist that didn’t before:

- Updated interactive menu labels in `cookimport/cli.py` such that:
  - “Label Studio benchmark import” is renamed to something like “Label Studio: create labeling tasks (upload)”.
  - “Label Studio benchmark export” is renamed to “Label Studio: export completed labels (gold)”.
  - “Benchmark vs freeform gold” is renamed to “Evaluate predictions vs gold (freeform)” or similar.
- CLI `--help` strings updated to match.

Constraints:

- Keep command names (`labelstudio-import`, `labelstudio-export`, `labelstudio-benchmark`, `labelstudio-eval`) for now, to avoid breaking scripts.
- If you introduce new alias commands, document them and add tests, but do not remove old ones in this plan.

Acceptance:

- A novice reading `cookimport --help` and using the interactive menu understands what each option does and whether it uploads.
- Where upload can happen, the UI text must explicitly say “uploads to Label Studio” and mention write-consent gating.


### Milestone 4: Add an automated parity test that protects “stage vs benchmark alignment” at the right abstraction layer

This milestone is specifically about your original worry: “if benchmark and import aren’t the same, benchmarks won’t line up.”

The correct target is not “identical output files,” but:

- same source identity (hash / stable IDs)
- same block coordinate space for span-based evaluation
- same config knobs being applied (or explicitly recorded differences)

What will exist that didn’t before:

- A test that uses a small fixture source file (ideally already in `tests/fixtures/` or added as a tiny new one) and runs:
  - a stage conversion
  - a pred-run generation (the same one used by benchmark/bench)
- The test asserts:
  - both runs agree on source hash
  - pred-run manifest references the same source file
  - the block index / segment coordinate system is stable across both when generated with the same split/segment settings
  - the config snapshot recorded in `run_manifest.json` contains the same key knobs (workers, ocr device, epub extractor, split sizes, segment blocks/overlap) and that defaults are explicit

Implementation guidance:

- Prefer testing internal functions over shelling out to CLI if the repo already has patterns for this (many existing tests do).
- If you must use CLI subprocess calls, keep it deterministic and run in a temporary directory.

Fail-before / pass-after requirement:

- Before adding manifests and offline benchmark mode, this test should fail (for example: missing manifest, or missing config parity fields).
- After implementing the changes, it should pass and become a regression guard.


### Milestone 5: Fix the two analytics sharp edges that undermine iteration trust

This milestone is intentionally limited to the two known mismatches that are most confusing during iteration.

What will exist that didn’t before:

- `cookimport perf-report` can auto-detect the latest run directory using the current timestamp folder format (`YYYY-MM-DD_HH.MM.SS`).
- When a user stages to a custom output root (`cookimport stage … --out X`), the history CSV append targets `X/.history/performance_history.csv`, not the default root.

Acceptance checks:

- From repo root:

    source .venv/bin/activate
    rm -rf /tmp/cookimport_out
    cookimport stage data/input/<small fixture> --out /tmp/cookimport_out
    cookimport perf-report --out-dir /tmp/cookimport_out

  Expect:
  - perf-report finds the latest run without needing `--run-dir`
  - history CSV exists under `/tmp/cookimport_out/.history/performance_history.csv`

Also ensure `cookimport stats-dashboard --output-root /tmp/cookimport_out` shows the new run’s records without relying on default `data/output`.


### Milestone 6: Documentation updates (minimal but sufficient)

Update only the docs that become incorrect due to the changes above. Do not rewrite everything.

Minimum doc edits expected:

- `docs/02-cli/02-cli_README.md`: update the interactive menu wording and describe the new offline benchmark flag/alias.
- `docs/06-label-studio/06-label-studio_README.md`: clarify the offline benchmark path and add a short explanation of manifests.
- `docs/07-bench/07-bench_README.md`: ensure the distinction between stage outputs vs scored artifacts is still accurate, but mention that offline single-case benchmarking is now available outside the suite runner.
- If you add new manifest fields, update the relevant section readmes where run artifacts are described.

Acceptance:

- After docs edits, the docs match reality when you run `cookimport --help` and the referenced commands.


## Concrete Steps

1) Create a new module for run manifests.

- Create `cookimport/runs/manifest.py` (or `cookimport/core/run_manifest.py` if that fits the existing repo layout better).
- Define a Pydantic v2 model with fields that are stable and intentionally small. Recommended fields:

  - `schema_version`: integer (start at 1)
  - `run_kind`: string enum-like (examples: `stage`, `labelstudio_import`, `labelstudio_export`, `labelstudio_eval`, `labelstudio_benchmark`, `bench_pred_run`)
  - `run_id`: string (the folder name, usually timestamp-based)
  - `created_at`: ISO timestamp string
  - `source`: object with:
    - `path`: repo-relative or absolute path
    - `source_hash`: string if available
    - `importer_name`: string if known
  - `run_config`: object containing the key knobs relevant to reproducibility:
    - workers, split worker counts, split sizes, ocr settings, epub extractor, segment sizing, overlap threshold, force_source_match, mapping/overrides paths
  - `artifacts`: object mapping semantic names to relative paths (for example `final_drafts_dir`, `pred_tasks_jsonl`, `gold_spans_jsonl`, `eval_report_json`, `processed_output_run_dir`)
  - `notes`: optional free text

- Add `write_run_manifest(run_root: Path, manifest: RunManifest) -> None` that writes atomically:
  - write to `run_manifest.json.tmp`, then rename to `run_manifest.json`

2) Integrate manifest writing into each relevant command.

- In `cookimport/cli.py`:
  - In the `stage` command, after the run directory is created and once outputs are successfully written, create and write the manifest.
  - Ensure the manifest points to the per-file report JSON (or multiple report JSONs if stage processes a folder). If multiple, include an array under artifacts (for example `reports`).

- In `cookimport/labelstudio/ingest.py`:
  - When creating a labelstudio-import run directory under the golden root, write a manifest that points to:
    - `label_studio_tasks.jsonl`
    - `manifest.json` (existing ingest manifest)
    - `coverage.json`
    - `extracted_archive.json`
    - `extracted_text.txt`

- In `cookimport/labelstudio/export.py`:
  - When writing exports, create (or update) a `run_manifest.json` in the export destination that records:
    - project name / project id (if available)
    - export scope
    - key output JSONLs produced

- In `cookimport/labelstudio/eval_*`:
  - After writing eval artifacts, write a manifest that points to:
    - `pred_run` path used
    - `gold_spans` path used
    - `eval_report.json` and `eval_report.md`
    - `missed_gold_spans.jsonl` and `false_positive_preds.jsonl`

3) Add offline benchmark mode.

- If implementing `--no-upload` on `labelstudio-benchmark`:
  - Ensure the code path that triggers upload is strictly behind:
    - explicit `--allow-labelstudio-write` AND `--no-upload` is false
  - In offline mode, do not resolve Label Studio credentials and do not import/upload.
  - Write the same evaluation artifacts as the normal benchmark.

- Update the interactive benchmark flow text to reflect:
  - upload vs eval-only vs offline/no-upload clearly

4) Fix analytics mismatches.

- In `cookimport/analytics/perf_report.py`:
  - Update run directory resolution logic to match the actual timestamp folder format used by stage.
  - Add a test for `resolve_run_dir` that creates a temp output root with a folder named like `2026-02-16_12.34.56` and asserts it’s discoverable.

- In `cookimport/cli.py` stage end-of-run history append:
  - Ensure the history path is computed from the actual `--out` root passed to stage, not from a global default constant.
  - Add or update tests in `tests/test_cli_output_structure.py` or a new test to assert history CSV ends up under the chosen output root.

5) Update naming strings and docs.

- Adjust menu labels in interactive mode in `cookimport/cli.py`.
- Adjust Typer `help=` strings for relevant commands and options.
- Update the three docs readmes listed in Milestone 6.

Throughout, keep diffs minimal and avoid drive-by refactors. If you discover significant structural duplication, record it in `Surprises & Discoveries` and either:
- do a small contained refactor with tests, or
- open a follow-up task plan (out of scope for this ExecPlan).


## Validation and Acceptance

Run tests (from repo root):

    source .venv/bin/activate
    pytest -q

If the suite is large, run a focused subset first (then full suite before finalizing):

    source .venv/bin/activate
    pytest -q \
      tests/test_labelstudio_benchmark_helpers.py \
      tests/test_stats_dashboard.py \
      tests/test_bench.py \
      tests/test_cli_output_structure.py

Manual acceptance scenarios (repo root):

1) Stage manifest + custom out root:

    source .venv/bin/activate
    rm -rf /tmp/cookimport_out
    cookimport stage data/input/<small fixture> --out /tmp/cookimport_out

  Verify:
  - `/tmp/cookimport_out/<timestamp>/run_manifest.json` exists
  - `/tmp/cookimport_out/.history/performance_history.csv` exists and contains a row for this run

2) Offline benchmark run:

    source .venv/bin/activate
    rm -rf /tmp/cookimport_eval
    cookimport labelstudio-benchmark \
      --gold-spans data/golden/<project_slug>/exports/freeform_span_labels.jsonl \
      --source-file data/input/<matching source> \
      --no-upload \
      --eval-output-dir /tmp/cookimport_eval

  Verify:
  - `/tmp/cookimport_eval/eval_report.json` and `/tmp/cookimport_eval/eval_report.md` exist
  - `/tmp/cookimport_eval/run_manifest.json` exists and records gold path + pred-run path + settings

3) CLI/menu naming sanity:

    source .venv/bin/activate
    cookimport

  Verify:
  - The interactive menu options communicate “create labeling tasks” vs “export labels” vs “evaluate” clearly.
  - Any option that uploads says so explicitly.

Acceptance criteria summary:

- The new manifest exists for run-producing commands and is correct enough to debug “what happened in this run” without reading code.
- Offline benchmarking is possible non-interactively, with no Label Studio credentials.
- The system still supports the existing Label Studio upload-first workflow when consent is explicitly granted.
- Analytics tools (perf-report, stats-dashboard) correctly follow the chosen output root and find runs with the real timestamp format.
- At least one new test fails before these changes and passes after, proving the new behavior.


## Idempotence and Recovery

- Manifest writing must be idempotent: re-running a command should overwrite the manifest for that run directory (or write a new run directory), not accumulate conflicting files.
- Offline benchmark runs should never modify Label Studio state, so they are safe to run repeatedly.
- If a user accidentally runs an upload path, the existing `--allow-labelstudio-write` gate should continue to prevent side effects unless explicitly enabled.

If a change breaks backward compatibility unexpectedly:

- Roll back by:
  - removing the new flags/aliases (keep manifests if harmless), or
  - restoring old help/menu strings
- Ensure tests and docs revert with the behavior.


## Artifacts and Notes

Expected manifest example (illustrative; do not treat field names as mandatory if you choose better ones):

    {
      "schema_version": 1,
      "run_kind": "labelstudio_benchmark",
      "run_id": "2026-02-16_14.03.22",
      "created_at": "2026-02-16T14:03:22-05:00",
      "source": {
        "path": "data/input/book.epub",
        "source_hash": "…",
        "importer_name": "epub"
      },
      "run_config": {
        "epub_extractor": "unstructured",
        "workers": 7,
        "segment_blocks": 40,
        "segment_overlap": 5,
        "overlap_threshold": 0.5,
        "force_source_match": false,
        "upload": false
      },
      "artifacts": {
        "pred_run_dir": "prediction-run/",
        "pred_tasks": "prediction-run/label_studio_tasks.jsonl",
        "gold_spans": "…/exports/freeform_span_labels.jsonl",
        "eval_report_json": "eval_report.json",
        "eval_report_md": "eval_report.md"
      }
    }

This should make it immediately obvious (to you and to future contributors) why “benchmark” output differs from “stage” output while still proving they are aligned at the correct abstraction layer (source identity + coordinate space + config).


## Interfaces and Dependencies

New internal interfaces introduced by this plan should be stable and intentionally small.

In `cookimport/runs/manifest.py` (or chosen path), define:

- `class RunManifest(BaseModel): ...` (Pydantic v2)
- `def write_run_manifest(run_root: Path, manifest: RunManifest) -> None`
- `def load_run_manifest(path: Path) -> RunManifest` (optional but recommended for tests and future tooling)

In `cookimport/cli.py` and Label Studio modules, ensure each run-producing flow has access to:

- the run root directory (Path)
- the effective configuration values (not Typer OptionInfo placeholders)
- source identity (path + hash where available)

No new external dependencies are required beyond existing ones (Typer, Pydantic, standard library). If you need git commit hashes, prefer a best-effort approach (read from environment or `git rev-parse` if available) and keep it optional so the tool works outside a git checkout.

Plan revision notes:

- None yet (initial version).
