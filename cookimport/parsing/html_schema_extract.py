from __future__ import annotations

import importlib
import json
import re
from typing import Any

from bs4 import BeautifulSoup

from cookimport.parsing.schemaorg_ingest import collect_schemaorg_recipe_objects

_JSONLD_SCRIPT_TYPE_RE = re.compile(r"ld\+json", re.IGNORECASE)
_SUPPORTED_SCHEMA_EXTRACTORS = {
    "builtin_jsonld",
    "extruct",
    "scrape_schema_recipe",
    "recipe_scrapers",
    "ensemble_v1",
}
_SUPPORTED_SCHEMA_NORMALIZERS = {"simple", "pyld"}
_WEBSCHEMA_EXTRA = "webschema"


def extract_schema_recipes_from_html(
    html_text: str,
    *,
    extractor: str = "builtin_jsonld",
    normalizer: str = "simple",
    source_url: str | None = None,
) -> list[dict[str, Any]]:
    """Extract schema recipe objects from HTML."""

    selected_extractor = str(extractor or "builtin_jsonld").strip().lower()
    if selected_extractor not in _SUPPORTED_SCHEMA_EXTRACTORS:
        raise RuntimeError(
            f"Unsupported web schema extractor {extractor!r}. "
            f"Expected one of: {', '.join(sorted(_SUPPORTED_SCHEMA_EXTRACTORS))}."
        )

    selected_normalizer = str(normalizer or "simple").strip().lower()
    if selected_normalizer not in _SUPPORTED_SCHEMA_NORMALIZERS:
        raise RuntimeError(
            f"Unsupported web schema normalizer {normalizer!r}. "
            f"Expected one of: {', '.join(sorted(_SUPPORTED_SCHEMA_NORMALIZERS))}."
        )

    raw_payloads: list[object] = []
    if selected_extractor == "builtin_jsonld":
        raw_payloads.extend(_extract_with_builtin_jsonld(html_text))
    elif selected_extractor == "extruct":
        raw_payloads.extend(_extract_with_extruct(html_text, source_url=source_url))
    elif selected_extractor == "scrape_schema_recipe":
        raw_payloads.extend(_extract_with_scrape_schema_recipe(html_text))
    elif selected_extractor == "recipe_scrapers":
        raw_payloads.extend(_extract_with_recipe_scrapers(html_text, source_url=source_url))
    else:  # ensemble_v1
        raw_payloads.extend(_extract_with_builtin_jsonld(html_text))
        for fn in (
            lambda: _extract_with_extruct(html_text, source_url=source_url),
            lambda: _extract_with_scrape_schema_recipe(html_text),
            lambda: _extract_with_recipe_scrapers(html_text, source_url=source_url),
        ):
            try:
                raw_payloads.extend(fn())
            except RuntimeError:
                continue

    normalized_payloads = [_normalize_schema_payload(payload, selected_normalizer) for payload in raw_payloads]

    recipes: list[dict[str, Any]] = []
    seen: set[str] = set()
    for payload in normalized_payloads:
        for recipe in collect_schemaorg_recipe_objects(payload):
            signature = _signature(recipe)
            if signature in seen:
                continue
            seen.add(signature)
            recipes.append(recipe)
    return recipes


def _extract_with_builtin_jsonld(html_text: str) -> list[object]:
    soup = BeautifulSoup(html_text, "lxml")
    payloads: list[object] = []
    for script in soup.find_all("script"):
        script_type = str(script.get("type") or "")
        if not _JSONLD_SCRIPT_TYPE_RE.search(script_type):
            continue
        raw = script.string or script.get_text()
        if not raw or not str(raw).strip():
            continue
        try:
            payloads.append(json.loads(raw))
        except Exception:
            continue
    return payloads


def _extract_with_extruct(html_text: str, *, source_url: str | None) -> list[object]:
    extruct = _import_optional_dependency(
        "extruct",
        context="web_schema_extractor=extruct",
    )
    # w3lib is an extruct dependency, but import lazily so we can surface clear errors.
    get_base_url = _import_optional_dependency(
        "w3lib.html",
        context="web_schema_extractor=extruct",
    ).get_base_url
    extracted = extruct.extract(
        html_text,
        base_url=get_base_url(html_text, source_url or ""),
        syntaxes=["json-ld"],
        errors="ignore",
    )
    if not isinstance(extracted, dict):
        return []
    json_ld = extracted.get("json-ld")
    if isinstance(json_ld, list):
        return json_ld
    if json_ld is None:
        return []
    return [json_ld]


