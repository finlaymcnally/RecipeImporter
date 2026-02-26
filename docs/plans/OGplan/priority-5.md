# ExecPlan: Priority 5 — Deterministic fallback step segmentation (pluggable backends)

References (inputs for this plan):
- ExecPlan format rules: PLANS.md :contentReference[oaicite:0]{index=0}:contentReference[oaicite:1]{index=1}
- Feature requirements + priority mapping: BIG PICTURE UPGRADES.md :contentReference[oaicite:2]{index=2}:contentReference[oaicite:4]{index=4}:contentReference[oaicite:5]{index=5}
- Current program docs (staging + bench + artifacts): 2026-02-25_18.22.10_recipeimport-docs-summary.md :contentReference[oaicite:6]{index=6}:contentReference[oaicite:7]{index=7}:contentReference[oaicite:8]{index=8}:contentReference[oaicite:9]{index=9}:contentReference[oaicite:12]{index=12}

## Purpose and Big Picture

Implement **Priority 5: Step segmentation fallback**: add a deterministic, staging-time “safety net” that can split overly-long instruction blocks into usable steps when an importer provides only 1–2 huge paragraphs, while preserving instruction section headers like “For the frosting:” as headers. This reduces downstream failure modes (time/temp extraction, ingredient-step linking, section awareness) without depending on importer block boundaries alone. 

Key requirements from Priority 5:
- Trigger fallback when instruction blocks look “suspicious” (single long paragraph, many sentences/verbs, newline-heavy).
- Deterministic heuristic pipeline:
  - Split on explicit numbering/bullets/newlines.
  - If still too long, split into sentences.
  - Merge tiny fragments back.
  - Preserve subheaders like “For the frosting:” as section headers.
- Placement: preferred importer-side, but acceptable as a **staging-side safety net** in `recipe_candidate_to_draft_v1`.
- Incorporate all related libraries/tools mentioned for this priority as selectable options:
  - **pySBD** (rule-based sentence boundary detection) — priority mapping explicitly calls it out for Priority 5.:contentReference[oaicite:17]{index=17}
  - Optional boundary-proposer libraries (secondary for Priority 5): **NLTK TextTilingTokenizer**, **ruptures**, **textsplit**, **DeepTiling** — incorporate as additional selectable segmenter backends for benchmarking permutations.:contentReference[oaicite:18]{index=18}

Non-goals (explicitly out of scope for Priority 5 unless discovered necessary during wiring):
- Changing how recipes are detected/segmented from block streams (that’s other priorities).
- Changing cookbook3 schema shape. (We only change how we derive the list of instruction steps within the existing shape.)

## Progress

- [ ] 2026-02-25: Create step segmentation module (heuristic_v1 + policy logic).
- [ ] 2026-02-25: Wire new RunSettings fields + CLI + interactive editor + bench knobs plumbing.
- [ ] 2026-02-25: Integrate step segmentation safety net into staging conversions (draft_v1, and also JSON-LD for intermediate parity).
- [ ] 2026-02-25: Add optional backends (pySBD + NLTK TextTilingTokenizer + ruptures + textsplit + DeepTiling adapter).
- [ ] 2026-02-25: Add unit + integration tests and run an end-to-end stage validation using staging artifacts.

## Surprises and Discoveries

- (Fill in during implementation)
- Potential gotcha: intermediate JSON-LD already has instruction section behavior (removes instruction section headers from step text and emits `HowToSection` when multiple sections are detected). This makes preserving and isolating headers during segmentation extra important for “intermediate parity.”:contentReference[oaicite:19]{index=19}

## Decision Log

- 2026-02-25: Implement fallback segmentation primarily as a **staging-side safety net** (shared across importers), per Priority 5 guidance.
- 2026-02-25: Add **two explicit run-config knobs**:
  1) policy (`off|auto|always`) and
  2) backend (`heuristic_v1|pysbd_v1|nltk_texttiling_v1|ruptures_v1|textsplit_v1|deeptiling_v1`),
  so existing behavior is preserved as an option (`off`) and every new library backend becomes a benchmarkable permutation.
