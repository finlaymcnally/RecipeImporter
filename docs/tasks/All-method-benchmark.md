---
summary: "ExecPlan for interactive all-method freeform benchmark sweep."
read_when:
  - "When implementing or reviewing all-method benchmark behavior"
  - "When modifying interactive benchmark menu branching"
---

# Add All-method benchmark mode for freeform-gold evaluation

This ExecPlan is a living document. The sections `Progress`, `Surprises & Discoveries`, `Decision Log`, and `Outcomes & Retrospective` must be kept up to date as work proceeds.

PLANS.md is checked into the repo at `docs/PLANS.md`. This document must be maintained in accordance with that file (single fenced `md` block, no nested fences, prose-first, checklists only in `Progress`).

## Purpose / Big Picture

Today, the interactive tool has an “EPUB race” debug workflow that scores extractor output with a heuristic (`score_blocks(...)`) and picks a winner. That is useful for extractor diagnostics, but it is not the “real” benchmark score the project uses for golden sets.

After this change, interactive benchmark evaluation gains an explicit mode submenu:

- **All method benchmark**: for a selected source file that has a **freeform gold export**, generate predictions for **every permutation of configured extraction settings**, then evaluate every run against the same gold using the **same freeform-gold scorer** used by `labelstudio-benchmark` and `labelstudio-eval`. The tool must print the **total number of permutations** before running anything, and it must ask whether to include **Codex Farm** permutations (default **No**).

User-visible proof it works:

- Running `cookimport` (interactive) → “Evaluate predictions vs freeform gold” → “All method benchmark” shows an “N configurations will run” summary and (optionally) a Codex Farm toggle prompt.
- It produces a single output directory containing per-configuration benchmark artifacts plus a top-level summary report that ranks configurations by the same metrics used in normal freeform-gold benchmarking (precision/recall/F1).
- The per-configuration results match running the normal benchmark command once with the same run settings.

## Progress

- [x] (2026-02-23 15:12Z) Located current interactive benchmark wiring and confirmed the old eval-only branch no longer exists in interactive mode.
- [x] (2026-02-23 15:23Z) Extracted shared source/gold resolver (`_resolve_benchmark_gold_and_source`) and reused it in benchmark command + all-method interactive flow.
- [x] (2026-02-23 15:29Z) Implemented method-space permutation builder (`_build_all_method_variants`) with explicit EPUB extractor/tuning axes and non-EPUB fallback.
- [x] (2026-02-23 15:33Z) Implemented all-method orchestrator (`_run_all_method_benchmark`) with `config X/Y` progress, per-config artifacts, and ranked aggregate report JSON/MD.
- [x] (2026-02-23 15:35Z) Added interactive benchmark mode submenu (`single_upload` vs `all_method`) and routed all-method through offline benchmark runs.
- [x] (2026-02-23 15:43Z) Added tests for variant counting, Codex Farm gating fallback, submenu wiring, and all-method aggregate report generation.
- [x] (2026-02-23 15:47Z) Updated CLI/Label Studio/bench docs, conventions, and understandings to reflect the new interactive benchmark contract.

## Surprises & Discoveries

- Observation: Interactive benchmark had already removed the old eval-only chooser, so the plan’s “option 3” assumption was stale.
  Evidence: Existing tests explicitly asserted that `How would you like to evaluate?` should not appear.

- Observation: Recipe Codex Farm permutations cannot be enabled yet because `llm_recipe_pipeline` normalization in both CLI and ingest enforces `off`.
  Evidence: `_normalize_llm_recipe_pipeline(...)` in both `cookimport/cli.py` and `cookimport/labelstudio/ingest.py` rejects non-`off` values with policy errors.

## Decision Log

- Decision: All-method benchmark uses the existing freeform-gold evaluation pipeline (the same logic used by `labelstudio-benchmark` / `labelstudio-eval freeform-spans`) rather than EPUB heuristic scoring.
  Rationale: The user wants “the scoring I use for the golden set” and shared code so future scoring changes apply to both paths.
  Date/Author: 2026-02-23 / ExecPlan author

