DO NOT DO NOW, MAYBE DO THIS LATER

# Add PDF Page Box-Annotation Golden Set Workflow in Label Studio

This ExecPlan is a living document. The sections `Progress`, `Surprises & Discoveries`, `Decision Log`, and `Outcomes & Retrospective` must be kept up to date as work proceeds.

Maintain this document in accordance with `PLANS.md` at repo root (or wherever it is checked in), which defines the required ExecPlan format and workflow rules. :contentReference[oaicite:0]{index=0}

## Purpose / Big Picture

After this change, a user can import a cookbook PDF and, inside Label Studio, draw freeform bounding boxes directly on the rendered PDF pages (as page images). Each box is labeled with a user-chosen category (for example: RECIPE, INGREDIENTS, INSTRUCTIONS, TIP, etc.). The exported dataset becomes a “golden set” benchmark that reflects exactly what the user drew, not what the pipeline guessed.

The user-visible proof is simple: importing a PDF creates a Label Studio project where each task displays the document pages and the user can draw boxes on them using rectangle labels, which Label Studio supports for image-style tasks. :contentReference[oaicite:1]{index=1}

## Progress

- [ ] (2026-02-10) Add a new Label Studio import mode for PDF page-image box annotation (project creation + task upload).
- [ ] (2026-02-10) Add a robust “image hosting / accessibility” strategy so the Label Studio container can load page images reliably.
- [ ] (2026-02-10) Add export support that produces stable, benchmark-friendly JSONL with page references and box coordinates.
- [ ] (2026-02-10) Add an end-to-end validation script / command that demonstrates import → annotate → export works on a sample PDF.
- [ ] (2026-02-10) Update repo docs/help text so a novice can use the new mode without understanding internals.

## Surprises & Discoveries

- Observation: Label Studio’s native `Pdf` tag is not generally suitable for “draw boxes on the PDF page” unless you are on Label Studio Enterprise; for Community/Starter Cloud, the official guidance is to convert PDFs to images and use the multi-page document annotation approach. :contentReference[oaicite:2]{index=2}
- Observation: Label Studio supports multi-page document annotation by representing each page as an image and loading them as a paginated multi-image task. :contentReference[oaicite:3]{index=3}

(As you implement, add concrete evidence snippets here: exact Label Studio version, any gotchas with container networking, sample export fragments, etc.)

## Decision Log

- Decision: Default to “convert PDF to page images and annotate with RectangleLabels,” not “annotate PDFs directly.”
  Rationale: This is the broadly supported path across Label Studio distributions and matches Label Studio’s own documentation for non-Enterprise users. :contentReference[oaicite:4]{index=4}
  Date/Author: 2026-02-10 / AI + repo maintainer

(Add future decisions here as they occur.)

## Outcomes & Retrospective

(Leave empty until you complete at least the first milestone; then summarize what works, what remains, and what you learned.)

## Context and Orientation

This repo already integrates Label Studio for benchmarking via `cookimport labelstudio-import ...` and exports labeled results via `cookimport labelstudio-export ...` (as described in the user-provided quick start text). Today’s flows focus on text/block labeling and chunk-based tasks.

This ExecPlan adds a new, separate labeling workflow designed specifically for “draw rectangles on the original PDF pages,” implemented as “draw rectangles on page images.” Label Studio supports drawing rectangles on images using `RectangleLabels`. :contentReference[oaicite:5]{index=5}

Key concept definitions (plain language):

- Page-image conversion: Turning a PDF into a list of page images (one image per page), because Label Studio’s widely-supported box drawing tools operate on images.
- Task: One unit of work in Label Studio. In this workflow, one task represents one entire PDF (multiple pages) so the user keeps document context while labeling. :contentReference[oaicite:6]{index=6}
- Rectangle label: A labeled bounding box drawn by the annotator on an image. :contentReference[oaicite:7]{index=7}
- Golden set: A trusted set of human-created annotations used to evaluate and compare extraction models/pipelines.

## Plan of Work

### Milestone 1: Add a new Label Studio project type for “PDF page boxes”

Goal: A new import mode creates a Label Studio project with a labeling interface designed for bounding boxes over page images, and uploads tasks built from a PDF converted to pages.

