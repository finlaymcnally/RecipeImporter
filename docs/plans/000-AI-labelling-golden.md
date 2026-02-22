---
summary: "ExecPlan and implementation record for Codex-CLI freeform prelabeling plus additive Label Studio decorate workflows."
read_when:
  - "When implementing or debugging freeform prelabel/decorate behavior"
  - "When changing Label Studio import payload semantics for completed annotations"
---

# LLM pre-annotation for Label Studio freeform-spans via Codex CLI

This ExecPlan is a living document. The sections `Progress`, `Surprises & Discoveries`, `Decision Log`, and `Outcomes & Retrospective` must be kept up to date as work proceeds.

Maintain this plan in accordance with `PLANS.md` at the repository root (the “Codex Execution Plans (ExecPlans)” requirements). This plan is written so a novice can implement it end-to-end with only the working tree and this file.


## Purpose / Big Picture

Today, creating a freeform-spans “golden set” in Label Studio is slow because every segment must be manually highlighted and labeled. After this change, a developer can run `cookimport labelstudio-import ... --task-scope freeform-spans --prelabel` and get a Label Studio project where tasks already contain completed annotations (created via the API), so opening Label Studio is mostly review and correction instead of first-pass labeling.

We also need a “decorate” path for existing projects: if a human already labeled tasks and later the label set expands (or we just want an LLM to add missing label types), we can run a CLI command that fetches existing tasks/annotations and creates a new “augmented” annotation per task that merges the prior human work with the LLM’s additional spans.

You can see it working when:

- Label Studio shows a freeform-spans project where most tasks are already marked completed, and opening a task shows pre-highlighted spans.
- Running `cookimport labelstudio-export --export-scope freeform-spans` on that project produces the normal golden artifacts (`freeform_span_labels.jsonl`, `freeform_segment_manifest.jsonl`) without crashing.
- Running the new “decorate” command against an existing project creates new annotations that include newly-added label types (for example `YIELD_LINE`, `TIME_LINE`) without deleting prior human annotations.


## Progress

- [x] (2026-02-20 20:35Z) Inventory freeform task/result shape from existing freeform builders + export fixtures, then codify shared constants (`from_name`, `to_name`, labels) in `label_config_freeform.py`.
- [x] (2026-02-20 20:45Z) Implemented inline-annotation upload fallback path (task-only upload + post-import annotation create) so behavior is resilient across Label Studio versions/configs.
- [x] (2026-02-20 20:55Z) Implemented offline prelabel generation for freeform tasks in `generate_pred_run_artifacts(...)`, including `prelabel_report.json` and `prelabel_errors.jsonl`.
- [x] (2026-02-20 21:05Z) Wired `cookimport labelstudio-import --prelabel` CLI/config surface through `run_labelstudio_import(...)` with `annotations|predictions` upload mode.
- [x] (2026-02-20 21:15Z) Added `cookimport labelstudio-decorate` additive workflow (merge existing + new spans, metadata marker for rerun idempotence, and `--no-write` dry-run mode).
- [x] (2026-02-20 21:30Z) Added unit tests for JSON extraction, alias normalization, span/offset correctness, merge dedupe, import fallback wiring, and decorate dry-run behavior.
- [x] (2026-02-20 21:40Z) Updated docs (`02-cli`, `06-label-studio`, `IMPORTANT CONVENTIONS`, `understandings`, `cookimport/labelstudio/README.md`) for operator guidance.
- [x] (2026-02-20 22:55Z) Wired interactive menu parity: freeform import now prompts for AI prelabel and a dedicated interactive decorate action supports dry-run/write without leaving interactive mode.
- [ ] (2026-02-20 21:40Z) Manual live Label Studio smoke test (UI-completed status + export + decorate rerun) still pending in a real LS instance.


## Surprises & Discoveries

- Label Studio may or may not accept `annotations` inside the “project import tasks” payload depending on version/config. We must prove this with a live prototype and keep a fallback path that creates annotations via a per-task API call.
  Evidence: `tests/test_labelstudio_ingest_parallel.py::test_run_labelstudio_import_falls_back_to_post_import_annotations` now forces inline import rejection and verifies fallback creates per-task annotations.

- Freeform offset correctness is brittle if the prelabeler computes offsets against a different string than Label Studio displays. We must compute offsets against the exact `data.text` (or equivalent) shipped in each task and never normalize whitespace.
  Evidence: `tests/test_labelstudio_prelabel.py::test_prelabel_freeform_task_uses_block_offsets_and_exact_text` asserts `start/end/text` values match the exact `segment_text` substring for each selected block.

