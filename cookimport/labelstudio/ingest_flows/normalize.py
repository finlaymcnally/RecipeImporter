from __future__ import annotations

from cookimport.epub_extractor_names import (
    EPUB_EXTRACTOR_CANONICAL_SET,
    EPUB_EXTRACTOR_ENABLE_MARKDOWN_ENV,
    epub_extractor_choices_for_help,
    is_policy_locked_epub_extractor_name,
    normalize_epub_extractor_name,
)
from cookimport.config.run_settings import (
    RECIPE_CODEX_FARM_ALLOWED_PIPELINES,
    RECIPE_CODEX_FARM_PIPELINE_POLICY_ERROR,
)


def _coerce_bool(value: bool | str | None, *, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    normalized = str(value).strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    return default

def _normalize_unstructured_html_parser_version(value: str) -> str:
    normalized = value.strip().lower()
    if normalized not in {"v1", "v2"}:
        raise ValueError(
            "Invalid epub_unstructured_html_parser_version. "
            "Expected one of: v1, v2."
        )
    return normalized

def _normalize_unstructured_preprocess_mode(value: str) -> str:
    normalized = value.strip().lower()
    if normalized not in {"none", "br_split_v1"}:
        raise ValueError(
            "Invalid epub_unstructured_preprocess_mode. "
            "Expected one of: none, br_split_v1."
        )
    return normalized

def _normalize_epub_extractor(value: str) -> str:
    normalized = normalize_epub_extractor_name(value)
    if normalized not in EPUB_EXTRACTOR_CANONICAL_SET:
        raise ValueError(
            "Invalid epub_extractor. "
            f"Expected one of: {epub_extractor_choices_for_help()}."
        )
    if is_policy_locked_epub_extractor_name(normalized):
        raise ValueError(
            f"epub_extractor {normalized!r} is policy-locked off for now "
            f"(set {EPUB_EXTRACTOR_ENABLE_MARKDOWN_ENV}=1 to temporarily re-enable)."
        )
    return normalized

def _normalize_llm_recipe_pipeline(value: str) -> str:
    normalized = value.strip().lower()
    if normalized in RECIPE_CODEX_FARM_ALLOWED_PIPELINES:
        return normalized
    raise ValueError(
        f"Invalid llm_recipe_pipeline. {RECIPE_CODEX_FARM_PIPELINE_POLICY_ERROR}"
    )

def _normalize_codex_farm_failure_mode(value: str) -> str:
    normalized = value.strip().lower()
    if normalized not in {"fail", "fallback"}:
        raise ValueError(
            "Invalid codex_farm_failure_mode. Expected one of: fail, fallback."
        )
    return normalized

def _normalize_codex_farm_recipe_mode(value: str) -> str:
    normalized = str(value or "").strip().lower().replace("_", "-")
    if normalized in {"", "extract"}:
        return "extract"
    if normalized == "benchmark":
        return "benchmark"
    raise ValueError(
        "Invalid codex_farm_recipe_mode. Expected one of: extract, benchmark."
    )

def _normalize_codex_farm_pipeline_id(value: str, *, field_name: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"Invalid {field_name}. Expected a non-empty pipeline id.")
    return normalized

def _normalize_prelabel_upload_as(value: str) -> str:
    normalized = value.strip().lower()
    if normalized not in {"annotations", "predictions"}:
        raise ValueError(
            "prelabel_upload_as must be one of: annotations, predictions"
        )
    return normalized
