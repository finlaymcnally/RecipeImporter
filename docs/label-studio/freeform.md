---
summary: "ExecPlan for freeform Label Studio span import/export/eval and implemented notes."
read_when:
  - Implementing freeform Label Studio workflows
  - Debugging freeform span offsets or source mapping behavior
---

# Add freeform text-span highlighting in Label Studio for cookbook golden sets

This ExecPlan is a living document. The sections `Progress`, `Surprises & Discoveries`, `Decision Log`, and `Outcomes & Retrospective` must be kept up to date as work proceeds. Maintain this document in accordance with `PLANS.md` at the repo root. 

## Purpose / Big Picture

We want a new Label Studio project type where a human can open extracted cookbook text and highlight arbitrary spans (any substring) in a way that feels like “freeform highlighting,” then assign each highlight a label. The output becomes a golden set for benchmarking: it records labeled spans using character offsets, so we can later compare pipeline predictions to what the human highlighted.

This should feel different from the existing “chunk-based” and “one-label-per-block” flows. The user is not constrained to pre-cut chunks and not forced to label every block. They should be able to highlight exactly what they care about.

The change is done when a user can import a cookbook into a “freeform spans” Label Studio project, highlight multiple spans per task, export the annotations, and the exported data is stable and usable for evaluation (including mapping back to the original source blocks/pages).

## Progress

* [x] (2026-02-10 20:12Z) Read the current Label Studio integration code and identify where label configs, task generation, and export live.
* [x] (2026-02-10 20:22Z) Add a new Label Studio labeling config for text span highlights (freeform spans) and ensure whitespace/newlines are preserved so offsets are reliable. ([Label Studio][1])
* [x] (2026-02-10 20:34Z) Add a new import scope that creates span-highlight tasks from extracted cookbook text, with stable task IDs and a source mapping.
* [x] (2026-02-10 20:45Z) Add a new export scope that emits a golden-set JSONL of labeled spans (with offsets, labels, and source mapping).
* [x] (2026-02-10 20:55Z) Add an evaluation adapter that can compare pipeline outputs to the span gold set (smoke-test level on block-range overlap).
* [ ] (2026-02-10 21:05Z) Add full live Label Studio manual validation transcript (completed: deterministic regression fixture for offsets/export/eval; remaining: manual UI run against a real project).

## Surprises & Discoveries

(Keep this updated during implementation.)

* Observation: Offsets depend on exact whitespace and newline handling in the displayed text; if the UI collapses spaces, saved offsets won’t line up with your stored text.
  Evidence: Label Studio’s `Text` tag docs recommend `white-space: pre-wrap` specifically because every space counts for offsets. ([Label Studio][1])
* Observation: Resume/idempotence logic in this repo is keyed entirely by per-scope task ID fields loaded from prior manifests (`chunk_id`/`block_id`/`segment_id`), not by Label Studio internal task IDs.
  Evidence: `cookimport/labelstudio/ingest.py` reads prior `task_ids` and falls back to parsing `label_studio_tasks.jsonl` by a scope-specific key.
* Observation: Freeform evaluation is most robust in this codebase when converting gold offsets to touched block ranges and matching by label + overlap.
  Evidence: Export now stores `touched_block_indices` and `eval_freeform.py` compares those block ranges to predicted pipeline chunk ranges.

## Decision Log

(Record decisions as they are made during implementation.)

* Decision: Default to text-span annotation (offset-based) rather than PDF page box annotation.
  Rationale: The user requested “Highlight spans in text,” which Label Studio supports with `Text`-based span annotation and exports offsets directly.
  Date/Author: 2026-02-10 / implementing agent
* Decision: Segment tasks are fixed-size overlapping windows over extracted blocks (`--segment-blocks`, `--segment-overlap`) with IDs based on source hash + block range.
  Rationale: This keeps offsets stable within each task while preserving boundary context and deterministic resume behavior.
  Date/Author: 2026-02-10 / implementing agent
* Decision: Use Option B for evaluation (convert gold offsets to touched block ranges) instead of comparing in raw character coordinates.
  Rationale: Pipeline predictions already carry block provenance, so block-range overlap avoids brittle text-normalization differences across task types.
  Date/Author: 2026-02-10 / implementing agent

## Outcomes & Retrospective

