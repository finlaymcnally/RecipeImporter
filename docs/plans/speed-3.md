# Avoid redundant canonical alignment in canonical-text evaluation

This ExecPlan is a living document. The sections `Progress`, `Surprises & Discoveries`, `Decision Log`, and `Outcomes & Retrospective` must be kept up to date as work proceeds.

PLANS.md is checked into the repo at `PLANS.md` from the repository root, and this plan must be maintained in accordance with it. :contentReference[oaicite:0]{index=0}:contentReference[oaicite:1]{index=1}


## Purpose / Big Picture

After this change, running `cookimport labelstudio-benchmark --eval-mode canonical-text` as part of an all-method sweep will avoid re-running the expensive “canonical alignment” step (full-book `difflib.SequenceMatcher`) when the exact same prediction text stream (same extracted blocks and boundaries) is being scored again. This preserves accuracy because we only reuse an alignment result when the inputs are identical; we do not change the alignment algorithm or loosen correctness constraints.

You can see it working by looking at `eval_report.json` `evaluation_telemetry`: the first time a particular (prediction text stream, canonical gold text) pair is evaluated you’ll see a cache miss and a large `alignment_sequence_matcher_seconds`; subsequent evaluations with the same text stream will show `alignment_cache_hit=true` and `alignment_sequence_matcher_seconds` near zero while the final metrics and diagnostics remain identical. Canonical-text evaluation is currently dominated by this alignment cost. :contentReference[oaicite:2]{index=2}:contentReference[oaicite:3]{index=3}


## Progress

- [x] (2026-02-27 00:13Z) Drafted ExecPlan for “avoid redundant canonical alignment” implementation.
- [ ] Implement disk-backed alignment cache and integrate into canonical evaluator (cache miss → compute legacy SequenceMatcher alignment; cache hit → load and reuse).
- [ ] Make cache safe under concurrency (multiple worker processes) and safe under corruption/stale locks (fallback to recompute).
- [ ] Wire all-method execution so all configs for the same source share an alignment cache directory.
- [ ] Add tests that prove: (1) metrics/diagnostics are unchanged, (2) cache hit path is exercised, (3) cache key invalidation works when inputs differ.
- [ ] Run a small all-method sweep and capture before/after eval telemetry snippets demonstrating cache hits.


## Surprises & Discoveries

- Observation: Canonical-text benchmark runtime is overwhelmingly evaluation-bound, and evaluation is overwhelmingly alignment-bound; within alignment, the full-book `SequenceMatcher` dominates. This makes “avoid repeated alignment” one of the few accuracy-preserving changes with potentially large impact.  
  Evidence: `evaluation_seconds / total_seconds` median ~94.48%, `evaluate_alignment_seconds / evaluation_seconds` median ~0.9958, and `sequence_matcher_seconds / alignment_seconds` median ~0.9996 in the Feb 25–26 data. :contentReference[oaicite:4]{index=4}

- Observation: Canonical-text scoring aligns a prediction “block text stream” (`extracted_archive.json`) to canonical gold text and then projects labels; the expensive alignment depends only on the text stream + boundaries, not on per-block label values. This makes cross-config reuse possible when multiple configs share the same extracted text stream.  
  Evidence: canonical scoring surface inputs and scoring description. :contentReference[oaicite:5]{index=5}

- Observation: The evaluator’s fast/bounded alignment path is intentionally deprecated and forced to legacy for accuracy. This plan must not re-enable or approximate alignment; caching is strictly “reuse identical results.”  
  Evidence: evaluator notes about legacy enforcement and fast-path deprecation. :contentReference[oaicite:6]{index=6}


## Decision Log

- Decision: Implement an accuracy-preserving, content-addressed alignment cache that reuses a previously computed *legacy* alignment result when and only when the canonical normalized text, prediction normalized text, and prediction block-boundary layout are identical.  
  Rationale: This avoids redundant `SequenceMatcher` work without changing the algorithm. Block boundaries are included because two different block segmentations could (in rare cases) produce the same concatenated text, yet require different per-block projection mapping.  
  Date/Author: 2026-02-27 / GPT-5.2 Pro