- Decision: All-method benchmark runs **offline** (no Label Studio upload) by default and does not require `--allow-labelstudio-write`.
  Rationale: The goal is to compare extraction configurations against gold, not to create/upload new labeling tasks. Uploading many permutations would be noisy and expensive.
  Date/Author: 2026-02-23 / ExecPlan author

- Decision: Codex Farm permutations are included only when the user explicitly opts in at runtime (default No). Additionally, keep the existing “policy-locked off” safety by requiring an explicit unlock (environment variable) before actually running any Codex Farm configuration; otherwise, print a clear warning and run without Codex Farm.
  Rationale: The repo currently rejects non-`off` `llm_recipe_pipeline` values; the user wants Codex Farm as an option but explicitly does not want it used by default. A two-step opt-in prevents accidental token spend and preserves the current policy stance.
  Date/Author: 2026-02-23 / ExecPlan author

- Decision: The permutation space is defined in one obvious place in code (a small, well-commented “method space” mapping), and the tool prints the computed total before executing.
  Rationale: The user expects the space to grow and wants an early warning when it becomes exponential.
  Date/Author: 2026-02-23 / ExecPlan author

- Decision: Keep the existing `labelstudio_benchmark` command as the single-run primitive and orchestrate all-method by calling that command in offline mode (`no_upload=True`) per variant.
  Rationale: Reusing the existing command path guarantees scoring and artifact parity with normal benchmark runs while minimizing risky benchmark-logic rewrites.
  Date/Author: 2026-02-23 / implementation pass

- Decision: Because interactive benchmark no longer has eval-only mode, add a two-option benchmark submenu (`single_upload`, `all_method`) instead of resurrecting the old three-option menu.
  Rationale: Matches the current CLI contract and user note that menus had changed since the original plan draft.
  Date/Author: 2026-02-23 / implementation pass

## Outcomes & Retrospective

- Implemented all-method benchmark end-to-end in interactive mode with offline per-config runs, permutation-count/proceed prompts, and aggregate ranked reporting.
- Preserved existing upload benchmark behavior as the default interactive path via a new benchmark-mode submenu.
- Added regression coverage for permutation counts, Codex Farm fallback behavior, submenu routing, and aggregate report generation.
- Remaining future work: if recipe Codex Farm policy unlocks, extend `_build_all_method_variants(...)` to truly multiply Codex permutations instead of warning/falling back.

## Context and Orientation

Key terms (define for a novice):

- **Freeform gold (freeform spans)**: Label Studio export format stored as `exports/freeform_span_labels.jsonl`. It contains labeled spans mapped to touched block indices.
- **Prediction run artifacts**: Generated artifacts used for scoring, notably `label_studio_tasks.jsonl` plus an associated `manifest.json`. These artifacts are produced by `generate_pred_run_artifacts(...)` in `cookimport/labelstudio/ingest.py`.
- **Freeform eval scorer**: The deterministic evaluation that compares predicted labeled ranges (from prediction artifacts) vs gold freeform spans (from gold export). It produces `eval_report.json`, `eval_report.md`, `missed_gold_spans.jsonl`, and `false_positive_preds.jsonl`. The primary metrics used across analytics are `precision`, `recall`, and `f1`.
- **Run settings**: The per-run configuration model in `cookimport/config/run_settings.py` used by both stage and prediction-generation paths. Benchmark prediction manifests include `run_config`, `run_config_hash`, and `run_config_summary`.

Current relevant flows (from docs):

- Interactive benchmark now supports two branches under one benchmark mode submenu:
  - **Upload mode**: one upload+evaluate benchmark run.
  - **All method mode**: offline multi-config benchmark sweep with one aggregate report.
- Eval-only remains a separate command: `cookimport labelstudio-eval --scope freeform-spans`.
- The existing “EPUB extractor race (debug)” uses `score_blocks(...)` (a heuristic). It writes `epub_race_report.json` and prints a summary, but it does not score against gold labels.

Implementation touchpoints you will need to inspect in the working tree:

