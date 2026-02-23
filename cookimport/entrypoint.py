from __future__ import annotations

import sys

from cookimport.cli import DEFAULT_INPUT, DEFAULT_OUTPUT, _fail, _load_settings, app, stage


def main() -> None:
    args = sys.argv[1:]
    settings = _load_settings()
    common_args = {
        "out": DEFAULT_OUTPUT,
        "mapping": None,
        "overrides": None,
        "workers": settings.get("workers", 7),
        "pdf_split_workers": settings.get("pdf_split_workers", 7),
        "epub_split_workers": settings.get("epub_split_workers", 7),
        "epub_extractor": settings.get("epub_extractor", "unstructured"),
        "epub_unstructured_html_parser_version": settings.get(
            "epub_unstructured_html_parser_version",
            "v1",
        ),
        "epub_unstructured_skip_headers_footers": settings.get(
            "epub_unstructured_skip_headers_footers",
            False,
        ),
        "epub_unstructured_preprocess_mode": settings.get(
            "epub_unstructured_preprocess_mode",
            "br_split_v1",
        ),
        "ocr_device": settings.get("ocr_device", "auto"),
        "ocr_batch_size": settings.get("ocr_batch_size", 1),
        "pdf_pages_per_job": settings.get("pdf_pages_per_job", 50),
        "epub_spine_items_per_job": settings.get("epub_spine_items_per_job", 10),
        "warm_models": settings.get("warm_models", False),
        "llm_recipe_pipeline": settings.get("llm_recipe_pipeline", "off"),
        "llm_knowledge_pipeline": settings.get("llm_knowledge_pipeline", "off"),
        "codex_farm_cmd": settings.get("codex_farm_cmd", "codex-farm"),
        "codex_farm_root": settings.get("codex_farm_root"),
        "codex_farm_workspace_root": settings.get("codex_farm_workspace_root"),
        "codex_farm_pipeline_pass1": settings.get(
            "codex_farm_pipeline_pass1",
            "recipe.chunking.v1",
        ),
        "codex_farm_pipeline_pass2": settings.get(
            "codex_farm_pipeline_pass2",
            "recipe.schemaorg.v1",
        ),
        "codex_farm_pipeline_pass3": settings.get(
            "codex_farm_pipeline_pass3",
            "recipe.final.v1",
        ),
        "codex_farm_pipeline_pass4_knowledge": settings.get(
            "codex_farm_pipeline_pass4_knowledge",
            "recipe.knowledge.v1",
        ),
        "codex_farm_context_blocks": settings.get("codex_farm_context_blocks", 30),
        "codex_farm_knowledge_context_blocks": settings.get(
            "codex_farm_knowledge_context_blocks",
            12,
        ),
        "codex_farm_failure_mode": settings.get("codex_farm_failure_mode", "fail"),
    }
    if not args:
        stage(path=DEFAULT_INPUT, limit=None, **common_args)
        return
    if len(args) == 1:
        try:
            limit = int(args[0])
        except ValueError:
            limit = None
        if limit is not None:
            if limit <= 0:
                _fail("Limit must be a positive integer.")
            stage(path=DEFAULT_INPUT, limit=limit, **common_args)
            return
    app()