- Decision: Make caching opt-in by passing an explicit cache directory from the all-method runner (shared per source), rather than enabling a global cache by default.  
  Rationale: This keeps scope tight, prevents unbounded cache growth, and makes the behavior easy to reason about: “in all-method, configs for the same source share alignment results.” It also reduces the risk of surprising behavior changes in single-offline benchmark runs.  
  Date/Author: 2026-02-27 / GPT-5.2 Pro

- Decision: Use an atomic write + lock-file protocol so multiple worker processes don’t all compute the same alignment concurrently, and so partial writes never get consumed.  
  Rationale: All-method runs are multi-process; without coordination, cache misses at startup could still duplicate alignment work. Atomic writes prevent corrupted cache entries from being treated as hits.  
  Date/Author: 2026-02-27 / GPT-5.2 Pro

- Decision: Store the cached payload as a versioned JSON (optionally gzipped) representation of the *post-SequenceMatcher* alignment result that the evaluator already consumes (for example: a “prediction-block → canonical-span/line-range mapping” structure), rather than storing raw difflib internals.  
  Rationale: This minimizes coupling to Python’s difflib implementation details and makes cache validation straightforward (“does this mapping match the expected signatures?”). It also lets the evaluator skip both `SequenceMatcher` and any expensive post-processing that derives the mapping.  
  Date/Author: 2026-02-27 / GPT-5.2 Pro


## Outcomes & Retrospective

(Empty until implementation work is completed. At the end of Milestone 2, record the observed cache hit rate on a real all-method run and the measured wall-time reduction.)


## Context and Orientation

This repository has two benchmark evaluation modes: `stage-blocks` and `canonical-text`. Canonical-text is used for extractor-permutation sweeps because it aligns prediction text to a canonical gold text representation rather than requiring exact blockization parity. :contentReference[oaicite:7]{index=7}

In canonical-text evaluation:

- Predictions come from two files in the prediction-run artifacts:  
  - `stage_block_predictions.json`: one label per `block_index` (the predicted label values).  
  - `extracted_archive.json`: the prediction block text stream (the text content per block, in order) used for alignment. :contentReference[oaicite:8]{index=8}

- Gold comes from canonical export artifacts under `<gold_dir>/exports/`:  
  - `canonical_text.txt` (the gold canonical text),  
  - `canonical_span_labels.jsonl` (gold labels projected to spans/lines),  
  - `canonical_manifest.json` (+ block map). :contentReference[oaicite:9]{index=9}

- Scoring conceptually does three steps:  
  1) align the prediction text stream to the canonical gold text using a legacy full-book alignment,  
  2) project predicted block labels onto canonical text lines using the alignment mapping,  
  3) compare predicted line labels to gold line labels and write metrics + diagnostics. :contentReference[oaicite:10]{index=10}

The expensive part is the alignment in `cookimport/bench/eval_canonical_text.py`, which normalizes the full prediction and canonical text and runs a global `difflib.SequenceMatcher`. The fast/bounded alignment path is deprecated and forced to legacy for accuracy. :contentReference[oaicite:11]{index=11}

Definitions used in this plan:

- “Prediction block”: a contiguous chunk of extracted text assigned a `block_index`. Prediction labels are per block, and the prediction text stream is the ordered concatenation of these block texts.
- “Canonical text”: the gold reference text (`canonical_text.txt`) that acts as the alignment target.
- “Canonical alignment”: the process of computing a deterministic mapping from positions in the prediction text stream to positions in the canonical text, using full-book `SequenceMatcher` legacy alignment.
- “Alignment mapping”: the concrete data structure the evaluator uses after `SequenceMatcher` to project each prediction block onto one or more canonical text ranges/lines.