- `cookimport/cli.py`: interactive menu wiring and Typer command surfaces.
- `cookimport/cli_ui/run_settings_flow.py` and `cookimport/cli_ui/toggle_editor.py`: how interactive benchmark/upload picks run settings today.
- `cookimport/config/run_settings.py`: `RunSettings` fields, summary/hash generation, and any validators (including the Codex Farm policy lock).
- `cookimport/labelstudio/ingest.py`: `generate_pred_run_artifacts(...)` and prediction-run layout/manifest.
- `cookimport/labelstudio/eval_freeform.py`: freeform scoring logic and report rendering.
- `cookimport/analytics/perf_report.py`: if benchmark runs auto-append to CSV, understand the side effects of many permutations.

## Plan of Work

### Milestone 1: Identify and factor the shared “benchmark once” primitive

Goal of this milestone: There is exactly one internal function that performs “generate predictions for a source file under a given `RunSettings` → evaluate vs a given gold spans file → write standard eval artifacts → return the parsed metric summary”.

Work:

1. Locate the implementation of the non-interactive `cookimport labelstudio-benchmark` command and find where it:
   - resolves gold spans path,
   - resolves source file,
   - generates prediction run artifacts (upload vs `--no-upload`),
   - runs freeform eval and writes `eval_report.*` and the misses/FPs.
2. Extract that into a helper, for example in a new module:
   - `cookimport/labelstudio/benchmark_runner.py`
   - or into an existing labelstudio benchmark module if one already exists.
3. Ensure the existing CLI command still behaves exactly the same, just calling the helper once.

Prescriptive interface (adjust names to match repo style, but keep the intent):

- Define `run_freeform_benchmark_once(...)` that accepts:
  - `gold_spans_path: Path`
  - `source_file: Path`
  - `run_settings: RunSettings`
  - `eval_output_dir: Path` (destination where eval artifacts will be written)
  - `processed_output_dir: Path` (destination for stage-style processed outputs if the benchmark run produces them)
  - `no_upload: bool` (must support offline mode; interactive all-method will always pass `True`)
  - `overlap_threshold: float`
  - `force_source_match: bool`
- Return:
  - a small structured result containing:
    - `eval_report_path`
    - `metrics` (precision/recall/f1 plus any other top-level numbers already used)
    - `run_config_hash` and `run_config_summary` (either directly from `RunSettings` or from the pred-run manifest fields)

Acceptance proof:

- Running the existing `cookimport labelstudio-benchmark --no-upload ...` still produces the same output artifacts as before.
- Unit tests that cover benchmark helper behavior (likely `tests/test_labelstudio_benchmark_helpers.py`) continue passing.

### Milestone 2: Implement the extraction-settings permutation space + upfront count

Goal of this milestone: Given a base `RunSettings` and a source file path, you can enumerate all “method variants” you intend to benchmark. You can compute and print the total count before running anything.

Work:

1. Create a “method space” definition in one place, as plain data, with comments explaining how to keep it small.
2. Implement `build_all_method_variants(...)` that:
   - takes `base_settings`, `source_file`, and `include_codex_farm` (bool),
   - returns a list of `MethodVariant` objects that each embed a fully-populated `RunSettings` instance,
   - filters out nonsensical combinations (for example, EPUB-unstructured tuning fields should not multiply configurations for extractors that do not use Unstructured).

Recommended initial “method space” (based on currently documented benchmark flags):

- For `.epub` sources:
  - `epub_extractor`: `unstructured`, `legacy`, `markdown`, `markitdown`
  - Unstructured tuning (applies only when the effective extractor uses Unstructured; do not multiply legacy/markdown/markitdown variants):
    - `epub_unstructured_html_parser_version`: `v1`, `v2`
    - `epub_unstructured_skip_headers_footers`: `false`, `true`
    - `epub_unstructured_preprocess_mode`: `none`, `br_split_v1`, `semantic_v1`
- For `.pdf` sources (only if these settings exist in `RunSettings` and actually affect extraction deterministically):
  - `ocr_device`: start with `auto` only (hardware-specific values can be added later)
  - `ocr_batch_size`: start with the default only (it is primarily performance, not quality)
  - `warm_models`: start with default only
- Codex Farm dimension:
  - If enabled, add a second axis `llm_recipe_pipeline` with values `off` and `codex-farm` (or whatever value the code uses when unlocked).

Codex Farm gating behavior (must be explicit in code and UX):