- Codex CLI output formatting is not guaranteed to be strict JSON. We should design robust “extract JSON from stdout” parsing and cache prompts/responses for reproducibility.
  Evidence: `tests/test_labelstudio_prelabel.py::test_parse_block_label_output_extracts_embedded_json` validates that parser logic can extract JSON arrays wrapped in extra prose.


## Decision Log

- Decision: Prelabel by creating completed Label Studio annotations (not just predictions), because the goal is “open Label Studio and review a mostly-done labeling job.”
  Rationale: The user explicitly wants tasks to appear already labeled/completed; predictions typically do not mark completion.
  Date/Author: 2026-02-20 / ExecPlan author

- Decision: For offset correctness, prelabel spans will be generated from block-level labeling (block_index → label) and then converted to character offsets using the same block-to-offset mapping used by `cookimport/labelstudio/freeform_tasks.py`.
  Rationale: LLMs are unreliable at hand-counting character offsets. Block-index selection is easier to validate and then deterministically convert into offsets.
  Date/Author: 2026-02-20 / ExecPlan author

- Decision: For decorating existing tasks, we will not overwrite existing annotations in place. We will create a new annotation per task that merges the “base” annotation results with LLM-suggested additional spans, and mark the new annotation with a `meta` marker so it can be detected/skipped on reruns.
  Rationale: Overwriting human data is risky and hard to recover; multiple-annotation history is safer and reversible.
  Date/Author: 2026-02-20 / ExecPlan author

- Decision: The LLM integration will be implemented as a small provider interface with a Codex CLI subprocess implementation that is configured via an env var / CLI option.
  Rationale: Keeps the feature usable without adding network SDK dependencies and aligns with the user’s preference for Codex CLI.
  Date/Author: 2026-02-20 / ExecPlan author

- Decision: Keep `--prelabel-upload-as predictions` as an explicit debug/compatibility mode while defaulting to completed `annotations`.
  Rationale: Some Label Studio setups are easier to validate with predictions first, but primary workflow target is “tasks appear completed.”
  Date/Author: 2026-02-20 / Implementer


## Outcomes & Retrospective

Implemented:

- New `cookimport/labelstudio/prelabel.py` module with:
  - Codex CLI subprocess provider + prompt/response cache,
  - robust JSON extraction/parsing for block-label outputs,
  - deterministic block-index -> Label Studio span result conversion,
  - merge/idempotence helpers for additive decorate mode.
- `labelstudio-import` gained prelabel options and freeform prelabel wiring:
  - `--prelabel`, provider/cmd/timeout/cache flags,
  - `--prelabel-upload-as annotations|predictions`,
  - `--prelabel-allow-partial`,
  - run artifacts now include `prelabel_report.json` and `prelabel_errors.jsonl`.
- Interactive `cookimport` menu now supports the same core flow end-to-end:
  - freeform task upload prompts `Enable AI prelabel before upload?`,
  - prelabel-enabled runs print `prelabel_report.json`,
  - `Label Studio: decorate existing freeform project with AI spans` supports dry-run/write without exiting interactive mode.
- Upload hardening:
  - if inline `annotations` import fails, code falls back to task-only import and then creates per-task annotations via API.
- New `labelstudio-decorate` CLI command:
  - additive merge behavior (base annotation preserved),
  - idempotence marker via annotation metadata,
  - `--no-write` dry-run reporting (`decorate_report.json`, `decorate_errors.jsonl`).
- Tests added/updated:
  - `tests/test_labelstudio_prelabel.py`
  - `tests/test_labelstudio_ingest_parallel.py` (fallback + predictions mode)
  - existing Label Studio suites still pass.

Remaining:

- Manual live Label Studio smoke validation is still required to confirm UI “completed” state and end-to-end operator UX against an actual server.


## Context and Orientation

This repository contains a deterministic cookbook import pipeline (`cookimport/`) with an optional Label Studio integration for creating and evaluating golden sets. The Label Studio integration already supports three task scopes: `pipeline`, `canonical-blocks`, and `freeform-spans`. The user’s golden set effort is focused on `freeform-spans`.

The relevant code areas (repository-relative paths) are:

