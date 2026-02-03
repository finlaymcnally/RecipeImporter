---
summary: "ExecPlan for adding canonical block-based Label Studio tasks and evaluation."
read_when:
  - When extending Label Studio import/export workflows
  - When reviewing canonical block-based golden set design
---

# Add a canonical, block-based Label Studio workflow alongside the existing chunk-based benchmark

This ExecPlan is a living document. The sections `Progress`, `Surprises & Discoveries`, `Decision Log`, and `Outcomes & Retrospective` must be kept up to date as work proceeds.

This plan must be maintained in accordance with `PLANS.md` at the repository root.


## Purpose / Big Picture

After this change, a user can create two complementary “golden sets” using Label Studio:

1) A “pipeline golden set” (existing behavior): label the pipeline’s proposed chunks (structural recipe candidates and atomic lines) to measure boundary quality and parsing correctness.

2) A “canonical markup golden set” (new behavior, based on blocks): label every extracted block (paragraph-ish unit) as Recipe/Tip/Narrative/etc. so you can measure recall (missed recipes/tips) and derive stable, chunker-independent ground truth keyed by `(source_hash, block_index)`.

A user can see this working by running a new import mode that uploads block-level tasks to a separate Label Studio project, labeling a few blocks in the UI, exporting them to JSONL, and running an evaluation command that reports at least:
- how many “gold recipes” exist vs how many pipeline recipes match them (recall),
- how often pipeline recipes are correct vs over/under segmented relative to the gold block ranges (boundary quality),
- and how many blocks were labeled tip/narrative for future tip extraction evaluation.

The key user-visible improvement is: “I can label what’s actually in the book even if the chunker missed it,” while preserving the fast regression loop of the existing chunk-based benchmark.


## Progress

Add timestamps when you mark items done.

- [ ] (YYYY-MM-DD HH:MMZ) Establish baseline: run current `labelstudio-import` and `labelstudio-export` end-to-end and capture artifacts + one exported golden set file for reference.
- [x] (2026-02-02 00:00Z) Implement block-task generation (canonical mode) and a dedicated Label Studio label config for block classification.
- [x] (2026-02-02 00:00Z) Implement export for block annotations (JSONL) and derivation of gold “recipe spans” as block ranges.
- [x] (2026-02-02 00:00Z) Implement evaluation that compares pipeline structural chunks to derived gold block spans (precision/recall + boundary diagnostics).
- [x] (2026-02-02 00:00Z) Add tests for deterministic task IDs, resume/idempotence behavior, and derivation logic on a small synthetic archive.
- [x] (2026-02-02 00:00Z) Update docs/help text to describe the two-project workflow and how to run it.


## Surprises & Discoveries

- Observation: No implementation surprises yet (code changes only; baseline runs not executed).
  Evidence: N/A


## Decision Log

- Decision: Prefer block-based “canonical” labeling (classification per extracted block) rather than span-offset labeling as the primary workflow.
  Rationale: Block indices are stable across chunker changes and avoid brittle character-offset drift when cleaning/normalization changes whitespace. Span-labeling remains optional as a prototype if needed for UX.
  Date/Author: 2026-02-02 / (author)

- Decision: Keep the existing chunk-based benchmark workflow unchanged and add canonical labeling as a parallel mode (new project + new export artifacts), not a replacement.
  Rationale: The current workflow is valuable for quick regression testing of the current pipeline and should remain frictionless.
  Date/Author: 2026-02-02 / (author)

- Decision: Use stable identifiers for canonical tasks: `block_id = urn:cookimport:block:{source_hash}:{block_index}`.
  Rationale: This detaches canonical ground truth from `location.chunk_index` (which can change when chunking strategies change) and makes “gold” portable across pipeline iterations.
  Date/Author: 2026-02-02 / (author)

- Decision: Include `source_hash` in pipeline task payloads and persist `task_scope`/`task_ids` in manifests.
  Rationale: Canonical evaluation needs a stable source identity, and resume behavior must prevent mixing pipeline vs canonical tasks in one project.
  Date/Author: 2026-02-02 / (author)

- Decision: Allow prefix matching on `source_hash` during evaluation to support older pipeline tasks that only stored the short hash inside `chunk_id`.
  Rationale: Keeps canonical evaluation compatible with historical runs while new tasks include full file hashes.
  Date/Author: 2026-02-02 / (author)


## Outcomes & Retrospective