- 2026-02-25: Default policy will be **auto** (so Priority 5 actually provides a safety net), but `off` will be first-class for regressions + benchmarking.
- 2026-02-25: Keep the default backend deterministic and dependency-free (`heuristic_v1`), and gate optional backends behind optional dependencies; selecting an unavailable backend must fail fast with a clear “install extra X” style error.

## Outcomes and Retrospective

Expected outcomes:
- Staged recipes that currently contain 1–2 massive instruction paragraphs produce a cleaner `steps[]` list, improving parse quality.
- Instruction section headers survive segmentation as distinct header boundaries, improving `sections.py` extraction and section-aware step-ingredient linking.
- New segmenter backend options are surfaced through RunSettings and `cookimport bench knobs`, enabling automated permutation benchmarking.:contentReference[oaicite:24]{index=24}

Retrospective prompts (fill after landing):
- Did `auto` trigger too often or too rarely?
- Which backends produce stable improvements on your benchmark harness?
- Are there recurring false splits around abbreviations, temperatures, fractions, or parenthetical clauses?

---

## Context and Orientation

Where this belongs in your current program:

- Staging conversion logic lives in:
  - `cookimport/staging/jsonld.py` (intermediate schema.org JSON-LD)
  - `cookimport/staging/draft_v1.py` (final cookbook3 output shape; internal `RecipeDraftV1`)
  - `cookimport/staging/writer.py` (writes intermediate/final outputs + section artifacts):contentReference[oaicite:25]{index=25}
- Section extraction already exists and is deterministic-first:
  - `cookimport/parsing/sections.py` extracts ingredient + instruction headers; conservative heuristics.
  - Step-ingredient linking uses optional section context to bias matches.
- Output artifacts you’ll use to validate:
  - `final drafts/<workbook_slug>/r{index}.json`
  - `intermediate drafts/<workbook_slug>/r{index}.jsonld`
  - `sections/<workbook_slug>/r{index}.sections.json` and `sections.md`
  - plus other run outputs at `data/output/<timestamp>/...`:contentReference[oaicite:27]{index=27}

Wiring expectations:
- New run-config knobs must be wired across surfaces (RunSettings, CLI stage, interactive editor, bench knobs, etc.). There is an explicit “pipeline-option wiring checklist” to follow.

---

## Plan of Work

### Milestone 1 — Baseline deterministic fallback step segmenter (no new deps)
Deliver the Priority 5 heuristic pipeline as `heuristic_v1` and integrate it into staging conversion paths behind a `policy` knob.

### Milestone 2 — Add pySBD as a sentence splitter option
Add `pysbd_v1` backend for sentence splitting (Priority 5 recommended library) while preserving `heuristic_v1` behavior as a baseline option.:contentReference[oaicite:29]{index=29}

### Milestone 3 — Add optional boundary-proposer backends as benchmarkable options
Add selectable backends wrapping:
- NLTK TextTilingTokenizer
- ruptures
- textsplit
- DeepTiling
These are explicitly mapped as “Priority 5 (secondary)” options and must exist as additional backends rather than replacing `heuristic_v1`.:contentReference[oaicite:30]{index=30}

### Milestone 4 — Validation: tests + stage run + bench knob surfacing
Add unit tests and do an end-to-end stage run on a synthetic “single paragraph instructions” sample; confirm artifacts.

---

## Concrete Steps

### 1) Define configuration knobs (RunSettings + CLI + interactive editor + bench knobs)

1.1 Add RunSettings fields (config surface)
- Edit: `cookimport/config/run_settings.py`
- Add fields (names can be adjusted to match conventions, but keep them stable + JSON-serializable):
  - `instruction_step_segmentation_policy: Literal["off","auto","always"] = "auto"`
  - `instruction_step_segmenter: Literal["heuristic_v1","pysbd_v1","nltk_texttiling_v1","ruptures_v1","textsplit_v1","deeptiling_v1"] = "heuristic_v1"`
- Ensure:
  - both fields appear in `RunSettingsSummary`
  - both fields are included in config hashing / summary ordering (whatever your existing pattern is) so they impact benchmark permutations.
  - no non-pickle-safe objects are stored in RunSettings (strings only).