- `cookimport/labelstudio/ingest.py`: orchestrates Label Studio “import” runs. It generates run artifacts (tasks JSONL, extracted text/archive, coverage, manifest) and optionally uploads to Label Studio.
- `cookimport/labelstudio/freeform_tasks.py`: builds freeform segment tasks and owns the mapping between “blocks” and “segment text offsets” (this is critical for span correctness).
- `cookimport/labelstudio/client.py`: a Label Studio API client wrapper used by import/export flows.
- `cookimport/labelstudio/export.py`: exports completed labels from a Label Studio project and writes golden artifacts.
- `cookimport/labelstudio/label_config_freeform.py`: defines the Label Studio XML config and the allowed freeform label set (currently includes `RECIPE_TITLE`, `INGREDIENT_LINE`, `INSTRUCTION_LINE`, `TIP`, `NOTES`, `VARIANT`, `YIELD_LINE`, `TIME_LINE`, `OTHER`).

Important behavioral constraints already present in the repo:

- Non-interactive upload operations are guarded by a write-consent flag (`--allow-labelstudio-write`) to prevent accidental uploads.
- Freeform tasks preserve whitespace in the UI (pre-wrap) to keep offsets stable. Any prelabel feature must preserve that: no trimming, no whitespace normalization, no newline rewriting.
- Freeform workflows rely on deterministic IDs (`segment_id`) and stable block indices across split-job merges.

New terms introduced by this plan:

- “Prelabel”: Use an LLM to generate a first-pass annotation for each freeform task before a human sees it.
- “Decorate”: Given existing Label Studio tasks (often already human-labeled), generate an additional annotation that adds missing labels/spans without deleting the prior annotation.
- “Codex CLI”: A local command-line program we call as a subprocess to get an LLM completion. In this plan, it is treated as an external dependency that must be installed and configured by the developer running `cookimport`.


## Plan of Work

We will implement this in four milestones. Each milestone is independently verifiable and moves us closer to the core user-visible outcome: “open Label Studio and review pre-labeled freeform segments.”


### Milestone 1 — Establish the exact Label Studio payload shapes we must generate

At the end of this milestone we will have a concrete, code-checked understanding of:

- The freeform task JSON shape produced by `freeform_tasks.py` (especially where the segment text lives and how blocks are represented).
- The freeform annotation “result” payload shape that Label Studio exports for a span label (so we can generate the same structure).

Work:

- Generate a tiny freeform-spans project from a small source (use very small `--segment-blocks` so there are few tasks).
- Manually label one task in Label Studio with 2–3 spans.
- Run `cookimport labelstudio-export --export-scope freeform-spans` for that project and inspect `exports/labelstudio_export.json` and the derived `exports/freeform_span_labels.jsonl`.

What to record in the codebase as “source of truth” for later milestones:

- The relevant annotation `result` item shape, including `from_name`, `to_name`, `type`, and `value` keys used for freeform span labels.
- Whether Label Studio expects `start`/`end` vs `startOffset`/`endOffset` keys (use the export payload to decide; do not guess).
- Whether the `value.text` field is required and whether it must exactly match the substring.

Acceptance:

- A short note is added to this ExecPlan’s `Surprises & Discoveries` with an indented snippet of one exported result item so future work can match it.
- A new internal helper function skeleton exists (not yet wired) that can construct a result item given `start`, `end`, `label`, and the segment text substring, using the exact keys observed in export.


### Milestone 2 — Implement offline LLM prelabel generation for freeform tasks

At the end of this milestone, running the freeform task builder + prelabel step locally will produce a `label_studio_tasks.jsonl` where each task includes an `annotations` array containing a completed annotation result matching the Label Studio export schema. This milestone does not require a live Label Studio server, but should be testable with unit tests and inspection of artifacts.

Implementation approach:

- Add a new module `cookimport/labelstudio/prelabel.py` that owns:
  - Prompt construction for a single freeform segment.
  - A provider interface for “LLM completion” with a Codex CLI implementation.
  - Post-processing and validation:
    - enforce allowed label set,
    - enforce that every span is valid (start < end, inside bounds),
    - enforce that any embedded `text` matches the substring from the segment text.

- The prelabel output for a segment will be built as “label per block index”, then converted to one span per block by mapping block indices to character offsets in the segment text. This avoids relying on the LLM for raw offsets.

