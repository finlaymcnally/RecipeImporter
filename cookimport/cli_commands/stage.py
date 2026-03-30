from __future__ import annotations

import typer

from cookimport.cli_support import (
    Any,
    BarColumn,
    DEFAULT_GOLDEN,
    DEFAULT_OUTPUT,
    EPUB_EXTRACTOR_ENABLE_MARKDOWN_ENV,
    JobSpec,
    KNOWLEDGE_CODEX_PIPELINE_CANDIDATE_V2,
    MappingConfig,
    PROCESSING_TIMESERIES_FILENAME,
    PROCESSING_TIMESERIES_HEARTBEAT_SECONDS,
    Path,
    Progress,
    ProgressDashboardCore,
    RECIPE_CODEX_FARM_PIPELINE_SHARD_V1,
    REPO_ROOT,
    SpinnerColumn,
    TextColumn,
    _ProcessingTimeseriesWriter,
    _STATUS_TICK_SECONDS,
    _acquire_live_status_slot,
    _effective_live_status_slots,
    _fail,
    _iter_files,
    _merge_source_jobs,
    _normalize_codex_farm_failure_mode,
    _normalize_epub_extractor,
    _normalize_ingredient_missing_unit_policy,
    _normalize_ingredient_packaging_mode,
    _normalize_ingredient_parser_backend,
    _normalize_ingredient_pre_normalize_mode,
    _normalize_ingredient_text_fix_backend,
    _normalize_ingredient_unit_canonicalizer,
    _normalize_llm_knowledge_pipeline,
    _normalize_llm_recipe_pipeline,
    _normalize_multi_recipe_splitter,
    _normalize_ocr_device,
    _normalize_p6_ovenlike_mode,
    _normalize_p6_temperature_backend,
    _normalize_p6_temperature_unit_backend,
    _normalize_p6_time_backend,
    _normalize_p6_time_total_strategy,
    _normalize_p6_yield_mode,
    _normalize_pdf_column_gap_ratio,
    _normalize_pdf_ocr_policy,
    _normalize_unstructured_html_parser_version,
    _normalize_unstructured_preprocess_mode,
    _normalize_web_html_text_extractor,
    _normalize_web_schema_extractor,
    _normalize_web_schema_normalizer,
    _normalize_web_schema_policy,
    _plain_progress_override_requested,
    _print_codex_decision,
    _print_stage_summary,
    _refresh_dashboard_after_history_write,
    _resolve_live_status_console,
    _set_epub_unstructured_env,
    _should_default_plain_progress_for_agent,
    _unwrap_typer_option_default,
    _warm_all_models,
    _write_error_report,
    _write_knowledge_index_best_effort,
    _write_stage_observability_best_effort,
    _write_stage_run_manifest,
    _write_stage_run_summary,
    apply_bucket1_fixed_behavior_metadata,
    apply_codex_execution_policy_metadata,
    as_completed,
    bucket1_fixed_behavior,
    build_run_settings,
    compute_effective_workers,
    console,
    defaultdict,
    deque,
    dt,
    hashlib,
    json,
    llm_prompt_artifacts,
    load_mapping_config,
    load_parsing_overrides,
    logger,
    multiprocessing,
    pickle,
    plan_source_jobs,
    queue,
    re,
    resolve_codex_execution_policy,
    resolve_process_thread_executor,
    rich_escape,
    shutdown_executor,
    subprocess,
    summarize_run_config_payload,
    sys,
    threading,
    time,
)