What will exist at the end:
- A new Label Studio label config dedicated to page-image box annotation, built around `RectangleLabels` + multi-page image display.
- A new `task-scope` (or parallel command) that generates “page list” tasks for a PDF.

How it should work conceptually:

1) Label config: use Label Studio’s rectangle-on-image capability.
   - The labeling config must include a rectangle labeling control that targets an image viewer. Label Studio’s canonical pattern is `RectangleLabels` pointing at an `Image` tag. :contentReference[oaicite:8]{index=8}
   - For multi-page documents, use the multi-page document annotation pattern: treat the document as a list of images (pages) within one task, with pagination. :contentReference[oaicite:9]{index=9}
   - Keep labels user-focused and stable (the list of allowed labels for boxes should be explicitly named and versionable so golden sets remain comparable over time).

2) Task structure: one task = one PDF = many pages.
   - Convert the PDF into page images at import time.
   - Store those images in the run’s output folder so tasks are reproducible and exports can reference the exact visual source used during labeling.
   - Create a task payload that includes:
     - a list of page image references (in order)
     - document metadata (source filename, a stable document ID / hash, page count)
   - Ensure the page order and naming convention are stable so re-import does not produce drift.

Acceptance for this milestone:
- Running the import mode creates a Label Studio project whose task view shows page 1, page 2, … and the annotator can draw labeled rectangles on any page.

### Milestone 2: Make page images reliably accessible to Label Studio (Docker)

Goal: When Label Studio runs in Docker, it must be able to load the page images referenced by tasks.

This is the core operational challenge, and you should be prescriptive: pick one “default path” and implement it end-to-end, while documenting the fallback.

There are two viable conceptual strategies:

A) “Static server” strategy (recommended default):
- Run a small static file server on the host (the machine running `cookimport`) that serves the generated page images over HTTP.
- In tasks, reference pages as `http://<host-accessible-address>/<path-to-image>`.
- Make sure the Label Studio container can reach the host. Commonly, this means using a host-resolvable address from inside Docker (for example, “host.docker.internal” on many setups) and binding the server to a reachable interface.
- This is robust because it avoids relying on Docker volume layouts inside the container and aligns with Label Studio’s typical “Image points to a URL” usage.

B) “Upload images into Label Studio storage” strategy (fallback):
- Upload page images as files into Label Studio (so they become internal uploads), then reference them using Label Studio’s internal upload paths in task data.
- This can be more portable but requires a clean, repeatable mapping between your run outputs and the uploaded asset references.

Decision criteria:
- Choose (A) unless the repo already has a “task file upload” abstraction that is proven to work with the existing Label Studio client.
- Whichever strategy you choose, add a diagnostic step: a preflight check that fetches the first page image from inside the container (or via Label Studio UI) and fails fast if unreachable.

Acceptance for this milestone:
- A fresh run on a typical dev machine with Label Studio in Docker loads page images with no broken-image placeholders.

### Milestone 3: Export a benchmark-friendly “page boxes” golden set

Goal: Export annotations into a stable, evaluation-ready format.

Requirements for the exported format (conceptual, not code-level):
- Each record should include:
  - document ID / hash (stable across re-runs on the same PDF)
  - page number (1-indexed, stable)
  - bounding box geometry in a clearly defined coordinate system
  - label name
  - optional annotator + timestamp
- Geometry normalization:
  - Prefer normalized coordinates (0–1 relative to page width/height) to avoid differences if images are rendered at different pixel sizes.
  - Also store the original image dimensions used during labeling for traceability.
- Provenance:
  - Store the exact page image identifier (filename or URL) that was labeled, so you can reproduce the same visual later.

You do not need to force one single schema immediately, but you must define it clearly in this plan and implement it consistently. Also define how multiple boxes per page are represented (usually an array of box objects per page).

Acceptance for this milestone:
- Export produces a JSONL (or similar) that a novice can open and see: “doc X, page 12, label RECIPE, box coordinates …”
- Export is idempotent: exporting twice yields equivalent outputs (ordering may be stable-sorted).

### Milestone 4: Integrate into existing CLI/menu flow without disrupting current workflows

Goal: Keep existing pipeline/canonical workflows intact, and add the new workflow as a separate option.

