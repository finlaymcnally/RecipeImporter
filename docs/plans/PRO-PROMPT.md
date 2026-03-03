# Fix CodexFarm prelabel accuracy and benchmark metrics for canonical line labels

This ExecPlan is a living document. The sections `Progress`, `Surprises & Discoveries`, `Decision Log`, and `Outcomes & Retrospective` must be kept up to date as work proceeds.

This repository has a `PLANS.md` at the repo root. This ExecPlan must be maintained in accordance with `PLANS.md` (format rules, living sections, and milestone verification).


## Purpose / Big Picture

Today, enabling CodexFarm (`llm_recipe_pipeline=codex-farm-3pass-v1`) does not reliably improve the canonical “one label per line” benchmark, and parts of the benchmark report are misleading (for example `HOWTO_SECTION` appears as zero-count even when the sampled correct lines clearly include it). After this change, you will be able to run the same `cookimport labelstudio-benchmark` workflow and see:

1) correct per-label counts (including `HOWTO_SECTION`) and a confusion matrix that matches reality, and  
2) a new CodexFarm pipeline that is explicitly optimized for the benchmark contract (canonical line labeling), with prompt logs saved in run artifacts, and with materially improved recall on `INSTRUCTION_LINE` and a dramatic reduction in over-predicting `KNOWLEDGE`.

You will “see it working” by running the benchmark against an existing golden dataset (for example the same SeaAndSmokeCUTDOWN run used in the exported package) and observing a higher overall line accuracy / macro F1 plus sensible per-label totals.


## Progress

- [x] (2026-03-03 00:00Z) Wrote initial ExecPlan based on observed benchmark artifacts and current repo architecture summary.
- [ ] (2026-03-03 00:00Z) Reproduce the current benchmark locally and confirm the evaluation bug (HOWTO_SECTION totals incorrectly reported as 0).
- [ ] (2026-03-03 00:00Z) Fix the benchmark metric computation so per-label metrics and confusion matrices include all line labels (especially HOWTO_SECTION).
- [ ] (2026-03-03 00:00Z) Add regression tests that fail before the metrics fix and pass after.
- [ ] (2026-03-03 00:00Z) Implement a new CodexFarm pipeline that produces canonical line labels directly (deterministic-first + LLM fallback), with strict output validation and prompt logging.
- [ ] (2026-03-03 00:00Z) Wire the new pipeline into CLI selection (`llm_recipe_pipeline`) and ensure it is exercised by `labelstudio-benchmark`.
- [ ] (2026-03-03 00:00Z) Add regression tests for the new line-label pipeline on small synthetic fixtures that encode the failure modes (instruction vs knowledge; headings like “FOR THE …”; single-word ingredients; yield lines).
- [ ] (2026-03-03 00:00Z) Run end-to-end benchmark(s) on at least one real golden dataset and record “before vs after” metrics in the repo (as a short artifact excerpt and/or a committed test fixture).
- [ ] (2026-03-03 00:00Z) Document the new pipeline and how to debug it (where prompt logs are stored, what to grep, how to reproduce).


## Surprises & Discoveries

- Observation: The current evaluation report shows `HOWTO_SECTION` as having `gold_total=0` and `pred_total=0`, even though sampled “correct label lines” include multiple lines where `gold_label` and `pred_label` are `HOWTO_SECTION`. This strongly suggests a bug or an unintended label-filter list in the per-label metric computation (not merely model performance).
  Evidence (from exported `need_to_know_summary` excerpts): per-label metrics include an entry for HOWTO_SECTION with all zeros, while sampled correct lines include entries like `gold_label: HOWTO_SECTION, pred_label: HOWTO_SECTION`.

- Observation: In the CodexFarm run on SeaAndSmokeCUTDOWN, `INSTRUCTION_LINE` recall is extremely low because a large share of instruction lines are predicted as `KNOWLEDGE` (e.g., the top confusion is `INSTRUCTION_LINE -> KNOWLEDGE`, count ~155). At the same time, `KNOWLEDGE` is massively over-predicted (predicted total ~259 vs gold total ~9). This matches the “KNOWLEDGE catch-all bucket” failure mode discussed earlier.

