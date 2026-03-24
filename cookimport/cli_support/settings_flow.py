from __future__ import annotations

from cookimport import cli_support as runtime

# Snapshot the fully initialized root support namespace so these moved
# flow/progress helpers can keep their historical unqualified references.
globals().update(
    {name: value for name, value in vars(runtime).items() if name != "__builtins__"}
)

def _settings_menu(current_settings: Dict[str, Any]) -> None:
    """Run the settings configuration menu."""
    while True:
        enabled_epub_extractors = epub_extractor_enabled_choices()
        enabled_epub_extractors_display = "/".join(enabled_epub_extractors)
        current_epub_extractor = _coerce_configured_epub_extractor(
            current_settings.get("epub_extractor", "unstructured")
        )
        current_settings["epub_extractor"] = current_epub_extractor
        current_pdf_ocr_policy = str(
            current_settings.get("pdf_ocr_policy", "auto") or "auto"
        ).strip().lower()
        if current_pdf_ocr_policy not in {"off", "auto", "always"}:
            current_pdf_ocr_policy = "auto"
        current_recipe_pipeline = str(
            current_settings.get("llm_recipe_pipeline", "off") or "off"
        ).strip().lower()
        if current_recipe_pipeline not in RECIPE_CODEX_FARM_ALLOWED_PIPELINES:
            current_recipe_pipeline = "off"
        current_knowledge_pipeline = str(
            current_settings.get("llm_knowledge_pipeline", "off") or "off"
        ).strip().lower()
        if current_knowledge_pipeline not in {"off", KNOWLEDGE_CODEX_PIPELINE_SHARD_V1}:
            current_knowledge_pipeline = "off"
        current_web_schema_extractor = str(
            current_settings.get("web_schema_extractor", "builtin_jsonld")
            or "builtin_jsonld"
        ).strip().lower().replace("-", "_")
        if current_web_schema_extractor not in {
            "builtin_jsonld",
            "extruct",
            "scrape_schema_recipe",
            "recipe_scrapers",
            "ensemble_v1",
        }:
            current_web_schema_extractor = "builtin_jsonld"
        current_web_schema_normalizer = str(
            current_settings.get("web_schema_normalizer", "simple") or "simple"
        ).strip().lower().replace("-", "_")
        if current_web_schema_normalizer not in {"simple", "pyld"}:
            current_web_schema_normalizer = "simple"
        current_web_html_text_extractor = str(
            current_settings.get("web_html_text_extractor", "bs4") or "bs4"
        ).strip().lower().replace("-", "_")
        if current_web_html_text_extractor not in {
            "bs4",
            "trafilatura",
            "readability_lxml",
            "justext",
            "boilerpy3",
            "ensemble_v1",
        }:
            current_web_html_text_extractor = "bs4"
        current_web_schema_policy = str(
            current_settings.get("web_schema_policy", "prefer_schema")
            or "prefer_schema"
        ).strip().lower().replace("-", "_")
        if current_web_schema_policy not in ALL_METHOD_WEBSCHEMA_POLICIES:
            current_web_schema_policy = "prefer_schema"
        current_codex_cmd = _display_optional_setting(
            current_settings.get("codex_farm_cmd"),
            empty_label="codex-farm",
        )
        current_codex_root = _display_optional_setting(
            current_settings.get("codex_farm_root"),
            empty_label="<auto>",
        )
        current_codex_workspace_root = _display_optional_setting(
            current_settings.get("codex_farm_workspace_root"),
            empty_label="<auto>",
        )
        current_codex_model = _display_optional_setting(
            current_settings.get("codex_farm_model"),
            empty_label="<pipeline default>",
        )
        current_codex_reasoning_effort = _display_optional_setting(
            current_settings.get("codex_farm_reasoning_effort"),
            empty_label="<pipeline default>",
        )
        current_label_studio_url = _display_optional_setting(
            current_settings.get("label_studio_url"),
            empty_label="<unset>",
        )
        current_label_studio_api_key_status = (
            "set"
            if str(current_settings.get("label_studio_api_key") or "").strip()
            else "unset"
        )

        # Refresh values in display
        choice = _menu_select(
            "Settings Configuration",
            menu_help=(
                "Tune defaults used by stage/benchmark jobs. "
                "These settings are saved to cookimport.json."
            ),
            choices=[
                questionary.Choice(
                    f"Workers: {current_settings.get('workers', 4)} - max parallel file jobs",
                    value="workers",
                ),
                questionary.Choice(
                    f"PDF Split Workers: {current_settings.get('pdf_split_workers', 7)} - max PDF shard jobs",
                    value="pdf_split_workers",
                ),
                questionary.Choice(
                    f"EPUB Split Workers: {current_settings.get('epub_split_workers', 7)} - max EPUB shard jobs",
                    value="epub_split_workers",
                ),
                questionary.Choice(
                    (
                        "All-Method Parallel Sources: "
                        f"{_resolve_positive_int_setting(current_settings, key=ALL_METHOD_MAX_PARALLEL_SOURCES_SETTING_KEY, fallback=_all_method_default_parallel_sources_from_cpu())} "
                        "- max matched sources run in parallel"
                    ),
                    value=ALL_METHOD_MAX_PARALLEL_SOURCES_SETTING_KEY,
                ),
                questionary.Choice(
                    (
                        "All-Method Scheduler Scope: "
                        f"{_normalize_all_method_scheduler_scope(current_settings.get(ALL_METHOD_SCHEDULER_SCOPE_SETTING_KEY))} "
                        "- global mega queue or per-source schedulers"
                    ),
                    value=ALL_METHOD_SCHEDULER_SCOPE_SETTING_KEY,
                ),
                questionary.Choice(
                    (
                        "All-Method Source Scheduling: "
                        f"{_normalize_all_method_source_scheduling(current_settings.get(ALL_METHOD_SOURCE_SCHEDULING_SETTING_KEY))} "
                        "- discovery or tail_pair (heavy/light interleave)"
                    ),
                    value=ALL_METHOD_SOURCE_SCHEDULING_SETTING_KEY,
                ),
                questionary.Choice(
                    (
                        "All-Method Source Shard Threshold (s): "
                        f"{_resolve_positive_float_setting(current_settings, key=ALL_METHOD_SOURCE_SHARD_THRESHOLD_SECONDS_SETTING_KEY, fallback=ALL_METHOD_SOURCE_SHARD_THRESHOLD_SECONDS_DEFAULT):.1f} "
                        "- shard only when source estimate reaches this runtime"
                    ),
                    value=ALL_METHOD_SOURCE_SHARD_THRESHOLD_SECONDS_SETTING_KEY,
                ),
                questionary.Choice(
                    (
                        "All-Method Source Shard Max Parts: "
                        f"{_resolve_positive_int_setting(current_settings, key=ALL_METHOD_SOURCE_SHARD_MAX_PARTS_SETTING_KEY, fallback=ALL_METHOD_SOURCE_SHARD_MAX_PARTS_DEFAULT)} "
                        "- max workload shards per source"
                    ),
                    value=ALL_METHOD_SOURCE_SHARD_MAX_PARTS_SETTING_KEY,
                ),
                questionary.Choice(
                    (
                        "All-Method Source Shard Min Variants: "
                        f"{_resolve_positive_int_setting(current_settings, key=ALL_METHOD_SOURCE_SHARD_MIN_VARIANTS_SETTING_KEY, fallback=ALL_METHOD_SOURCE_SHARD_MIN_VARIANTS_DEFAULT)} "
                        "- minimum variants required before sharding"
                    ),
                    value=ALL_METHOD_SOURCE_SHARD_MIN_VARIANTS_SETTING_KEY,
                ),
                questionary.Choice(
                    (
                        "All-Method Inflight Pipelines: "
                        f"{_resolve_positive_int_setting(current_settings, key=ALL_METHOD_MAX_INFLIGHT_SETTING_KEY, fallback=ALL_METHOD_MAX_INFLIGHT_DEFAULT)} "
                        "- max all-method configs run in parallel"
                    ),
                    value=ALL_METHOD_MAX_INFLIGHT_SETTING_KEY,
                ),
                questionary.Choice(
                    (
                        "All-Method Split Slots: "
                        f"{_resolve_positive_int_setting(current_settings, key=ALL_METHOD_MAX_SPLIT_SLOTS_SETTING_KEY, fallback=ALL_METHOD_MAX_SPLIT_PHASE_SLOTS_DEFAULT)} "
                        "- max split-heavy all-method configs"
                    ),
                    value=ALL_METHOD_MAX_SPLIT_SLOTS_SETTING_KEY,
                ),
                questionary.Choice(
                    (
                        "All-Method Eval Tail Cap: "
                        f"{_resolve_positive_int_setting(current_settings, key=ALL_METHOD_MAX_EVAL_TAIL_SETTING_KEY, fallback=_resolve_positive_int_setting(current_settings, key=ALL_METHOD_MAX_SPLIT_SLOTS_SETTING_KEY, fallback=ALL_METHOD_MAX_SPLIT_PHASE_SLOTS_DEFAULT))} "
                        "- smart-mode extra pipelines when configs are in evaluate phase"
                    ),
                    value=ALL_METHOD_MAX_EVAL_TAIL_SETTING_KEY,
                ),
                questionary.Choice(
                    (
                        "All-Method Config Timeout (s): "
                        f"{_resolve_non_negative_int_setting(current_settings, key=ALL_METHOD_CONFIG_TIMEOUT_SETTING_KEY, fallback=ALL_METHOD_CONFIG_TIMEOUT_SECONDS_DEFAULT)} "
                        "- 0 disables timeout for a single config run"
                    ),
                    value=ALL_METHOD_CONFIG_TIMEOUT_SETTING_KEY,
                ),
                questionary.Choice(
                    (
                        "All-Method Failed Retries: "
                        f"{_resolve_non_negative_int_setting(current_settings, key=ALL_METHOD_RETRY_FAILED_CONFIGS_SETTING_KEY, fallback=ALL_METHOD_RETRY_FAILED_CONFIGS_DEFAULT)} "
                        "- retry only failed configs after first pass"
                    ),
                    value=ALL_METHOD_RETRY_FAILED_CONFIGS_SETTING_KEY,
                ),
                questionary.Choice(
                    (
                        "All-Method Wing Backlog: "
                        f"{_resolve_positive_int_setting(current_settings, key=ALL_METHOD_WING_BACKLOG_SETTING_KEY, fallback=_resolve_positive_int_setting(current_settings, key=ALL_METHOD_MAX_SPLIT_SLOTS_SETTING_KEY, fallback=ALL_METHOD_MAX_SPLIT_PHASE_SLOTS_DEFAULT))} "
                        "- smart scheduler runway before split-heavy slots"
                    ),
                    value=ALL_METHOD_WING_BACKLOG_SETTING_KEY,
                ),
                questionary.Choice(
                    (
                        "All-Method Smart Scheduler: "
                        f"{'On' if _coerce_bool_setting(current_settings.get(ALL_METHOD_SMART_SCHEDULER_SETTING_KEY), default=True) else 'Off'} "
                        "- phase-aware queue admission"
                    ),
                    value=ALL_METHOD_SMART_SCHEDULER_SETTING_KEY,
                ),
                questionary.Choice(
                    (
                        f"EPUB Extractor: {current_epub_extractor} - "
                        f"{enabled_epub_extractors_display}"
                    ),
                    value="epub_extractor",
                ),
                questionary.Choice(
                    (
                        "Unstructured HTML Parser: "
                        f"{current_settings.get('epub_unstructured_html_parser_version', 'v1')} - v1/v2"
                    ),
                    value="epub_unstructured_html_parser_version",
                ),
                questionary.Choice(
                    (
                        "Unstructured Skip Headers/Footers: "
                        f"{'Yes' if current_settings.get('epub_unstructured_skip_headers_footers', True) else 'No'}"
                    ),
                    value="epub_unstructured_skip_headers_footers",
                ),
                questionary.Choice(
                    (
                        "Unstructured EPUB Preprocess: "
                        f"{current_settings.get('epub_unstructured_preprocess_mode', 'br_split_v1')} - none/br_split_v1"
                    ),
                    value="epub_unstructured_preprocess_mode",
                ),
                questionary.Choice(
                    (
                        f"PDF OCR Policy: {current_pdf_ocr_policy} - "
                        "off/auto/always"
                    ),
                    value="pdf_ocr_policy",
                ),
                questionary.Choice(
                    (
                        "Web Schema Extractor: "
                        f"{current_web_schema_extractor}"
                    ),
                    value="web_schema_extractor",
                ),
                questionary.Choice(
                    (
                        "Web Schema Normalizer: "
                        f"{current_web_schema_normalizer}"
                    ),
                    value="web_schema_normalizer",
                ),
                questionary.Choice(
                    (
                        "Web HTML Text Extractor: "
                        f"{current_web_html_text_extractor}"
                    ),
                    value="web_html_text_extractor",
                ),
                questionary.Choice(
                    (
                        "Web Schema Policy: "
                        f"{current_web_schema_policy}"
                    ),
                    value="web_schema_policy",
                ),
                questionary.Choice(
                    (
                        "Web Schema Min Confidence: "
                        f"{float(current_settings.get('web_schema_min_confidence', 0.75)):.2f}"
                    ),
                    value="web_schema_min_confidence",
                ),
                questionary.Choice(
                    (
                        "Web Schema Min Ingredients: "
                        f"{current_settings.get('web_schema_min_ingredients', 2)}"
                    ),
                    value="web_schema_min_ingredients",
                ),
                questionary.Choice(
                    (
                        "Web Schema Min Instruction Steps: "
                        f"{current_settings.get('web_schema_min_instruction_steps', 1)}"
                    ),
                    value="web_schema_min_instruction_steps",
                ),
                questionary.Choice(
                    (
                        "Recipe Pipeline Default: "
                        f"{current_recipe_pipeline}"
                    ),
                    value="llm_recipe_pipeline",
                ),
                questionary.Choice(
                    (
                        "Knowledge Pipeline Default: "
                        f"{current_knowledge_pipeline}"
                    ),
                    value="llm_knowledge_pipeline",
                ),
                questionary.Choice(
                    f"Codex Farm Command: {current_codex_cmd}",
                    value="codex_farm_cmd",
                ),
                questionary.Choice(
                    f"Codex Farm Root: {current_codex_root}",
                    value="codex_farm_root",
                ),
                questionary.Choice(
                    f"Codex Farm Workspace Root: {current_codex_workspace_root}",
                    value="codex_farm_workspace_root",
                ),
                questionary.Choice(
                    f"Codex Farm Model Default: {current_codex_model}",
                    value="codex_farm_model",
                ),
                questionary.Choice(
                    (
                        "Codex Farm Reasoning Default: "
                        f"{current_codex_reasoning_effort}"
                    ),
                    value="codex_farm_reasoning_effort",
                ),
                questionary.Choice(
                    (
                        "Codex Farm Context Blocks: "
                        f"{current_settings.get('codex_farm_context_blocks', 30)}"
                    ),
                    value="codex_farm_context_blocks",
                ),
                questionary.Choice(
                    (
                        "Codex Farm Knowledge Context Blocks: "
                        f"{current_settings.get('codex_farm_knowledge_context_blocks', 0)}"
                    ),
                    value="codex_farm_knowledge_context_blocks",
                ),
                questionary.Choice(
                    f"Output Folder: {current_settings.get('output_dir', str(DEFAULT_INTERACTIVE_OUTPUT))} - stage artifacts",
                    value="output_dir",
                ),
                questionary.Choice(
                    f"PDF Pages/Job: {current_settings.get('pdf_pages_per_job', 50)} - split size per PDF task",
                    value="pdf_pages_per_job",
                ),
                questionary.Choice(
                    f"EPUB Spine Items/Job: {current_settings.get('epub_spine_items_per_job', 10)} - split size per EPUB task",
                    value="epub_spine_items_per_job",
                ),
                questionary.Choice(
                    f"Warm Models: {'Yes' if current_settings.get('warm_models', False) else 'No'} - preload heavy models",
                    value="warm_models",
                ),
                questionary.Choice(
                    f"Label Studio URL: {current_label_studio_url}",
                    value="label_studio_url",
                ),
                questionary.Choice(
                    f"Label Studio API Key: {current_label_studio_api_key_status}",
                    value="label_studio_api_key",
                ),
                questionary.Separator(),
                questionary.Choice("Back to Main Menu - return without changing anything", value="back"),
            ]
        )
        
        if choice in {"back", BACK_ACTION} or choice is None:
            break
            
        if choice == "workers":
            val = _prompt_text(
                "Enter number of workers:",
                default=str(current_settings.get("workers", 7)),
            )
            if val and val.isdigit() and int(val) > 0:
                current_settings["workers"] = int(val)
                _save_settings(current_settings)

        elif choice == "pdf_split_workers":
            val = _prompt_text(
                "Enter PDF split workers:",
                default=str(current_settings.get("pdf_split_workers", 7)),
            )
            if val and val.isdigit() and int(val) > 0:
                current_settings["pdf_split_workers"] = int(val)
                _save_settings(current_settings)

        elif choice == "epub_split_workers":
            val = _prompt_text(
                "Enter EPUB split workers:",
                default=str(current_settings.get("epub_split_workers", 7)),
            )
            if val and val.isdigit() and int(val) > 0:
                current_settings["epub_split_workers"] = int(val)
                _save_settings(current_settings)

        elif choice == ALL_METHOD_MAX_PARALLEL_SOURCES_SETTING_KEY:
            val = _prompt_text(
                "Enter all-method max parallel sources:",
                default=str(
                    _resolve_positive_int_setting(
                        current_settings,
                        key=ALL_METHOD_MAX_PARALLEL_SOURCES_SETTING_KEY,
                        fallback=_all_method_default_parallel_sources_from_cpu(),
                    )
                ),
            )
            parsed = _coerce_positive_int(val)
            if parsed is not None:
                current_settings[ALL_METHOD_MAX_PARALLEL_SOURCES_SETTING_KEY] = parsed
                _save_settings(current_settings)

        elif choice == ALL_METHOD_SCHEDULER_SCOPE_SETTING_KEY:
            current_scope = _normalize_all_method_scheduler_scope(
                current_settings.get(ALL_METHOD_SCHEDULER_SCOPE_SETTING_KEY)
            )
            val = _menu_select(
                "Select all-method scheduler scope:",
                choices=[
                    questionary.Choice(
                        "global - one global config queue across all matched sources",
                        value=ALL_METHOD_SCHEDULER_SCOPE_GLOBAL,
                    ),
                ],
                default=current_scope,
                menu_help=(
                    "global shares split slots and eval-signature dedupe across the full "
                    "all-matched run."
                ),
            )
            if val and val != BACK_ACTION:
                current_settings[ALL_METHOD_SCHEDULER_SCOPE_SETTING_KEY] = (
                    _normalize_all_method_scheduler_scope(val)
                )
                _save_settings(current_settings)

        elif choice == ALL_METHOD_SOURCE_SCHEDULING_SETTING_KEY:
            current_strategy = _normalize_all_method_source_scheduling(
                current_settings.get(ALL_METHOD_SOURCE_SCHEDULING_SETTING_KEY)
            )
            val = _menu_select(
                "Select all-method source scheduling strategy:",
                choices=[
                    questionary.Choice(
                        "tail_pair - interleave heavy/light planned jobs",
                        value=ALL_METHOD_SOURCE_SCHEDULING_TAIL_PAIR,
                    ),
                    questionary.Choice(
                        "discovery - source discovery order",
                        value=ALL_METHOD_SOURCE_SCHEDULING_DISCOVERY,
                    ),
                ],
                default=current_strategy,
                menu_help=(
                    "tail_pair starts heavy jobs earlier and alternates with lighter jobs "
                    "to reduce one-source endgame tails."
                ),
            )
            if val and val != BACK_ACTION:
                current_settings[ALL_METHOD_SOURCE_SCHEDULING_SETTING_KEY] = (
                    _normalize_all_method_source_scheduling(val)
                )
                _save_settings(current_settings)

        elif choice == ALL_METHOD_SOURCE_SHARD_THRESHOLD_SECONDS_SETTING_KEY:
            val = _prompt_text(
                "Enter source-sharding threshold in estimated seconds:",
                default=(
                    f"{_resolve_positive_float_setting(current_settings, key=ALL_METHOD_SOURCE_SHARD_THRESHOLD_SECONDS_SETTING_KEY, fallback=ALL_METHOD_SOURCE_SHARD_THRESHOLD_SECONDS_DEFAULT):.1f}"
                ),
            )
            parsed = _coerce_positive_float(val)
            if parsed is not None:
                current_settings[ALL_METHOD_SOURCE_SHARD_THRESHOLD_SECONDS_SETTING_KEY] = parsed
                _save_settings(current_settings)

        elif choice == ALL_METHOD_SOURCE_SHARD_MAX_PARTS_SETTING_KEY:
            val = _prompt_text(
                "Enter maximum shard parts per source:",
                default=str(
                    _resolve_positive_int_setting(
                        current_settings,
                        key=ALL_METHOD_SOURCE_SHARD_MAX_PARTS_SETTING_KEY,
                        fallback=ALL_METHOD_SOURCE_SHARD_MAX_PARTS_DEFAULT,
                    )
                ),
            )
            parsed = _coerce_positive_int(val)
            if parsed is not None:
                current_settings[ALL_METHOD_SOURCE_SHARD_MAX_PARTS_SETTING_KEY] = parsed
                _save_settings(current_settings)

        elif choice == ALL_METHOD_SOURCE_SHARD_MIN_VARIANTS_SETTING_KEY:
            val = _prompt_text(
                "Enter minimum variants required to allow source sharding:",
                default=str(
                    _resolve_positive_int_setting(
                        current_settings,
                        key=ALL_METHOD_SOURCE_SHARD_MIN_VARIANTS_SETTING_KEY,
                        fallback=ALL_METHOD_SOURCE_SHARD_MIN_VARIANTS_DEFAULT,
                    )
                ),
            )
            parsed = _coerce_positive_int(val)
            if parsed is not None:
                current_settings[ALL_METHOD_SOURCE_SHARD_MIN_VARIANTS_SETTING_KEY] = parsed
                _save_settings(current_settings)

        elif choice == ALL_METHOD_MAX_INFLIGHT_SETTING_KEY:
            val = _prompt_text(
                "Enter all-method max inflight pipelines:",
                default=str(
                    _resolve_positive_int_setting(
                        current_settings,
                        key=ALL_METHOD_MAX_INFLIGHT_SETTING_KEY,
                        fallback=ALL_METHOD_MAX_INFLIGHT_DEFAULT,
                    )
                ),
            )
            parsed = _coerce_positive_int(val)
            if parsed is not None:
                current_settings[ALL_METHOD_MAX_INFLIGHT_SETTING_KEY] = parsed
                _save_settings(current_settings)

        elif choice == ALL_METHOD_MAX_SPLIT_SLOTS_SETTING_KEY:
            val = _prompt_text(
                "Enter all-method max split-phase slots:",
                default=str(
                    _resolve_positive_int_setting(
                        current_settings,
                        key=ALL_METHOD_MAX_SPLIT_SLOTS_SETTING_KEY,
                        fallback=ALL_METHOD_MAX_SPLIT_PHASE_SLOTS_DEFAULT,
                    )
                ),
            )
            parsed = _coerce_positive_int(val)
            if parsed is not None:
                current_settings[ALL_METHOD_MAX_SPLIT_SLOTS_SETTING_KEY] = parsed
                _save_settings(current_settings)

        elif choice == ALL_METHOD_MAX_EVAL_TAIL_SETTING_KEY:
            val = _prompt_text(
                "Enter all-method max eval-tail pipelines (smart mode):",
                default=str(
                    _resolve_positive_int_setting(
                        current_settings,
                        key=ALL_METHOD_MAX_EVAL_TAIL_SETTING_KEY,
                        fallback=_resolve_positive_int_setting(
                            current_settings,
                            key=ALL_METHOD_MAX_SPLIT_SLOTS_SETTING_KEY,
                            fallback=ALL_METHOD_MAX_SPLIT_PHASE_SLOTS_DEFAULT,
                        ),
                    )
                ),
            )
            parsed = _coerce_positive_int(val)
            if parsed is not None:
                current_settings[ALL_METHOD_MAX_EVAL_TAIL_SETTING_KEY] = parsed
                _save_settings(current_settings)

        elif choice == ALL_METHOD_CONFIG_TIMEOUT_SETTING_KEY:
            val = _prompt_text(
                "Enter all-method per-config timeout seconds (0 disables timeout):",
                default=str(
                    _resolve_non_negative_int_setting(
                        current_settings,
                        key=ALL_METHOD_CONFIG_TIMEOUT_SETTING_KEY,
                        fallback=ALL_METHOD_CONFIG_TIMEOUT_SECONDS_DEFAULT,
                    )
                ),
            )
            parsed = _coerce_non_negative_int(val)
            if parsed is not None:
                current_settings[ALL_METHOD_CONFIG_TIMEOUT_SETTING_KEY] = parsed
                _save_settings(current_settings)

        elif choice == ALL_METHOD_RETRY_FAILED_CONFIGS_SETTING_KEY:
            val = _prompt_text(
                "Enter all-method failed-config retry count (0 disables retries):",
                default=str(
                    _resolve_non_negative_int_setting(
                        current_settings,
                        key=ALL_METHOD_RETRY_FAILED_CONFIGS_SETTING_KEY,
                        fallback=ALL_METHOD_RETRY_FAILED_CONFIGS_DEFAULT,
                    )
                ),
            )
            parsed = _coerce_non_negative_int(val)
            if parsed is not None:
                current_settings[ALL_METHOD_RETRY_FAILED_CONFIGS_SETTING_KEY] = parsed
                _save_settings(current_settings)

        elif choice == ALL_METHOD_WING_BACKLOG_SETTING_KEY:
            val = _prompt_text(
                "Enter all-method wing backlog target:",
                default=str(
                    _resolve_positive_int_setting(
                        current_settings,
                        key=ALL_METHOD_WING_BACKLOG_SETTING_KEY,
                        fallback=_resolve_positive_int_setting(
                            current_settings,
                            key=ALL_METHOD_MAX_SPLIT_SLOTS_SETTING_KEY,
                            fallback=ALL_METHOD_MAX_SPLIT_PHASE_SLOTS_DEFAULT,
                        ),
                    )
                ),
            )
            parsed = _coerce_positive_int(val)
            if parsed is not None:
                current_settings[ALL_METHOD_WING_BACKLOG_SETTING_KEY] = parsed
                _save_settings(current_settings)

        elif choice == ALL_METHOD_SMART_SCHEDULER_SETTING_KEY:
            current_value = _coerce_bool_setting(
                current_settings.get(ALL_METHOD_SMART_SCHEDULER_SETTING_KEY),
                default=True,
            )
            val = _prompt_confirm(
                "Enable smart phase-aware all-method scheduler?",
                default=current_value,
            )
            if val is not None:
                current_settings[ALL_METHOD_SMART_SCHEDULER_SETTING_KEY] = bool(val)
                _save_settings(current_settings)

        elif choice == "epub_extractor":
            val = _menu_select(
                "Select EPUB extraction engine:",
                choices=list(enabled_epub_extractors),
                default=current_epub_extractor,
                menu_help=(
                    "Unstructured uses semantic HTML partitioning for richer block extraction. "
                    "BeautifulSoup uses tag-based parsing. "
                    f"Markdown extractors are policy-locked off unless {EPUB_EXTRACTOR_ENABLE_MARKDOWN_ENV}=1."
                ),
            )
            if val and val != BACK_ACTION:
                current_settings["epub_extractor"] = val
                _save_settings(current_settings)

        elif choice == "epub_unstructured_html_parser_version":
            val = _menu_select(
                "Select Unstructured HTML parser version:",
                choices=["v1", "v2"],
                default=current_settings.get(
                    "epub_unstructured_html_parser_version",
                    "v1",
                ),
                menu_help=(
                    "Choose Unstructured partition_html parser version for EPUB extraction."
                ),
            )
            if val and val != BACK_ACTION:
                current_settings["epub_unstructured_html_parser_version"] = val
                _save_settings(current_settings)

        elif choice == "epub_unstructured_skip_headers_footers":
            val = _prompt_confirm(
                "Skip headers/footers in Unstructured HTML partitioning?",
                default=bool(
                    current_settings.get(
                        "epub_unstructured_skip_headers_footers",
                        True,
                    )
                ),
            )
            if val is not None:
                current_settings["epub_unstructured_skip_headers_footers"] = bool(val)
                _save_settings(current_settings)

        elif choice == "epub_unstructured_preprocess_mode":
            val = _menu_select(
                "Select EPUB HTML preprocess mode before Unstructured:",
                choices=["none", "br_split_v1"],
                default=current_settings.get(
                    "epub_unstructured_preprocess_mode",
                    "br_split_v1",
                ),
                menu_help=(
                    "none keeps raw HTML; br_split_v1 splits BR-separated paragraphs "
                    "into block tags."
                ),
            )
            if val and val != BACK_ACTION:
                current_settings["epub_unstructured_preprocess_mode"] = val
                _save_settings(current_settings)

        elif choice == "pdf_ocr_policy":
            val = _menu_select(
                "Select PDF OCR policy:",
                choices=[
                    questionary.Choice("off - never run OCR", value="off"),
                    questionary.Choice(
                        "auto - OCR only when text extraction needs it",
                        value="auto",
                    ),
                    questionary.Choice("always - force OCR for PDFs", value="always"),
                ],
                default=current_pdf_ocr_policy,
                menu_help=(
                    "Choose how PDF imports decide between native text extraction "
                    "and OCR."
                ),
            )
            if val and val != BACK_ACTION:
                current_settings["pdf_ocr_policy"] = _normalize_pdf_ocr_policy(str(val))
                _save_settings(current_settings)

        elif choice == "web_schema_extractor":
            val = _menu_select(
                "Select web schema extractor:",
                choices=[
                    "builtin_jsonld",
                    "extruct",
                    "scrape_schema_recipe",
                    "recipe_scrapers",
                    "ensemble_v1",
                ],
                default=current_web_schema_extractor,
                menu_help="Choose the structured-data extractor for webschema imports.",
            )
            if val and val != BACK_ACTION:
                current_settings["web_schema_extractor"] = _normalize_web_schema_extractor(
                    str(val)
                )
                _save_settings(current_settings)

        elif choice == "web_schema_normalizer":
            val = _menu_select(
                "Select web schema normalizer:",
                choices=["simple", "pyld"],
                default=current_web_schema_normalizer,
                menu_help="Choose schema normalization before mapping.",
            )
            if val and val != BACK_ACTION:
                current_settings["web_schema_normalizer"] = (
                    _normalize_web_schema_normalizer(str(val))
                )
                _save_settings(current_settings)

        elif choice == "web_html_text_extractor":
            val = _menu_select(
                "Select web HTML text extractor:",
                choices=[
                    "bs4",
                    "trafilatura",
                    "readability_lxml",
                    "justext",
                    "boilerpy3",
                    "ensemble_v1",
                ],
                default=current_web_html_text_extractor,
                menu_help="Choose the fallback text extractor when schema data is missing.",
            )
            if val and val != BACK_ACTION:
                current_settings["web_html_text_extractor"] = (
                    _normalize_web_html_text_extractor(str(val))
                )
                _save_settings(current_settings)

        elif choice == "web_schema_policy":
            val = _menu_select(
                "Select web schema policy:",
                choices=list(ALL_METHOD_WEBSCHEMA_POLICIES),
                default=current_web_schema_policy,
                menu_help=(
                    "prefer_schema uses schema first, schema_only disables heuristic "
                    "fallback, heuristic_only skips schema data."
                ),
            )
            if val and val != BACK_ACTION:
                current_settings["web_schema_policy"] = _normalize_web_schema_policy(
                    str(val)
                )
                _save_settings(current_settings)

        elif choice == "web_schema_min_confidence":
            val = _prompt_text(
                "Enter web schema minimum confidence (0.0 to 1.0):",
                default=str(current_settings.get("web_schema_min_confidence", 0.75)),
            )
            parsed = _coerce_float_between(val, minimum=0.0, maximum=1.0)
            if parsed is not None:
                current_settings["web_schema_min_confidence"] = parsed
                _save_settings(current_settings)

        elif choice == "web_schema_min_ingredients":
            val = _prompt_text(
                "Enter minimum ingredient lines for web schema acceptance:",
                default=str(current_settings.get("web_schema_min_ingredients", 2)),
            )
            parsed = _coerce_positive_int(val)
            if parsed is not None:
                current_settings["web_schema_min_ingredients"] = parsed
                _save_settings(current_settings)

        elif choice == "web_schema_min_instruction_steps":
            val = _prompt_text(
                "Enter minimum instruction steps for web schema acceptance:",
                default=str(current_settings.get("web_schema_min_instruction_steps", 1)),
            )
            parsed = _coerce_positive_int(val)
            if parsed is not None:
                current_settings["web_schema_min_instruction_steps"] = parsed
                _save_settings(current_settings)

        elif choice == "llm_recipe_pipeline":
            val = _menu_select(
                "Select default recipe pipeline for interactive runs:",
                choices=[
                    questionary.Choice(
                        "off - default to deterministic/vanilla top-tier",
                        value="off",
                    ),
                    questionary.Choice(
                        f"{RECIPE_CODEX_FARM_PIPELINE_SHARD_V1} - default to CodexFarm top-tier",
                        value=RECIPE_CODEX_FARM_PIPELINE_SHARD_V1,
                    ),
                ],
                default=current_recipe_pipeline,
                menu_help=(
                    "This sets the default choice shown by the per-run interactive "
                    "top-tier picker."
                ),
            )
            if val and val != BACK_ACTION:
                current_settings["llm_recipe_pipeline"] = _normalize_llm_recipe_pipeline(
                    str(val)
                )
                _save_settings(current_settings)

        elif choice == "llm_knowledge_pipeline":
            val = _menu_select(
                "Select default knowledge pipeline for interactive runs:",
                choices=[
                    questionary.Choice("off", value="off"),
                    questionary.Choice(
                        KNOWLEDGE_CODEX_PIPELINE_SHARD_V1,
                        value=KNOWLEDGE_CODEX_PIPELINE_SHARD_V1,
                    ),
                ],
                default=current_knowledge_pipeline,
                menu_help=(
                    "This becomes the default knowledge-harvest choice when the "
                    "interactive benchmark flow asks for per-run Codex surfaces."
                ),
            )
            if val and val != BACK_ACTION:
                current_settings["llm_knowledge_pipeline"] = (
                    _normalize_llm_knowledge_pipeline(str(val))
                )
                _save_settings(current_settings)

        elif choice == "codex_farm_cmd":
            val = _prompt_text(
                "Enter Codex Farm command:",
                default=current_codex_cmd,
            )
            if val is not None:
                current_settings["codex_farm_cmd"] = str(val).strip() or "codex-farm"
                _save_settings(current_settings)

        elif choice == "codex_farm_root":
            val = _prompt_text(
                "Enter Codex Farm root path (blank to use repo default):",
                default=str(current_settings.get("codex_farm_root") or ""),
            )
            if val is not None:
                current_settings["codex_farm_root"] = str(val).strip() or None
                _save_settings(current_settings)

        elif choice == "codex_farm_workspace_root":
            val = _prompt_text(
                "Enter Codex Farm workspace root (blank to use pipeline default):",
                default=str(current_settings.get("codex_farm_workspace_root") or ""),
            )
            if val is not None:
                current_settings["codex_farm_workspace_root"] = str(val).strip() or None
                _save_settings(current_settings)

        elif choice == "codex_farm_model":
            val = _prompt_text(
                "Enter Codex Farm model default (blank for pipeline default):",
                default=str(current_settings.get("codex_farm_model") or ""),
            )
            if val is not None:
                current_settings["codex_farm_model"] = str(val).strip() or None
                _save_settings(current_settings)

        elif choice == "codex_farm_reasoning_effort":
            reasoning_choices, reasoning_default = build_codex_farm_reasoning_effort_choices(
                selected_model=str(current_settings.get("codex_farm_model") or "").strip() or None,
                selected_effort=current_settings.get("codex_farm_reasoning_effort"),
                supported_efforts_by_model={},
                include_minimal=True,
            )
            reasoning_choices = [
                questionary.Choice("Pipeline default", value="__default__"),
                *[
                    choice
                    for choice in reasoning_choices
                    if str(choice.value) != "__default__"
                ],
            ]
            val = _menu_select(
                "Select Codex Farm reasoning default:",
                choices=reasoning_choices,
                default=reasoning_default,
                menu_help=(
                    "Choose the saved default reasoning effort for Codex-backed runs. "
                    "Pipeline default leaves the pack default in control."
                ),
            )
            if val and val != BACK_ACTION:
                current_settings["codex_farm_reasoning_effort"] = (
                    None if str(val) == "__default__" else str(val)
                )
                _save_settings(current_settings)

        elif choice == "codex_farm_context_blocks":
            val = _prompt_text(
                "Enter Codex Farm context blocks:",
                default=str(current_settings.get("codex_farm_context_blocks", 30)),
            )
            parsed = _coerce_positive_int(val)
            if parsed is not None:
                current_settings["codex_farm_context_blocks"] = parsed
                _save_settings(current_settings)

        elif choice == "codex_farm_knowledge_context_blocks":
            val = _prompt_text(
                "Enter Codex Farm knowledge context blocks:",
                default=str(
                    current_settings.get("codex_farm_knowledge_context_blocks", 1)
                ),
            )
            parsed = _coerce_positive_int(val)
            if parsed is not None:
                current_settings["codex_farm_knowledge_context_blocks"] = parsed
                _save_settings(current_settings)

        elif choice == "output_dir":
            val = _prompt_text(
                "Enter output folder for interactive runs:",
                default=str(current_settings.get("output_dir", str(DEFAULT_INTERACTIVE_OUTPUT))),
            )
            if val:
                current_settings["output_dir"] = str(Path(val).expanduser())
                _save_settings(current_settings)

        elif choice == "pdf_pages_per_job":
            val = _prompt_text(
                "Enter PDF pages per job:",
                default=str(current_settings.get("pdf_pages_per_job", 50)),
            )
            if val and val.isdigit() and int(val) > 0:
                current_settings["pdf_pages_per_job"] = int(val)
                _save_settings(current_settings)

        elif choice == "epub_spine_items_per_job":
            val = _prompt_text(
                "Enter EPUB spine items per job:",
                default=str(current_settings.get("epub_spine_items_per_job", 10)),
            )
            if val and val.isdigit() and int(val) > 0:
                current_settings["epub_spine_items_per_job"] = int(val)
                _save_settings(current_settings)

        elif choice == "warm_models":
            val = _prompt_confirm(
                "Warm models on start?",
                default=current_settings.get("warm_models", False),
            )
            if val is not None:
                current_settings["warm_models"] = val
                _save_settings(current_settings)

        elif choice == "label_studio_url":
            val = _prompt_text(
                "Enter Label Studio URL (blank clears saved value):",
                default=str(current_settings.get("label_studio_url") or ""),
            )
            if val is not None:
                current_settings["label_studio_url"] = str(val).strip()
                _save_settings(current_settings)

        elif choice == "label_studio_api_key":
            val = _prompt_password(
                "Enter Label Studio API key (blank keeps current, __clear__ clears):",
                default="",
            )
            if val is not None:
                cleaned = str(val).strip()
                if cleaned == "__clear__":
                    current_settings["label_studio_api_key"] = ""
                    _save_settings(current_settings)
                elif cleaned:
                    current_settings["label_studio_api_key"] = cleaned
                    _save_settings(current_settings)

__all__ = ['_settings_menu']