- (2026-02-02) Implemented canonical import/export/eval scaffolding, tests, and docs updates. Remaining: run baseline Label Studio flows and capture artifacts for this plan.


## Context and Orientation

This repository is a Python-based recipe ingestion and normalization pipeline. For unstructured sources (EPUB/PDF/text), the pipeline extracts a linear sequence of `Block` objects (paragraph-ish units) and enriches them with signals (heading/ingredient/time/yield heuristics). The system then proposes higher-level candidates (recipes/tips/topics) and produces structured outputs, with provenance that records file hashes and block indices for traceability.

Label Studio is integrated as an annotation UI to build ground truth datasets for evaluation, not as part of extraction/parsing itself. The current Label Studio integration lives in `cookimport/labelstudio/` and supports importing tasks into a Label Studio project and exporting labeled data as JSONL golden sets.

Key current behaviors you must preserve and build upon:

- `cookimport labelstudio-import <path> --project-name <name> --chunk-level {structural|atomic|both}` uploads tasks to Label Studio for:
  - Structural chunks: recipe-level candidates to judge segmentation/boundaries.
  - Atomic chunks: line-level units to judge parsing correctness (ingredient/instruction line fields).
- Each import run writes artifacts under a timestamped directory similar to:
    data/output/<timestamp>/labelstudio/<book_slug>/
      manifest.json
      extracted_archive.json
      extracted_text.txt
      label_studio_tasks.jsonl
      project.json
      coverage.json

The known limitation of the current workflow is recall: if the chunker fails to propose a recipe at all, there is no task to label as “missed.” The canonical block-based workflow solves this by uploading all blocks (or a deterministic subset) as tasks so missed recipes can still be discovered and labeled.

Terms used in this plan:

- Block: A low-level extracted unit (paragraph/list item/heading) with a stable order and an integer `block_index` within a source.
- Structural chunk: A recipe-candidate unit (spanning multiple blocks) used to evaluate segmentation.
- Atomic chunk: A line-level unit used to evaluate parsing (quantity/unit/item correctness, etc.).
- Pipeline golden set: Labels for structural/atomic chunks produced by the pipeline (fast regression loop).
- Canonical golden set: Labels applied directly to blocks (source-truth loop), from which “gold recipes” can be derived as block ranges independent of the chunker.


## Plan of Work

We will add a parallel “canonical mode” to the Label Studio integration that generates block-level tasks from the existing extraction archive, uploads them to a separate Label Studio project with a dedicated labeling config, and exports the resulting annotations as a canonical JSONL dataset. We will then derive “gold recipe spans” (contiguous block ranges) from these block labels and implement an evaluator that compares pipeline structural chunks to these derived gold spans to compute recall/precision and boundary diagnostics.

This will be implemented additively:
- The existing `--chunk-level` path remains unchanged.
- Canonical mode will be selected via a new, explicit flag (e.g., `--task-scope canonical-blocks`) or via a new subcommand, whichever is less invasive to existing CLI structure. Prefer a new flag on the existing `labelstudio-import` and `labelstudio-export` commands to reduce CLI surface area, but do not overload `--chunk-level` with non-chunk semantics.

We will also add tests that run without a live Label Studio server by testing task JSON generation, stable IDs, derivation logic, and resume/idempotence behavior in pure Python.

Finally, we will update `docs/label-studio/README.md` (and CLI help strings) to describe:
- when to use pipeline golden set vs canonical golden set,
- the recommended two-project setup in Label Studio,
- exact commands to run and what artifacts to expect.


## Milestone 1: Baseline the existing chunk-based workflow (no code changes)

At the end of this milestone, a novice can run the current Label Studio workflow end-to-end and recognize the expected artifacts and exported JSONL format. This creates an anchor so future changes don’t silently break existing behavior.

Work:
- Start Label Studio locally (Docker).
- Run `cookimport labelstudio-import` on a small EPUB/PDF.
- Verify artifacts are written.
- Label a handful of tasks in the UI.
- Run `cookimport labelstudio-export` and verify JSONL output exists.

Result:
- You have a real project in Label Studio with tasks.
- You have exported JSONL golden set files for structural/atomic chunks.
- You have captured a short transcript of commands and the artifact directory listing in `Artifacts and Notes`.

Proof:
- The exported JSONL contains at least one structural chunk record and one atomic chunk record.
- The artifact directory contains `label_studio_tasks.jsonl` and `extracted_archive.json`.