- Observation: The exported benchmark package does not always contain a prompt log artifact (`codexfarm_prompt_log.dedup.txt`). That makes prompt iteration slower and forces post-hoc inference from confusion matrices. Logging needs to be part of the pipeline’s contract, not “best effort.”


## Decision Log

- Decision: Treat the benchmark as a line-structure classification problem, not a schema-extraction problem, and implement a dedicated line-label pipeline (`codex-farm-line-label-v1`) rather than trying to tune the existing 3-pass schema pipeline into correctness.
  Rationale: The benchmark is scored at canonical line granularity. Multi-pass schema extraction can be useful for recipe JSON, but it is a poor fit for line-label scoring and makes debugging harder. A direct line-labeler is easier to validate, test, and iterate.
  Date/Author: 2026-03-03 / assistant (GPT-5.2 Pro)

- Decision: Make `KNOWLEDGE` an explicit “last resort” label in the prompt and enforce it via deterministic rules (for example: never label an imperative sentence as KNOWLEDGE; never label a quantity/unit line as KNOWLEDGE).
  Rationale: Gold `KNOWLEDGE` lines appear to be rare. Over-predicting this label destroys instruction recall and harms accuracy. It is safer to bias away from KNOWLEDGE unless strong signals exist.
  Date/Author: 2026-03-03 / assistant (GPT-5.2 Pro)

- Decision: Fix the evaluation label accounting first, before optimizing the model pipeline.
  Rationale: If metrics are miscounting labels (HOWTO_SECTION=0), you cannot trust deltas. Fixing evaluation first makes subsequent improvements measurable.
  Date/Author: 2026-03-03 / assistant (GPT-5.2 Pro)


## Outcomes & Retrospective

(Write after each milestone and at completion.)

- Intended end state: `labelstudio-benchmark` reports correct per-label totals for all labels present in gold/pred, including `HOWTO_SECTION`, and the new line-label CodexFarm pipeline produces materially higher instruction recall and lower knowledge false positives on at least one real golden dataset.
- Known open questions to resolve during implementation: where exactly the current eval code filters labels; where the `llm_recipe_pipeline` dispatch table lives; whether existing Label Studio “freeform-only” constraints change how predictions must be encoded for line labels.


## Context and Orientation

This repo is a deterministic-first importer + staging pipeline called `cookimport`. It supports importing recipes from formats like EPUB/PDF/DOCX/etc and can produce Label Studio artifacts for annotation and evaluation. The key user-facing command surface is the Typer CLI in `cookimport/cli.py`, which exposes commands including `labelstudio-import`, `labelstudio-eval`, and `labelstudio-benchmark`.

Important: current operational LLM usage is concentrated in Label Studio prelabel flows via a local Codex CLI invocation (`codex exec -`) implemented in `cookimport/labelstudio/prelabel.py`. The benchmark artifacts in the exported package indicate a configuration knob `llm_recipe_pipeline` with values like `off` and `codex-farm-3pass-v1`.

The benchmark output being discussed is “Canonical Text Evaluation,” which compares predicted labels vs gold labels at canonical line granularity and emits:
- overall line accuracy,
- macro F1 (excluding OTHER),
- per-label precision/recall/F1,
- top confusions (confusion matrix),
- sampled correct/wrong lines and blocks.

The observed issues fall into two buckets:

1) Evaluation correctness issues: label totals and confusion reporting appear inconsistent (HOWTO_SECTION reported as zero even when present in sampled lines).  
2) Pipeline quality issues: CodexFarm predicts far too many KNOWLEDGE labels, crushing INSTRUCTION_LINE recall, and likely uses prompts not aligned to “structural role labeling.”

This plan fixes both.


## Plan of Work

Milestone 1 fixes the benchmark evaluation accounting so metrics are trustworthy. This is a code change inside the labelstudio evaluation implementation. You will add a targeted unit test that reproduces the bug with a tiny synthetic gold/pred dataset containing `HOWTO_SECTION` labels.

