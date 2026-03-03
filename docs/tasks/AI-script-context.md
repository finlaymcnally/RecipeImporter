---
summary: "Merged ExecPlan for adding a compact benchmark-context digest and project-context pointers to external-AI cutdown outputs."
read_when:
  - "When changing scripts/benchmark_cutdown_for_external_ai.py flattened summary/readme content."
  - "When adding or modifying project-context metadata in cutdown manifests."
---

# ExecPlan: Add Benchmark Context Digest To External-AI Cutdown

This ExecPlan is a living document. The sections `Progress`, `Surprises & Discoveries`, `Decision Log`, and `Outcomes & Retrospective` must be kept up to date as work proceeds.

This plan must be maintained in accordance with `docs/PLANS.md`.

## Purpose / Big Picture

After this change, a first-time external reviewer opening a cutdown package can understand what is being scored, where Codex vs baseline differences occur in the pipeline, and which artifacts to inspect next without reading the full repository docs first. The package will include a compact benchmark-context digest plus stable pointers to the full onboarding context file.

Today the script produces strong per-run metrics and diagnostics, but it does not include a concise interpretation layer (benchmark semantics, freeform-to-canonical projection bridge, label ontology cheat sheet, pipeline boundary map, and artifact legend). This plan closes that gap with deterministic, low-token output.

## Progress

- [x] (2026-03-03_11.58.00) Audited `scripts/benchmark_cutdown_for_external_ai.py` output flow and confirmed no project-context digest exists in current README/flattened summary.
- [x] (2026-03-03_11.58.00) Consolidated the three raw feedback drafts into an implementation-ready ExecPlan.
- [x] (2026-03-03_00.21.03) Merged prior `AI-script-context.md` draft notes and `AI-script-context2.md` into this single canonical file.
- [x] (2026-03-03_00.26.00) Implemented deterministic context metadata helpers and digest generation in `scripts/benchmark_cutdown_for_external_ai.py`.
- [x] (2026-03-03_00.26.00) Wired `## Project Context Digest` into root README (which also feeds flattened `benchmark_summary.md`).
- [x] (2026-03-03_00.26.00) Added `project_context_*` pointer/hash metadata to `process_manifest.json` and `comparison_summary.json`.
- [x] (2026-03-03_00.26.00) Added regression tests in `tests/bench/test_benchmark_cutdown_for_external_ai.py` for digest presence and metadata stability.
- [x] (2026-03-03_00.27.00) Updated `scripts/README.md` and `docs/07-bench/07-bench_README.md` with the new context-digest contract.
- [x] (2026-03-03_00.28.00) Ran fail-before/pass-after tests, bench-domain subset, and one end-to-end package build; recorded evidence below.
- [x] (2026-03-03_00.35.12) Closed post-review gaps by adding flatten-summary digest assertions, missing-context fallback assertions, and explicit `label_ontology_cheat_sheet` digest coverage.

## Surprises & Discoveries

- Observation: Flattened root summary is generated from the cutdown root `README.md` plus JSON artifacts, then source metadata files are removed from the flattened folder.
  Evidence: `_flatten_output(...)` and `_write_root_summary_markdown(...)` in `scripts/benchmark_cutdown_for_external_ai.py`.

- Observation: Existing outputs already include many run-local clues (`eval_type`, run settings snapshots, prompt-warning aggregates), but there is no explicit explanation of scoring unit/label ontology/projection bridge.
  Evidence: `need_to_know_summary.json` payload from `_build_run_cutdown(...)` and current `_write_readme(...)` content.

- Observation: Root manifest currently has no pointer/hash fields for `docs/AI_Context.md`, so external reviewers cannot tell which context version the package assumed.
  Evidence: `process_manifest` construction in `main()` has no project-context metadata keys.

- Observation: `docs/AI_Context.md` already contains a stable date marker in the H1 (`code-verified on YYYY-MM-DD`), so version extraction can stay deterministic without relying on mutable git state.
  Evidence: top heading in `docs/AI_Context.md` plus helper behavior in `_extract_project_context_version_or_date(...)`.

## Decision Log

- Decision: Implement a compact digest once at package root (README), not per run folder.
  Rationale: Context is package-level and should not duplicate per-run payloads; this keeps token cost low and deterministic.
  Date/Author: 2026-03-03 / Codex

- Decision: Keep digest content deterministic and rule-based in code (no AI summarization/parsing), while exposing pointer/hash metadata for the full context doc.
  Rationale: Project constraints prohibit AI-based parsing/cleaning for this flow and deterministic output is required for regression tests.
  Date/Author: 2026-03-03 / Codex

- Decision: Prefer "always include compact digest" instead of stateful "first run only" behavior across invocations.
  Rationale: The script runs statelessly against arbitrary roots; carrying cross-run state would add complexity/risk for limited benefit.
  Date/Author: 2026-03-03 / Codex