## Milestone 2: Prototyping — add canonical block-task generation and a Label Studio UI config

At the end of this milestone, you can create a new Label Studio project populated with block-level tasks where each task shows one block plus a small amount of surrounding context, and the labeler can classify the block with a single choice (Recipe title / Ingredient line / Instruction line / Tip / Narrative / Other).

Work:
- Add a new label config (XML) for block classification.
- Add code that converts `extracted_archive.json` blocks into Label Studio tasks with stable `block_id`s.
- Add a new “canonical blocks” import mode that:
  - creates/updates a project with the block label config
  - uploads block tasks (idempotently, skipping previously uploaded block_ids when resuming)

What to implement (concrete file edits):

1) Label config
- Create `cookimport/labelstudio/label_config_blocks.py` with a function:
    def build_block_label_config() -> str:
        """Return Label Studio XML config for block classification tasks."""
- The config should:
  - display a header with source and block index (from task data)
  - display context_before, block_text, context_after as pre-wrapped text
  - provide a single-choice set of labels, at minimum:
      RECIPE_TITLE
      INGREDIENT_LINE
      INSTRUCTION_LINE
      TIP
      NARRATIVE
      OTHER
  - include a short instruction header telling labelers to pick the “best” label for the block.

2) Task generation
- Add `cookimport/labelstudio/block_tasks.py` (new) with:
    - a Pydantic model (or simple dataclass) representing the task “data” you send to Label Studio.
    - a function:
        def build_block_tasks(archive: Iterable[ArchiveBlock | dict], source_hash: str, source_file: str, context_window: int) -> list[dict]:
            """Return Label Studio tasks JSON objects for each block, including stable IDs and context."""
    - a helper:
        def load_task_ids_from_jsonl(path: Path, data_key: str) -> set[str]
- Each task should include at least:
    data.block_id: "urn:cookimport:block:{source_hash}:{block_index}"
    data.source_hash
    data.source_file
    data.block_index
    data.block_text
    data.context_before
    data.context_after
  Optional but useful:
    data.signals: a compact summary of block flags (is_heading, starts_with_quantity, etc.) if easily available in the archive.

- Context behavior:
  - context_before: join up to N previous blocks’ text with "\n"
  - context_after: join up to N next blocks’ text with "\n"
  - Use a deterministic join and preserve newlines; avoid trimming that would make UI confusing.

3) CLI integration
- Locate the Typer command that implements `cookimport labelstudio-import`. (Use ripgrep: search for "labelstudio-import" and for Typer command definitions.)
- Add a new option:
    --task-scope [pipeline|canonical-blocks]
  Default should be "pipeline" to preserve existing behavior.
- When task-scope == pipeline:
  - behave exactly as today (structural/atomic/both via --chunk-level)
- When task-scope == canonical-blocks:
  - ignore --chunk-level (or error if provided, but prefer ignoring with a warning printed to console)
  - ensure project uses the block label config
  - generate block tasks from the extracted archive and upload them

4) Resume/idempotence
- Reuse the existing “resume mode” approach (manifest/project.json) to avoid duplicating tasks.
- Implement “already uploaded” detection by reading prior `label_studio_tasks.jsonl` (or manifest chunk IDs) and skipping any task whose block_id is already present.
- Persist `task_scope` + task IDs in `manifest.json` and refuse to resume if the project scope differs.

Promotion criteria for this prototype:
- You can import canonical-block tasks for a small book and see them in Label Studio.
- Rerunning the same command does not duplicate tasks (task count stays the same in Label Studio, and your logs state how many were skipped vs uploaded).


## Milestone 3: Export canonical block annotations and derive gold recipe spans

At the end of this milestone, a user can export canonical block annotations to JSONL and also derive “gold recipe spans” (start_block_index/end_block_index ranges) for evaluation.

Work:
- Extend `cookimport labelstudio-export` to support canonical-block exports, without breaking existing chunk exports.
- Implement derivation logic that groups contiguous blocks into “gold recipes” using a simple, explainable rule set.

What to implement:

1) Export mode
- Add an option to the export command:
    --export-scope [pipeline|canonical-blocks]
  Default "pipeline" preserves current behavior.

- When export-scope == pipeline:
  - behave exactly as today (export labeled chunks as JSONL)