Milestone 2 introduces a new CodexFarm pipeline dedicated to line labels (`codex-farm-line-label-v1`). It will:
- operate on canonical lines (the same unit the benchmark scores),
- classify using deterministic heuristics first for high-confidence patterns,
- use the LLM only for ambiguous lines, with a prompt that enforces strict label precedence and bans common failure modes,
- validate and normalize outputs strictly (no free-form “warnings”),
- write prompt/response logs to run artifacts so future debugging is fast.

Milestone 3 wires the pipeline into CLI selection and ensures `labelstudio-benchmark` can run it. It then adds regression tests for the pipeline using synthetic fixtures that encode the known confusing cases.

Milestone 4 runs at least one real benchmark end-to-end and records the “before vs after” metrics (as a short excerpt in the plan and optionally as a committed golden fixture if licensing permits).


## Milestones


### Milestone 1: Make benchmark per-label metrics and confusion matrices count all labels correctly

At the end of this milestone, running `cookimport labelstudio-benchmark` (or the underlying eval code) on a dataset that includes `HOWTO_SECTION` will report a non-zero `gold_total` for that label, and the confusion matrix rows/columns will include it. A new unit test will fail on the current code and pass after the fix.

Work:

1) Locate the evaluation implementation.

   From the repo root, run:

     rg -n "per_label_metrics|top_confusions|macro_f1|Canonical Text Evaluation" cookimport

   Also search for the label string:

     rg -n "HOWTO_SECTION|RECIPE_TITLE|INSTRUCTION_LINE|KNOWLEDGE" cookimport

   You are looking for the code that:
   - iterates over gold/pred labels,
   - builds a confusion matrix,
   - and derives per-label totals.

2) Identify how the label set is chosen.

   The likely bug pattern is:
   - overall accuracy is computed from raw line comparisons,
   - but per-label metrics are computed from a restricted “label allowlist,” and HOWTO_SECTION is missing from that allowlist (or is being mapped away).

   Fix the code so per-label metrics are computed over the union of:
   - labels present in gold primary labels,
   - labels present in predicted labels,
   - and labels declared in the canonical label enum (if one exists),
   with a stable ordering.

   If the code intentionally excludes some labels from metrics, make that explicit:
   - rename the metric to “scored_label_metrics,”
   - and add a second metric block “all_label_counts” that always includes all labels.
   For this bug report, the default should include HOWTO_SECTION in “scored labels.”

3) Add a regression test.

   Create a new test file (or extend an existing one) such as:

     tests/test_labelstudio_eval_metrics_labels.py

   The test should:
   - construct a minimal canonical text with at least 3 lines, one being a HOWTO_SECTION line (for example “FOR THE SAUCE”),
   - construct gold labels and predicted labels that match perfectly,
   - call the eval function that returns the metrics object (or CLI runner if that is the only interface),
   - assert that `per_label_metrics` includes HOWTO_SECTION with `gold_total==1`, `pred_total==1`, and `tp==1`.

   Keep the fixture tiny and purely synthetic so it can be committed without licensing issues.

4) Validate and record.

   Run:

     pytest -q

   and ensure the new test passes.

Acceptance:

- The test described above passes.
- Running the benchmark on a real dataset no longer reports `HOWTO_SECTION` totals as zero when HOWTO_SECTION is present in gold/pred data.


### Milestone 2: Add a dedicated CodexFarm pipeline for canonical line labels with strict prompt + deterministic-first gating

At the end of this milestone, a new pipeline name (for example `codex-farm-line-label-v1`) exists and can be selected via the existing configuration mechanism (`llm_recipe_pipeline`). When enabled, it produces line-level predictions in the same label set the benchmark uses. It also writes prompt logs into the run folder so the exported “need-to-know” cutdown can include them.

Work:

1) Locate how pipelines are dispatched.

   From the repo root, find where `llm_recipe_pipeline` is read and used:

     rg -n "llm_recipe_pipeline|codex-farm-3pass-v1|codex_farm" cookimport

   Identify:
   - where pipeline strings are validated (likely in `cookimport/config/run_settings.py`),
   - where a string is mapped to an implementation function (likely in `cookimport/labelstudio/prelabel.py` or a helper module).