- Introduce an env var, for example `COOKIMPORT_ALLOW_CODEX_FARM=1`, that unlocks running Codex Farm configurations.
- If the user says “include Codex Farm” but the env var is not set:
  - print: “Codex Farm is policy-locked off; set COOKIMPORT_ALLOW_CODEX_FARM=1 to include it. Continuing without Codex Farm.”
  - proceed with `include_codex_farm=False`.

Upfront count UX:

- Before running any configuration, print:
  - the base method count (without Codex Farm),
  - what the count would be with Codex Farm,
  - and a short list of what dimensions are multiplying (for transparency).
- Then ask:
  - “Include Codex Farm permutations? (default No)”
  - “Proceed with N benchmark runs? (default No)”

Acceptance proof:

- Running the all-method flow in a dry-run mode (or simply printing count before executing) shows stable, correct counting and the Codex Farm prompt appears with default No.

### Milestone 3: Implement all-method benchmark orchestration + aggregate report

Goal of this milestone: Given a list of `MethodVariant`s, run each benchmark sequentially and write a single root folder with per-variant artifacts plus an aggregate summary report ranking results.

Work:

1. Implement an orchestrator function, for example:
   - `run_all_method_benchmark(...)` in a new module like `cookimport/labelstudio/all_method_benchmark.py`.
2. For each variant:
   - Create a stable subdirectory name that is filesystem-safe and human-readable, such as:
     - `config_001_<run_config_hash_prefix>_<short_slug>`
   - Call `run_freeform_benchmark_once(...)` (from Milestone 1) with:
     - `no_upload=True`
     - per-variant `RunSettings`
     - `eval_output_dir=<root>/<variant_dir>`
     - `processed_output_dir=<root>/processed/<variant_dir>` (to avoid polluting `data/output` with dozens of runs)
3. Capture the metric summary for each run and build an aggregate structure.
4. Write:
   - `<root>/all_method_benchmark_report.json`
   - `<root>/all_method_benchmark_report.md`
5. Print a compact console summary at the end:
   - top 3 configs by F1 (and their precision/recall/F1),
   - plus the output root.

Aggregate report content (minimum contract):

- Source identity:
  - `source_file`
  - `gold_spans_path`
- Run list (ordered by ranking):
  - variant slug / directory name
  - `run_config_hash`
  - `run_config_summary`
  - `precision`, `recall`, `f1`
  - paths to per-variant `eval_report.json` (relative path is fine)
- Winner:
  - include the best variant by F1 and its metrics.

Progress display:

- Follow the “known-size loops should emit counters” UX contract:
  - show `config X/Y` while running variants.

Acceptance proof:

- Running all-method benchmark on a real gold+source pair produces:
  - one root directory containing per-variant runs and a top-level report,
  - a terminal summary showing the ranked winners,
  - and per-variant `eval_report.json` files consistent with normal benchmark output.

### Milestone 4: Wire interactive benchmark mode submenu with all-method branch

Goal of this milestone: Interactive benchmark mode selection includes an all-method branch and selecting it runs the new orchestration.

Work:

1. In `cookimport/cli.py`, locate the interactive benchmark flow and insert a benchmark mode submenu after run-settings selection.
2. Add an all-method menu option alongside the existing upload mode option.
3. Route it to a new interactive handler that:
   - selects gold spans export (same as existing benchmark flow),
   - selects source file (same as benchmark flow),
   - asks for `overlap_threshold` and `force_source_match` only if those are already prompted in the normal flow (do not invent new prompts unless required),
   - prints permutation counts and asks about Codex Farm (default No),
   - runs the all-method benchmark orchestrator,
   - then returns to the main menu.

The user-visible benchmark mode snippet should look like:

    ? How would you like to evaluate?
      1) Generate predictions + evaluate (uploads to Label Studio)
      2) All method benchmark (offline, no upload)

Doc updates in the interactive CLI reference (`docs/02-cli/02-cli_README.md`):

- Under “Benchmark vs Freeform Gold Flow”, add a new branch describing:
  - what all-method does,
  - the upfront permutation count prompt,
  - the Codex Farm prompt (default No),
  - and the output report location/filenames.

Optional but recommended clarity change:

- Keep the “EPUB extractor race (debug)” menu item, but update its help text to make clear it is a heuristic scorer and point users to “All method benchmark” for gold-based scoring.

Acceptance proof:

- Running `cookimport` interactive mode shows the new option and successfully executes it.

### Milestone 5: Tests and guardrails

Goal of this milestone: The feature is protected against regressions (menu wiring, permutation counting, and Codex Farm gating).

Work:

1. Add unit tests for the permutation builder:
   - given a base `RunSettings` and a `.epub` source path, assert the expected number of variants (based on your chosen filtering rules).
   - assert that unstructured-only tuning does not multiply non-unstructured extractors.
2. Add a unit test for Codex Farm gating:
   - when `include_codex_farm=True` but env var not set, either:
     - no Codex Farm variants are produced, or
     - the builder raises a clear exception that the interactive caller converts into a warning + fallback.
3. Add a CLI test that ensures the interactive evaluate mode picker includes “All method benchmark”.
   - Follow patterns in `tests/cli/` for menu-choice testing (search for tests that assert menu option text or prompt choices).
4. Ensure existing Label Studio benchmark helper tests pass (especially those around artifact layout and metric parsing).

Acceptance proof:

- `pytest -m smoke` passes.
- Domain tests relevant to Label Studio and CLI pass (at minimum `pytest tests/labelstudio tests/cli` with the repo’s standard markers).

## Concrete Steps

All commands should be run from the repository root.

1. Orient to current implementations:

    . .venv/bin/activate
    rg -n "Evaluate predictions vs freeform gold" cookimport/cli.py
    rg -n "How would you like to evaluate" cookimport/cli.py
    rg -n "labelstudio-benchmark" cookimport/cli.py cookimport/labelstudio -S
    rg -n "generate_pred_run_artifacts" cookimport/labelstudio -S
    rg -n "eval_freeform" cookimport/labelstudio -S

2. Implement Milestone 1 (shared benchmark-once helper), then run focused tests:

    pytest tests/labelstudio -m "labelstudio and not slow"

3. Implement Milestone 2 (variant enumeration + count printing), then run unit tests you added:

    pytest tests/labelstudio -m "labelstudio and not slow"

4. Implement Milestone 3 (orchestrator + aggregate report), then do a manual run with a known gold export:

    cookimport

   Expected interactive behavior includes a line like:

    All method benchmark will run N configurations (Codex Farm excluded).
    With Codex Farm included: M configurations.
    Include Codex Farm? [y/N]:

5. Implement Milestone 4 (menu option wiring) and confirm the user-facing menu:

    CLI Recipe Import Tool
    ...
    ? How would you like to evaluate?
      1) Generate predictions + evaluate (uploads to Label Studio)
      2) All method benchmark (offline, no upload)

6. Run full smoke:

    pytest -m smoke

## Validation and Acceptance

The change is accepted when all of the following are true:

1. Interactive menu presence:

- Run `cookimport` with no subcommand.
- Choose “Evaluate predictions vs freeform gold (re-score or generate)”.
- The benchmark mode picker shows the new option “All method benchmark (offline, no upload)”.

2. Upfront permutation count + Codex Farm prompt:

- Selecting “All method benchmark” shows:
  - how many configurations will be run (without Codex Farm),
  - how many would be run with Codex Farm,
  - and asks “Include Codex Farm?” with default No.

3. Shared scorer correctness:

- Pick one configuration from the all-method run (e.g., `epub_extractor=markdown` with default tuning).
- Run the normal benchmark once with the same settings (offline) and compare:
  - precision/recall/F1 in `eval_report.json` match (or match within the repo’s documented rounding behavior).

4. Artifacts:

- The all-method root output directory contains:
  - `all_method_benchmark_report.json`
  - `all_method_benchmark_report.md`
  - one subdirectory per configuration, each containing:
    - `prediction-run/` (or whatever the normal benchmark uses)
    - `eval_report.json`
    - `eval_report.md`
    - misses/FP JSONLs

5. Tests:

- `pytest -m smoke` passes.
- New tests for the permutation builder and menu wiring pass.

## Idempotence and Recovery