- When export-scope == canonical-blocks:
  - fetch annotations for tasks in the project
  - output two files under the user’s `--output-dir`:
      canonical_block_labels.jsonl
      canonical_gold_spans.jsonl

2) canonical_block_labels.jsonl format
Each line should be a single block label record:
    {
      "block_id": "urn:cookimport:block:...",
      "source_hash": "...",
      "source_file": "...",
      "block_index": 123,
      "label": "TIP",
      "annotator": "...",
      "annotated_at": "..."
    }

3) Derive canonical_gold_spans.jsonl
Define “span” as a contiguous block range with a derived kind. Start with recipes only; tips can be added next.
Implement derivation in `cookimport/labelstudio/canonical.py` so label constants and rules stay centralized.

Recipe derivation rule (simple v1):
- A recipe begins at a block labeled RECIPE_TITLE.
- It includes subsequent blocks labeled INGREDIENT_LINE or INSTRUCTION_LINE until:
  - the next RECIPE_TITLE, or
  - a run of >= K blocks labeled OTHER/NARRATIVE/TIP (choose K=2 for v1 to avoid one stray block ending recipes too early).
- The span record includes:
    {
      "span_id": "urn:cookimport:gold_recipe:{source_hash}:{start}:{end}",
      "source_hash": "...",
      "source_file": "...",
      "start_block_index": ...,
      "end_block_index": ...,
      "title_block_index": ...,
      "notes": { "k_end_run": 2, "rule_version": "v1" }
    }

Make the rule versioned and explicit so you can evolve it without breaking past gold sets.

4) Tests
- Create a small, synthetic “archive” fixture (a list of blocks with indices and text) and a synthetic annotation set (block_index -> label).
- Test that derivation produces expected spans for:
  - two back-to-back recipes
  - a recipe with an interleaved single OTHER block (should still be included or tolerated)
  - a recipe interrupted by a tip block (should end before the tip if K threshold is met)


## Milestone 4: Evaluate pipeline structural chunks against canonical gold spans (recall + boundary diagnostics)

At the end of this milestone, a user can run one command that compares:
- pipeline structural chunks (predicted recipe candidates) vs
- canonical derived gold recipe spans (block ranges)

…and produces a human-readable report plus a machine-readable JSON output.

Work:
- Implement an evaluator that maps each pipeline structural chunk to a block-index range (it already has provenance block indices; locate where that is stored in the task data or export data).
- Compare predicted ranges to gold ranges and compute:
  - recall: fraction of gold recipes matched by at least one predicted recipe
  - precision: fraction of predicted recipes that match a gold recipe
  - boundary quality: for matches, compute overlap and classify as correct/over/under segmented based on thresholds

What to implement:

1) Data inputs
- Predicted structural chunks:
  - Use either:
    a) the existing `manifest.json` / `label_studio_tasks.jsonl` artifacts from a pipeline import run, or
    b) the exported pipeline golden set JSONL if it includes block ranges.
  Prefer using the artifacts already written under `data/output/<timestamp>/labelstudio/<book_slug>/` so evaluation can run without needing Label Studio.

- Gold spans:
  - Use `canonical_gold_spans.jsonl` from Milestone 3.

2) Evaluator module + CLI
- Add `cookimport/labelstudio/eval_canonical.py` with:
    def evaluate_structural_vs_gold(predicted: list[PredSpan], gold: list[GoldSpan]) -> EvalReport

- Add a new CLI command (Typer subcommand), for example:
    cookimport labelstudio-eval canonical-blocks \
      --pred-run data/output/<timestamp>/labelstudio/<book_slug>/ \
      --gold-spans data/golden/<book_slug>/canonical_gold_spans.jsonl \
      --output-dir data/golden/<book_slug>/eval/

- Output:
  - eval_report.json (machine readable)
  - eval_report.md (human readable summary)
  - optionally, a “missed_gold_spans.jsonl” and “false_positive_preds.jsonl” to make debugging easy.

3) Matching rule (v1, simple and explainable)
- Represent each predicted structural chunk as [start_block_index, end_block_index].
- A prediction matches a gold span if Jaccard overlap over blocks >= 0.5 (tunable). For v1, use:
    overlap = |intersection| / |union|
- For each gold span, take the best-overlap prediction as its candidate match.
- A gold span is “recalled” if best overlap >= threshold.
- A predicted span is a “true positive” if it is the best match for some gold span and overlap >= threshold.