1.2 Wire stage CLI flags
- Edit: `cookimport/cli.py` stage command.
- Add two new flags (Typer options):
  - `--instruction-step-segmentation-policy {off,auto,always}`
  - `--instruction-step-segmenter {heuristic_v1,pysbd_v1,nltk_texttiling_v1,ruptures_v1,textsplit_v1,deeptiling_v1}`
- Ensure these flags flow into the RunSettings passed down into worker staging, matching the repo’s “option wiring checklist.”

1.3 Wire interactive editor
- Edit: `cookimport/cli_ui/run_settings_flow.py` and `cookimport/cli_ui/toggle_editor.py`
- Add entries so the interactive editor can select:
  - policy
  - backend
- Follow the same patterns as other categorical knobs (e.g., table_extraction, epub_extractor, llm_* pipeline toggles).

1.4 Wire Label Studio benchmark / prediction-run path
- If `labelstudio-benchmark` reuses the same writer flow for processed outputs (it does), ensure the RunSettings passed to the processed-output staging path includes the two new knobs.:contentReference[oaicite:32]{index=32}

1.5 Wire bench knobs
- Edit: `cookimport/bench/knobs.py` (or wherever `cookimport bench knobs` draws from; follow existing structure).
- Add:
  - categorical knob for `instruction_step_segmentation_policy`
  - categorical knob for `instruction_step_segmenter`
- Ensure `cookimport bench knobs` lists them (defaults + descriptions), and sweeps can choose values. Bench docs emphasize knobs are the tunable parameters and `cookimport bench knobs` enumerates them.:contentReference[oaicite:34]{index=34}

Implementation detail: for segmenter backend options, strongly prefer making “availability” explicit:
- If backend dependency is not installed, either:
  - remove the backend from the available list at runtime (better for `bench sweep`), or
  - keep it but fail fast with a clear error if selected.
Given you want benchmarking permutations, the first approach is nicer: the knob’s domain can be “installed backends only.”

### 2) Implement the step segmentation module (deterministic heuristic_v1)

2.1 Create a new parsing module
- New file: `cookimport/parsing/step_segmentation.py` (or `step_segmenter.py`, consistent with naming)
- Public API suggestion:
  - `segment_instruction_steps(instructions: list[str], *, policy: str, backend: str) -> list[str]`
  - plus small helper:
    - `should_fallback_segment(instructions: list[str]) -> bool`
- Keep it deterministic and dependency-light by default.

2.2 Implement `should_fallback_segment(...)` (auto trigger)
Per Priority 5, “suspicious” includes: single long paragraph, many sentences/verbs, newline-heavy.
Implement deterministic proxies:
- suspicious if:
  - `len(instructions) == 1` and char length > N (e.g., 350–500 chars), OR
  - `len(instructions) <= 2` and sentence-ish punctuation count >= 4, OR
  - any block contains many newlines (e.g., `\n` count >= 3), OR
  - a block contains multiple explicit numbering markers (e.g., “1.” … “2.” …).
- not suspicious if:
  - `len(instructions) >= 4` and median length is small (already step-like), unless there is explicit “1. 2. 3.” inside a single block.

2.3 Implement the heuristic splitting pipeline (heuristic_v1)
Must match Priority 5 heuristic steps.

Algorithm (deterministic):
1) Normalize:
- normalize whitespace/newlines (`\r\n` → `\n`), trim, collapse excessive blank lines.

2) Split on explicit numbering/bullets/newlines:
- Split by newlines into candidate lines.
- Within each line (and within long paragraphs), split on:
  - leading list markers: `1.`, `1)`, `1:`, `(1)`, `-`, `•`, `*`
  - inline numbering sequences like `... 1. Do X 2. Do Y ...` (only when it clearly matches list markers, not decimals).
- Strip the marker tokens from the resulting step text (optional but usually desirable: the ordered list already implies step index).

3) Preserve subheaders (“For the frosting:”)
- Identify header-like fragments and keep them as their own boundaries. Requirements explicitly call out these lines.
- Header detection heuristic:
  - ends with `:` and is short (e.g., <= 60 chars OR <= 8 words), and
  - does not look like a normal sentence (no trailing period), and
  - optional: starts with `For` / `For the` / title-cased / all-caps
- Mark these fragments as “hard boundaries”: never merge them into neighbors.