* (2026-02-10) Implemented `freeform-spans` end-to-end in code: import scope, label config, task builder with source mapping, export JSONL contract, and eval adapter. Added regression tests for deterministic offsets, freeform export shaping, and freeform eval matching. Remaining work is manual live-UI validation transcript against a running Label Studio instance.

## Context and Orientation

This repository already integrates Label Studio in two ways:

1. “Pipeline” projects that label chunks the pipeline proposes (structural and atomic).
2. “Canonical blocks” projects that label every extracted block with one label.

We are adding a third project type: “Freeform spans.” In Label Studio terms, this is classic text span annotation (like NER): the task shows a text field, and the annotator selects and labels arbitrary spans. Label Studio supports large documents and overlapping spans in its NER template family. ([Label Studio][2])

Key concept: Label Studio stores span labels using character offsets into the exact text presented to the annotator. Therefore, the import side must control the exact text string and preserve it consistently, and the export side must include enough information to map those offsets back to the cookbook source.

Label Studio labeling configs are XML composed of tags (object tags that display data, control tags for labels, and other structural tags). ([Label Studio][3])

## Plan of Work

### Milestone 1: Add a new Label Studio labeling configuration for freeform spans

Goal: Create a separate Label Studio project config that allows selecting arbitrary spans in a displayed text field and assigning one label from a controlled set (you can allow multiple labels across different highlights). The UI must preserve whitespace and newlines so offsets are stable.

What should exist after this milestone:

* A new labeling config file alongside the existing configs (keep it separate so projects don’t share configs).
* The config displays text using the `Text` tag and preserves whitespace using the recommended `pre-wrap` styling, because offsets count every character including spaces/newlines. ([Label Studio][1])
* A clear, repo-native label set for spans (for example, the same semantic categories you care about in benchmarking: recipe title, ingredient span, instruction span, tip span, narrative span, etc.). You can start with a minimal set and evolve it, but treat label names as part of the golden set contract once used.

Conceptual details the config must satisfy:

* The annotator must be able to create multiple highlights per task.
* Highlights must be stored as spans with start/end offsets relative to the task’s text field.
* Newlines and spacing must appear exactly as in the stored text string.

### Milestone 2: Define the “task unit” for freeform span labeling

Goal: Decide how much text goes into one labeling task, because “the whole book in one task” can be heavy, while “tiny snippets” makes it hard to highlight across boundaries.

Make this a deliberate product decision inside the repo, not left implicit.

Constraints and tradeoffs:

* Very large tasks can be slow and awkward to annotate, but Label Studio’s NER-style workflows explicitly support very large documents, so this can work if you’re careful. ([Label Studio][2])
* Offsets only make sense inside the exact text of a task; splitting text into multiple tasks means spans can’t cross task boundaries.
* Your exporter/evaluator will be much easier to build if every task has a stable, explicit mapping back to the source (block IDs and/or page numbers).

Recommended default approach (conceptual):

* Build tasks as “document segments” derived from the existing extracted block stream (the same extracted archive used in other flows).
* Each segment includes a contiguous run of blocks, joined with a consistent separator that preserves the original newlines.
* Include a small, configurable “context window” around segment boundaries (extra blocks on each side) so annotators can highlight spans that are near boundaries without missing context. This mirrors the repo’s existing approach of adding context for block-based tasks.
* Ensure task IDs are stable based on (source file hash + segment index or block range). This enables safe re-import/resume behavior and prevents duplicates.

Make this task-unit rule an explicit contract in docs and in the exported golden set.

### Milestone 3: Add a new import scope that creates freeform span tasks

Goal: Extend the existing labelstudio-import flow so it can create a new kind of project (“freeform spans”) and upload tasks in the expected JSON shape for Label Studio.

What should exist after this milestone:

* A new `--task-scope` (or equivalent) that routes task generation into the new “segment text for freeform spans” builder.
* The importer must attach, per task:

  * the exact `text` that Label Studio will display for annotation,
  * stable identifiers (task ID / segment ID),
  * a “source mapping” payload that describes how the task text was constructed (at minimum: the list of source blocks included, their stable block IDs, and their order; optionally page numbers if available).
* The importer must create or find a Label Studio project that uses the new labeling config and then import tasks.

Important correctness requirements:

* The `text` string must be identical between what is uploaded and what is later used to interpret offsets on export.
* Whitespace must be preserved; otherwise offsets won’t line up. The `Text` tag + `pre-wrap` styling is part of that end-to-end guarantee. ([Label Studio][1])
* Re-running import should be idempotent: existing tasks must be detected and skipped, consistent with how the current integration behaves.