The goal of this change is to compute that alignment mapping once per unique (canonical text, prediction text stream + boundaries) pair and reuse it across subsequent evaluations, which is common in all-method sweeps where multiple configs may share identical extracted text but differ in downstream labeling logic.


## Plan of Work

### Milestone 1: Add a versioned, disk-backed alignment cache in the canonical evaluator

At the end of this milestone, canonical evaluation can be passed an `alignment_cache_dir`, and when enabled it will read/write an alignment cache entry keyed by the canonical + prediction text signatures. Running the evaluator twice with the same inputs should produce identical metrics/diagnostics, while the second run should skip `SequenceMatcher` and record a cache hit.

Work (code changes):

1) Identify where alignment is computed. Start by opening:

   - `cookimport/bench/eval_canonical_text.py` and locate:
     - `evaluate_canonical_text(...)` (reported around line ~991). :contentReference[oaicite:12]{index=12}
     - The helper that performs alignment, likely named `_align_prediction_blocks_to_canonical(...)` (mentioned in docs as the SequenceMatcher hotspot). :contentReference[oaicite:13]{index=13}

   The caching should wrap the “SequenceMatcher + block mapping” portion, because that is the expensive part and (critically) depends only on text + boundaries, not on labels.

2) Define a cache entry schema and key derivation.

   Create a new module: `cookimport/bench/canonical_alignment_cache.py` (or keep it in `eval_canonical_text.py` if the project style prefers single-file locality; choose one and be consistent). This module should contain:

   - A constant `CANONICAL_ALIGNMENT_CACHE_SCHEMA_VERSION = "canonical_alignment_cache.v1"`.
   - A function `sha256_text(s: str) -> str` that returns hex SHA-256 of UTF-8 bytes.
   - A function `hash_block_boundaries(boundaries: list[tuple[int,int]]) -> str` that hashes a stable JSON encoding of normalized block start/end offsets.
   - A Pydantic model (or dataclass) `CanonicalAlignmentCacheEntry` that includes:
     - `schema_version` (string literal),
     - `created_at` (ISO timestamp),
     - `alignment_strategy` (should always be `"legacy"`),
     - `canonical_normalized_sha256`,
     - `prediction_normalized_sha256`,
     - `prediction_block_boundaries_sha256`,
     - `canonical_normalized_char_count`,
     - `prediction_normalized_char_count`,
     - `payload` (the alignment mapping object serialized as JSON),
     - optional: `python_version` and `repo_alignment_algo_version` for additional invalidation safety.

   Cache key and validation must include the normalization settings implicitly. If normalization logic has a single function, treat that function as part of the “algo version”: define `NORMALIZATION_VERSION = 1` and bump it any time normalization behavior changes. Store it in the cache entry and incorporate it into the file name.

3) Decide what “payload” is.

   The payload should be the exact alignment mapping object used by downstream projection. Concretely, you want to cache the output of the alignment step *after* SequenceMatcher and any block-to-canonical mapping post-processing. The payload should include enough to:
   - project each prediction block onto canonical text line(s),
   - reproduce diagnostics like `unmatched_pred_blocks.jsonl` and `alignment_gaps.jsonl` if those are derived from the mapping.

   Implementation approach:
   - If the alignment step already returns a Pydantic model (recommended), store `payload = alignment_result.model_dump(mode="json")` and restore with `AlignmentResult.model_validate(payload)`.
   - If it is a dict/list structure, store it directly as JSON, but add strict validation on load (types, lengths, required keys) and compare signatures before using.

