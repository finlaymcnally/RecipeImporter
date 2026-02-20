---
summary: "Staging architecture/build/fix-attempt log used to avoid repeated dead ends and circular debugging."
read_when:
  - When you are going in multi-turn circles on staging behavior or implementation
  - When the human says "we are going in circles on this"
  - When you need historical architecture versions, build attempts, and known failed paths before trying another change
---

# Staging Log: Architecture, Builds, and Fix Attempts

Read this file when work starts looping across turns, or when someone says "we are going in circles on this."

This log is the anti-loop record for staging: what changed, why, what worked, and what remains risky.

## Chronology: What Was Documented/Tried Before

This section preserves the historical task notes that were previously in `05-staging_readme.md`.

### Baseline staging section doc (non-timestamped, prior summary)

Contained initial map of:

- code locations,
- output surfaces,
- links to contract/naming notes.

Status now: superseded by the readme, but key map retained and expanded there.

### 2026-02-12_10.25.47 format naming conventions

Decision captured:

- Use `schema.org Recipe JSON` for intermediate and `cookbook3` for final in docs/help text.
- Do not describe intermediate format as `RecipeSage`.
- `RecipeDraftV1` remains internal term.

Status now: still correct and reflected in current CLI help text (`cookimport/cli.py:322`, `cookimport/cli.py:1515`).

### 2026-02-12_10.41.48 staging contract alignment

Problem captured:

- Final draft output drifted from Cookbook staging import invariants.
- Failures occurred even after resolver normalization.

Key decisions/actions captured:

- Normalize ingredient lines in `draft_v1.py` post-parse/post-assignment.
- Do not generate random UUIDs for unresolved ingredient IDs.
- Preserve lowercasing and step-linking behavior.

Recorded evidence at that time:

- `pytest -q tests/test_draft_v1_lowercase.py tests/test_draft_v1_variants.py tests/test_ingredient_parser.py tests/test_draft_v1_staging_alignment.py`
- Result recorded: `35 passed`.
- Cross-repo schema validation cases recorded as passing for:
  - `salt, to taste`
  - `0`
  - `1 cup flour`

Status now: rules still present in current `draft_v1.py` and corresponding tests remain in repo.

### 2026-02-12_10.41.48 staging contract edge cases

Critical invariant note captured:

- Cookbook staging tolerates unresolved IDs if placeholders are non-empty and unresolved unit IDs are `null`.
- But quantity invariants are strict:
  - `exact`/`approximate` require `input_qty > 0`
- `unquantified` must have null/omitted quantity+unit

Status now: these edge-case rules are still actively normalized in `draft_v1.py`.

### 2026-02-15_22.10.59 staging output contract flow map

Merged source file:
- `2026-02-15_22.10.59-staging-output-contract-flow.md` (formerly in `docs/understandings`)

Preserved outcomes:
- Single-file stage flow (`cli_worker`) and split-job merge flow (`cli.py`) both converge on the same writer functions for intermediate/final/tips/topic/chunks/report outputs.
- Split jobs add one extra step: move raw artifacts from `.job_parts/<workbook>/job_<index>/raw/...` into run `raw/...`.
- Cookbook safety normalization remains in `draft_v1.py` (ingredient line shaping), not in writer functions.
- Historical staging failures were primarily quantity-kind/qty invariant violations, not unresolved ID placeholder handling.

### 2026-02-15_22.48.59 report metadata flow consistency

Merged source file:
- `2026-02-15_22.48.59-report-metadata-flow.md` (formerly in `docs/understandings`)

Preserved rule:
- Single-file report writes happen in `cli_worker.stage_one_file`.
- Split EPUB/PDF report writes happen in `cli._merge_split_jobs`.
- Metadata fields that downstream tooling depends on (notably `importerName` and `runConfig`) must be set in both paths or split runs will silently drift.

### 2026-02-15_22.59.48 split-merge bottleneck diagnosis from real run data

Merged source file:
- `2026-02-15_22.59.48-split-merge-write-topic-candidates-bottleneck.md` (formerly in `docs/understandings`)

Preserved diagnosis:
- Long "idle" periods after worker completion can be real merge output work, not a deadlock.
- Example captured from `data/output/2026-02-15_22.47.11`: one EPUB merge spent about 172 seconds in `write_topic_candidates_seconds`.
- Root cause in that run shape was repeated `_resolve_file_hash(...)` fallback hashing for candidates missing `file_hash`.

Anti-loop note:
- Do not treat post-100%-progress hangs as automatic concurrency bugs until merge-phase timing fields are checked.
- Do not remove topic-candidate provenance to speed up writes; keep provenance and cache hash lookup instead.

### 2026-02-15_22.59.30 split-merge visibility and topic hash cache

Merged source:
- `docs/tasks/2026-02-15_22.59.30 - split-merge-visibility-and-topic-hash-cache.md`

Problem captured:
- Large split EPUB/PDF runs could look hung after workers completed because merge stayed under a generic MainProcess label while doing long post-merge writes.
- Topic-candidate writing repeatedly hashed the same source file, inflating merge-time write cost on knowledge-heavy inputs.

Decisions/actions captured:
- Add phase-level main-process status updates across merge/report/raw/topic-candidate write phases.
- Cache source hash resolution per source file during topic-candidate ID generation so `_hash_file` runs once per file version, not once per candidate.

Task-spec evidence preserved:
- Fail-before command recorded:
  - `. .venv/bin/activate && pytest -q tests/test_tip_writer.py::test_write_topic_candidates_hashes_source_file_once tests/test_split_merge_status.py::test_merge_split_jobs_reports_main_process_phases`
- Pass-after command recorded:
  - `. .venv/bin/activate && pytest -q tests/test_tip_writer.py tests/test_split_merge_status.py`
- Recorded pass-after result: `3 passed`.

Constraints that should remain:
- Keep split merge output contract unchanged (same files, IDs, and artifact structure).
- Merge progress/status callbacks must be best-effort and never allowed to fail the merge itself.

Rollback note captured in task:
- Removing callback plumbing and hash caching reverts to prior behavior where long merges appear stalled and topic-candidate writes can re-hash per candidate.

## Known Bad Patterns and Anti-Regression Notes

These are the loops we should avoid repeating.

1. Using random UUIDs for unresolved `ingredient_id`
- Why bad: bypasses resolver mapping semantics and can mask true unresolved state.
- Keep: unresolved placeholder should remain meaningful raw text fallback.

2. Letting `approximate`/`exact` lines through with missing/non-positive quantity
- Why bad: Cookbook staging contract rejects these combinations.
- Keep: downgrade to `unquantified` during staging conversion.

3. Emitting unresolved `input_unit_id` as non-null fake value
- Why bad: can violate staging import expectations and creates false precision.
- Keep: `input_unit_id = null` when unresolved; preserve `raw_unit_text`.

4. Leaking section headers into ingredient lines
- Why bad: section headers are structural and invalid as ingredient entries.
- Keep: remove `section_header` lines before final output.

5. Re-hashing the same source file for every topic candidate
- Why bad: adds avoidable merge-time write overhead, especially on knowledge-heavy split runs.
- Keep: source-hash cache behavior in topic-candidate write path.

6. Reporting only a generic merge status after worker completion
- Why bad: long post-merge phases can look like a hang and trigger false debugging loops.
- Keep: phase-level merge status callbacks for report/raw/topic-candidate stages.