- Decision: Include a projection-bridge note in the digest that explains how freeform benchmark artifacts relate to `canonical_text_classification` scoring outputs.
  Rationale: This was the highest-signal gap identified in feedback and prevents first-pass misdiagnosis of label errors.
  Date/Author: 2026-03-03 / Codex

- Decision: Derive context title/date from markdown content first (H1/front matter), with filesystem mtime fallback only when date markers are absent.
  Rationale: Content-derived metadata stays deterministic across reruns and is robust to missing front matter version keys.
  Date/Author: 2026-03-03 / Codex

## Outcomes & Retrospective

Implemented outcome:
- root cutdown `README.md` now includes a deterministic `## Project Context Digest` section with benchmark contract, projection bridge, pipeline map, backend caveats, artifact legend, and sampling caveats.
- `process_manifest.json` now emits `project_context_path`, `project_context_title`, `project_context_version_or_date`, `project_context_hash`, and `project_context_digest_included`.
- `comparison_summary.json` now emits a `project_context` object with matching pointer/hash metadata.
- tests now lock digest presence in both root README and flattened summary, verify explicit `missing` fallback behavior when `docs/AI_Context.md` is absent, and verify cross-run metadata stability.

Validation confirmed the intended fail-before/pass-after flow and successful end-to-end packaging on a real local benchmark root.

## Context and Orientation

Primary implementation target:

- `scripts/benchmark_cutdown_for_external_ai.py`

Primary regression test target:

- `tests/bench/test_benchmark_cutdown_for_external_ai.py`

Documentation surfaces to update:

- `scripts/README.md`
- `docs/07-bench/07-bench_README.md`
- `docs/AI_Context.md` (reference-only pointer source; content update is optional and only if stale)

Current root cutdown artifacts include `README.md`, `run_index.json`, `comparison_summary.json`, `process_manifest.json`, and pair diagnostics. Flattening turns these into `<output>_md/benchmark_summary.md`.

Terms used in this plan:

- Benchmark context digest: a short, deterministic section that explains benchmark purpose/contract, active pipeline boundary, label semantics, projection assumptions, and artifact interpretation.
- Project-context pointer metadata: `project_context_path`, title/date/version, and content hash that identify the full onboarding doc used as reference.

The merged feedback from both source drafts converges on this scope:

- Include high-value interpretation context inline.
- Keep full repo onboarding content out of the cutdown by default.
- Prefer compact stable pointers to `docs/AI_Context.md` with hash/date for traceability.

## Plan of Work

### Milestone 1: Add deterministic context + pointer helpers

In `scripts/benchmark_cutdown_for_external_ai.py`, add helpers that:

- Read `docs/AI_Context.md` safely (if present).
- Compute a stable SHA-256 hash of file bytes.
- Extract a display title and simple version/date marker (front matter or file mtime fallback).
- Build a compact digest payload from stable facts and observed run data:
  - one-line system summary,
  - benchmark contract (scoring unit and label space framing),
  - freeform-to-canonical projection bridge note,
  - active-path architecture boundary (where LLM is in loop for these runs),
  - active backend/preprocess caveat from run settings,
  - artifact legend and sampling caveat for prompt logs.

Keep this helper deterministic and small (target about 20-40 rendered lines).

### Milestone 2: Wire digest into root output

Update `_write_readme(...)` to append a new section (`## Project Context Digest`) populated from Milestone 1 helper output. This automatically flows into flattened `benchmark_summary.md` because that file embeds README content.

Add matching structured metadata to root JSON artifacts:

- `process_manifest.json` gets `project_context_path`, `project_context_title`, `project_context_version_or_date`, `project_context_hash`, and `project_context_digest_included`.
- `comparison_summary.json` gets a small `project_context` object with the same pointer/hash fields.

### Milestone 3: Test contract hardening

Extend `tests/bench/test_benchmark_cutdown_for_external_ai.py` to assert:

- Root README contains the new digest heading and key lines.
- `process_manifest.json` includes project-context pointer/hash fields.
- `comparison_summary.json` includes project-context metadata.
- Pointer/hash fields remain stable for identical fixture input.

Tests should use temporary fixture runs and avoid dependence on large benchmark roots.

### Milestone 4: Docs alignment

Update docs to describe what is now guaranteed:

- `scripts/README.md`: mention that cutdown outputs now include a compact project/benchmark interpretation digest and context pointer/hash metadata.
- `docs/07-bench/07-bench_README.md`: mention new cutdown context-digest contract and where to find it in output.

Keep updates short and operational.

## Concrete Steps

All commands run from `/home/mcnal/projects/recipeimport`.

1. Implement helper + wiring changes in `scripts/benchmark_cutdown_for_external_ai.py`.

2. Add regression tests in `tests/bench/test_benchmark_cutdown_for_external_ai.py`.

3. Run targeted tests:

    source .venv/bin/activate && pytest tests/bench/test_benchmark_cutdown_for_external_ai.py -q