4) Add a disk cache API with concurrency control.

   In `canonical_alignment_cache.py`, implement:

   - `CanonicalAlignmentDiskCache(cache_dir: Path, *, wait_seconds: int = 3600)` with methods:
     - `cache_path_for_key(key: str) -> Path` that creates a filesystem-safe name (use prefixes of hashes to avoid super long filenames).
     - `try_load(key: str, expected_signatures: ...) -> AlignmentResult | None`:
       - If cache file missing: return None.
       - If present: load JSON (gzip if used), validate schema_version, validate signatures, validate payload, then return AlignmentResult.
       - If validation fails: treat as miss (and optionally move the file aside as `.corrupt`).
     - `lock_for_key(key: str)` context manager:
       - Lock file path like `<cache_path>.lock`.
       - Acquire by atomic create (`os.open(..., O_CREAT|O_EXCL)`), writing pid+timestamp into the lock file.
       - If lock exists, poll for the cache file to appear. If lock is older than `wait_seconds`, consider it stale: delete lock and try to acquire again.
     - `write_atomic(key: str, entry: CanonicalAlignmentCacheEntry) -> None`:
       - Write to `tmp` file in same directory, fsync, then `os.replace(tmp, final)` for atomic commit.
       - If another process already wrote the final file, `os.replace` will overwrite; avoid that by checking existence first inside the lock, or by writing to a unique tmp and then doing a “create-if-not-exists” finalization (prefer: inside lock, check again; if exists, skip writing).

5) Integrate into `_align_prediction_blocks_to_canonical(...)`.

   Update the alignment function signature to accept `alignment_cache_dir: Path | None` (or a `CanonicalAlignmentDiskCache | None`).

   Flow inside the function should be:

   - Compute normalized canonical text and normalized prediction text as it does today (do not change normalization behavior).
   - Build a normalized prediction “block boundary list”: for each prediction block, the (start_offset, end_offset) range of that block in the concatenated normalized prediction text.
   - Derive:
     - `canon_hash = sha256_text(normalized_canonical_text)`
     - `pred_hash = sha256_text(normalized_prediction_text)`
     - `boundaries_hash = hash_block_boundaries(boundaries)`
   - If `alignment_cache_dir` is provided:
     - Create/ensure directory exists.
     - Derive a cache key from `(schema_version, normalization_version, alignment_strategy="legacy", canon_hash, pred_hash, boundaries_hash)`.
     - Attempt `try_load(...)`.
       - On hit: return loaded mapping, and record telemetry fields (see below).
     - On miss: acquire lock, check again for a cache file (another worker might have populated it), compute alignment as today, then write cache entry.

   Important: do not bypass any existing “gold/prediction compatibility checks” that happen before alignment (for example blockization mismatch guardrails). Caching should only happen after inputs are known-good.

6) Add telemetry fields to `evaluation_telemetry`.

   Wherever canonical eval currently records micro-telemetry (alignment subphases exist today), add:

   - `alignment_cache_enabled: bool`
   - `alignment_cache_hit: bool`
   - `alignment_cache_key: str` (or a shortened form like first 12 chars of each hash, to avoid huge JSON)
   - `alignment_cache_load_seconds: float`
   - `alignment_cache_write_seconds: float`
   - `alignment_cache_validation_error: str | null` (optional, only populated when a cache file exists but is rejected)

   Keep existing `alignment_sequence_matcher_seconds` semantics:
   - On cache hit: set it to `0.0` (or omit) and add a new field explicitly indicating it was skipped due to cache.
   - On cache miss: preserve the measured time.

   This is important because downstream performance analysis relies on `evaluation_telemetry` richness. :contentReference[oaicite:14]{index=14}

Acceptance for Milestone 1 (proof):

- A targeted test (added in Milestone 3 below) shows that for identical inputs, the second evaluation path is a cache hit and produces identical metrics/diagnostics.
- Manual run: running the same canonical-text evaluation twice with the same prediction artifacts and same gold, with caching enabled, produces:
  - identical `overall_*` metrics fields and identical diagnostic JSONL contents,
  - telemetry showing cache hit on second run and near-zero `alignment_sequence_matcher_seconds`.


### Milestone 2: Enable cache sharing in all-method runs (per-source shared cache directory)