Suggested internal interface (define in `cookimport/labelstudio/prelabel.py`):

    class LlmProvider(Protocol):
        def complete(self, prompt: str) -> str:
            ...

    class CodexCliProvider:
        def __init__(self, *, cmd: str, timeout_s: int, cache_dir: Path | None): ...
        def complete(self, prompt: str) -> str: ...

    def prelabel_freeform_task(
        task: dict,
        *,
        provider: LlmProvider,
        allowed_labels: set[str],
        mode: str,  # "full" or "augment"
        augment_only_labels: set[str] | None = None,
        base_annotation: dict | None = None,
    ) -> dict | None:
        """
        Returns a Label Studio annotation object with a `result` list, or None if the prelabel failed.
        """

Prompt shape (keep it short and deterministic):

- Provide the allowed labels and brief definitions.
- Provide the segment blocks as a numbered list keyed by `block_index`, and the exact block text.
- Ask for strict JSON output as an array of objects: `[{ "block_index": 123, "label": "INGREDIENT_LINE" }, ...]`.
- In “augment” mode, include the existing labeled blocks/spans and ask only for additional blocks for specified labels.

Parsing and validation:

- Extract the first JSON array/object from stdout (handle Codex CLI adding prose around it).
- Validate block indices exist in this segment.
- Validate labels are in the allowed set (normalize legacy synonyms like `TIME` → `TIME_LINE`, `YIELD` → `YIELD_LINE` if the repo already has that normalization logic; otherwise implement it here).
- Convert each `{block_index, label}` to a span:
  - Use freeform task builder data structures to map block_index → (start_char, end_char) in the segment text.
  - Build the result item with the exact keys observed in Milestone 1.
- Attach the resulting annotation object to the task as `task["annotations"] = [annotation_obj]`.

Artifacts:

- When prelabeling runs as part of artifact generation, write a `prelabel_report.json` under the run root that includes:
  - number of tasks pre-labeled successfully,
  - number failed,
  - label distribution counts,
  - a pointer to a JSONL “errors” file with per-task failures (segment_id, reason).
- Cache Codex prompts/responses by prompt hash in a local cache folder (default something like `<run_root>/prelabel_cache/` or `.cache/cookimport/prelabel/`), but never store API keys.

Acceptance:

- A developer can run an offline artifact generation path (either via an existing offline function like `generate_pred_run_artifacts(...)` or via a new `--no-upload` mode for `labelstudio-import`) and see `label_studio_tasks.jsonl` tasks containing `annotations`.
- Unit tests exist that construct a tiny synthetic segment and a fake LLM provider output, then assert:
  - every generated result item has correct offsets,
  - `value.text` (if present) matches the substring,
  - invalid labels are rejected/normalized,
  - failures are recorded without crashing the whole run.


### Milestone 3 — Upload tasks with completed annotations (Option A)

At the end of this milestone, `cookimport labelstudio-import ... --task-scope freeform-spans --prelabel --allow-labelstudio-write` uploads tasks to Label Studio and they appear “completed” (already annotated) in the Label Studio UI.

Work:

- Add CLI flags to the `labelstudio-import` command in `cookimport/cli.py` (and route through to `run_labelstudio_import` in `cookimport/labelstudio/ingest.py`):
  - `--prelabel / --no-prelabel` (default off).
  - `--prelabel-provider codex-cli` (default codex-cli; keep extensible).
  - `--codex-cmd TEXT` (optional; default from env var such as `COOKIMPORT_CODEX_CMD`, fallback to `codex`).
  - `--prelabel-timeout-seconds INTEGER` (sane default, e.g. 120).
  - `--prelabel-cache-dir PATH` (optional).
  - `--prelabel-upload-as annotations|predictions` (default `annotations`; keep `predictions` available for debugging).

- In `cookimport/labelstudio/ingest.py`, after tasks are generated for freeform-spans (and before writing/upload), apply the prelabeler to each task when `prelabel=True`.

- In `cookimport/labelstudio/client.py` / upload logic:
  - First attempt: include `annotations` in the task objects in the existing “import tasks” API call. Verify via Milestone 1 prototype that Label Studio accepts it and marks tasks completed.
  - Fallback: if the import endpoint rejects annotations, import tasks without annotations, then create annotations via a second endpoint per task:
    - After import, fetch the created tasks back (in a deterministic way) so we can map our `segment_id` (deterministic) to the Label Studio `task_id`.
    - Create an annotation for each task with the `result` payload.

We must keep this safe:

- No uploads should happen without the existing write-consent flag.
- If prelabel is enabled but Codex CLI is not configured or fails, the command should fail fast by default (so the user doesn’t think they got prelabels when they didn’t). If partial completion is desired, add a `--prelabel-allow-partial` flag that uploads tasks even if some prelabels failed, but records failures in the report and prints a loud warning.