def register(app: typer.Typer) -> dict[str, object]:
    @app.command()
    def stage(
        path: Path = typer.Argument(..., help="File or folder containing source files."),
        out: Path = typer.Option(DEFAULT_OUTPUT, "--out", help="Output folder."),
        mapping: Path | None = typer.Option(None, "--mapping", help="Mapping file path."),
        overrides: Path | None = typer.Option(
            None,
            "--overrides",
            help="Parsing overrides file path.",
        ),
        limit: int | None = typer.Option(
            None,
            "--limit",
            "-n",
            min=1,
            help="Limit output to the first N recipes per file.",
        ),
        ocr_device: str = typer.Option(
            "auto",
            "--ocr-device",
            hidden=True,
            help="OCR device to use (auto, cpu, cuda, mps).",
        ),
        pdf_ocr_policy: str = typer.Option(
            "auto",
            "--pdf-ocr-policy",
            help="PDF OCR policy: off, auto, or always.",
        ),
        ocr_batch_size: int = typer.Option(
            1,
            "--ocr-batch-size",
            min=1,
            hidden=True,
            help="Number of pages to process per OCR model call.",
        ),
        pdf_column_gap_ratio: float = typer.Option(
            0.12,
            "--pdf-column-gap-ratio",
            min=0.01,
            max=0.95,
            hidden=True,
            help="Minimum horizontal gap ratio used for PDF column-boundary detection.",
        ),
        pdf_pages_per_job: int = typer.Option(
            50,
            "--pdf-pages-per-job",
            min=1,
            help="Target page count per PDF job when splitting large PDFs.",
        ),
        epub_spine_items_per_job: int = typer.Option(
            10,
            "--epub-spine-items-per-job",
            min=1,
            help="Target spine items per EPUB job when splitting large EPUBs.",
        ),
        warm_models: bool = typer.Option(
            False,
            "--warm-models",
            help="Proactively load heavy models before processing.",
        ),
        workers: int = typer.Option(
            7,
            "--workers",
            "-w",
            min=1,
            help="Number of parallel worker processes.",
        ),
        require_process_workers: bool = typer.Option(
            False,
            "--require-process-workers/--allow-worker-fallback",
            help=(
                "Fail fast when process-based worker concurrency is unavailable instead of "
                "falling back to subprocess/thread/serial workers."
            ),
        ),
        pdf_split_workers: int = typer.Option(
            7,
            "--pdf-split-workers",
            min=1,
            help="Max workers used to split a single PDF into jobs.",
        ),
        epub_split_workers: int = typer.Option(
            7,
            "--epub-split-workers",
            min=1,
            help="Max workers used to split a single EPUB into jobs.",
        ),
        write_markdown: bool = typer.Option(
            True,
            "--write-markdown/--no-write-markdown",
            help="Write markdown sidecar artifacts (sections/chunks/tables).",
        ),
        epub_extractor: str = typer.Option(
            "unstructured",
            "--epub-extractor",
            help=(
                "EPUB extraction engine: unstructured (semantic), beautifulsoup "
                "(BeautifulSoup), markdown (HTML->Markdown), or markitdown (whole-book "
                "EPUB->markdown mode). Markdown extractors are policy-locked off unless "
                f"{EPUB_EXTRACTOR_ENABLE_MARKDOWN_ENV}=1."
            ),
        ),
        epub_unstructured_html_parser_version: str = typer.Option(
            "v1",
            "--epub-unstructured-html-parser-version",
            hidden=True,
            help="Unstructured HTML parser version for EPUB extraction: v1 or v2.",
        ),
        epub_unstructured_skip_headers_footers: bool = typer.Option(
            True,
            "--epub-unstructured-skip-headers-footers/--no-epub-unstructured-skip-headers-footers",
            hidden=True,
            help="Enable Unstructured skip_headers_and_footers for EPUB HTML partitioning.",
        ),
        epub_unstructured_preprocess_mode: str = typer.Option(
            "br_split_v1",
            "--epub-unstructured-preprocess-mode",
            hidden=True,
            help="EPUB HTML preprocess mode before Unstructured partitioning: none, br_split_v1.",
        ),
        section_detector_backend: str = typer.Option(
            "shared_v1",
            "--section-detector-backend",
            hidden=True,
            help="Section detector backend: shared_v1.",
        ),
        multi_recipe_splitter: str = typer.Option(
            "rules_v1",
            "--multi-recipe-splitter",
            hidden=True,
            help="Shared multi-recipe splitter backend: off or rules_v1.",
        ),
        multi_recipe_trace: bool = typer.Option(
            False,
            "--multi-recipe-trace/--no-multi-recipe-trace",
            hidden=True,
            help="Write shared multi-recipe splitter trace artifacts.",
        ),
        multi_recipe_min_ingredient_lines: int = typer.Option(
            1,
            "--multi-recipe-min-ingredient-lines",
            min=0,
            hidden=True,
            help="Minimum ingredient-like lines required on each side of a split boundary.",
        ),
        multi_recipe_min_instruction_lines: int = typer.Option(
            1,
            "--multi-recipe-min-instruction-lines",
            min=0,
            hidden=True,
            help="Minimum instruction-like lines required on each side of a split boundary.",
        ),
        multi_recipe_for_the_guardrail: bool = typer.Option(
            True,
            "--multi-recipe-for-the-guardrail/--no-multi-recipe-for-the-guardrail",
            hidden=True,
            help="Prevent boundaries on component headers like 'For the sauce'.",
        ),
        instruction_step_segmentation_policy: str = typer.Option(
            "auto",
            "--instruction-step-segmentation-policy",
            hidden=True,
            help="Fallback instruction-step segmentation policy: off, auto, or always.",
        ),
        instruction_step_segmenter: str = typer.Option(
            "heuristic_v1",
            "--instruction-step-segmenter",
            hidden=True,
            help="Instruction-step fallback segmenter backend: heuristic_v1 or pysbd_v1.",
        ),
        web_schema_extractor: str = typer.Option(
            "builtin_jsonld",
            "--web-schema-extractor",
            help=(
                "Schema extractor backend for HTML/JSON schema sources: "
                "builtin_jsonld, extruct, scrape_schema_recipe, recipe_scrapers, ensemble_v1."
            ),
        ),
        web_schema_normalizer: str = typer.Option(
            "simple",
            "--web-schema-normalizer",
            hidden=True,
            help="Schema normalization mode: simple or pyld.",
        ),
        web_html_text_extractor: str = typer.Option(
            "bs4",
            "--web-html-text-extractor",
            hidden=True,
            help=(
                "Fallback HTML text extractor when schema is absent/disabled: "
                "bs4, trafilatura, readability_lxml, justext, boilerpy3, ensemble_v1."
            ),
        ),
        web_schema_policy: str = typer.Option(
            "prefer_schema",
            "--web-schema-policy",
            help="Schema policy: prefer_schema, schema_only, or heuristic_only.",
        ),
        web_schema_min_confidence: float = typer.Option(
            0.75,
            "--web-schema-min-confidence",
            min=0.0,
            max=1.0,
            hidden=True,
            help="Minimum schema confidence required before schema candidates are accepted.",
        ),
        web_schema_min_ingredients: int = typer.Option(
            1,
            "--web-schema-min-ingredients",
            min=0,
            hidden=True,
            help="Minimum ingredient lines used in schema confidence scoring.",
        ),
        web_schema_min_instruction_steps: int = typer.Option(
            1,
            "--web-schema-min-instruction-steps",
            min=0,
            hidden=True,
            help="Minimum instruction steps used in schema confidence scoring.",
        ),
        ingredient_text_fix_backend: str = typer.Option(
            "none",
            "--ingredient-text-fix-backend",
            hidden=True,
            help="Ingredient text-fix backend: none or ftfy.",
        ),
        ingredient_pre_normalize_mode: str = typer.Option(
            "aggressive_v1",
            "--ingredient-pre-normalize-mode",
            hidden=True,
            help="Ingredient pre-normalization mode: aggressive_v1.",
        ),
        ingredient_packaging_mode: str = typer.Option(
            "off",
            "--ingredient-packaging-mode",
            hidden=True,
            help="Ingredient packaging extraction mode: off or regex_v1.",
        ),
        ingredient_parser_backend: str = typer.Option(
            "ingredient_parser_nlp",
            "--ingredient-parser-backend",
            hidden=True,
            help=(
                "Ingredient parser backend: ingredient_parser_nlp, "
                "quantulum3_regex, or hybrid_nlp_then_quantulum3."
            ),
        ),
        ingredient_unit_canonicalizer: str = typer.Option(
            "pint",
            "--ingredient-unit-canonicalizer",
            hidden=True,
            help="Ingredient unit canonicalizer: pint.",
        ),
        ingredient_missing_unit_policy: str = typer.Option(
            "null",
            "--ingredient-missing-unit-policy",
            hidden=True,
            help="Policy when quantity has no unit: medium, null, or each.",
        ),
        p6_time_backend: str = typer.Option(
            "regex_v1",
            "--p6-time-backend",
            hidden=True,
            help=(
                "Priority 6 time extraction backend: regex_v1, quantulum3_v1, "
                "or hybrid_regex_quantulum3_v1."
            ),
        ),
        p6_time_total_strategy: str = typer.Option(
            "sum_all_v1",
            "--p6-time-total-strategy",
            hidden=True,
            help="Priority 6 step-time rollup strategy: sum_all_v1, max_v1, or selective_sum_v1.",
        ),
        p6_temperature_backend: str = typer.Option(
            "regex_v1",
            "--p6-temperature-backend",
            hidden=True,
            help=(
                "Priority 6 temperature extraction backend: regex_v1, quantulum3_v1, "
                "or hybrid_regex_quantulum3_v1."
            ),
        ),
        p6_temperature_unit_backend: str = typer.Option(
            "builtin_v1",
            "--p6-temperature-unit-backend",
            hidden=True,
            help="Priority 6 temperature-unit conversion backend: builtin_v1 or pint_v1.",
        ),
        p6_ovenlike_mode: str = typer.Option(
            "keywords_v1",
            "--p6-ovenlike-mode",
            hidden=True,
            help="Priority 6 oven-like temperature classifier mode: keywords_v1 or off.",
        ),
        p6_yield_mode: str = typer.Option(
            "scored_v1",
            "--p6-yield-mode",
            hidden=True,
            help="Priority 6 yield parser mode: scored_v1.",
        ),
        p6_emit_metadata_debug: bool = typer.Option(
            False,
            "--p6-emit-metadata-debug/--no-p6-emit-metadata-debug",
            hidden=True,
            help="Write optional Priority 6 metadata debug sidecar artifacts.",
        ),
        recipe_scorer_backend: str = typer.Option(
            "heuristic_v1",
            "--recipe-scorer-backend",
            hidden=True,
            help="Recipe-likeness scorer backend (default: heuristic_v1).",
        ),
        recipe_score_gold_min: float = typer.Option(
            0.75,
            "--recipe-score-gold-min",
            min=0.0,
            max=1.0,
            hidden=True,
            help="Minimum recipe-likeness score for gold tier.",
        ),
        recipe_score_silver_min: float = typer.Option(
            0.55,
            "--recipe-score-silver-min",
            min=0.0,
            max=1.0,
            hidden=True,
            help="Minimum recipe-likeness score for silver tier.",
        ),
        recipe_score_bronze_min: float = typer.Option(
            0.35,
            "--recipe-score-bronze-min",
            min=0.0,
            max=1.0,
            hidden=True,
            help="Minimum recipe-likeness score for bronze tier (below is reject).",
        ),
        recipe_score_min_ingredient_lines: int = typer.Option(
            1,
            "--recipe-score-min-ingredient-lines",
            min=0,
            hidden=True,
            help="Soft minimum ingredient lines used by scoring/gating.",
        ),
        recipe_score_min_instruction_lines: int = typer.Option(
            1,
            "--recipe-score-min-instruction-lines",
            min=0,
            hidden=True,
            help="Soft minimum instruction lines used by scoring/gating.",
        ),
        llm_recipe_pipeline: str = typer.Option(
            "off",
            "--llm-recipe-pipeline",
            help=(
                "Recipe codex-farm parsing correction pipeline. "
                f"Values: off or {RECIPE_CODEX_FARM_PIPELINE_SHARD_V1}."
            ),
        ),
        recipe_prompt_target_count: int = typer.Option(
            5,
            "--recipe-prompt-target-count",
            min=1,
            hidden=True,
            help="Internal: preferred recipe shard count for Codex-backed stage runs.",
        ),
        llm_knowledge_pipeline: str = typer.Option(
            "off",
            "--llm-knowledge-pipeline",
            help=f"Optional knowledge LLM pipeline: off or {KNOWLEDGE_CODEX_PIPELINE_CANDIDATE_V2}.",
        ),
        knowledge_prompt_target_count: int = typer.Option(
            5,
            "--knowledge-prompt-target-count",
            min=1,
            hidden=True,
            help="Internal: preferred knowledge shard count for Codex-backed stage runs.",
        ),
        allow_codex: bool = typer.Option(
            False,
            "--allow-codex/--no-allow-codex",
            help=(
                "Required when this stage run enables any Codex-backed recipe, line-role, "
                "or knowledge surface."
            ),
        ),
        codex_farm_cmd: str = typer.Option(
            "codex-farm",
            "--codex-farm-cmd",
            help="Executable used for codex-farm calls when LLM recipe pipeline is enabled.",
        ),
        codex_farm_root: Path | None = typer.Option(
            None,
            "--codex-farm-root",
            help="Optional codex-farm pipeline-pack root. Defaults to <repo_root>/llm_pipelines.",
        ),
        codex_farm_workspace_root: Path | None = typer.Option(
            None,
            "--codex-farm-workspace-root",
            help=(
                "Optional workspace root passed to codex-farm. "
                "When omitted, codex-farm pipeline codex_cd_mode decides."
            ),
        ),
        codex_farm_pipeline_knowledge: str = typer.Option(
            "recipe.knowledge.packet.v1",
            "--codex-farm-pipeline-knowledge",
            hidden=True,
            help="Stage-7 codex-farm pipeline id for non-recipe knowledge review.",
        ),
        codex_farm_context_blocks: int = typer.Option(
            30,
            "--codex-farm-context-blocks",
            min=0,
            help="Blocks before/after each recipe candidate included in pass-1 codex-farm bundles.",
        ),
        codex_farm_knowledge_context_blocks: int = typer.Option(
            2,
            "--codex-farm-knowledge-context-blocks",
            min=0,
            help="Blocks before/after each non-recipe review chunk included as context in Stage-7 bundles.",
        ),
        codex_farm_failure_mode: str = typer.Option(
            "fail",
            "--codex-farm-failure-mode",
            hidden=True,
            help="Behavior when codex-farm setup/invocation fails: fail or fallback.",
        ),
    ) -> Path:
        """Stage recipes from a source file or folder.

        Outputs are organized as:
          {out}/{timestamp}/intermediate drafts/{filename}/  - schema.org Recipe JSON
          {out}/{timestamp}/final drafts/{filename}/         - cookbook3 format
          {out}/{timestamp}/chunks/{filename}/               - Non-recipe knowledge chunks
          {out}/{timestamp}/<workbook>.excel_import_report.json - Conversion report
        """
        out = _unwrap_typer_option_default(out)
        mapping = _unwrap_typer_option_default(mapping)
        overrides = _unwrap_typer_option_default(overrides)
        limit = _unwrap_typer_option_default(limit)
        ocr_device = _unwrap_typer_option_default(ocr_device)
        pdf_ocr_policy = _unwrap_typer_option_default(pdf_ocr_policy)
        ocr_batch_size = _unwrap_typer_option_default(ocr_batch_size)
        pdf_column_gap_ratio = _unwrap_typer_option_default(pdf_column_gap_ratio)
        pdf_pages_per_job = _unwrap_typer_option_default(pdf_pages_per_job)
        epub_spine_items_per_job = _unwrap_typer_option_default(epub_spine_items_per_job)
        warm_models = _unwrap_typer_option_default(warm_models)
        workers = _unwrap_typer_option_default(workers)
        require_process_workers = _unwrap_typer_option_default(require_process_workers)
        pdf_split_workers = _unwrap_typer_option_default(pdf_split_workers)
        epub_split_workers = _unwrap_typer_option_default(epub_split_workers)
        write_markdown = _unwrap_typer_option_default(write_markdown)
        epub_extractor = _unwrap_typer_option_default(epub_extractor)
        epub_unstructured_html_parser_version = _unwrap_typer_option_default(
            epub_unstructured_html_parser_version
        )
        epub_unstructured_skip_headers_footers = _unwrap_typer_option_default(
            epub_unstructured_skip_headers_footers
        )
        epub_unstructured_preprocess_mode = _unwrap_typer_option_default(
            epub_unstructured_preprocess_mode
        )
        section_detector_backend = _unwrap_typer_option_default(section_detector_backend)
        multi_recipe_splitter = _unwrap_typer_option_default(multi_recipe_splitter)
        multi_recipe_trace = _unwrap_typer_option_default(multi_recipe_trace)
        multi_recipe_min_ingredient_lines = _unwrap_typer_option_default(
            multi_recipe_min_ingredient_lines
        )
        multi_recipe_min_instruction_lines = _unwrap_typer_option_default(
            multi_recipe_min_instruction_lines
        )
        multi_recipe_for_the_guardrail = _unwrap_typer_option_default(
            multi_recipe_for_the_guardrail
        )
        instruction_step_segmentation_policy = _unwrap_typer_option_default(
            instruction_step_segmentation_policy
        )
        instruction_step_segmenter = _unwrap_typer_option_default(
            instruction_step_segmenter
        )
        web_schema_extractor = _unwrap_typer_option_default(web_schema_extractor)
        web_schema_normalizer = _unwrap_typer_option_default(web_schema_normalizer)
        web_html_text_extractor = _unwrap_typer_option_default(web_html_text_extractor)
        web_schema_policy = _unwrap_typer_option_default(web_schema_policy)
        web_schema_min_confidence = _unwrap_typer_option_default(web_schema_min_confidence)
        web_schema_min_ingredients = _unwrap_typer_option_default(web_schema_min_ingredients)
        web_schema_min_instruction_steps = _unwrap_typer_option_default(
            web_schema_min_instruction_steps
        )
        ingredient_text_fix_backend = _unwrap_typer_option_default(
            ingredient_text_fix_backend
        )
        ingredient_pre_normalize_mode = _unwrap_typer_option_default(
            ingredient_pre_normalize_mode
        )
        ingredient_packaging_mode = _unwrap_typer_option_default(
            ingredient_packaging_mode
        )
        ingredient_parser_backend = _unwrap_typer_option_default(
            ingredient_parser_backend
        )
        ingredient_unit_canonicalizer = _unwrap_typer_option_default(
            ingredient_unit_canonicalizer
        )
        ingredient_missing_unit_policy = _unwrap_typer_option_default(
            ingredient_missing_unit_policy
        )
        p6_time_backend = _unwrap_typer_option_default(p6_time_backend)
        p6_time_total_strategy = _unwrap_typer_option_default(p6_time_total_strategy)
        p6_temperature_backend = _unwrap_typer_option_default(p6_temperature_backend)
        p6_temperature_unit_backend = _unwrap_typer_option_default(
            p6_temperature_unit_backend
        )
        p6_ovenlike_mode = _unwrap_typer_option_default(p6_ovenlike_mode)
        p6_yield_mode = _unwrap_typer_option_default(p6_yield_mode)
        p6_emit_metadata_debug = _unwrap_typer_option_default(p6_emit_metadata_debug)
        recipe_scorer_backend = _unwrap_typer_option_default(recipe_scorer_backend)
        recipe_score_gold_min = _unwrap_typer_option_default(recipe_score_gold_min)
        recipe_score_silver_min = _unwrap_typer_option_default(recipe_score_silver_min)
        recipe_score_bronze_min = _unwrap_typer_option_default(recipe_score_bronze_min)
        recipe_score_min_ingredient_lines = _unwrap_typer_option_default(
            recipe_score_min_ingredient_lines
        )
        recipe_score_min_instruction_lines = _unwrap_typer_option_default(
            recipe_score_min_instruction_lines
        )
        llm_recipe_pipeline = _unwrap_typer_option_default(llm_recipe_pipeline)
        recipe_prompt_target_count = _unwrap_typer_option_default(recipe_prompt_target_count)
        llm_knowledge_pipeline = _unwrap_typer_option_default(llm_knowledge_pipeline)
        knowledge_prompt_target_count = _unwrap_typer_option_default(
            knowledge_prompt_target_count
        )
        allow_codex = _unwrap_typer_option_default(allow_codex)
        codex_farm_cmd = _unwrap_typer_option_default(codex_farm_cmd)
        codex_farm_root = _unwrap_typer_option_default(codex_farm_root)
        codex_farm_workspace_root = _unwrap_typer_option_default(codex_farm_workspace_root)
        codex_farm_pipeline_knowledge = _unwrap_typer_option_default(
            codex_farm_pipeline_knowledge
        )
        codex_farm_context_blocks = _unwrap_typer_option_default(codex_farm_context_blocks)
        codex_farm_knowledge_context_blocks = _unwrap_typer_option_default(
            codex_farm_knowledge_context_blocks
        )
        codex_farm_failure_mode = _unwrap_typer_option_default(codex_farm_failure_mode)

        selected_epub_extractor = _normalize_epub_extractor(epub_extractor)
        selected_html_parser_version = _normalize_unstructured_html_parser_version(
            epub_unstructured_html_parser_version
        )
        selected_preprocess_mode = _normalize_unstructured_preprocess_mode(
            epub_unstructured_preprocess_mode
        )
        selected_skip_headers_footers = bool(epub_unstructured_skip_headers_footers)
        selected_ocr_device = _normalize_ocr_device(ocr_device)
        selected_pdf_ocr_policy = _normalize_pdf_ocr_policy(pdf_ocr_policy)
        selected_pdf_column_gap_ratio = _normalize_pdf_column_gap_ratio(
            pdf_column_gap_ratio
        )
        fixed_bucket1_behavior = bucket1_fixed_behavior()
        selected_section_detector_backend = fixed_bucket1_behavior.section_detector_backend
        selected_multi_recipe_splitter = _normalize_multi_recipe_splitter(
            multi_recipe_splitter
        )
        selected_multi_recipe_trace = fixed_bucket1_behavior.multi_recipe_trace
        selected_multi_recipe_min_ingredient_lines = max(
            0,
            int(multi_recipe_min_ingredient_lines),
        )
        selected_multi_recipe_min_instruction_lines = max(
            0,
            int(multi_recipe_min_instruction_lines),
        )
        selected_multi_recipe_for_the_guardrail = bool(multi_recipe_for_the_guardrail)
        selected_instruction_step_segmentation_policy = (
            fixed_bucket1_behavior.instruction_step_segmentation_policy
        )
        selected_instruction_step_segmenter = (
            fixed_bucket1_behavior.instruction_step_segmenter
        )
        selected_web_schema_extractor = _normalize_web_schema_extractor(
            web_schema_extractor
        )
        selected_web_schema_normalizer = _normalize_web_schema_normalizer(
            web_schema_normalizer
        )
        selected_web_html_text_extractor = _normalize_web_html_text_extractor(
            web_html_text_extractor
        )
        selected_web_schema_policy = _normalize_web_schema_policy(web_schema_policy)
        selected_web_schema_min_confidence = max(
            0.0,
            min(1.0, float(web_schema_min_confidence)),
        )
        selected_web_schema_min_ingredients = max(0, int(web_schema_min_ingredients))
        selected_web_schema_min_instruction_steps = max(
            0,
            int(web_schema_min_instruction_steps),
        )
        selected_ingredient_text_fix_backend = _normalize_ingredient_text_fix_backend(
            ingredient_text_fix_backend
        )
        selected_ingredient_pre_normalize_mode = _normalize_ingredient_pre_normalize_mode(
            ingredient_pre_normalize_mode
        )
        selected_ingredient_packaging_mode = _normalize_ingredient_packaging_mode(
            ingredient_packaging_mode
        )
        selected_ingredient_parser_backend = _normalize_ingredient_parser_backend(
            ingredient_parser_backend
        )
        selected_ingredient_unit_canonicalizer = _normalize_ingredient_unit_canonicalizer(
            ingredient_unit_canonicalizer
        )
        selected_ingredient_missing_unit_policy = _normalize_ingredient_missing_unit_policy(
            ingredient_missing_unit_policy
        )
        selected_p6_time_backend = _normalize_p6_time_backend(p6_time_backend)
        selected_p6_time_total_strategy = _normalize_p6_time_total_strategy(
            p6_time_total_strategy
        )
        selected_p6_temperature_backend = _normalize_p6_temperature_backend(
            p6_temperature_backend
        )
        selected_p6_temperature_unit_backend = _normalize_p6_temperature_unit_backend(
            p6_temperature_unit_backend
        )
        selected_p6_ovenlike_mode = _normalize_p6_ovenlike_mode(p6_ovenlike_mode)
        selected_p6_yield_mode = _normalize_p6_yield_mode(p6_yield_mode)
        selected_p6_emit_metadata_debug = fixed_bucket1_behavior.p6_emit_metadata_debug
        selected_recipe_scorer_backend = (
            str(recipe_scorer_backend or "heuristic_v1").strip() or "heuristic_v1"
        )
        selected_recipe_score_gold_min = max(0.0, min(1.0, float(recipe_score_gold_min)))
        selected_recipe_score_silver_min = max(
            0.0, min(1.0, float(recipe_score_silver_min))
        )
        selected_recipe_score_bronze_min = max(
            0.0, min(1.0, float(recipe_score_bronze_min))
        )
        selected_recipe_score_min_ingredient_lines = max(
            0,
            int(recipe_score_min_ingredient_lines),
        )
        selected_recipe_score_min_instruction_lines = max(
            0,
            int(recipe_score_min_instruction_lines),
        )
        selected_llm_recipe_pipeline = _normalize_llm_recipe_pipeline(llm_recipe_pipeline)
        selected_llm_knowledge_pipeline = _normalize_llm_knowledge_pipeline(llm_knowledge_pipeline)
        selected_codex_farm_failure_mode = _normalize_codex_farm_failure_mode(
            codex_farm_failure_mode
        )
        selected_codex_farm_pipeline_knowledge = (
            fixed_bucket1_behavior.codex_farm_pipeline_knowledge
        )

        # Apply EPUB unstructured runtime options for this run.
        # Extractor choice is passed explicitly into worker calls.
        _set_epub_unstructured_env(
            html_parser_version=selected_html_parser_version,
            skip_headers_footers=selected_skip_headers_footers,
            preprocess_mode=selected_preprocess_mode,
        )

        if not path.exists():
            _fail(f"Path not found: {path}")
        if mapping is not None and not mapping.exists():
            _fail(f"Mapping file not found: {mapping}")
        if overrides is not None and not overrides.exists():
            _fail(f"Overrides file not found: {overrides}")
        stage_started_monotonic = time.monotonic()

        # Create timestamped output folder for this run
        run_dt = dt.datetime.now()
        timestamp = run_dt.strftime("%Y-%m-%d_%H.%M.%S")
        output_root = out
        out = output_root / timestamp
        out.mkdir(parents=True, exist_ok=True)

        files_to_process = list(_iter_files(path))

        if not files_to_process:
            typer.secho("No files found to process.", fg=typer.colors.YELLOW)
            return out

        mapping_override: MappingConfig | None = None
        if mapping is not None:
            mapping_override = load_mapping_config(mapping)
    
        # Resolve mapping config once for parallel runs if provided
        # or use it as a template for overrides
        base_mapping = mapping_override or MappingConfig()
        base_mapping.ocr_device = selected_ocr_device
        base_mapping.ocr_batch_size = ocr_batch_size
        if overrides is not None:
            base_mapping.parsing_overrides = load_parsing_overrides(overrides)

        imported = 0
        errors: list[str] = []
        effective_epub_extractors: dict[Path, str] = {
            file_path: selected_epub_extractor
            for file_path in files_to_process
            if file_path.suffix.lower() == ".epub"
        }

        all_epub = all(f.suffix.lower() == ".epub" for f in files_to_process)
        run_settings = build_run_settings(
            workers=workers,
            pdf_split_workers=pdf_split_workers,
            epub_split_workers=epub_split_workers,
            pdf_pages_per_job=pdf_pages_per_job,
            epub_spine_items_per_job=epub_spine_items_per_job,
            epub_extractor=selected_epub_extractor,
            epub_unstructured_html_parser_version=selected_html_parser_version,
            epub_unstructured_skip_headers_footers=selected_skip_headers_footers,
            epub_unstructured_preprocess_mode=selected_preprocess_mode,
            ocr_device=selected_ocr_device,
            pdf_ocr_policy=selected_pdf_ocr_policy,
            ocr_batch_size=ocr_batch_size,
            pdf_column_gap_ratio=selected_pdf_column_gap_ratio,
            warm_models=warm_models,
            multi_recipe_splitter=selected_multi_recipe_splitter,
            multi_recipe_min_ingredient_lines=selected_multi_recipe_min_ingredient_lines,
            multi_recipe_min_instruction_lines=selected_multi_recipe_min_instruction_lines,
            multi_recipe_for_the_guardrail=selected_multi_recipe_for_the_guardrail,
            web_schema_extractor=selected_web_schema_extractor,
            web_schema_normalizer=selected_web_schema_normalizer,
            web_html_text_extractor=selected_web_html_text_extractor,
            web_schema_policy=selected_web_schema_policy,
            web_schema_min_confidence=selected_web_schema_min_confidence,
            web_schema_min_ingredients=selected_web_schema_min_ingredients,
            web_schema_min_instruction_steps=selected_web_schema_min_instruction_steps,
            ingredient_text_fix_backend=selected_ingredient_text_fix_backend,
            ingredient_pre_normalize_mode=selected_ingredient_pre_normalize_mode,
            ingredient_packaging_mode=selected_ingredient_packaging_mode,
            ingredient_parser_backend=selected_ingredient_parser_backend,
            ingredient_unit_canonicalizer=selected_ingredient_unit_canonicalizer,
            ingredient_missing_unit_policy=selected_ingredient_missing_unit_policy,
            p6_time_backend=selected_p6_time_backend,
            p6_time_total_strategy=selected_p6_time_total_strategy,
            p6_temperature_backend=selected_p6_temperature_backend,
            p6_temperature_unit_backend=selected_p6_temperature_unit_backend,
            p6_ovenlike_mode=selected_p6_ovenlike_mode,
            p6_yield_mode=selected_p6_yield_mode,
            recipe_scorer_backend=selected_recipe_scorer_backend,
            recipe_score_gold_min=selected_recipe_score_gold_min,
            recipe_score_silver_min=selected_recipe_score_silver_min,
            recipe_score_bronze_min=selected_recipe_score_bronze_min,
            recipe_score_min_ingredient_lines=selected_recipe_score_min_ingredient_lines,
            recipe_score_min_instruction_lines=selected_recipe_score_min_instruction_lines,
            llm_recipe_pipeline=selected_llm_recipe_pipeline,
            recipe_prompt_target_count=recipe_prompt_target_count,
            llm_knowledge_pipeline=selected_llm_knowledge_pipeline,
            knowledge_prompt_target_count=knowledge_prompt_target_count,
            codex_farm_cmd=codex_farm_cmd,
            codex_farm_root=codex_farm_root,
            codex_farm_workspace_root=codex_farm_workspace_root,
            codex_farm_context_blocks=codex_farm_context_blocks,
            codex_farm_knowledge_context_blocks=codex_farm_knowledge_context_blocks,
            codex_farm_failure_mode=selected_codex_farm_failure_mode,
            mapping_path=mapping,
            overrides_path=overrides,
            all_epub=all_epub,
            effective_workers=compute_effective_workers(
                workers=workers,
                epub_split_workers=epub_split_workers,
                epub_extractor=selected_epub_extractor,
                all_epub=all_epub,
            ),
        )
        stage_codex_execution = resolve_codex_execution_policy(
            "stage",
            run_settings.to_run_config_dict(),
            execution_policy_mode="execute",
            allow_codex=bool(allow_codex),
        )
        if stage_codex_execution.blocked:
            codex_surfaces = ", ".join(stage_codex_execution.surface.codex_surfaces) or "unknown"
            _fail(
                "stage enables Codex-backed surfaces "
                f"({codex_surfaces}) and requires explicit approval. "
                "Re-run with --allow-codex only after explicit positive user approval."
            )
        _print_codex_decision(stage_codex_execution)
        effective_workers = run_settings.effective_workers or workers
        run_config = apply_bucket1_fixed_behavior_metadata(
            apply_codex_execution_policy_metadata(
                run_settings.to_run_config_dict(),
                stage_codex_execution,
            )
        )
        run_config["epub_extractor_requested"] = selected_epub_extractor
        run_config["epub_extractor_effective"] = selected_epub_extractor
        run_config["write_markdown"] = bool(write_markdown)
        run_config["require_process_workers"] = bool(require_process_workers)
        if warm_models:
            with console.status("[bold cyan]Warming models...[/bold cyan]", spinner="dots"):
                _warm_all_models(ocr_device=selected_ocr_device)

        def _stable_run_config_hash(payload: dict[str, Any]) -> str:
            canonical = json.dumps(
                payload,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=True,
            )
            return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

        def _render_run_config_summary(payload: dict[str, Any]) -> str:
            return summarize_run_config_payload(payload, contract="operator")

        def _run_config_for_file(file_path: Path) -> dict[str, Any]:
            if file_path.suffix.lower() != ".epub":
                return dict(run_config)
            payload = dict(run_config)
            payload["epub_extractor_effective"] = effective_epub_extractors.get(
                file_path,
                selected_epub_extractor,
            )
            return payload

        run_config_hash = _stable_run_config_hash(run_config)
        run_config_summary = _render_run_config_summary(run_config)

        from cookimport.cli_worker import execute_source_job
        progress_queue = None
        try:
            manager = multiprocessing.Manager()
            progress_queue = manager.Queue()
        except Exception:
            progress_queue = None
    
        job_specs = plan_source_jobs(
            files_to_process,
            pdf_pages_per_job=pdf_pages_per_job,
            epub_spine_items_per_job=epub_spine_items_per_job,
            pdf_split_workers=pdf_split_workers,
            epub_split_workers=epub_split_workers,
            epub_extractor=selected_epub_extractor,
            epub_extractor_by_file=effective_epub_extractors,
        )
        total_jobs = len(job_specs)
        expected_jobs: dict[Path, int] = {}
        for job in job_specs:
            if job.file_path not in expected_jobs:
                expected_jobs[job.file_path] = job.job_count

        progress_bar = Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TextColumn("{task.percentage:>3.0f}%"),
            TextColumn("{task.completed}/{task.total}"),
        )
        overall_task = progress_bar.add_task("Total Progress", total=total_jobs)
        stage_timeseries_path = out / PROCESSING_TIMESERIES_FILENAME
        if stage_timeseries_path.exists():
            stage_timeseries_path.unlink()
        stage_timeseries_writer = _ProcessingTimeseriesWriter(
            path=stage_timeseries_path,
            heartbeat_seconds=PROCESSING_TIMESERIES_HEARTBEAT_SECONDS,
        )
        stage_timeseries_stop = threading.Event()
        stage_timeseries_thread: threading.Thread | None = None

        _supports_live_status = bool(console.is_terminal and not console.is_dumb_terminal)
        _plain_progress_override = _plain_progress_override_requested()
        if _plain_progress_override is True:
            _supports_live_status = False
        elif _plain_progress_override is None and _should_default_plain_progress_for_agent():
            _supports_live_status = False

        stage_worker_dashboard = ProgressDashboardCore()
        stage_worker_status_snapshot = ""

        class _StageProgressAdapter:
            def __init__(self) -> None:
                self._worker_lock = threading.Lock()
                self._worker_status: dict[str, dict[str, Any]] = {}
                self._active_file = ""

            def set_active_file(self, file_path: str) -> None:
                clean = str(file_path or "").strip()
                if not clean:
                    return
                with self._worker_lock:
                    self._active_file = clean

            def set_worker_status(
                self,
                worker_label: str,
                filename: str,
                status: str,
                *,
                updated_at: float | None = None,
            ) -> None:
                if updated_at is None:
                    updated_at = time.time()
                clean_label = str(worker_label or "").strip() or "worker"
                clean_file = str(filename or "").strip()
                clean_status = str(status or "").strip()
                payload = {
                    "file": clean_file,
                    "status": clean_status,
                    "updated_at": float(updated_at),
                }
                self.set_active_file(clean_file)
                with self._worker_lock:
                    self._worker_status[clean_label] = payload

            def collect_worker_rows(self) -> dict[str, dict[str, str]]:
                with self._worker_lock:
                    return {
                        str(label): {
                            "file": str(entry.get("file") or ""),
                            "status": str(entry.get("status") or ""),
                            "updated_at": str(entry.get("updated_at") or ""),
                        }
                        for label, entry in self._worker_status.items()
                    }

            def resolve_current_file(self, *, fallback_file: str = "") -> str:
                worker_rows = self.collect_worker_rows()
                active_rows: list[tuple[float, str]] = []
                for entry in worker_rows.values():
                    status = str(entry.get("status") or "").strip().lower()
                    file_value = str(entry.get("file") or "").strip()
                    if not file_value:
                        continue
                    if status in {"", "idle", "done", "skipped"}:
                        continue
                    try:
                        updated_at = float(entry.get("updated_at", 0.0))
                    except (TypeError, ValueError):
                        updated_at = 0.0
                    active_rows.append((updated_at, file_value))

                if active_rows:
                    active_rows.sort(key=lambda item: item[0], reverse=True)
                    return active_rows[0][1]

                with self._worker_lock:
                    if self._active_file:
                        return self._active_file

                if worker_rows:
                    return list(worker_rows.values())[0].get("file", "").strip()

                return str(fallback_file).strip()

            def build_worker_lines(
                self,
                *,
                now: float | None = None,
                run_complete: bool = False,
            ) -> list[str]:
                current_time = float(time.time() if now is None else now)
                with self._worker_lock:
                    items = list(self._worker_status.items())
                if not items:
                    return ["Waiting for worker updates..."]

                lines: list[str] = []
                for worker_label, entry in sorted(items, key=lambda item: item[0]):
                    try:
                        age_seconds = max(
                            0,
                            int(current_time - float(entry.get("updated_at", 0.0))),
                        )
                    except (TypeError, ValueError):
                        age_seconds = 0
                    age_label = "just now" if age_seconds < 1 else f"{age_seconds}s ago"
                    worker_status_value = str(entry.get("status") or "")
                    if not run_complete and worker_status_value.lower() in {"done", "skipped"}:
                        worker_status_value = "Idle"
                    lines.append(
                        f"{worker_label}: {entry.get('file', '')} - "
                        f"{worker_status_value} ({age_label})"
                    )
                return lines

            def active_worker_count(
                self,
                worker_rows: dict[str, dict[str, str]] | None = None,
            ) -> int:
                if worker_rows is None:
                    worker_rows = self.collect_worker_rows()
                return sum(
                    1
                    for entry in worker_rows.values()
                    if str(entry.get("status") or "").strip().lower()
                    not in {"", "idle", "done", "skipped"}
                )

        stage_progress_adapter = _StageProgressAdapter()
        _status_style_tag_re = re.compile(r"\[[^\]]+\]")
        stage_status_widget: Any | None = None
        stage_status_console: Any | None = None

        def _strip_rich_style(message: str) -> str:
            return _status_style_tag_re.sub("", str(message))

        def _collect_stage_worker_status_rows() -> dict[str, dict[str, str]]:
            return stage_progress_adapter.collect_worker_rows()

        def _set_stage_active_file(file_path: str) -> None:
            stage_progress_adapter.set_active_file(file_path)

        def _set_worker_status(
            worker_label: str,
            filename: str,
            status: str,
            *,
            updated_at: float | None = None,
        ) -> None:
            stage_progress_adapter.set_worker_status(
                worker_label,
                filename,
                status,
                updated_at=updated_at,
            )
            _write_stage_timeseries(event="worker_update")

        def _write_stage_timeseries(*, event: str, force: bool = False) -> None:
            task_obj = progress_bar.tasks[0] if progress_bar.tasks else None
            completed_jobs = (
                max(0, int(task_obj.completed))
                if task_obj is not None
                else 0
            )
            status_rows = _collect_stage_worker_status_rows()
            active_workers = stage_progress_adapter.active_worker_count(status_rows)
            pending_jobs = max(0, total_jobs - completed_jobs)
            snapshot = (
                f"stage task {completed_jobs}/{total_jobs} | "
                f"imported {imported} | active_workers {active_workers} | "
                f"pending {pending_jobs} | errors {len(errors)}"
            )
            stage_timeseries_writer.write_row(
                snapshot=snapshot,
                force=force,
                payload={
                    "event": str(event or "").strip() or "update",
                    "mode": "stage",
                    "run_dir": str(out),
                    "elapsed_seconds": max(0.0, time.monotonic() - stage_started_monotonic),
                    "jobs_completed": completed_jobs,
                    "jobs_total": total_jobs,
                    "pending_jobs": pending_jobs,
                    "imported_files": imported,
                    "error_count": len(errors),
                    "worker_total": len(status_rows),
                    "worker_active": active_workers,
                    "worker_status": status_rows,
                },
            )

        def _build_stage_worker_lines(*, now: float | None = None) -> list[str]:
            task = progress_bar.tasks[0] if progress_bar.tasks else None
            run_complete = bool(task and task.completed >= task.total)
            return stage_progress_adapter.build_worker_lines(now=now, run_complete=run_complete)

        def _resolve_stage_current_file() -> str:
            return stage_progress_adapter.resolve_current_file(
                fallback_file=(
                    str(job_specs[0].display_name).strip() if job_specs else ""
                ),
            )

        def _build_stage_progress_snapshot(*, now: float | None = None) -> str:
            task = progress_bar.tasks[0] if progress_bar.tasks else None
            completed_jobs = max(0, int(task.completed)) if task is not None else 0
            pending_jobs = max(0, total_jobs - completed_jobs)
            worker_rows = _collect_stage_worker_status_rows()
            active_workers = stage_progress_adapter.active_worker_count(worker_rows)
            stage_worker_dashboard.set_status_line(
                f"overall jobs {completed_jobs}/{total_jobs} | imported {imported} | "
                f"active_workers {active_workers} | pending {pending_jobs} | "
                f"errors {len(errors)}"
            )
            stage_worker_dashboard.set_task(f"stage task {completed_jobs}/{total_jobs}")
            stage_worker_dashboard.set_current(_resolve_stage_current_file())
            stage_worker_dashboard.set_worker_lines(_build_stage_worker_lines(now=now))
            return stage_worker_dashboard.render()

        def _emit_stage_progress_snapshot(*, force: bool = False, now: float | None = None) -> None:
            nonlocal stage_worker_status_snapshot
            snapshot = _build_stage_progress_snapshot(now=now)
            if not force and snapshot == stage_worker_status_snapshot:
                return
            stage_worker_status_snapshot = snapshot
            if stage_status_widget is None:
                typer.secho(snapshot, fg=typer.colors.CYAN)
                return
            stage_status_widget.update(rich_escape(snapshot))

        def _emit_stage_message(
            message: str,
            *,
            fg: Any | None,
        ) -> None:
            if stage_status_console is None:
                typer.secho(_strip_rich_style(message), fg=fg)
                return
            stage_status_console.print(message)

        # Background thread to consume queue
        stop_event = threading.Event()
        queue_thread = None
        if progress_queue is not None:
            def process_queue():
                while not stop_event.is_set():
                    try:
                        # Non-blocking get with short timeout
                        try:
                            record = progress_queue.get(timeout=0.05)
                        except queue.Empty:
                            continue
                    
                        if isinstance(record, (tuple, list)) and len(record) == 4:
                            worker_label, filename, status, updated_at = record
                        elif isinstance(record, (tuple, list)) and len(record) == 2:
                            filename, status = record
                            worker_label = "worker"
                            updated_at = time.time()
                        else:
                            continue

                        _set_worker_status(
                            str(worker_label),
                            str(filename),
                            str(status),
                            updated_at=float(updated_at),
                        )
                    except Exception:
                        pass

            queue_thread = threading.Thread(target=process_queue, daemon=True)
            queue_thread.start()

        def _stage_timeseries_tick() -> None:
            while not stage_timeseries_stop.wait(
                max(0.05, PROCESSING_TIMESERIES_HEARTBEAT_SECONDS)
            ):
                _write_stage_timeseries(event="tick")

        _write_stage_timeseries(event="started", force=True)
        stage_timeseries_thread = threading.Thread(
            target=_stage_timeseries_tick,
            name="stage-processing-timeseries",
            daemon=True,
        )
        stage_timeseries_thread.start()

        typer.secho(
            f"Processing {len(files_to_process)} file(s) as {total_jobs} job(s) using {effective_workers} workers...",
            fg=typer.colors.CYAN,
        )

        job_results_by_file: dict[Path, list[dict[str, Any]]] = defaultdict(list)

        def _run_config_hash_for_file(file_path: Path) -> str:
            return _stable_run_config_hash(_run_config_for_file(file_path))

        def _run_config_summary_for_file(file_path: Path) -> str:
            return _render_run_config_summary(_run_config_for_file(file_path))

        def handle_job_result(job: JobSpec, res: dict[str, Any]) -> None:
            nonlocal imported
            job_run_config = _run_config_for_file(job.file_path)
            job_run_config_hash = _run_config_hash_for_file(job.file_path)
            job_run_config_summary = _run_config_summary_for_file(job.file_path)
            job_results_by_file[job.file_path].append(res)
            if res.get("status") == "error":
                _emit_stage_message(
                    f"[red]✘ Error {job.file_path.name} job {job.job_index}: {res.get('reason')}[/red]",
                    fg=typer.colors.RED,
                )

            expected_count = expected_jobs.get(job.file_path, job.job_count)
            if len(job_results_by_file[job.file_path]) == expected_count:
                results = job_results_by_file.pop(job.file_path)
                result_importer_name = next(
                    (
                        str(r.get("importer_name") or "").strip()
                        for r in results
                        if str(r.get("importer_name") or "").strip()
                    ),
                    None,
                )
                successful = [r for r in results if r.get("status") == "success"]
                skipped = [r for r in results if r.get("status") == "skipped"]
                failed = [
                    r for r in results if r.get("status") not in {"success", "skipped"}
                ]

                if successful and not failed and not skipped:
                    _set_worker_status(
                        "MainProcess",
                        job.file_path.name,
                        f"Merging {expected_count} source job(s)...",
                    )
                    _emit_stage_message(
                        f"Merging {expected_count} source job(s) for {job.file_path.name}...",
                        fg=typer.colors.CYAN,
                    )
                    try:
                        def _main_merge_status(message: str) -> None:
                            _set_worker_status(
                                "MainProcess",
                                job.file_path.name,
                                message,
                            )

                        merged = _merge_source_jobs(
                            job.file_path,
                            results,
                            out,
                            base_mapping,
                            limit,
                            run_dt,
                            run_config=job_run_config,
                            run_config_hash=job_run_config_hash,
                            run_config_summary=job_run_config_summary,
                            write_markdown=write_markdown,
                            status_callback=_main_merge_status,
                        )
                        imported += 1
                        _set_worker_status(
                            "MainProcess",
                            job.file_path.name,
                            f"Merge done ({merged['duration']:.2f}s)",
                        )
                        merged_tips = int(merged.get("tips") or 0)
                        _emit_stage_message(
                            f"[green]✔ {merged['file']}: {merged['recipes']} recipes, "
                            f"{merged_tips} tips (merge {merged['duration']:.2f}s)[/green]",
                            fg=typer.colors.GREEN,
                        )
                    except Exception as exc:
                        errors.append(f"{job.file_path.name}: {exc}")
                        _set_worker_status(
                            "MainProcess",
                            job.file_path.name,
                            "Merge error",
                        )
                        _emit_stage_message(
                            f"[red]✘ Error {job.file_path.name}: {exc}[/red]",
                            fg=typer.colors.RED,
                        )
                        _write_error_report(
                            out,
                            job.file_path,
                            run_dt,
                            [str(exc)],
                            importer_name=result_importer_name,
                            run_config=job_run_config,
                            run_config_hash=job_run_config_hash,
                            run_config_summary=job_run_config_summary,
                        )
                elif skipped and not successful and not failed:
                    reason = str(skipped[0].get("reason") or "No importer")
                    _emit_stage_message(
                        f"[yellow]⚠ Skipping {job.file_path.name}: {reason}[/yellow]",
                        fg=typer.colors.YELLOW,
                    )
                else:
                    reasons = [
                        f"job {r.get('job_index')}: {r.get('reason')}"
                        for r in [*failed, *skipped]
                    ]
                    if not reasons:
                        reasons = ["job failure"]
                    message = "; ".join(reasons)
                    errors.append(f"{job.file_path.name}: {message}")
                    _set_worker_status(
                        "MainProcess",
                        job.file_path.name,
                        "Merge skipped (job errors)",
                    )
                    _emit_stage_message(
                        f"[red]✘ Error {job.file_path.name}: {message}[/red]",
                        fg=typer.colors.RED,
                    )
                    _write_error_report(
                        out,
                        job.file_path,
                        run_dt,
                        reasons,
                        importer_name=result_importer_name,
                        run_config=job_run_config,
                        run_config_hash=job_run_config_hash,
                        run_config_summary=job_run_config_summary,
                    )
            _emit_stage_progress_snapshot(force=True)
            _write_stage_timeseries(event="job_completed", force=True)

        stage_worker_request_root = out / ".stage_worker_requests"
        stage_worker_request_root.mkdir(parents=True, exist_ok=True)
        stage_worker_mapping_payload = base_mapping.model_dump(mode="json")
        stage_subprocess_worker_probe_cache: bool | None = None

        def _stage_subprocess_worker_available() -> bool:
            nonlocal stage_subprocess_worker_probe_cache
            if stage_subprocess_worker_probe_cache is not None:
                return stage_subprocess_worker_probe_cache
            command = [
                sys.executable,
                "-m",
                "cookimport.cli_worker",
                "--stage-worker-self-test",
            ]
            try:
                completed = subprocess.run(
                    command,
                    cwd=str(REPO_ROOT),
                    check=False,
                    capture_output=True,
                    text=True,
                )
            except Exception:
                stage_subprocess_worker_probe_cache = False
                return False
            stage_subprocess_worker_probe_cache = completed.returncode == 0
            return bool(stage_subprocess_worker_probe_cache)

        def _stage_job_failure_payload(job: JobSpec, reason: str) -> dict[str, Any]:
            payload: dict[str, Any] = {
                "file": job.file_path.name,
                "status": "error",
                "reason": reason,
                "importer_name": None,
                "job_index": job.job_index,
                "job_count": job.job_count,
            }
            if job.start_page is not None:
                payload["start_page"] = job.start_page
            if job.end_page is not None:
                payload["end_page"] = job.end_page
            if job.start_spine is not None:
                payload["start_spine"] = job.start_spine
            if job.end_spine is not None:
                payload["end_spine"] = job.end_spine
            return payload

        def _stage_subprocess_job_payload(job: JobSpec) -> dict[str, Any]:
            job_run_config = _run_config_for_file(job.file_path)
            job_run_config_hash = _run_config_hash_for_file(job.file_path)
            job_run_config_summary = _run_config_summary_for_file(job.file_path)
            payload: dict[str, Any] = {
                **job.to_payload(),
                "out_path": str(out),
                "mapping_config": stage_worker_mapping_payload,
                "run_dt": run_dt.isoformat(timespec="seconds"),
                "display_name": job.display_name,
                "run_config": job_run_config,
                "run_config_hash": job_run_config_hash,
                "run_config_summary": job_run_config_summary,
                "job_kind": "source_job",
                "epub_extractor": effective_epub_extractors.get(job.file_path),
            }
            return payload

        def _run_stage_job_via_subprocess(job: JobSpec) -> dict[str, Any]:
            job_key = f"{job.file_path.stem}_{job.job_index}_{int(time.time() * 1_000_000)}"
            request_path = stage_worker_request_root / f"{job_key}.request.json"
            result_path = stage_worker_request_root / f"{job_key}.result.pkl"
            request_payload = {
                "result_path": str(result_path),
                "job": _stage_subprocess_job_payload(job),
            }
            request_path.write_text(
                json.dumps(request_payload, indent=2, sort_keys=True),
                encoding="utf-8",
            )
            command = [
                sys.executable,
                "-m",
                "cookimport.cli_worker",
                "--stage-worker-request",
                str(request_path),
            ]
            try:
                completed = subprocess.run(
                    command,
                    cwd=str(REPO_ROOT),
                    check=False,
                    capture_output=True,
                    text=True,
                )
            except Exception as exc:
                return _stage_job_failure_payload(
                    job,
                    f"Subprocess worker launch failed: {exc}",
                )
            finally:
                try:
                    request_path.unlink(missing_ok=True)
                except OSError:
                    pass
            if completed.returncode != 0:
                stderr_tail = (completed.stderr or "").strip()
                stdout_tail = (completed.stdout or "").strip()
                detail = stderr_tail or stdout_tail
                if detail:
                    detail = detail.splitlines()[-1]
                    reason = (
                        "Subprocess worker exited non-zero "
                        f"({completed.returncode}): {detail}"
                    )
                else:
                    reason = f"Subprocess worker exited non-zero ({completed.returncode})."
                return _stage_job_failure_payload(job, reason)
            if not result_path.exists() or not result_path.is_file():
                return _stage_job_failure_payload(
                    job,
                    "Subprocess worker did not produce a result payload.",
                )
            try:
                with result_path.open("rb") as handle:
                    result_payload = pickle.load(handle)  # noqa: S301
            except Exception as exc:
                return _stage_job_failure_payload(
                    job,
                    f"Failed to read subprocess worker result payload: {exc}",
                )
            finally:
                try:
                    result_path.unlink(missing_ok=True)
                except OSError:
                    pass
            if not isinstance(result_payload, dict):
                return _stage_job_failure_payload(
                    job,
                    "Invalid subprocess worker result payload.",
                )
            return result_payload

        def _run_jobs_with_executor(executor: Any) -> None:
            futures: dict[Any, JobSpec] = {}
            for job in job_specs:
                _set_stage_active_file(job.display_name)
                job_run_config = _run_config_for_file(job.file_path)
                job_run_config_hash = _run_config_hash_for_file(job.file_path)
                job_run_config_summary = _run_config_summary_for_file(job.file_path)
                job_epub_extractor = effective_epub_extractors.get(job.file_path)
                futures[
                    executor.submit(
                        execute_source_job,
                        job,
                        out,
                        base_mapping,
                        run_dt,
                        progress_queue,
                        job.display_name,
                        job_epub_extractor,
                        job_run_config,
                        job_run_config_hash,
                        job_run_config_summary,
                    )
                ] = job

            for future in as_completed(futures):
                job = futures[future]
                try:
                    res = future.result()
                except Exception as exc:
                    res = {
                        "file": job.file_path.name,
                        "status": "error",
                        "reason": str(exc),
                        "job_index": job.job_index,
                        "job_count": job.job_count,
                        "start_page": job.start_page,
                        "end_page": job.end_page,
                        "start_spine": job.start_spine,
                        "end_spine": job.end_spine,
                    }

                progress_bar.update(overall_task, advance=1)
                handle_job_result(job, res)

        def _run_jobs_with_subprocess_executor(executor: Any) -> None:
            worker_limit = max(1, min(effective_workers, len(job_specs)))
            pending_jobs = list(job_specs)
            futures: dict[Any, tuple[JobSpec, int]] = {}
            available_slots: deque[int] = deque(range(1, worker_limit + 1))

            def _submit_job(job: JobSpec, slot: int) -> None:
                _set_stage_active_file(job.display_name)
                futures[executor.submit(_run_stage_job_via_subprocess, job)] = (job, slot)
                _set_worker_status(
                    f"SubprocessWorker-{slot}",
                    job.display_name,
                    "Running subprocess worker...",
                )

            while pending_jobs and available_slots:
                _submit_job(pending_jobs.pop(0), available_slots.popleft())

            while futures:
                future = next(as_completed(list(futures.keys())))
                job, slot = futures.pop(future)
                try:
                    res = future.result()
                except Exception as exc:
                    res = _stage_job_failure_payload(
                        job,
                        f"Subprocess worker dispatch failed: {exc}",
                    )
                _set_worker_status(
                    f"SubprocessWorker-{slot}",
                    job.display_name,
                    "Done",
                )
                progress_bar.update(overall_task, advance=1)
                handle_job_result(job, res)
                if pending_jobs:
                    _submit_job(pending_jobs.pop(0), slot)
                else:
                    available_slots.append(slot)

        def _run_jobs_serial() -> None:
            for job in job_specs:
                _set_stage_active_file(job.display_name)
                job_run_config = _run_config_for_file(job.file_path)
                job_run_config_hash = _run_config_hash_for_file(job.file_path)
                job_run_config_summary = _run_config_summary_for_file(job.file_path)
                job_epub_extractor = effective_epub_extractors.get(job.file_path)
                res = execute_source_job(
                    job,
                    out,
                    base_mapping,
                    run_dt,
                    progress_queue,
                    job.display_name,
                    job_epub_extractor,
                    job_run_config,
                    job_run_config_hash,
                    job_run_config_summary,
                )
                progress_bar.update(overall_task, advance=1)
                handle_job_result(job, res)

        stage_worker_backend_effective = "serial"
        stage_worker_resolution_messages: list[str] = []

        def _run_jobs() -> None:
            nonlocal stage_worker_backend_effective
            nonlocal stage_worker_resolution_messages
            executor_resolution = resolve_process_thread_executor(
                max_workers=effective_workers,
                process_unavailable_message=lambda exc: (
                    "Process-based worker concurrency unavailable "
                    f"({exc}); using subprocess-backed worker concurrency."
                ),
                thread_unavailable_message=lambda exc: (
                    "Thread-based worker concurrency unavailable "
                    f"({exc}); running jobs serially."
                ),
            )
            stage_worker_resolution_messages = list(executor_resolution.messages)
            for message in executor_resolution.messages:
                _emit_stage_message(
                    f"[yellow]⚠ {message}[/yellow]",
                    fg=typer.colors.YELLOW,
                )

            if require_process_workers and executor_resolution.backend != "process":
                detail = (
                    "; ".join(executor_resolution.messages)
                    if executor_resolution.messages
                    else "process worker pool could not be established."
                )
                raise RuntimeError(
                    "Process-based worker concurrency is required for this stage run, "
                    f"but it is unavailable: {detail}"
                )
            stage_worker_backend_effective = str(executor_resolution.backend)
            if executor_resolution.executor is None:
                _run_jobs_serial()
            else:
                executor = executor_resolution.executor
                try:
                    use_subprocess_workers = (
                        executor_resolution.backend == "thread"
                        and _stage_subprocess_worker_available()
                    )
                    if executor_resolution.backend == "thread" and not use_subprocess_workers:
                        _emit_stage_message(
                            "[yellow]⚠ Subprocess-backed worker concurrency unavailable; "
                            "using in-process thread worker concurrency.[/yellow]",
                            fg=typer.colors.YELLOW,
                        )
                    if use_subprocess_workers:
                        stage_worker_backend_effective = "subprocess"
                        _run_jobs_with_subprocess_executor(executor)
                    else:
                        _run_jobs_with_executor(executor)
                finally:
                    shutdown_executor(executor, wait=True, cancel_futures=False)

        stage_live_status_slots = _effective_live_status_slots()

        try:
            _emit_stage_progress_snapshot(force=True)
            if _supports_live_status:
                with _acquire_live_status_slot(stage_live_status_slots) as live_slot_acquired:
                    if live_slot_acquired:
                        stage_live_console = _resolve_live_status_console(
                            live_status_slots=stage_live_status_slots
                        )
                        with stage_live_console.status(
                            _build_stage_progress_snapshot(),
                            spinner="dots",
                            refresh_per_second=4.0,
                        ) as status:
                            stage_status_widget = status
                            stage_status_console = status.console
                            _emit_stage_progress_snapshot(force=True)

                            def _tick() -> None:
                                while not stop_event.wait(max(0.05, _STATUS_TICK_SECONDS)):
                                    now = time.monotonic()
                                    _emit_stage_progress_snapshot(now=now)
                                    _write_stage_timeseries(event="tick", now=now)

                            ticker = threading.Thread(
                                target=_tick,
                                name="stage-progress-ticker",
                                daemon=True,
                            )
                            ticker.start()

                            try:
                                _run_jobs()
                            finally:
                                stop_event.set()
                                ticker.join(timeout=max(0.2, float(_STATUS_TICK_SECONDS) * 2))
                    else:
                        _run_jobs()
            else:
                _run_jobs()
        finally:
            stop_event.set()
            if queue_thread is not None:
                queue_thread.join()
            stage_timeseries_stop.set()
            if stage_timeseries_thread is not None:
                stage_timeseries_thread.join(timeout=2.0)
            _write_stage_timeseries(event="finished", force=True)

        typer.secho(f"\nStaged {imported} file(s).", fg=typer.colors.GREEN)
        typer.secho(
            f"Processing telemetry: {stage_timeseries_path}",
            fg=typer.colors.BRIGHT_BLACK,
        )
        if errors:
            typer.secho("Errors encountered:", fg=typer.colors.YELLOW)
            for message in errors:
                typer.secho(f"- {message}", fg=typer.colors.YELLOW)

        stage_worker_resolution_path = out / "stage_worker_resolution.json"
        stage_worker_resolution_payload = {
            "process_workers_required": bool(require_process_workers),
            "backend_effective": stage_worker_backend_effective,
            "messages": stage_worker_resolution_messages,
        }
        stage_worker_resolution_path.write_text(
            json.dumps(stage_worker_resolution_payload, indent=2, sort_keys=True),
            encoding="utf-8",
        )

        try:
            from cookimport.analytics.perf_report import (
                append_history_csv,
                build_perf_summary,
                format_summary_line,
                history_path,
            )

            summary = build_perf_summary(out)
            if summary.rows:
                typer.secho("\nPerformance summary:", fg=typer.colors.CYAN)
                typer.echo(f"Run: {out}")
                for row in summary.rows:
                    typer.echo(format_summary_line(row))

                if summary.total_outliers:
                    outlier_names = ", ".join(row.file_name for row in summary.total_outliers)
                    typer.secho(
                        f"Outliers (total time > 3x median): {outlier_names}",
                        fg=typer.colors.YELLOW,
                    )
                if summary.parsing_outliers:
                    outlier_names = ", ".join(row.file_name for row in summary.parsing_outliers)
                    typer.secho(
                        f"Outliers (parsing time > 3x median): {outlier_names}",
                        fg=typer.colors.YELLOW,
                    )
                if summary.writing_outliers:
                    outlier_names = ", ".join(row.file_name for row in summary.writing_outliers)
                    typer.secho(
                        f"Outliers (writing time > 3x median): {outlier_names}",
                        fg=typer.colors.YELLOW,
                    )
                if summary.per_unit_outliers:
                    outlier_names = ", ".join(row.file_name for row in summary.per_unit_outliers)
                    typer.secho(
                        f"Outliers (per-unit > 3x median): {outlier_names}",
                        fg=typer.colors.YELLOW,
                    )
                if summary.per_recipe_outliers:
                    outlier_names = ", ".join(row.file_name for row in summary.per_recipe_outliers)
                    typer.secho(
                        "Outliers (per-recipe > 3x median, recipe-heavy only): " + outlier_names,
                        fg=typer.colors.YELLOW,
                    )
                if summary.knowledge_heavy:
                    heavy_names = ", ".join(row.file_name for row in summary.knowledge_heavy)
                    typer.secho(
                        "Knowledge-heavy runs (topic candidates dominate): " + heavy_names,
                        fg=typer.colors.CYAN,
                    )

                csv_history_path = history_path(output_root)
                append_history_csv(summary.rows, csv_history_path)
                _refresh_dashboard_after_history_write(
                    csv_path=csv_history_path,
                    output_root=output_root,
                    golden_root=DEFAULT_GOLDEN,
                    reason="stage history append",
                )
        except Exception as exc:
            logger.warning("Performance summary skipped: %s", exc)

        _write_knowledge_index_best_effort(out)

        _write_stage_observability_best_effort(
            run_root=out,
            run_kind="stage",
            run_dt=run_dt,
            run_config=run_config,
        )

        llm_prompt_artifacts.build_codex_farm_prompt_response_log(
            pred_run=out,
            eval_output_dir=out,
            repo_root=REPO_ROOT,
        )

        stage_run_summary = _write_stage_run_summary(
            run_root=out,
            requested_path=path,
            run_config=run_config,
            errors=errors,
            write_markdown=write_markdown,
        )
        if stage_run_summary is not None:
            _print_stage_summary(stage_run_summary, write_markdown=write_markdown)

        _write_stage_run_manifest(
            run_root=out,
            output_root=output_root,
            requested_path=path,
            run_dt=run_dt,
            run_config=run_config,
        )

        return out

        typer.secho(f"\nStaged {imported} file(s).", fg=typer.colors.GREEN)
        if errors:
            typer.secho("Errors encountered:", fg=typer.colors.YELLOW)
            for message in errors:
                typer.secho(f"- {message}", fg=typer.colors.YELLOW)

        return out

    exports = {"stage": stage}
    globals().update(exports)
    return exports