def _extract_with_scrape_schema_recipe(html_text: str) -> list[object]:
    module = _import_optional_dependency(
        "scrape_schema_recipe",
        context="web_schema_extractor=scrape_schema_recipe",
    )
    for function_name in ("scrape_html", "extract_recipe_json", "extract", "scrape"):
        fn = getattr(module, function_name, None)
        if not callable(fn):
            continue
        try:
            value = fn(html_text)
        except TypeError:
            continue
        payloads = _coerce_payload_list(value)
        if payloads:
            return payloads
    raise RuntimeError(
        "scrape-schema-recipe is installed, but no supported extraction function was found. "
        "Install/upgrade dependencies with: pip install -e '.[webschema]'."
    )


def _extract_with_recipe_scrapers(html_text: str, *, source_url: str | None) -> list[object]:
    module = _import_optional_dependency(
        "recipe_scrapers",
        context="web_schema_extractor=recipe_scrapers",
    )
    scrape_html = getattr(module, "scrape_html", None)
    if not callable(scrape_html):
        raise RuntimeError(
            "recipe-scrapers is installed, but scrape_html(...) is unavailable. "
            "Install/upgrade dependencies with: pip install -e '.[webschema]'."
        )

    kwargs: dict[str, Any] = {"html": html_text}
    if source_url:
        kwargs["org_url"] = source_url
    scraper = scrape_html(**kwargs)

    payload: dict[str, Any] = {"@type": "Recipe"}
    title = _safe_call(scraper, "title")
    if isinstance(title, str) and title.strip():
        payload["name"] = title.strip()

    ingredients = _safe_call(scraper, "ingredients")
    if isinstance(ingredients, list):
        payload["recipeIngredient"] = [str(item).strip() for item in ingredients if str(item).strip()]

    instruction_list = _safe_call(scraper, "instructions_list")
    if isinstance(instruction_list, list):
        payload["recipeInstructions"] = [
            str(item).strip() for item in instruction_list if str(item).strip()
        ]
    else:
        instructions_text = _safe_call(scraper, "instructions")
        if isinstance(instructions_text, str) and instructions_text.strip():
            payload["recipeInstructions"] = [
                line.strip()
                for line in instructions_text.splitlines()
                if line.strip()
            ]

    yields_text = _safe_call(scraper, "yields")
    if isinstance(yields_text, str) and yields_text.strip():
        payload["recipeYield"] = yields_text.strip()
    if source_url:
        payload["url"] = source_url

    if not payload.get("name") and not payload.get("recipeIngredient"):
        return []
    return [payload]


def _normalize_schema_payload(payload: object, normalizer: str) -> object:
    if normalizer != "pyld":
        return payload

    jsonld = _import_optional_dependency(
        "pyld.jsonld",
        context="web_schema_normalizer=pyld",
    )
    try:
        return jsonld.compact(payload, "https://schema.org")
    except Exception:
        return payload


def _import_optional_dependency(module_name: str, *, context: str):
    try:
        return importlib.import_module(module_name)
    except Exception as exc:  # noqa: BLE001
        package_hint = module_name.split(".", 1)[0]
        raise RuntimeError(
            f"Selected {context} requires optional dependency '{package_hint}'. "
            f"Install with: pip install -e '.[{_WEBSCHEMA_EXTRA}]'."
        ) from exc


def _coerce_payload_list(value: object) -> list[object]:
    if value is None:
        return []
    if isinstance(value, list):
        return list(value)
    if isinstance(value, dict):
        return [value]
    maybe_dict = getattr(value, "dict", None)
    if callable(maybe_dict):
        try:
            converted = maybe_dict()
        except Exception:
            return []
        if isinstance(converted, dict):
            return [converted]
        if isinstance(converted, list):
            return list(converted)
    return []


def _safe_call(obj: object, method_name: str) -> object:
    method = getattr(obj, method_name, None)
    if not callable(method):
        return None
    try:
        return method()
    except Exception:
        return None


def _signature(payload: dict[str, Any]) -> str:
    try:
        return json.dumps(payload, sort_keys=True, ensure_ascii=True, separators=(",", ":"))
    except TypeError:
        return str(id(payload))

