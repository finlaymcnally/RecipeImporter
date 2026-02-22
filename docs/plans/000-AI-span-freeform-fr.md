---
summary: "ExecPlan and implementation record for freeform prelabel span-mode with legacy block-mode compatibility."
read_when:
  - "When changing freeform AI prelabel parsing/resolution modes"
  - "When updating interactive Label Studio freeform prelabel prompts"
---

# ExecPlan: Upgrade freeform AI prelabeling from block-level to true span-level highlighting

This ExecPlan is a living document. The sections `Progress`, `Surprises & Discoveries`, `Decision Log`, and `Outcomes & Retrospective` must be kept up to date as work proceeds.

This plan must be maintained in accordance with `docs/PLANS.md`.

## Purpose / Big Picture

After this change, freeform prelabeling supports two operator-selectable modes:

1. `span` (actual freeform): the model can label partial text spans inside a block.
2. `block` (legacy, block based): the old one-label-per-block behavior.

User-visible outcome: in interactive Label Studio import, once AI prelabel mode is enabled, the user can choose between these two labeling styles and proceed with the same upload flow.

## Progress

- [x] (2026-02-22 17:25Z) Read `docs/PLANS.md`, `docs/02-cli/02-cli_README.md`, `docs/06-label-studio/06-label-studio_README.md`, and current prelabel runtime (`cookimport/labelstudio/prelabel.py`, `cookimport/labelstudio/ingest.py`, `cookimport/cli.py`).
- [x] (2026-02-22 17:28Z) Added prelabel granularity contract (`block|span`) and normalization aliases in `cookimport/labelstudio/prelabel.py`.
- [x] (2026-02-22 17:30Z) Implemented span-mode parsing schema (`quote` + optional `occurrence`, optional validated absolute `start/end`) with deterministic offset resolution against segment/block text.
- [x] (2026-02-22 17:31Z) Added span-mode prompt template selection and new file-backed template `llm_pipelines/prompts/freeform-prelabel-span.prompt.md`.
- [x] (2026-02-22 17:32Z) Wired `prelabel_granularity` through ingest runtime (`generate_pred_run_artifacts`, `run_labelstudio_import`) and persisted it in `prelabel_report.json` summary payload.
- [x] (2026-02-22 17:34Z) Added non-interactive CLI flag `--prelabel-granularity` and interactive selector shown immediately after AI prelabel mode choice.
- [x] (2026-02-22 17:35Z) Added/updated tests for parser behavior, span resolution, ingest plumbing, and interactive routing.
- [x] (2026-02-22 17:36Z) Updated docs and conventions for the dual-mode contract.
- [ ] (2026-02-22 17:36Z) Manual live Label Studio smoke run still pending.

## Surprises & Discoveries

- Observation: quote-based span resolution needs explicit ambiguity handling, because repeated substrings in a block cannot be resolved safely without an occurrence index.
  Evidence: `tests/test_labelstudio_prelabel.py::test_span_resolution_requires_occurrence_for_ambiguous_quote`.

- Observation: span-mode can still produce valid sub-block highlights even when one span ends at block end; the meaningful invariant is “not forced to full-block coverage,” not “must be strictly interior on both ends.”
  Evidence: `tests/test_labelstudio_prelabel.py::test_prelabel_freeform_task_span_mode_creates_partial_block_spans`.

## Decision Log

- Decision: keep `block` as default mode and make `span` opt-in.
  Rationale: avoids changing existing prelabel behavior for current workflows and preserves backward compatibility.
  Date/Author: 2026-02-22 / Codex

- Decision: use quote-anchored span schema as primary mode (`block_index`, `label`, `quote`, optional `occurrence`).
  Rationale: models are weak at raw offset counting; quote matching against deterministic block slices keeps offsets stable.
  Date/Author: 2026-02-22 / Codex

- Decision: support absolute `start/end` selections only as a validated fallback.
  Rationale: keeps parser forward-compatible while preserving strict offset validation in runtime.
  Date/Author: 2026-02-22 / Codex

- Decision: interactive style labels are operator-language focused (`actual freeform` vs `legacy, block based`) while runtime values remain stable (`span`/`block`).
  Rationale: UX clarity without changing internal API contract.
  Date/Author: 2026-02-22 / Codex

## Outcomes & Retrospective

Implemented and shipped in code:

- True span-mode parsing and deterministic resolution in `cookimport/labelstudio/prelabel.py`.
- Legacy block-mode retained and explicitly named in interactive flow.
- End-to-end mode plumbing across CLI and ingest (`prelabel_granularity`).
- New span prompt template in `llm_pipelines/prompts/`.
- Documentation updates in CLI + Label Studio + conventions + template instructions.

Remaining:

- Manual Label Studio UI smoke validation of span-mode highlights in a live project.

## Context and Orientation

Key files touched by this plan:

- Runtime parser/resolution: `cookimport/labelstudio/prelabel.py`
- Artifact generation and upload orchestration: `cookimport/labelstudio/ingest.py`
- Interactive and non-interactive CLI wiring: `cookimport/cli.py`
- Span-mode template: `llm_pipelines/prompts/freeform-prelabel-span.prompt.md`
- Tests: `tests/test_labelstudio_prelabel.py`, `tests/test_labelstudio_ingest_parallel.py`, `tests/test_labelstudio_benchmark_helpers.py`
- Operator docs: `docs/02-cli/02-cli_README.md`, `docs/06-label-studio/06-label-studio_README.md`, `docs/06-label-studio/AI-labelling-instructions.md`, `docs/IMPORTANT CONVENTIONS.md`

## Plan of Work

1. Add dual-mode prelabel granularity contract and keep old behavior as default.
2. Implement span-schema parsing and deterministic quote resolution into Label Studio result offsets.
3. Wire granularity through ingest and CLI (flags + interactive prompt).
4. Add tests that prove:
   - span parsing accepts quote and absolute item shapes,
   - span mode creates multi-span/same-block outputs,
   - ambiguity requires `occurrence`,
   - ingest and interactive flow pass granularity through.
5. Update docs and conventions to match new UX and runtime contracts.

## Concrete Steps

Run from repo root:

    source .venv/bin/activate
    pip install -e .[dev]
    pytest -q tests/test_labelstudio_prelabel.py tests/test_labelstudio_ingest_parallel.py tests/test_labelstudio_benchmark_helpers.py
    pytest -q tests/test_cli_llm_flags.py

## Validation and Acceptance

Acceptance criteria met in tests:

- Span parser and resolver tests pass (`tests/test_labelstudio_prelabel.py`).
- Ingest runtime propagates `prelabel_granularity` and records it (`tests/test_labelstudio_ingest_parallel.py`).
- Interactive freeform flow maps style picker to runtime arg (`tests/test_labelstudio_benchmark_helpers.py`).
- Existing CLI LLM flag smoke test still passes (`tests/test_cli_llm_flags.py`).

Manual acceptance still pending:

- Live Label Studio run verifying highlight rendering for span mode.

## Idempotence and Recovery

- Safe fallback: run with `--prelabel-granularity block` or pick `legacy, block based` interactively.
- Cache reset: delete `prelabel_cache/` under run root to force fresh completions.
- Failure handling remains unchanged: unresolved selections are dropped at item level; task-level strictness still controlled by `--prelabel-allow-partial`.

## Artifacts and Notes

- New prompt template file: `llm_pipelines/prompts/freeform-prelabel-span.prompt.md`.
- Prelabel reports now include `granularity` for easier run auditing.

Revision note (2026-02-22): Replaced design-only draft with implementation-complete record for the shipped `span|block` prelabel granularity feature, including interactive UX contract naming requested by the user.