Key behaviors:
- The new mode should:
  - create a separate Label Studio project (distinct naming) so label configs do not collide
  - write artifacts under the existing run folder conventions, with a clear subfolder such as `labelstudio/<book_slug>/page_boxes/` (or equivalent)
  - be safe to re-run (resume behavior) without duplicating tasks or corrupting prior projects

Acceptance for this milestone:
- Existing Label Studio imports/exports still work unchanged.
- The new mode appears as a distinct workflow that produces its own artifacts and exports.

## Concrete Steps

Run everything from the repository root (adjust if the repo uses a different convention). Use indented command blocks in this section, not nested Markdown fences.

1) Start Label Studio in Docker and confirm it is reachable.
   - Start container (existing repo guidance).
   - Confirm you can open the UI and create a project.

2) Convert a sample PDF into page images (as part of the new import mode).
   - Verify generated files exist in the run output directory and the count matches the PDF page count.

3) Run the new import mode to create the “page boxes” project and tasks.
   - Confirm that:
     - the project exists
     - tasks exist
     - opening a task shows page images
     - rectangle drawing is enabled (Label Studio rectangle labeling on images). :contentReference[oaicite:10]{index=10}

4) Label a few boxes across multiple pages.
   - Confirm that multiple boxes per page are supported and saved.

5) Run the new export mode.
   - Confirm export outputs are created in a deterministic location and include document/page/box/label data.

Expected “what you should see” examples (fill in with real values during implementation):
- Task view shows page thumbnails/pagination (multi-page doc pattern). :contentReference[oaicite:11]{index=11}
- Drawing a rectangle prompts label selection and stores a region.

## Validation and Acceptance

Acceptance is a human-verifiable end-to-end scenario:

- Given a PDF cookbook placed in the input folder,
- When the new “Label Studio: PDF Page Boxes” import mode is run,
- Then a Label Studio project is created where:
  - one task corresponds to the PDF
  - the task displays multiple pages as images with pagination
  - the user can draw labeled rectangles on any page (RectangleLabels). :contentReference[oaicite:12]{index=12}
- And when export is run:
  - the output contains at least one record for each drawn rectangle
  - each record includes document ID, page number, label, and normalized box coordinates
  - export is repeatable/idempotent

Also include regression validation:
- Run existing labelstudio import/export flows and confirm their outputs are unchanged.

## Idempotence and Recovery

- Import should support resume semantics:
  - If a project already exists, do not create a second project with the same name unless explicitly requested.
  - If tasks for the same document already exist, do not duplicate them; either skip or reconcile by stable task IDs.
- If image hosting fails (pages not reachable from Label Studio):
  - Provide a clear “preflight failed” error that points to the specific page URL that could not be fetched.
  - Provide a deterministic cleanup path: remove the created project (if appropriate) or allow re-running after fixing networking.

## Artifacts and Notes

Artifacts to persist per run:
- Page images for the PDF, stored under the run output folder.
- A manifest describing:
  - document ID/hash
  - page image list (ordered)
  - mapping from page number → image reference used in tasks
- Task JSONL uploaded to Label Studio.
- Exported golden set JSONL for page boxes.

Keep naming stable and include enough metadata so someone can reconstruct “what was labeled” without opening Label Studio.

## Interfaces and Dependencies

- Label Studio labeling interface:
  - Use `RectangleLabels` for bounding boxes on images. :contentReference[oaicite:13]{index=13}
  - For multi-page PDFs, follow the “convert pages to images, annotate as a multi-page image task” approach described by Label Studio templates and docs. :contentReference[oaicite:14]{index=14}
- Do not depend on Label Studio Enterprise-only PDF features for this workflow unless the repo explicitly targets Enterprise. Label Studio’s docs indicate PDF OCR workflows outside Enterprise require conversion to images. :contentReference[oaicite:15]{index=15}

---

Plan change note (required for living plans):
- (2026-02-10) Initial plan authored to add “draw boxes on PDF pages” golden set workflow by converting PDFs to page images and using Label Studio multi-page image annotation with rectangle labels; chose this route based on Label Studio docs describing rectangle labels and multi-page document annotation patterns. :contentReference[oaicite:16]{index=16}
