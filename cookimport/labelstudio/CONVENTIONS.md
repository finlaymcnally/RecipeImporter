# Label Studio Conventions

Durable contracts for Label Studio import/export/eval/prelabel flows in `cookimport/labelstudio/`.

## Benchmark Prediction Rule

- `labelstudio-benchmark` should score stage block evidence (`stage_block_predictions.json`) with `cookimport.bench.eval_stage_blocks`, not pipeline chunk span overlap.
- Prediction-run artifact generation for benchmark must still write `extracted_archive.json` and copy any processed-output stage evidence into prediction-run root as `stage_block_predictions.json`.
- Benchmark helpers/tests that mock prediction runs must include both `extracted_archive.json` and `stage_block_predictions.json`.

## Label Studio Prelabel Rule

- Freeform prelabeling must derive final span offsets from task-local `segment_text` + `data.source_map.blocks[*].segment_start/end`; `block` mode uses block bounds directly and `span` mode resolves quotes against block text (with strict validation for optional absolute `start`/`end` fallbacks).
- Freeform prelabel flows must preserve `data.segment_text` exactly (no whitespace normalization) so exported offsets remain stable.
- Freeform Label Studio payload contract: `data.segment_text` + `data.source_map.blocks` are focus-only labelable rows; adjacent context for AI prompting must be carried in `data.source_map.context_before_blocks` / `data.source_map.context_after_blocks` so UI text stays dedupe-friendly while prompts keep boundary context.
- Prompt text for freeform prelabel lives in `llm_pipelines/prompts/freeform-prelabel-full.prompt.md`; iterate prompt wording there and keep required placeholder tokens (`{{SEGMENT_ID}}`, `{{BLOCKS_JSON_LINES}}`, etc.) intact.
- Freeform prelabel granularity contract: `block` mode is legacy, block based full-block spans; `span` mode is actual freeform quote-anchored spans (`block_index` + `quote` + optional `occurrence`) with optional validated absolute fallback (`start`/`end`).
- Freeform context-vs-focus contract: `segment_blocks` controls context visibility, `segment_focus_blocks` controls which blocks may receive labels, focus windows should be centered inside each segment when possible (so context appears before and after), and prelabel runtime must enforce focus filtering parser-side (including absolute spans that cross non-focus blocks).
- Freeform target-task contract: when `target_task_count` is provided, resolve and persist both `segment_overlap_requested` and `segment_overlap_effective` in manifests; `segment_overlap` should reflect the effective runtime overlap.
- Freeform prelabel overlap floor: effective overlap must satisfy `segment_overlap_effective >= segment_blocks - segment_focus_blocks` so focus windows remain contiguous across tasks and do not leave uncovered block gaps.
- Freeform prelabel concurrency contract: task-level provider calls are bounded by `prelabel_workers` (default `15`), progress should still report `task X/Y` completions (parallel status should keep `(workers=N)` visible), and prompt logs/reports must remain deterministic per task id.
- Freeform prelabel rate-limit contract: if any provider call reports `HTTP 429`/rate-limit text, set a shared stop signal immediately, stop issuing new provider calls for queued tasks, mark queued tasks as skipped, and emit a visible warning containing `429`.
- Freeform prelabel timeout default is `300` seconds per provider call unless overridden by `--prelabel-timeout-seconds`.
- Label Studio import CLI must print an explicit red completion summary (`PRELABEL ERRORS: X/Y ...`) plus `prelabel_errors.jsonl` path whenever prelabel failures occur, including allow-partial runs.
- Prompt text for actual freeform mode lives in `llm_pipelines/prompts/freeform-prelabel-span.prompt.md`; keep placeholder tokens intact.
- Actual freeform (`span`) prompts should provide block text once via `{{BLOCKS_WITH_FOCUS_MARKERS_COMPACT_LINES}}` (legacy alias `{{BLOCKS_WITH_FOCUS_MARKERS_JSON_LINES}}` still supported) with explicit context-before/context-after markers plus `<<<START_LABELING_BLOCKS_HERE>>>` / `<<<STOP_LABELING_BLOCKS_HERE_CONTEXT_ONLY>>>` focus boundaries; avoid duplicating focus blocks as a second full text payload list.
- Actual freeform (`span`) prompts should explicitly discourage whole-block selections for long blocks, treat nearby blocks as context-only (no auto-propagation to adjacent blocks), and include mixed-block split examples (for example yield+time or note+instruction in one block).
- Freeform canonical label names are `RECIPE_TITLE`, `INGREDIENT_LINE`, `INSTRUCTION_LINE`, `YIELD_LINE`, `TIME_LINE`, `RECIPE_NOTES`, `RECIPE_VARIANT`, `KNOWLEDGE`, `OTHER`; normalize legacy `TIP`/`NOTES`/`VARIANT` labels to those names.
- Codex prelabel invocations must use non-interactive CLI mode (`codex exec -`); plain `codex` is interactive and fails in pipeline subprocess calls without a TTY.
- Codex command resolution for prelabel is: explicit `--codex-cmd` -> `COOKIMPORT_CODEX_CMD` -> `codex exec -`.
- Interactive freeform prelabel should use that resolved command directly (no command chooser prompt) and display the resolved account email when available.
- Codex model resolution order for prelabel is: explicit `--codex-model` -> `COOKIMPORT_CODEX_MODEL` -> Codex config `model` (`~/.codex/config.toml`, `~/.codex-alt/config.toml`).
- Codex thinking effort for prelabel resolves from explicit command/CLI override first (`--codex-thinking-effort` / `--codex-reasoning-effort`, mapped to `model_reasoning_effort`), then Codex config `model_reasoning_effort`.
- Interactive prelabel model choices should be sourced from the selected command's Codex home cache metadata (`models_cache.json`) when available, with custom-id fallback.
- Prelabel runs should perform one model-access preflight probe before task loops; account/model mismatches should fail once up front with provider detail.
- Codex JSON `turn.failed` errors must be surfaced as provider failures (not collapsed into generic "no labels produced" parse misses).
- Token usage accounting for prelabel is always on and should be persisted as aggregate totals in `prelabel_report.json` (including resolved command/account metadata) without changing annotation semantics; capture `reasoning_tokens` when present in Codex usage payloads.
- Prelabel runs must persist `prelabel_prompt_log.md` in the run root (`data/golden/sent-to-labelstudio/<timestamp>/labelstudio/<book_slug>/`) with one section per prompt containing full prompt text and prompt-context metadata/description for auditing.