At the end of this milestone, configs in the same all-method source sweep share a cache directory so that if multiple configs produce the same extracted text stream, only the first one pays the SequenceMatcher alignment cost.

Work (code changes):

1) Identify the all-method execution site.

   In `cookimport/cli.py`, locate `_run_all_method_config_once(...)` (noted around `cookimport/cli.py:4502` in the performance report) and the all-method runtime resolution helpers. :contentReference[oaicite:15]{index=15}

   Find the point where a config run invokes the benchmark evaluation (it likely calls into the same internal function that backs `cookimport labelstudio-benchmark`).

2) Decide the cache directory path for a given source.

   Use a directory that is shared by all config runs for the same source within an all-method root, and that is safe to delete when the run is done. Recommended:

   - `<all_method_source_root>/.cache/canonical_alignment/`

   The `<all_method_source_root>` should be the same directory where the per-source report is written (for example `all_method_benchmark_source_report.json`), so it’s naturally grouped.

3) Pass the cache dir down to evaluation.

   Thread `alignment_cache_dir` through the call chain:

   - all-method config runner → benchmark run wrapper → `evaluate_canonical_text(...)` → `_align_prediction_blocks_to_canonical(...)`.

   If the public Typer CLI function signature for `labelstudio-benchmark` would unintentionally expose a new CLI option, keep the new parameter confined to internal helper functions. If you cannot avoid passing through Typer’s command function, mark the option hidden (Typer supports hidden options) and document it as internal-only.

4) Ensure cache is only enabled for canonical-text mode.

   The cache directory should be ignored in stage-block mode (no-op), and only canonical-text should use it.

Acceptance for Milestone 2 (proof):

- Run a small all-method sweep for a single source where at least two configs share extracted text. On the first matching config:
  - telemetry shows `alignment_cache_hit=false` and large alignment time.
  On the subsequent matching config(s):
  - telemetry shows `alignment_cache_hit=true` and the alignment time is skipped.
- Metrics remain unchanged relative to a run with caching disabled (verify by re-running one config with cache disabled and comparing `eval_report.json` metrics and diagnostics).


### Milestone 3: Add regression tests proving correctness + cache hits

At the end of this milestone, automated tests prevent any regression where caching changes metrics/diagnostics or incorrectly reuses mismatched alignments.

Work (tests):

1) Find existing canonical eval tests and fixtures.

   Use ripgrep to locate tests that mention canonical evaluation or `evaluate_canonical_text`:

   - Search: `rg -n "evaluate_canonical_text|canonical-text|canonical_text.txt|alignment_gaps" tests/`

   If there are no existing canonical fixtures, create a minimal synthetic fixture in the test itself:
   - canonical text with a few lines and clear boundaries,
   - prediction blocks that concatenate to something similar but not identical (so alignment is non-trivial),
   - a simple stage_block_predictions mapping.

2) Add a unit test for cache key validation.

   New test file: `tests/bench/test_canonical_alignment_cache.py` with a test that:

   - Creates a temp cache dir.
   - Calls the alignment function with caching enabled twice on identical inputs:
     - asserts second run reports cache hit (either via returned telemetry object or by inspecting evaluation_telemetry).
     - asserts the alignment mapping object is identical.
   - Mutates one of:
     - canonical text content, or
     - prediction block boundary layout (same concatenated text but different boundaries), or
     - normalization version (by overriding constant in test if feasible),
     and asserts this produces a cache miss (alignment recomputed) rather than reusing the old mapping.

3) Add an end-to-end evaluator test.

   If the project already has an integration fixture directory for bench/eval, write a test that runs `evaluate_canonical_text(...)` twice with caching enabled and compares:
   - `eval_report.json` metrics equality,
   - contents of diagnostics JSONLs equality.

   When comparing, ignore timing fields (they will differ). Compare the “meaningful” fields: metrics, confusion/mismatch lists, and diagnostics files.