Boundary diagnostics:
- If overlap >= threshold and predicted contains gold entirely but is longer: classify as over-segmented.
- If overlap >= threshold and predicted is contained by gold but shorter: classify as under-segmented.
- If start and end indices match exactly: classify as correct.
(These heuristics should be implemented carefully and explained in the report.)

4) Tests
- Unit tests for overlap/matching logic with small integer ranges.
- Golden fixture test using a tiny set of predicted spans and gold spans with known recall/precision.


## Milestone 5: Documentation and UX polish

At the end of this milestone, a novice can follow `docs/label-studio/README.md` to run either workflow, understands why two projects exist, and can troubleshoot common problems.

Work:
- Update `docs/label-studio/README.md`:
  - Add a section “Two golden sets: pipeline vs canonical”
  - Add canonical workflow commands and expected artifacts
  - Add guidance on project naming (e.g., “<Book> Benchmark (pipeline)” vs “<Book> Canonical (blocks)”)
  - Add a short “Gotchas” section:
    - keep canonical projects separate from pipeline projects
    - preserve newlines in displayed text
    - rerun import safely with resume mode

- Update CLI help text for new flags.
- Add a short example transcript in the doc showing:
  - import canonical blocks
  - label a few tasks
  - export canonical labels
  - run evaluation


## Concrete Steps

All commands are intended to be run from the repository root unless otherwise stated.

1) Start Label Studio

    docker run -it -p 8080:8080 heartexlabs/label-studio:latest

In another shell:

    export LABEL_STUDIO_URL=http://localhost:8080
    export LABEL_STUDIO_API_KEY=your_api_key_here

2) Create a small input sample

Place a small book at:

    data/input/sample.epub

If the repo supports limiting work for quicker iteration, set any existing limit env var(s) as appropriate (search docs for “LIMIT” or search code for `C3IMP_LIMIT`).

3) Baseline (pipeline workflow)

    cookimport labelstudio-import data/input/sample.epub \
      --project-name "Sample Benchmark (pipeline)" \
      --chunk-level both

Expected artifacts (paths will include a timestamped folder):

    data/output/<timestamp>/labelstudio/<book_slug>/
      manifest.json
      extracted_archive.json
      label_studio_tasks.jsonl
      project.json
      coverage.json

Then:

    cookimport labelstudio-export \
      --project-name "Sample Benchmark (pipeline)" \
      --output-dir data/golden/sample/pipeline/

Expected:

    data/golden/sample/pipeline/<some>.jsonl

4) Canonical workflow (new)

    cookimport labelstudio-import data/input/sample.epub \
      --project-name "Sample Canonical (blocks)" \
      --task-scope canonical-blocks \
      --context-window 1

In Label Studio UI (http://localhost:8080):
- Open “Sample Canonical (blocks)”
- Label ~20 blocks with a mix of RECIPE_TITLE / INGREDIENT_LINE / INSTRUCTION_LINE / TIP / NARRATIVE / OTHER.

Export:

    cookimport labelstudio-export \
      --project-name "Sample Canonical (blocks)" \
      --export-scope canonical-blocks \
      --output-dir data/golden/sample/canonical/

Expected:

    data/golden/sample/canonical/canonical_block_labels.jsonl
    data/golden/sample/canonical/canonical_gold_spans.jsonl

5) Evaluation (new)

    cookimport labelstudio-eval canonical-blocks \
      --pred-run data/output/<timestamp>/labelstudio/<book_slug>/ \
      --gold-spans data/golden/sample/canonical/canonical_gold_spans.jsonl \
      --output-dir data/golden/sample/eval/

Expected:

    data/golden/sample/eval/eval_report.json
    data/golden/sample/eval/eval_report.md

Example expected report excerpt (illustrative; update with real values once implemented):

    Canonical gold recipes: 12
    Pipeline predicted recipes: 10
    Recall (gold matched): 0.75 (9/12)
    Precision (pred matched): 0.80 (8/10)
    Boundary: correct=5, over=2, under=1
    Missed gold spans written to missed_gold_spans.jsonl


## Validation and Acceptance

A change is accepted when all of the following are true:

1) Existing behavior preserved
- Running the baseline pipeline import/export commands still works and produces the same artifact structure and exported JSONL as before.
- No new flags are required for pipeline mode.