Acceptance:

- Running the command uploads a project that shows tasks as completed.
- Opening a task shows highlighted spans already present.
- Running `cookimport labelstudio-export --export-scope freeform-spans` against the project succeeds and produces the standard golden artifacts.


### Milestone 4 — Decorate existing tasks (Option B)

At the end of this milestone, a user can point at an existing Label Studio project and have the tool create a new “augmented” annotation per task that adds missing label types without deleting prior human work.

User-facing behavior:

- `cookimport labelstudio-decorate --project-name "<name>" --task-scope freeform-spans --add-labels YIELD_LINE,TIME_LINE --allow-labelstudio-write`:
  - fetches tasks and their latest existing annotation,
  - asks the LLM for additional spans only for the requested labels,
  - creates a new merged annotation per task that includes both the original spans and the new spans,
  - marks the new annotation with metadata so reruns can skip tasks already decorated.

Implementation approach:

- Add a new command to `cookimport/cli.py` (either as its own top-level command or under a `labelstudio-` group). Name it `labelstudio-decorate` to match the concept.

- Reuse the existing Label Studio client/export fetching logic (do not re-implement pagination twice). Prefer adding a method on `cookimport/labelstudio/client.py` that returns tasks including annotations.

- Define a “base annotation selection rule”:
  - Prefer the most recent non-cancelled annotation on the task.
  - If there are multiple annotations, do not guess “best”; use recency.
  - If there are no annotations, treat as “augment from empty” (equivalent to prelabel full).

- Define merge behavior:
  - Parse the base annotation result items into an internal span list.
  - Ask Codex CLI for new spans only for `--add-labels`.
  - Convert suggested blocks/spans to result items.
  - Merge, dedupe exact duplicates (same label + same start/end).
  - Keep base spans untouched; only additive changes.
  - Store `meta` on the new annotation like:
    - `{"cookimport_prelabel": true, "mode": "augment", "added_labels": ["YIELD_LINE","TIME_LINE"], "prompt_hash": "..."}`
    so we can detect and skip already-decorated tasks on reruns.

- Add a “dry-run” mode:
  - `--no-write` that does everything except POST the new annotations, and writes a local report with what would change.

Acceptance:

- On a project that has older annotations missing yield/time labels, running decorate creates a second annotation per task that includes yield/time spans.
- The command is safe to rerun: it does not create infinite duplicate annotations because it can detect prior “cookimport_prelabel” meta markers (or because it can detect “already contains these labels” and skip).
- The run writes a local report artifact (counts, failures, sample diffs) so a user can audit what happened without opening every task.


## Concrete Steps

These are the exact commands a developer should run while implementing and validating. Run from the repository root.

Environment:

    source .venv/bin/activate
    export LABEL_STUDIO_URL="http://localhost:8080"            # adjust as needed
    export LABEL_STUDIO_API_KEY="..."                          # required for upload/decorate
    export COOKIMPORT_CODEX_CMD="codex"                        # or a full command line if needed

Step 1: Generate a tiny freeform project to inspect task shape.

    cookimport labelstudio-import data/input/<small_book>.epub \
      --task-scope freeform-spans \
      --segment-blocks 10 \
      --segment-overlap 2 \
      --allow-labelstudio-write

Then manually label one task in Label Studio and export:

    cookimport labelstudio-export \
      --project-name "<project name>" \
      --export-scope freeform-spans

Inspect the exported payload in:

    data/golden/<project_slug>/exports/labelstudio_export.json

Step 2: Run unit tests while developing.

    pytest -q \
      tests/test_labelstudio_freeform.py \
      tests/test_labelstudio_export.py \
      tests/test_labelstudio_chunking.py

Add the new prelabel tests to this list once created.

Step 3: After implementing prelabel upload, run a real prelabel import.

    cookimport labelstudio-import data/input/<small_book>.epub \
      --task-scope freeform-spans \
      --segment-blocks 10 \
      --segment-overlap 2 \
      --prelabel \
      --allow-labelstudio-write

Open Label Studio and verify tasks appear completed.

Step 4: After implementing decorate, run decorate on a project that already has tasks.

    cookimport labelstudio-decorate \
      --project-name "<existing project name>" \
      --task-scope freeform-spans \
      --add-labels YIELD_LINE,TIME_LINE \
      --allow-labelstudio-write