Acceptance for Milestone 3 (proof):

- `pytest` passes locally and in CI.
- At least one new test fails on the pre-cache codebase (because cache-hit telemetry can’t occur) and passes once caching is implemented.


## Concrete Steps

Run these commands from the repository root (the directory that contains `cookimport/` and `tests/`). Use a virtual environment consistent with the project’s usual workflow.

1) Baseline: run the test suite subset that covers bench/eval.

    $ pwd
    /path/to/repo
    $ pytest -q

   If the full suite is large, focus on bench tests first:

    $ pytest -q tests/bench

2) Implement Milestone 1 in small commits:

   After implementing the cache module and integrating it into `_align_prediction_blocks_to_canonical`, run:

    $ pytest -q tests/bench/test_canonical_alignment_cache.py -k cache

   Expected shape of output:

    1 passed in 0.XXs

3) Implement Milestone 2 wiring:

   Run a single canonical-text benchmark with caching enabled (whatever the project’s normal invocation is). You should be able to find `eval_report.json` under the eval output root.

   Then run the same benchmark again (or run a second config that shares extracted text) and compare:

   - `evaluation_telemetry.alignment_cache_hit` changes from `false` to `true`.
   - `alignment_sequence_matcher_seconds` is skipped/near-zero on the hit.
   - All non-timing metrics remain identical.

   Example “what to look for” in `eval_report.json` (names are illustrative; use the real JSON paths):

    evaluation_telemetry:
      alignment_cache_enabled: true
      alignment_cache_hit: true
      alignment_cache_key: "v1/legacy/norm1/canon=.../pred=.../b=..."
      alignment_sequence_matcher_seconds: 0.0

4) Capture evidence for Surprises & Discoveries:

   Paste a short snippet of the before/after `evaluation_telemetry` (just the alignment-related fields) into this ExecPlan’s `Surprises & Discoveries` section, and update `Progress` with timestamps.


## Validation and Acceptance

This change is accepted when all of the following are true:

- Correctness: For identical canonical gold + identical prediction text stream + identical block boundaries, evaluation produces identical:
  - metrics in `eval_report.json`,
  - diagnostic JSONL contents (`missed_gold_lines.jsonl`, `wrong_label_lines.jsonl`, `unmatched_pred_blocks.jsonl`, `alignment_gaps.jsonl`). :contentReference[oaicite:16]{index=16}
- Safety: If a cache entry exists but does not match expected signatures (or is corrupt), the evaluator falls back to recomputing alignment and still completes successfully.
- Observability: `evaluation_telemetry` clearly states whether caching was enabled and whether a cache hit occurred.
- Performance: In an all-method sweep where two or more configs share identical extracted text streams, the later configs skip `SequenceMatcher` alignment (observable via telemetry). Because `SequenceMatcher` dominates canonical evaluation time, even modest hit rates should yield large wall-time reductions. :contentReference[oaicite:17]{index=17}

This plan explicitly does not change alignment strategy (legacy full-book alignment remains enforced) and does not trade accuracy for speed. :contentReference[oaicite:18]{index=18}


## Idempotence and Recovery

- Idempotence: Cache entries are content-addressed. Re-running the same evaluation with caching enabled is safe; it either reuses a matching cache entry or recomputes and overwrites nothing. Cache writes are atomic, so partial files will not be consumed.
- Recovery: If evaluation behaves unexpectedly, delete the cache directory (for example `<all_method_source_root>/.cache/canonical_alignment/`) and rerun; the system should revert to the original behavior (compute alignment every time).
- Concurrency safety: The lock-file protocol prevents multiple worker processes from computing the same alignment simultaneously. If a worker crashes and leaves a stale lock, the TTL-based stale lock cleanup allows progress to continue without manual intervention.
- Cleanliness: Because the cache lives under the all-method source root, deleting the run root deletes the cache. No system-wide caches or hidden state are required for correctness.