### Milestone 4: Add a new export scope that produces a span-based golden set

Goal: Export Label Studio annotations for this project type and transform them into a repo-owned JSONL golden-set format suitable for benchmarking and long-term storage.

What should exist after this milestone:

* A new export mode (parallel to existing pipeline/canonical exports) that:

  * pulls Label Studio annotations (Label Studio provides “raw JSON” exports and export tooling), ([Label Studio][4])
  * extracts all labeled spans (each with label name + start/end offsets, and ideally also the selected text for debugging),
  * emits a JSONL where each line is one labeled span record, including:

    * cookbook identity (source file, file hash, and/or book slug),
    * task/segment identity,
    * offsets (start/end),
    * label,
    * and the source mapping context needed to map spans back to blocks/pages later (either inline or by referencing a stored segment manifest).
* The export should be deterministic: re-exporting without new labels produces identical output ordering and content.

Notes to keep the plan self-contained:

* Label Studio’s exports are raw JSON structures; don’t rely on “UI export” quirks. Standardize in your own JSONL format as the contract for the repo. ([Label Studio][4])

### Milestone 5: Provide at least a minimal evaluation path against the span golden set

Goal: Let the repo use span gold data to score pipeline predictions.

This does not need to be perfect in the first version, but it must produce a working, observable benchmark outcome.

Conceptual approach options (pick one and document the decision):

Option A: Compare spans to pipeline predictions in the same text coordinate system.

* For each pipeline prediction (recipe spans, ingredient lines, etc.), represent it as spans in segment-text offsets, then compute overlap metrics (exact match, token overlap, IoU, etc.) against gold spans.

Option B: Convert gold spans to block-level labels (or block ranges) and reuse canonical evaluation machinery.

* Use the stored source mapping to translate each gold span (offset range) into the set of blocks it touches.
* Then derive block-level labels or recipe ranges and reuse existing evaluation comparisons.

In either option, define what “match” means and provide at least one report artifact that a human can read (a short markdown report plus a JSON summary is fine, matching existing patterns).

### Milestone 6: Documentation and “it works” proof

Goal: Make this feature usable by a novice agent and verifiable without tribal knowledge.

Update the existing repo docs where Label Studio workflows are described to include:

* What “freeform spans” is, how it differs from pipeline/canonical.
* What labels are available and what they mean.
* What a task contains (segment unit, context window concept).
* What export produces (JSONL contract fields at a conceptual level).
* How to run the end-to-end scenario below and what outputs to expect.

## Concrete Steps

All commands below are examples of the user-visible workflow that must work when implementation is complete. Keep them aligned with the repo’s existing CLI entry points and conventions.

1. Start Label Studio as usual and set the same environment variables already used by the current integration.

2. Import a cookbook into a “freeform spans” project using the new scope. The command should mirror existing `labelstudio-import` usage but switch task scope to the new mode.

   Example:

      cookimport labelstudio-import data/input/sample.epub \
        --project-name "Sample Freeform (spans)" \
        --task-scope freeform-spans \
        --segment-blocks 40 \
        --segment-overlap 5

3. In the Label Studio UI, open the project, highlight several spans, and assign labels. Confirm that you can add multiple highlights per task.

4. Export using the new export scope. Ensure the output directory contains a JSONL of spans.

	   Example:

	      cookimport labelstudio-export \
	        --project-name "Sample Freeform (spans)" \
	        --export-scope freeform-spans \
	        --output-dir data/golden/

5. Run the evaluation command (new or adapted) and confirm it emits a small report and at least one “examples of mismatches” artifact.

	   Example:

	      cookimport labelstudio-eval freeform-spans \
	        --pred-run data/golden/<timestamp>/labelstudio/<book_slug>/ \
	        --gold-spans data/golden/<timestamp>/labelstudio/<book_slug>/exports/freeform_span_labels.jsonl \
	        --output-dir data/golden/<timestamp>/labelstudio/<book_slug>/eval-freeform/

As you implement, add short example transcripts here as indented blocks (not fenced blocks) showing what success looks like (created project name, number of tasks uploaded, number of spans exported, and a one-line summary from the evaluator).

   Automated regression run (local tests):

      $ . .venv/bin/activate && pytest tests/test_labelstudio_freeform.py
      ...
      3 passed in 0.05s

## Validation and Acceptance

Acceptance is met when all the following are true:

* Import:

  * Creating a “freeform spans” project results in tasks that show readable cookbook text in Label Studio.
  * The text preserves newlines/spaces as expected (visually, it should look like the extracted text, not collapsed).
  * Re-running import does not duplicate tasks and can safely resume.

* Labeling:

  * Annotators can highlight arbitrary spans and assign labels.
  * Multiple labeled spans per task are supported.

* Export:

  * Export emits a deterministic JSONL golden set containing (label, offsets, task/segment IDs, and a stable reference to source mapping).
  * Offsets are valid within the exact stored task text (no out-of-range offsets, no mismatch caused by whitespace collapsing).

* Evaluation:

  * There is a working command that consumes the exported span golden set and produces a report comparing pipeline predictions to gold.
  * The report includes at least: counts of gold spans, predicted spans, matched spans, and a small sample of misses/false positives.

## Idempotence and Recovery

* Imports must be safe to re-run. Stable task IDs are required so a second import can detect existing tasks and skip them.
* Exports must be safe to re-run; output should overwrite or version deterministically (match existing repo patterns).
* If labeling config changes after tasks exist, document the migration story (prefer: create a new project rather than mutating an existing one, because the golden set contract depends on the config and the exact text presentation).

## Artifacts and Notes

As you implement, capture the following minimal evidence here:

* A sample exported JSONL line (redact personal info) showing label + offsets + identifiers.
* A sample “segment manifest” record that shows how a task maps back to source blocks.
* A short evaluation report excerpt that demonstrates at least one match and one miss.

Sample exported span JSONL line (from synthetic regression fixture):

    {"span_id":"urn:cookimport:freeform_span:hash123:2fdca3a9f7365a11","segment_id":"urn:cookimport:segment:hash123:0:1","source_hash":"hash123","source_file":"book.epub","book_id":"book","label":"INGREDIENT_LINE","start_offset":0,"end_offset":5,"selected_text":"Alpha","segment_text_length":11,"touched_block_ids":["urn:cookimport:block:hash123:0"],"touched_block_indices":[0]}

Sample segment manifest record:

    {"segment_id":"urn:cookimport:segment:hash123:0:1","source_hash":"hash123","source_file":"book.epub","book_id":"book","segment_index":0,"segment_text_length":11,"source_map":{"separator":"\\n\\n","start_block_index":0,"end_block_index":1,"blocks":[{"block_id":"urn:cookimport:block:hash123:0","block_index":0,"segment_start":0,"segment_end":5},{"block_id":"urn:cookimport:block:hash123:1","block_index":1,"segment_start":7,"segment_end":11}]}}

Evaluation report excerpt (from regression fixture):

    Gold spans: 3
    Predicted spans: 3
    Recall (gold matched): 0.667 (2/3)
    Precision (pred matched): 0.667 (2/3)
    Missed gold spans: 1
    False-positive predictions: 1

## Interfaces and Dependencies

Label Studio concepts this feature relies on (embed these assumptions in the implementation and docs):

* Labeling configs are XML built from tags; a `Text` tag displays text and offsets are computed over the exact character stream shown to annotators. ([Label Studio][3])
* Whitespace/newlines must be preserved to keep offsets reliable; `pre-wrap` styling is the recommended approach for the `Text` tag. ([Label Studio][1])
* NER-style span labeling supports overlapping spans and large documents, which aligns with “freeform highlighting.” ([Label Studio][2])
* Exports are available as raw JSON; the repo should convert them into a stable JSONL golden-set contract. ([Label Studio][4])

---

Change note (required for living plans):

* (2026-02-10) Initial ExecPlan drafted to add “freeform text-span highlighting” Label Studio project type, including import/export/eval and a stable segment+mapping strategy, consistent with the repo’s existing Label Studio integration patterns.
* (2026-02-10) Updated after implementation: added progress timestamps, concrete commands, deterministic artifact examples, and documented final design choices (segment IDs, scope routing, block-range evaluation).

[1]: https://labelstud.io/tags/text?utm_source=chatgpt.com "Text Tags for Text Objects"
[2]: https://labelstud.io/templates/named_entity?utm_source=chatgpt.com "Text Named Entity Recognition Data Labeling Template"
[3]: https://labelstud.io/guide/setup?utm_source=chatgpt.com "Set up labeling configuration interface"
[4]: https://labelstud.io/guide/export?utm_source=chatgpt.com "Label Studio Documentation — Export Annotations"