- The all-method benchmark output root must be timestamped (format `YYYY-MM-DD_HH.MM.SS`) so rerunning does not overwrite prior runs by default.
- If a run is interrupted, rerunning the same all-method benchmark should be able to skip already-completed configurations if their `eval_report.json` exists (recommended), or it should offer an explicit overwrite/resume choice at the root level.
- Codex Farm safety:
  - Default behavior never runs Codex Farm.
  - If the user opts in but the unlock env var is missing, the program must continue safely without Codex Farm and print a clear warning.

## Artifacts and Notes

Proposed output layout (exact names can differ, but keep the idea of “one root + many configs + one summary”):

    data/golden/eval-vs-pipeline/2026-02-23_15.04.12/all-method-benchmark/<book_stem>/
      all_method_benchmark_report.json
      all_method_benchmark_report.md
      processed/
        config_001_...
        config_002_...
      config_001_<hash>_<slug>/
        prediction-run/
          label_studio_tasks.jsonl
          manifest.json
        eval_report.json
        eval_report.md
        missed_gold_spans.jsonl
        false_positive_preds.jsonl
      config_002_<hash>_<slug>/
        ...

Terminal summary example (keep it concise):

    All method benchmark complete: 24/24 configs evaluated.
    Best by F1: config_014 (precision=0.71 recall=0.68 f1=0.69) — epub_extractor=markdown
    Report: data/golden/eval-vs-pipeline/<ts>/all-method-benchmark/<book_stem>/all_method_benchmark_report.md

## Interfaces and Dependencies

New or refactored interfaces (names may be adjusted to match existing conventions, but these must exist as stable call points):

1. Shared single-run benchmark helper (Milestone 1)

In `cookimport/labelstudio/benchmark_runner.py` (or the existing benchmark module), define:

- `@dataclass`
  `class FreeformBenchmarkResult:`
    - `eval_output_dir: Path`
    - `eval_report_path: Path`
    - `run_config_hash: str`
    - `run_config_summary: str`
    - `precision: float`
    - `recall: float`
    - `f1: float`
    - `raw_metrics: dict` (full metrics payload as returned by evaluator)

- `def run_freeform_benchmark_once(*, gold_spans_path: Path, source_file: Path, run_settings: RunSettings, eval_output_dir: Path, processed_output_dir: Path, no_upload: bool, overlap_threshold: float, force_source_match: bool) -> FreeformBenchmarkResult:`
  - Must call the same prediction generation and evaluation code paths used by `labelstudio-benchmark`.
  - Must not duplicate scoring logic; it must route through `cookimport/labelstudio/eval_freeform.py`.

2. Method variant enumeration (Milestone 2)

In `cookimport/labelstudio/all_method_benchmark.py` (or similar), define:

- `@dataclass`
  `class MethodVariant:`
    - `slug: str` (filesystem-safe short identifier)
    - `run_settings: RunSettings`
    - `run_config_hash: str`
    - `run_config_summary: str`

- `def build_all_method_variants(*, base_settings: RunSettings, source_file: Path, include_codex_farm: bool) -> list[MethodVariant]:`
  - Must implement the permutation rules and filtering described above.

3. Orchestrator + report writer (Milestone 3)

- `@dataclass`
  `class AllMethodBenchmarkReport:`
    - `source_file: str`
    - `gold_spans_path: str`
    - `variants: list[FreeformBenchmarkResult]` (or a lighter result type)
    - `winner_by_f1: str` (variant slug or hash)
    - `created_at: str` (timestamp)

- `def run_all_method_benchmark(*, gold_spans_path: Path, source_file: Path, base_settings: RunSettings, include_codex_farm: bool, root_output_dir: Path, processed_root_dir: Path, overlap_threshold: float, force_source_match: bool) -> AllMethodBenchmarkReport:`

Dependencies:

- Use existing repo dependencies and Python stdlib only (dataclasses, pathlib, itertools).
- Reuse `RunSettings` for config summary/hash and avoid re-implementing run-config identity logic.

## Plan revision note

Initial version authored 2026-02-23.
Revised 2026-02-23 during implementation to reflect current CLI menu reality (no interactive eval-only branch), shipped architecture, concrete results, and completed milestones.