4. Run bench-domain subset for broader confidence:

    source .venv/bin/activate && ./scripts/test-suite.sh domain bench -k cutdown

5. Generate one local package and verify artifacts:

    source .venv/bin/activate && python scripts/benchmark_cutdown_for_external_ai.py <benchmark_root> --output-dir <cutdown_out> --overwrite --keep-cutdown

6. Spot-check digest and metadata fields:

    source .venv/bin/activate && rg "Project Context Digest|project_context_|benchmark contract|artifact legend|projection" <cutdown_out>/README.md <cutdown_out>/comparison_summary.json <cutdown_out>/process_manifest.json

## Validation and Acceptance

Acceptance is met when:

- Root `README.md` contains a compact deterministic context digest section.
- Flattened `benchmark_summary.md` includes that digest via embedded README content.
- Digest explicitly documents the benchmark contract, label framing, and freeform-to-canonical projection bridge.
- `process_manifest.json` and `comparison_summary.json` include project-context pointer/hash metadata.
- New/updated tests fail before implementation and pass after implementation.
- No AI/LLM-based parsing or cleaning is introduced in this script.

## Idempotence and Recovery

The script remains idempotent with `--overwrite`: rerunning against the same inputs regenerates the same digest and metadata content. If context file metadata is unexpectedly missing (for example `docs/AI_Context.md` absent), helper should emit explicit fallback values (`missing`) rather than failing package build.

If a test fixture breaks due to upstream helper refactor, recover by updating fixture construction in the same test module instead of depending on external benchmark directories.

## Artifacts and Notes

Expected new root-manifest shape:

    {
      "project_context_path": "docs/AI_Context.md",
      "project_context_title": "AI Onboarding & Project Summary",
      "project_context_version_or_date": "2026-03-03",
      "project_context_hash": "<sha256>",
      "project_context_digest_included": true
    }

Expected README section anchor:

    ## Project Context Digest
    - system_summary: ...
    - benchmark_contract: ...
    - projection_bridge: ...
    - active_pipeline_map: ...
    - artifact_legend: ...

Executed validation evidence:

    source .venv/bin/activate && COOKIMPORT_PYTEST_VERBOSE_OUTPUT=1 pytest tests/bench/test_benchmark_cutdown_for_external_ai.py -k "project_context or byte_stable" -vv --tb=short --show-capture=all --assert=rewrite -o addopts=''
    # result: 2 failed before implementation

    source .venv/bin/activate && pytest tests/bench/test_benchmark_cutdown_for_external_ai.py -q
    # result: pass (quiet mode; no failures)

    source .venv/bin/activate && ./scripts/test-suite.sh domain bench -k cutdown
    # result: 10 passed, 168 deselected, 1 warning in 2.17s

    source .venv/bin/activate && python scripts/benchmark_cutdown_for_external_ai.py data/golden/benchmark-vs-golden/2026-03-02_23.33.49/single-offline-benchmark/seaandsmokecutdown --output-dir /tmp/2026-03-03_00.27.46_ai_context_cutdown --overwrite --keep-cutdown
    # result: built cutdown + flattened output, runs processed: 2

    source .venv/bin/activate && rg "Project Context Digest|project_context_|benchmark_contract|artifact_legend|projection_bridge" /tmp/2026-03-03_00.27.46_ai_context_cutdown/README.md /tmp/2026-03-03_00.27.46_ai_context_cutdown/comparison_summary.json /tmp/2026-03-03_00.27.46_ai_context_cutdown/process_manifest.json
    # result: digest heading/keys present; project_context_* fields present with sha256 hash and version/date

## Interfaces and Dependencies

Additive helper interfaces to define in `scripts/benchmark_cutdown_for_external_ai.py`:

    def _project_context_metadata(repo_root: Path) -> dict[str, Any]:
        ...

    def _build_project_context_digest(
        *,
        records: list[RunRecord],
        comparison_summary: dict[str, Any],
        project_context_metadata: dict[str, Any],
        prompt_pairs_per_category: int,
    ) -> list[str]:
        ...

Update call sites:

- `_write_readme(...)` signature extended to receive digest lines (or metadata object) and render the section.
- `main()` process-manifest/comparison-summary assembly extended with project-context pointer/hash fields.

Constraints:

- Use Python stdlib only for hashing/metadata (`hashlib`, file I/O); no new dependencies.
- Keep digest text compact and deterministic.
- Do not introduce any LLM/AI parsing behavior.

Revision note (2026-03-03_00.21.03): Merged the prior unstructured feedback notes from `AI-script-context.md` and the structured draft in `AI-script-context2.md` into one canonical ExecPlan, preserving key requirements and implementation guidance.
Revision note (2026-03-03_00.28.00): Updated this ExecPlan after implementation to mark milestones complete, capture fail-before/pass-after evidence, and document finalized helper signatures/metadata contract.