4) If still too long: split into sentences
- For any fragment that is still “too long” (e.g., > 300 chars OR has >= 3 sentences):
  - run a sentence-split step (backend-specific; default is a simple deterministic regex sentence splitter).
  - keep sentences as separate candidate steps (but allow later merging).

5) Merge tiny fragments back
- Merge fragments that are too short to stand alone (e.g., < 20 chars and no ending punctuation), into adjacent non-header steps.
- Never merge into/from header steps (headers stay isolated).
- Also apply post-processing:
  - drop empty fragments
  - collapse whitespace
  - cap max steps to a sanity limit (e.g., 80). If exceeded, fall back to the unsplit input for safety.

2.4 Backend abstraction
Implement a small internal interface:
- `SentenceSplitter` for the “split into sentences” phase:
  - `regex_sentence_v1` (built-in)
  - `pysbd_v1` (uses pySBD)
- `BoundaryProposer` (optional) for “secondary segmentation”:
  - `nltk_texttiling_v1`
  - `ruptures_v1`
  - `textsplit_v1`
  - `deeptiling_v1`

Then define how these backends plug in:
- `heuristic_v1` is the overall pipeline.
- The `instruction_step_segmenter` setting selects which backend is used for the “if still too long” phase:
  - `heuristic_v1` → regex sentence splitter
  - `pysbd_v1` → pySBD sentence splitter
  - others → treat as boundary proposers operating on sentence units (recommended), then join sentences inside each proposed segment.

This keeps the Priority 5 pipeline consistent while still allowing different segmentation “brains” as options.

### 3) Integrate into staging conversions (draft_v1 + JSON-LD parity)

Priority 5 explicitly allows staging-side safety net in `recipe_candidate_to_draft_v1` (before `parse_instruction`).

3.1 Draft conversion integration
- Edit: `cookimport/staging/draft_v1.py`
- In `recipe_candidate_to_draft_v1`:
  - Before the loop that calls `parse_instruction` over `candidate.instructions`,
    compute `effective_instructions` using the new segmenter:
      - if policy == `off`: use `candidate.instructions` unchanged
      - if policy == `always`: segment always
      - if policy == `auto`: segment only if `should_fallback_segment(...)` is True
  - Use `effective_instructions` for parsing steps.
- Keep the existing behavior as an option (`off`) to satisfy “new options, not replacements.”

3.2 Intermediate JSON-LD integration (recommended for parity)
Why: Intermediate JSON-LD has explicit instruction section behavior: it removes instruction section headers from step text and emits structured sections when multiple are found.:contentReference[oaicite:39]{index=39}
If segmentation isolates headers better, JSON-LD sections improve too.
- Edit: `cookimport/staging/jsonld.py`
- Apply the same `effective_instructions` decision before emitting `recipeInstructions` / section grouping logic.

3.3 Ensure sections extraction + step-ingredient linking benefit
- Confirm `cookimport/parsing/sections.py` still operates correctly and benefits from better-separated headers; it uses conservative heuristics and feeds section context into step-ingredient linking.
- No schema changes required; just better inputs.

### 4) Add optional library backends (benchmarkable options)

All of these are mentioned as related to this priority and must appear as selectable options (even if “experimental”).:contentReference[oaicite:41]{index=41}:contentReference[oaicite:42]{index=42}

4.1 pySBD sentence splitting backend (pysbd_v1)
- Dependency: pySBD (pip package commonly `pysbd`).
- Implement `sentence_split_pysbd(text) -> list[str]`.
- Use it only when `instruction_step_segmenter == "pysbd_v1"`.
- This is the primary recommended library addition for Priority 5.:contentReference[oaicite:43]{index=43}

4.2 NLTK TextTilingTokenizer backend (nltk_texttiling_v1)
- Dependency: NLTK; backend should:
  - take a long fragment
  - segment it into “tiles”
  - then within each tile apply the same bullet/number cleanup and (optionally) sentence splitting to yield steps.
- Keep deterministic; handle missing corpora gracefully (either bundle minimal tokenization or provide a clear error when required NLTK resources are absent).

