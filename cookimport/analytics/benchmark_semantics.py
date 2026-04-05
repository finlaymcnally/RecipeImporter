from __future__ import annotations

from typing import Any

from cookimport.config.codex_decision import classify_codex_surfaces

AI_ASSISTANCE_PROFILE_LABELS: dict[str, str] = {
    "deterministic": "AI off",
    "line_role_only": "Line-role only",
    "recipe_only": "Recipe only",
    "full_stack": "Full-stack AI",
    "other": "Unknown",
}

_VARIANT_KEYS = {
    "vanilla",
    "codex-exec",
    "deterministic",
    "line_role_only",
    "recipe_only",
    "full_stack",
    "other",
}

_CANONICAL_VARIANT_BY_NORMALIZED_KEY = {
    "vanilla": "vanilla",
    "codex_exec": "codex-exec",
    "deterministic": "deterministic",
    "line_role_only": "line_role_only",
    "recipe_only": "recipe_only",
    "full_stack": "full_stack",
    "other": "other",
}


def _normalize_path(path_value: Any) -> str:
    return str(path_value or "").strip().replace("\\", "/").lower()


def _benchmark_path(record: Any) -> str:
    for key in ("artifact_dir", "run_dir", "report_path"):
        path = _normalize_path(_record_value(record, key))
        if path:
            return path
    return ""


def _record_value(record: Any, key: str) -> Any:
    if isinstance(record, dict):
        return record.get(key)
    return getattr(record, key, None)


def _clean_config_value(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    lower = text.lower()
    if lower in {"none", "null", "n/a", "<default>", "default", "(default)"}:
        return None
    return text


def _run_config_summary_map(record: Any) -> dict[str, str]:
    mapping: dict[str, str] = {}
    text = str(_record_value(record, "run_config_summary") or "").strip()
    if not text:
        return mapping
    for chunk in text.split("|"):
        part = str(chunk or "").strip()
        if not part:
            continue
        idx = part.find("=")
        if idx <= 0:
            continue
        key = part[:idx].strip()
        value = part[idx + 1 :].strip()
        if key and value:
            mapping[key] = value
    return mapping


def run_config_value(record: Any, keys: tuple[str, ...]) -> str | None:
    cfg = _record_value(record, "run_config")
    if not isinstance(cfg, dict):
        cfg = {}
    for key in keys:
        if key not in cfg:
            continue
        value = _clean_config_value(cfg.get(key))
        if value is not None:
            return value
    summary_fields = _run_config_summary_map(record)
    for key in keys:
        value = _clean_config_value(summary_fields.get(key))
        if value is not None:
            return value
    return None


def explicit_variant_for_record(record: Any) -> str | None:
    explicit = (
        _clean_config_value(_record_value(record, "benchmark_variant"))
        or run_config_value(record, ("benchmark_variant",))
    )
    if explicit is None:
        return None
    lowered = explicit.lower().replace("-", "_").replace(" ", "_")
    return _CANONICAL_VARIANT_BY_NORMALIZED_KEY.get(lowered)


def ai_assistance_profile_for_record(record: Any) -> str:
    explicit = (
        _clean_config_value(_record_value(record, "ai_assistance_profile"))
        or run_config_value(record, ("ai_assistance_profile",))
    )
    if explicit is not None:
        lowered = explicit.lower().replace("-", "_").replace(" ", "_")
        if lowered in AI_ASSISTANCE_PROFILE_LABELS:
            return lowered

    surface_payload: dict[str, str] = {}
    recipe_pipeline = run_config_value(record, ("llm_recipe_pipeline", "llm_pipeline"))
    line_role_pipeline = run_config_value(record, ("line_role_pipeline",))
    knowledge_pipeline = run_config_value(record, ("llm_knowledge_pipeline",))
    if recipe_pipeline is not None:
        surface_payload["llm_recipe_pipeline"] = recipe_pipeline
    if line_role_pipeline is not None:
        surface_payload["line_role_pipeline"] = line_role_pipeline
    if knowledge_pipeline is not None:
        surface_payload["llm_knowledge_pipeline"] = knowledge_pipeline
    surface = classify_codex_surfaces(surface_payload)
    if surface.ai_assistance_profile != "other":
        return surface.ai_assistance_profile
    if run_config_value(
        record,
        (
            "codex_farm_model",
            "codex_model",
            "provider_model",
            "model",
            "codex_farm_reasoning_effort",
            "codex_farm_thinking_effort",
            "codex_reasoning_effort",
            "model_reasoning_effort",
            "thinking_effort",
            "reasoning_effort",
        ),
    ):
        return "full_stack"
    return "other"


def ai_assistance_profile_label_for_record(record: Any) -> str:
    return AI_ASSISTANCE_PROFILE_LABELS[ai_assistance_profile_for_record(record)]


def is_official_golden_benchmark_record(record: Any) -> bool:
    path = _benchmark_path(record)
    if "/benchmark-vs-golden/" not in path or "/single-book-benchmark/" not in path:
        return False
    variant = benchmark_variant_for_record(record)
    profile = ai_assistance_profile_for_record(record)
    return (variant == "vanilla" and profile == "deterministic") or (
        variant == "codex-exec" and profile == "full_stack"
    )


def is_official_paired_benchmark_record(record: Any) -> bool:
    path = _benchmark_path(record)
    if "/benchmark-vs-golden/" not in path:
        return False
    return "/single-book-benchmark/" in path or "/single-profile-benchmark/" in path


def benchmark_variant_for_record(record: Any) -> str:
    explicit = explicit_variant_for_record(record)
    if explicit is not None:
        return explicit

    return ai_assistance_profile_for_record(record)