2) Introduce a line-label pipeline module.

   Create a new module (choose one and be consistent; do not scatter logic across files):
   - `cookimport/labelstudio/line_label_pipeline.py` (recommended), or
   - `cookimport/labelstudio/pipelines/codex_farm_line_label_v1.py`

   Define plain-Python data structures for the pipeline:

   - A `LineItem` that contains:
     - `line_index: int` (0-based index in canonical lines)
     - `text: str` (the line text as evaluated)
     - `start_char: int` and `end_char: int` (char offsets in canonical text)
     - optional `context_before: list[str]` and `context_after: list[str]` (for prompt building)

   - A `LineLabel` representation.
     If an enum already exists in the repo, reuse it. Otherwise define a constrained set of allowed strings matching the benchmark labels:
     `RECIPE_TITLE`, `YIELD_LINE`, `HOWTO_SECTION`, `INGREDIENT_LINE`, `INSTRUCTION_LINE`, `TIME_LINE`, `RECIPE_NOTES`, `KNOWLEDGE`, `RECIPE_VARIANT`, `OTHER`.

   - A `LinePrediction` that contains:
     - `line_index: int`
     - `label: LineLabel`
     - optional `confidence: float` (0–1) to support gating and debugging

3) Deterministic-first labeler.

   Implement a deterministic classifier that covers easy, high-confidence lines without LLM calls. Keep it conservative: only assign a non-OTHER label when the pattern is very strong.

   Suggested rules (express them as code and unit tests; do not leave them as “ideas”):

   - Yield:
     Lines matching (case-insensitive) patterns like:
     “SERVES”, “MAKES”, “YIELDS”, “SERVING(S)”, optionally with a number.
     Example: “SERVES 4” -> YIELD_LINE.

   - Section headings:
     Lines matching patterns like:
     “FOR THE …”, “TO SERVE”, “TO MAKE …”, “DAY 1”, “DAY 2”, and lines that are mostly uppercase and short (but explicitly do not treat an all-caps recipe title as a section if it looks like a title).
     Example: “FOR THE KOHLRABI” -> HOWTO_SECTION.

   - Ingredient lines:
     Lines beginning with a quantity or fraction or number-word and containing a unit or ingredient noun, or single-ingredient lines in an ingredient region (context-sensitive).
     Example: “1/2 cup/120 g heavy cream” -> INGREDIENT_LINE.
     Example: “Grapeseed oil” -> INGREDIENT_LINE when adjacent to other ingredient lines or under a HOWTO_SECTION.

   - Instruction lines:
     Lines that start with a verb in imperative form (“Add”, “Combine”, “Stir”, “Cook”, “Bake”, “Bring”, “Heat”, etc) or contain multiple sentences of procedural text and are not clearly notes/knowledge.

   - Hard bans for KNOWLEDGE:
     If the line matches an ingredient pattern or an instruction pattern, never label it KNOWLEDGE in deterministic mode.
     (The LLM prompt will have the same ban; this is defense in depth.)

   Make the deterministic labeler return `(label, confidence)` so later steps can decide whether to call the LLM.