4.3 ruptures backend (ruptures_v1)
- Dependency: ruptures.
- Backend design (deterministic, no embeddings required):
  - sentence-split the fragment
  - create a deterministic feature vector per sentence (e.g., stable hashed bag-of-words into fixed dimension)
  - run a deterministic change point algorithm (e.g., BinSeg / PELT) to propose boundaries
  - group sentences into step segments
- Add a minimal “target segments” heuristic so it doesn’t return trivial “one segment”.

4.4 textsplit backend (textsplit_v1)
- Dependency: textsplit.
- Backend design that avoids needing external embeddings:
  - sentence-split
  - build a deterministic “docmat” matrix from stable hashed bag-of-words sentence vectors
  - call textsplit greedy/optimal segmentation to choose boundaries
  - emit grouped sentences as steps
- Avoid any internal random penalty search; choose `max_splits` deterministically (e.g., based on sentence count and target average sentences per step).

4.5 DeepTiling backend (deeptiling_v1)
- Dependency: a DeepTiling implementation (this is likely heavier and may involve neural embeddings).
- Implement as an adapter backend:
  - If DeepTiling lib/model is installed and configured, run it to propose boundaries on sentence units.
  - Otherwise, fail fast with a clear “install + configure deeptiling backend” message.
- Since it’s a secondary option for Priority 5, it can be labeled “experimental” in knob descriptions, but it must remain selectable for your benchmarking harness.:contentReference[oaicite:44]{index=44}

4.6 Dependency management approach
- Add these libraries as optional dependencies (extras), so base deterministic runs remain lightweight:
  - base install supports `heuristic_v1`
  - installing extras unlocks additional backends
- Ensure selecting an unavailable backend yields a clear error message that points to the right extra.

### 5) Tests

5.1 Unit tests for segmentation logic
- New tests file: `tests/test_step_segmentation.py` (or similar).
- Include test cases mirroring Priority 5 heuristics:
  1) Long single paragraph becomes multiple steps in `always` mode.
  2) `auto` mode triggers on long paragraph but does NOT trigger for already step-split input.
  3) Splits on numbering/bullets/newlines.
  4) “For the frosting:” preserved as a standalone header step and not merged.
  5) Tiny fragments merged back (e.g., “until smooth” merges to neighbor).
  6) Safety cap: insane splits fall back (max steps).
- Ensure deterministic outputs (no randomness).

5.2 Integration test for staging conversion
- Add/extend a test that constructs a minimal `RecipeCandidate` with:
  - `instructions = ["For the sauce:\n1. Mix ... 2. Simmer ..."]` or a single paragraph with embedded markers
- Run `recipe_candidate_to_draft_v1` with run settings:
  - policy `always` and `heuristic_v1`
- Assert that produced draft has expected number/order of steps and that header handling matches expectations.

5.3 Optional-backend tests
- For each optional backend:
  - If dependency is installed in CI: assert it runs and produces non-empty steps.
  - If dependency is not installed: assert selecting it yields a predictable error with a clear message.
This keeps the backends benchmarkable without forcing heavy deps in every environment.

### 6) Docs updates (minimal but important)

6.1 Parsing docs
- Update relevant parsing documentation to note:
  - new run settings
  - auto-trigger logic
  - backends and the fact they are options (not replacements)
  - relationship to sections extraction and JSON-LD instruction sections.

6.2 Bench docs (optional but helpful)
- Add a short note where knobs are enumerated that the step segmentation knobs exist and are categorical options.

---

## Validation and Acceptance

Acceptance criteria (must all be true):

A) Feature correctness (Priority 5)
- With policy `auto`, a recipe with `instructions=["<very long paragraph with many sentences>"]` yields multiple steps and not a single giant step.
- It splits on numbering/bullets/newlines first, then sentences as needed, and merges tiny fragments back.
- A subheader like “For the frosting:” remains a distinct boundary and is not swallowed into step text.

B) No-regression configurability
- With policy `off`, staged outputs match prior behavior for step boundaries (or differ only where clearly intended).
- Every new backend is an explicit option; none silently replaces the old path.

C) Staging artifacts show the improvement
Run a local stage with a known “bad segmentation” input and inspect artifacts:
- `data/output/<ts>/final drafts/<workbook_slug>/r0.json` (step count/contents)
- `data/output/<ts>/intermediate drafts/<workbook_slug>/r0.jsonld` (instruction sections when present)
- `data/output/<ts>/sections/<workbook_slug>/r0.sections.json` and `sections.md` (headers recognized)
These file locations are part of the canonical output layout.:contentReference[oaicite:48]{index=48}

