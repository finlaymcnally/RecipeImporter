# Label Studio Conventions

Durable contracts for Label Studio import/export/eval/prelabel flows in `cookimport/labelstudio/`.

## Benchmark Prediction Rule

- `labelstudio-benchmark` is row-native only and accepts `--eval-mode source-rows`.
- `labelstudio-benchmark` scoring uses `cookimport.bench.eval_source_rows`.
- Interactive benchmark modes (`single_book`, `selected_matched_books`, and `all_matched_books`) should run `labelstudio-benchmark` in `source-rows` mode so one freeform gold export can benchmark extractor/config permutations without block-index parity.
- Prediction-run artifact generation for benchmark must still write `extracted_archive.json` and copy any processed-output stage evidence into prediction-run root as `semantic_row_predictions.json`.
- Benchmark helpers/tests that mock prediction runs must include both `extracted_archive.json` and `semantic_row_predictions.json`.

## Label Studio Prelabel Rule

- Freeform prelabeling is span-only and must derive final offsets from task-local `segment_text` + `data.source_map.rows[*].segment_start/end`.
- Freeform prelabel flows must preserve `data.segment_text` exactly (no whitespace normalization) so exported offsets remain stable.
- Freeform Label Studio payload contract for new tasks is `data.segment_text` + `data.source_map.rows` plus `data.source_map.context_before_rows` / `data.source_map.context_after_rows`.
- Legacy pulled exports may still carry `blocks` / `context_*_blocks`; prompt/parsing fallbacks may read them for compatibility, but new task generation must not write them.
- Prompt text for freeform prelabel lives in `llm_pipelines/prompts/freeform-prelabel-full.prompt.md`; iterate prompt wording there and keep required placeholder tokens (`{{SEGMENT_ID}}`, `{{BLOCKS_JSON_LINES}}`, etc.) intact.
- Freeform prelabel granularity contract: `span` mode writes quote-anchored spans (`block_index` + `quote` + optional `occurrence`) with optional validated absolute fallback (`start`/`end`).
- Freeform context-vs-focus contract: `segment_blocks` controls context visibility, `segment_focus_blocks` controls which blocks may receive labels, focus windows should be centered inside each segment when possible (so context appears before and after), and prelabel runtime must enforce focus filtering parser-side (including absolute spans that cross non-focus blocks).
- Freeform target-task contract: when `target_task_count` is provided, resolve and persist both `segment_overlap_requested` and `segment_overlap_effective` in manifests; `segment_overlap` should reflect the effective runtime overlap.
- Freeform prelabel overlap floor: effective overlap must satisfy `segment_overlap_effective >= segment_blocks - segment_focus_blocks` so focus windows remain contiguous across tasks and do not leave uncovered block gaps.
- Freeform prelabel concurrency contract: task-level provider calls are bounded by `prelabel_workers` (default `15`), progress should still report `task X/Y` completions (parallel status should keep `(workers=N)` visible), and prompt logs/reports must remain deterministic per task id.
- Freeform prelabel rate-limit contract: if any provider call reports `HTTP 429`/rate-limit text, set a shared stop signal immediately, stop issuing new provider calls for queued tasks, mark queued tasks as skipped, and emit a visible warning containing `429`.
- Freeform prelabel timeout default is `600` seconds per provider call unless overridden by `--prelabel-timeout-seconds`.
- Label Studio import CLI must print an explicit red completion summary (`PRELABEL ERRORS: X/Y ...`) plus `prelabel_errors.jsonl` path whenever prelabel failures occur, including allow-partial runs.
- Prompt text for actual freeform mode lives in `llm_pipelines/prompts/freeform-prelabel-span.prompt.md`; keep placeholder tokens intact.
- Actual freeform (`span`) prompts should provide block text once via `{{BLOCKS_WITH_FOCUS_MARKERS_COMPACT_LINES}}` with explicit context-before/context-after markers plus `<<<START_LABELING_BLOCKS_HERE>>>` / `<<<STOP_LABELING_BLOCKS_HERE_CONTEXT_ONLY>>>` focus boundaries; avoid duplicating focus blocks as a second full text payload list.
- Actual freeform (`span`) prompts should explicitly discourage whole-block selections for long blocks, treat nearby blocks as context-only (no auto-propagation to adjacent blocks), and include mixed-block split examples (for example yield+time or note+instruction in one block).
- Freeform canonical label names are `RECIPE_TITLE`, `INGREDIENT_LINE`, `INSTRUCTION_LINE`, `HOWTO_SECTION`, `YIELD_LINE`, `TIME_LINE`, `RECIPE_NOTES`, `RECIPE_VARIANT`, `KNOWLEDGE`, `OTHER`.
- Scoring/eval semantics: `HOWTO_SECTION` is resolved at eval time into `INGREDIENT_LINE` or `INSTRUCTION_LINE` using nearby structural context (surrounded-by rule with nearest-neighbor fallback).
- Codex prelabel invocations must run through CodexFarm pipeline `prelabel.freeform.v1`.
- Codex command resolution for prelabel is: explicit `--codex-cmd` -> `COOKIMPORT_CODEX_CMD` -> `COOKIMPORT_CODEX_FARM_CMD` -> `codex-farm`.
- Interactive freeform prelabel should use that resolved command directly (no command chooser prompt) and display the resolved account email when available.
- Codex model resolution order for prelabel is: explicit `--codex-model` -> `COOKIMPORT_CODEX_FARM_MODEL` -> `COOKIMPORT_CODEX_MODEL` -> local defaults.
- Codex thinking effort for prelabel resolves from explicit command/CLI override first (`--codex-thinking-effort` / `--codex-reasoning-effort`), then `COOKIMPORT_CODEX_FARM_REASONING_EFFORT`, then local defaults.
- Interactive prelabel model choices should be sourced from the selected command's Codex home cache metadata (`models_cache.json`) when available, with custom-id fallback.
- Prelabel runs should perform one model-access preflight probe before task loops; account/model mismatches should fail once up front with provider detail.
- Codex JSON `turn.failed` errors must be surfaced as provider failures (not collapsed into generic "no labels produced" parse misses).
- Token usage accounting for prelabel is always on and should be persisted as aggregate totals in `prelabel_report.json` (including resolved command/account metadata) without changing annotation semantics; capture `reasoning_tokens` when present in Codex usage payloads.
- Prelabel runs must persist `prelabel_prompt_log.md` in the run root (`data/golden/sent-to-labelstudio/<timestamp>/labelstudio/<book_slug>/`) with one section per prompt containing full prompt text and prompt-context metadata/description for auditing.