2) Canonical block workflow works end-to-end
- Running `cookimport labelstudio-import ... --task-scope canonical-blocks` creates/updates a Label Studio project using the new block label config and uploads tasks.
- In the UI, each task shows block text and context, and labelers can choose exactly one label.
- Rerunning the same canonical import does not duplicate tasks; logs clearly state “uploaded N, skipped M”.

3) Canonical export produces stable JSONL
- `canonical_block_labels.jsonl` records stable block_id/source_hash/block_index and the chosen label.
- `canonical_gold_spans.jsonl` is produced deterministically from the same annotations.

4) Evaluation produces actionable outputs
- The eval command runs without contacting Label Studio (it reads local artifacts + gold spans).
- It outputs recall/precision numbers and a list of missed gold spans and false positives for debugging.

5) Tests
- Run the project’s test command (likely `pytest` from repo root) and expect all tests to pass.
- New tests added for derivation/matching/resume logic (see `tests/test_labelstudio_canonical.py`) fail before the implementation and pass after.


## Idempotence and Recovery

- Import commands must be safe to rerun:
  - Pipeline mode: preserve existing resume behavior.
  - Canonical blocks mode: detect previously uploaded block_ids and skip them.
- If a run fails midway:
  - The presence of `project.json` and `label_studio_tasks.jsonl` in the output run directory should allow rerunning the same command to complete remaining uploads.
- Avoid destructive operations:
  - Never delete tasks from Label Studio automatically.
  - If schema/config changes require a new project, instruct the user to create a new project name; do not attempt in-place migrations silently.


## Artifacts and Notes

As you implement, paste concise evidence snippets here (indented) so the next contributor can verify behavior quickly:

- Baseline import transcript excerpt:
  Not captured in this implementation (requires live Label Studio).

- Canonical import transcript excerpt:
  Not captured in this implementation (requires live Label Studio).

- Example exported canonical block label line:
  Not captured in this implementation (requires live Label Studio).

- Example derived gold span line:
  Not captured in this implementation (requires live Label Studio).

- Eval report excerpt:
  Not captured in this implementation (unit tests cover overlap logic).


## Interfaces and Dependencies

Label Studio server requirements:
- The user must run a Label Studio server and set:
    LABEL_STUDIO_URL
    LABEL_STUDIO_API_KEY

New CLI flags (final names should be consistent across import/export/eval):
- `cookimport labelstudio-import`:
    --task-scope [pipeline|canonical-blocks]
    --context-window <int> (canonical-blocks only)

- `cookimport labelstudio-export`:
    --export-scope [pipeline|canonical-blocks]

- `cookimport labelstudio-eval`:
    canonical-blocks --pred-run <dir> --gold-spans <path> --output-dir <dir> [--overlap-threshold 0.5]

New/updated modules (expected at end of plan):
- `cookimport/labelstudio/label_config_blocks.py`:
    def build_block_label_config() -> str

- `cookimport/labelstudio/block_tasks.py`:
    def build_block_tasks(archive: Iterable[ArchiveBlock | dict], source_hash: str, source_file: str, context_window: int) -> list[dict]
    def load_task_ids_from_jsonl(path: Path, data_key: str) -> set[str]

- `cookimport/labelstudio/canonical.py`:
    def derive_gold_spans(block_labels, k_end_run: int = 2, rule_version: str = "v1") -> list[dict]

- `cookimport/labelstudio/eval_canonical.py`:
    def evaluate_structural_vs_gold(predicted_spans, gold_spans) -> dict
    (Returns a dict with `report`, `missed_gold`, and `false_positive_preds`.)

- `cookimport/labelstudio/chunking.py`:
    def chunk_records_to_tasks(chunks, source_hash: str | None = None) -> list[dict]

When you revise this plan:
- Update `Progress` to reflect reality.
- Add new decisions to `Decision Log`.
- Capture unexpected behaviors in `Surprises & Discoveries`.
- Add an `Outcomes & Retrospective` entry at milestone completion.
- Add a short note at the bottom describing what changed in the plan and why.

Plan revision note:
- (2026-02-02) Initial plan authored. Primary approach: canonical block classification in Label Studio + derived gold spans + evaluator, while preserving existing chunk-based benchmark path.
- (2026-02-02) Updated progress to reflect completed implementation work, added new helper modules/flags, documented manifest/task scope decisions, and noted missing live Label Studio artifacts.
- (2026-02-02) Documented prefix hash matching for evaluation compatibility and added coverage in tests/decision log.