## Validation and Acceptance

Automated validation:

- All existing test suites should continue to pass:
  - `pytest -q`
- New tests must cover:
  - block_index → offset conversion correctness,
  - label normalization and rejection of unknown labels,
  - merge semantics for decorate (base spans unchanged, new spans added, duplicates deduped),
  - JSON extraction/parsing from Codex CLI output (use a stub provider in tests).

Manual acceptance (must do at least once after implementation):

1. Start Label Studio, run prelabel import for a small source, and confirm in the UI:
   - Task “completed” count is high (ideally equals tasks total unless partial allowed).
   - Opening a task shows pre-highlighted spans.

2. Export that project and confirm:
   - `freeform_span_labels.jsonl` and `freeform_segment_manifest.jsonl` are produced.
   - The exported spans include the labels created by prelabel (including `YIELD_LINE` / `TIME_LINE` if present in the text).

3. Run decorate on an existing project:
   - Confirm a task now has multiple annotations (original + decorated), and the decorated one contains the additional label types.
   - Rerun decorate and confirm it does not create another duplicate annotation for the same task (idempotence check).


## Idempotence and Recovery

Safe reruns:

- Prelabel import:
  - If using `--overwrite`, rerunning is naturally idempotent (project replaced).
  - If using `--resume`, ensure prelabel only runs for newly-created tasks (do not create duplicate annotations for tasks already uploaded).

- Decorate:
  - Rerunning should be safe because we either:
    - detect a previous “cookimport_prelabel” annotation meta marker and skip, or
    - detect that the task already contains spans for all requested `--add-labels` and skip.

Recovery:

- If a prelabel run creates bad annotations:
  - Prefer creating a new project (overwrite) rather than trying to delete thousands of annotations.
  - If decorating created bad annotations, the original annotations are still present; users can ignore the decorated annotation or delete it manually in Label Studio UI if needed.

Secrets:

- Never write `LABEL_STUDIO_API_KEY` or any Codex credentials into run manifests or reports.
- If caching Codex prompts/responses, cache only prompts and outputs; do not cache environment variables.


## Artifacts and Notes

During development, keep one concrete example of a freeform annotation result item in this ExecPlan (from Milestone 1) so future refactors don’t regress the payload shape. Example template (replace keys to match actual exported payload):

    {
      "from_name": "<labels control name>",
      "to_name": "<text object name>",
      "type": "<result type>",
      "value": {
        "start": 123,
        "end": 156,
        "text": "exact substring here",
        "labels": ["INGREDIENT_LINE"]
      }
    }

Prelabel reporting artifacts to write under the import/decorate run root:

- `prelabel_report.json` with counts and summary.
- `prelabel_errors.jsonl` with per-task failures (segment_id, reason).
- Optionally `prelabel_samples.jsonl` with a small sample of successful prelabels for quick auditing.


## Interfaces and Dependencies

External dependencies introduced:

- A working Codex CLI binary available on PATH (or configured via `--codex-cmd` / `COOKIMPORT_CODEX_CMD`).
- Label Studio API credentials via `LABEL_STUDIO_URL` and `LABEL_STUDIO_API_KEY` for upload/decorate operations.

Internal interfaces to implement:

- In `cookimport/labelstudio/prelabel.py`:
  - `LlmProvider` protocol.
  - `CodexCliProvider` implementation using `subprocess.run`.
  - `prelabel_freeform_task(...)` that returns a Label Studio annotation object.

- In `cookimport/labelstudio/ingest.py`:
  - Thread the `prelabel` config from CLI down into task generation.
  - Apply prelabel only when `task_scope == "freeform-spans"` (other scopes can be added later).

- In `cookimport/labelstudio/client.py`:
  - Ensure there is a way to:
    - import tasks (existing),
    - and either import tasks with annotations inline or create annotations after import (new if not present).
  - Ensure decorate can fetch tasks plus their annotations (reuse export logic if possible).

Where the names and keys come from:

- Allowed freeform label values should come from `cookimport/labelstudio/label_config_freeform.py` (do not duplicate in multiple places).
- The “from_name” / “to_name” strings for result items must match the label config XML. Prefer defining them once as constants and reusing them in both task builder and prelabeler so they cannot drift.

Revision note (2026-02-20): Updated this ExecPlan from design-only to implementation record after shipping the core prelabel/decorate code paths, tests, and docs. Manual live Label Studio smoke validation remains explicitly pending.