4) LLM fallback labeler.

   Using `cookimport/labelstudio/prelabel.py`’s existing Codex CLI invocation pattern, implement an LLM labeler that takes a batch of `LineItem`s and returns one label per line.

   The prompt must be optimized for “structural role labeling,” not “semantic cooking knowledge.” The rules below should be embedded directly in the prompt template, not only in code comments.

   Prompt requirements:

   - Output must be strict JSON, nothing else, with a top-level list of objects:
     `[{"line_index": 123, "label": "INGREDIENT_LINE"}, ...]`

   - The label set must be explicitly enumerated in the prompt.

   - Include a precedence order. For example:
     “If multiple labels could apply, choose the first that matches:
      RECIPE_TITLE > RECIPE_VARIANT > YIELD_LINE > HOWTO_SECTION > INGREDIENT_LINE > INSTRUCTION_LINE > RECIPE_NOTES > KNOWLEDGE > OTHER.”

   - Include “negative rules” (must-not-do), especially:
     - Never label a quantity/unit ingredient line as KNOWLEDGE.
     - Never label an imperative instruction as KNOWLEDGE.
     - “FOR THE …” / “TO SERVE” / “DAY N” are HOWTO_SECTION unless they are clearly a full recipe title.

   - Include 6–10 few-shot examples directly matching your observed failure modes:
     - “FOR THE MALT COOKIES” -> HOWTO_SECTION
     - “Grapeseed oil” under ingredients -> INGREDIENT_LINE
     - “SERVES 4” -> YIELD_LINE
     - A 2–3 sentence step -> INSTRUCTION_LINE
     - A narrative paragraph about the chef/book -> KNOWLEDGE or RECIPE_NOTES depending on your gold definition (use your label docs as truth)
     Keep the examples short and synthetic.

   - Provide local context.
     For each line, show at least the previous and next line text. Context is essential for single-word ingredient lines and ambiguous headings.

   - Batching and token limits.
     Implement a batching strategy like:
     - 30–60 target lines per call,
     - include context lines in the prompt but do not ask the model to label context-only lines unless you include them as targets,
     - keep the prompt size bounded and deterministic (stable ordering, stable formatting).

   Output parsing requirements:

   - Validate that every returned label is in the allowed set.
   - Validate that every requested `line_index` appears exactly once.
   - If the model returns invalid JSON, missing indices, or unknown labels, do not silently accept it:
     - write the raw response to the prompt log,
     - fall back to deterministic label = OTHER for missing indices,
     - and mark the run as “LLM_PARSE_ERROR” in a report field so it is visible.

5) Hybrid combiner.

   Implement:
   - run deterministic labeler over all lines,
   - select only low-confidence or OTHER-labeled lines for LLM labeling,
   - merge results, preferring deterministic when confidence is high and label is non-OTHER.

   Make this behavior explicit and configurable in run settings, but provide sensible defaults:
   - deterministic threshold default: 0.85
   - maximum LLM lines per recipe default: 200 (safety bound)

6) Write predictions in the existing Label Studio / benchmark format.

   You must match whatever the current prelabel output format is. Use the existing “working” pipeline as your reference.
   The key requirement is: predicted spans must align to canonical line boundaries the benchmark evaluates.

   Implementation strategy:

   - Identify how the benchmark derives canonical lines (likely from canonical text + newline offsets).
   - For each `LineItem`, emit a predicted span that covers exactly that line’s char range and is labeled with the predicted label.

7) Prompt logging as a first-class artifact.

   Always write prompt logs when an LLM call is made, in a deterministic location under the run root (for example):
   `.../labelstudio/<book_slug>/prelabel/prompts/`

   For each call, write:
   - `prompt_<N>.txt`
   - `response_<N>.txt`
   - `parsed_<N>.json` (the normalized parsed result)

   Also maintain an append-only `codexfarm_prompt_log.dedup.txt` that contains a compact “input/output pair” representation with a stable hash so the benchmark cutdown script can include it.

Acceptance:

- A new pipeline string exists and is selectable.
- Running the pipeline produces predictions that the existing evaluator can read.
- LLM calls generate prompt log artifacts in the run folder.
- On a small synthetic fixture, the pipeline produces correct labels for the known failure cases (see Milestone 3 tests).


### Milestone 3: Add tests for the new pipeline and wire it into the CLI/benchmark entrypoints

At the end of this milestone, `pytest` includes coverage for both:
- evaluation label accounting (Milestone 1), and
- line-label pipeline behavior (Milestone 2).

Work:

1) Add synthetic fixture tests for the line-labeler.

   Create a new test module, for example:

     tests/test_line_label_pipeline_v1.py

   Include at least these cases:

   - A mini-recipe snippet:
     - “RECIPE NAME” (all caps) -> RECIPE_TITLE
     - “SERVES 4” -> YIELD_LINE
     - “FOR THE SAUCE” -> HOWTO_SECTION
     - “2 tbsp olive oil” -> INGREDIENT_LINE
     - “Grapeseed oil” in ingredient context -> INGREDIENT_LINE
     - “Combine the oil and vinegar…” -> INSTRUCTION_LINE
     - A paragraph of book narrative -> KNOWLEDGE (or RECIPE_NOTES, depending on repo definitions)

   Ensure the test exercises:
   - deterministic-only success paths,
   - LLM fallback selection logic (mock the LLM call so tests are stable and offline),
   - and output validation / error fallback behavior.