Concrete validation recipe (synthetic):
1. Create a scratch text input under `data/input/stepseg_scratch.txt` with a single recipe whose instructions are one paragraph plus a “For the frosting:” header.
2. Run (from repo root):
   - source .venv/bin/activate
   - cookimport stage data/input/stepseg_scratch.txt \
       --instruction-step-segmentation-policy always \
       --instruction-step-segmenter heuristic_v1
3. Verify `final drafts/.../r0.json` has multiple steps and preserves the header as its own step boundary.

D) Bench knob surfacing
- `cookimport bench knobs` lists the two new knobs with defaults and descriptions.:contentReference[oaicite:49]{index=49}
- A sweep can include these knobs (even if your current benchmark scoring doesn’t directly measure step boundaries, it must still be permutation-valid).

---

## Idempotence and Recovery

Idempotence:
- Deterministic default backend (`heuristic_v1`) must be stable across runs for identical inputs and identical run settings.
- Optional backends must be deterministic given fixed settings; if any backend requires randomness, set explicit seeds and/or avoid randomized search.

Recovery / rollback:
- If segmentation causes regressions for a source:
  - set policy to `off` (restores importer boundaries)
  - or keep policy `auto` but pick a different backend
- For failed optional dependency:
  - selecting that backend must fail fast with actionable “install extra” guidance; the system should not silently fall back to another backend (to preserve benchmark purity).

---

## Artifacts and Notes (what will change)

New/updated files (expected):
- NEW: `cookimport/parsing/step_segmentation.py` (core implementation)
- UPDATED:
  - `cookimport/staging/draft_v1.py` (apply safety net before `parse_instruction`)
  - `cookimport/staging/jsonld.py` (apply same effective instructions before section behavior):contentReference[oaicite:51]{index=51}
  - `cookimport/config/run_settings.py` (new knobs)
  - `cookimport/cli.py` (new flags)
  - `cookimport/cli_ui/run_settings_flow.py`, `cookimport/cli_ui/toggle_editor.py` (interactive exposure)
  - `cookimport/bench/knobs.py` (knob registry)
- NEW tests:
  - `tests/test_step_segmentation.py`
  - plus integration tests near existing staging/draft conversion tests (pick the repo’s conventions).

Optional dependencies (expected additions):
- pySBD (Priority 5 recommended):contentReference[oaicite:53]{index=53}
- NLTK TextTilingTokenizer / ruptures / textsplit / DeepTiling (Priority 5 secondary options):contentReference[oaicite:54]{index=54}

---

## Interfaces and Dependencies

User-facing configuration interface:
- Stage CLI:
  - `--instruction-step-segmentation-policy off|auto|always`
  - `--instruction-step-segmenter heuristic_v1|pysbd_v1|nltk_texttiling_v1|ruptures_v1|textsplit_v1|deeptiling_v1`
- Interactive editor:
  - same two knobs with dropdown choices
- Bench knobs:
  - same two knobs visible via `cookimport bench knobs` and usable in sweeps/configs.:contentReference[oaicite:55]{index=55}

Dependency boundaries:
- Base deterministic behavior (heuristic_v1) must work with no new third-party deps.
- Optional backends must be isolated behind conditional imports (import only when selected).
- Ensure stage worker multiprocessing remains stable: instantiate backend objects inside worker codepaths, not in global module scope, and don’t store them in RunSettings (pickle safety).

Implementation dependency notes:
- `sections.py` is conservative and used by step-ingredient linking; better segmentation should improve section header recognition and section-aware matching, but do not loosen section heuristics as part of this priority. 

---

## Plan Checklist (wiring anti-regression)

Follow the repo’s pipeline-option wiring checklist when adding knobs:
- Add to RunSettings
- Add CLI flags in stage
- Add to interactive settings editor
- Ensure propagation into Label Studio benchmark/prediction generation path
- Ensure bench knobs listing/sweep support
- Ensure run-config summary/hash includes it
This checklist is explicitly documented and should be treated as mandatory wiring hygiene.