2) Provide an LLM stub or mock.

   The repo currently has `cookimport/llm/client.py` and mock-backed plumbing. Prefer using that mock if it is already used in tests; otherwise implement a small stub in the test that injects a fake “Codex CLI result” and make the pipeline accept an injected runner for testability.

3) Wire the pipeline into the dispatch table.

   Ensure that:
   - `llm_recipe_pipeline=codex-farm-line-label-v1` triggers the new pipeline,
   - `llm_recipe_pipeline=off` remains unchanged,
   - existing pipelines remain available.

4) Ensure `labelstudio-benchmark` can run the new pipeline.

   If `labelstudio-benchmark` triggers a prelabel generation run internally, ensure the new pipeline can be used in that path. If it expects predictions already on disk, provide a documented workflow that generates predictions first and then evaluates them.

Acceptance:

- `pytest` passes (or, if the repo already has known failing tests unrelated to this work, document them in `Surprises & Discoveries` and ensure your new tests pass consistently).
- The new pipeline is reachable via the normal CLI workflow.


### Milestone 4: End-to-end benchmark run and recorded improvement

At the end of this milestone, you will have run at least one real benchmark (for example the same SeaAndSmokeCUTDOWN dataset) and recorded the before/after results in this ExecPlan’s `Artifacts and Notes` section.

Work:

1) Reproduce the baseline run and the old CodexFarm run.

   Use the run manifests in `data/golden/benchmark-vs-golden/<timestamp>/.../run_manifest.json` to discover the exact commands previously executed.

   If you cannot find those manifests, use `cookimport` CLI help to identify the intended invocation:

     cookimport labelstudio-benchmark --help
     cookimport bench --help

2) Run the benchmark with the new pipeline.

   Example target behavior (do not treat these numbers as guaranteed; they are goals):
   - overall line accuracy improves vs prior CodexFarm and is at least competitive with vanilla,
   - `INSTRUCTION_LINE` recall improves substantially (target: >= 0.30, matching or exceeding vanilla),
   - predicted KNOWLEDGE total is reduced dramatically (target: within 5–10x of gold total, not 25–30x).

3) Verify metrics correctness.

   Confirm that:
   - `HOWTO_SECTION` shows non-zero totals when present,
   - confusion matrix includes HOWTO_SECTION rows/cols.

4) Record results.

   Add a short excerpt of the new benchmark’s `eval_report.md` and the relevant per-label metrics (especially HOWTO_SECTION totals and INSTRUCTION_LINE recall) to this ExecPlan under `Artifacts and Notes`.


## Concrete Steps

All commands below assume you are in the repository root (the folder containing `pyproject.toml`).

1) Establish a clean baseline.

     python -V
     pytest -q

2) Locate evaluation and pipeline dispatch code.

     rg -n "labelstudio-benchmark|labelstudio-eval|Canonical Text Evaluation|per_label_metrics|top_confusions" cookimport
     rg -n "llm_recipe_pipeline|codex-farm-3pass-v1|prelabel" cookimport

3) Add the evaluation regression test and run it to see it fail before the fix.

     pytest -q tests/test_labelstudio_eval_metrics_labels.py -q

   Expected before-fix behavior: assertion failure showing HOWTO_SECTION totals reported as 0 even though the fixture contains it.

4) Implement the evaluation fix and re-run the test.

     pytest -q tests/test_labelstudio_eval_metrics_labels.py -q

   Expected after-fix behavior: the test passes.

5) Implement the new line-label pipeline and its unit tests.

     pytest -q tests/test_line_label_pipeline_v1.py -q

6) Run the end-to-end benchmark.

   First discover the exact invocation used in your environment. Start with:

     cookimport labelstudio-benchmark --help

   Then run the equivalent of your prior benchmark, but with:

     llm_recipe_pipeline=codex-farm-line-label-v1

   After the run, open the emitted `eval_report.md` in the run folder and verify the acceptance criteria.


## Validation and Acceptance

This work is complete when all of the following are true:

1) Evaluation correctness:
   - When gold/pred contain `HOWTO_SECTION`, the benchmark report’s per-label metrics show non-zero totals for `HOWTO_SECTION`.
   - The confusion matrix and “top confusions” logic includes HOWTO_SECTION (unless explicitly configured not to, in which case that exclusion is documented and tested).

2) Pipeline behavior:
   - A new pipeline `codex-farm-line-label-v1` exists and can be selected.
   - It produces one label per canonical line in the benchmark label set.
   - It logs prompts and responses into the run artifact directory in a predictable location, and includes a `codexfarm_prompt_log.dedup.txt`.

3) Quality improvement:
   - On at least one real golden dataset previously used (for example SeaAndSmokeCUTDOWN), the new pipeline improves `INSTRUCTION_LINE` recall and reduces `KNOWLEDGE` false positives compared to `codex-farm-3pass-v1`, and is competitive with or better than vanilla overall accuracy.

4) Tests:
   - The new regression tests pass and are stable offline (LLM calls are mocked/stubbed in unit tests).


## Idempotence and Recovery

- All steps should be safe to re-run. If you re-run a benchmark, it should create a new timestamped run directory without overwriting prior runs.
- Prompt logs should be written per-run; do not write into shared global paths.
- If the new pipeline causes failures in production-like runs, you can recover immediately by setting `llm_recipe_pipeline=off` (vanilla) or reverting to `codex-farm-3pass-v1` while keeping the evaluation fix (Milestone 1) and tests intact.
- If an LLM response is unparseable, the pipeline must not crash the run. It should:
  - log the raw response,
  - fall back to deterministic labels for that batch,
  - and mark the run report with a parse error count.


## Artifacts and Notes

(Keep this section updated with concise evidence as you implement.)

- Expected new artifacts per benchmark run (example shape; adapt to repo conventions):
  - `<run_root>/labelstudio/<book_slug>/prelabel/prompts/prompt_0001.txt`
  - `<run_root>/labelstudio/<book_slug>/prelabel/prompts/response_0001.txt`
  - `<run_root>/labelstudio/<book_slug>/prelabel/codexfarm_prompt_log.dedup.txt`
  - `<run_root>/.../eval_report.md`

- Before/after excerpt to paste here after Milestone 4:
  - overall line accuracy
  - macro F1 (excluding OTHER)
  - INSTRUCTION_LINE recall
  - KNOWLEDGE pred_total vs gold_total
  - HOWTO_SECTION gold_total and pred_total (should be non-zero when present)


## Interfaces and Dependencies

- Codex CLI invocation:
  The repo uses a local `codex exec -` invocation for LLM prompting in `cookimport/labelstudio/prelabel.py`. The new pipeline must reuse that mechanism (or wrap it) so runtime behavior is consistent with current usage.

- New code interfaces (recommended):

  In `cookimport/labelstudio/line_label_pipeline.py`, define:

    class LineItem:
        line_index: int
        text: str
        start_char: int
        end_char: int
        context_before: list[str]
        context_after: list[str]

    class LinePrediction:
        line_index: int
        label: str
        confidence: float

    def label_canonical_lines_v1(
        *,
        canonical_text: str,
        line_items: list[LineItem],
        codex_runner: CodexRunnerLike,
        settings: RunSettings,
        artifact_dir: pathlib.Path,
    ) -> list[LinePrediction]:
        ...

  The “runner” should be injectable for tests. In production, it should call the existing Codex CLI wrapper. In tests, it should return deterministic JSON.

- Prompt template:
  Store the prompt template in a version-controlled file (for example `cookimport/labelstudio/prompts/codex_farm_line_label_v1.txt`) so changes are reviewable and tied to a pipeline version. The pipeline name should match the template version.

- Dependencies:
  Prefer existing dependencies already in the repo (Typer, Rich, Pydantic v2, rapidfuzz if needed). Avoid adding new heavy libraries for this iteration.


## Plan change note

(Initial version, 2026-03-03): This plan was created to address two classes of issues observed in exported benchmark artifacts: incorrect per-label metric totals (notably HOWTO_SECTION=0) and CodexFarm pipeline underperformance due to over-predicting KNOWLEDGE and low instruction recall. Future revisions must update `Progress`, `Decision Log`, and `Artifacts and Notes` as implementation proceeds.