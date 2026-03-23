from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable

from bs4 import BeautifulSoup

from cookimport.core.models import (
    ConversionReport,
    ConversionResult,
    MappingConfig,
    RawArtifact,
    RecipeCandidate,
    SheetInspection,
    SourceSupport,
    WorkbookInspection,
)
from cookimport.core.reporting import compute_file_hash, generate_recipe_id
from cookimport.core.source_model import normalize_source_blocks
from cookimport.parsing import cleaning, signals
from cookimport.parsing.html_schema_extract import extract_schema_recipes_from_html
from cookimport.parsing.html_text_extract import extract_main_text_from_html
from cookimport.parsing.schemaorg_ingest import (
    collect_schemaorg_recipe_objects,
    schema_recipe_confidence,
    schema_recipe_to_candidate,
)
from cookimport.parsing.text_section_extract import extract_sections_from_text_blob
from cookimport.plugins import registry

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from cookimport.config.run_settings import RunSettings

_HTML_EXTENSIONS = {".html", ".htm"}
_JSON_EXTENSIONS = {".json", ".jsonld"}
_SCHEMA_POLICY_CHOICES = {"prefer_schema", "schema_only", "heuristic_only"}
_INSTRUCTION_LEAD_RE = re.compile(
    r"^\s*(preheat|heat|bring|make|mix|stir|whisk|cook|bake|roast|fry|grill|"
    r"season|serve|add|melt|place|put|pour|combine|fold|remove|drain|peel|chop|"
    r"slice|cut|toss|cool|refrigerate|strain|beat|whip|simmer|boil|reduce|cover)\b",
    re.IGNORECASE,
)


def _schema_source_support(schema_objects: list[dict[str, Any]]) -> list[SourceSupport]:
    support: list[SourceSupport] = []
    for index, schema_obj in enumerate(schema_objects):
        support.append(
            SourceSupport(
                hintClass="evidence",
                kind="structured_recipe_object",
                referencedBlockIds=[],
                payload={
                    "schema_index": index,
                    "type": schema_obj.get("@type"),
                    "name": schema_obj.get("name"),
                },
                provenance={"importer": "webschema", "source": "schema_org"},
            )
        )
    return support


def _source_blocks_from_text(
    text: str,
    *,
    source_kind: str,
    location_key: str,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line_index, line in enumerate(text.splitlines()):
        normalized = cleaning.normalize_text(str(line or ""))
        if not normalized:
            continue
        rows.append(
            {
                "block_id": f"b{len(rows)}",
                "order_index": len(rows),
                "text": normalized,
                "source_text": str(line),
                "location": {location_key: line_index},
                "features": {"source_kind": source_kind},
            }
        )
    return rows


def _schema_recipe_text(schema_obj: dict[str, Any], *, fallback_name: str) -> str:
    name = str(schema_obj.get("name") or fallback_name).strip()
    parts = [name]
    description = str(schema_obj.get("description") or "").strip()
    if description:
        parts.append(description)
    ingredients = schema_obj.get("recipeIngredient") or []
    if isinstance(ingredients, str):
        ingredients = [ingredients]
    if ingredients:
        parts.append("Ingredients:")
        parts.extend(f"- {item}" for item in ingredients if str(item).strip())
    instructions = schema_obj.get("recipeInstructions") or []
    if isinstance(instructions, str):
        instructions = [instructions]
    if instructions:
        parts.append("Instructions:")
        for index, item in enumerate(instructions, start=1):
            if isinstance(item, dict):
                text = str(item.get("text") or "").strip()
            else:
                text = str(item).strip()
            if text:
                parts.append(f"{index}. {text}")
    recipe_yield = str(schema_obj.get("recipeYield") or "").strip()
    if recipe_yield:
        parts.append(f"Yield: {recipe_yield}")
    source_url = str(schema_obj.get("url") or schema_obj.get("@id") or "").strip()
    if source_url:
        parts.append(f"Source URL: {source_url}")
    return "\n".join(parts)


class WebSchemaImporter:
    name = "webschema"

    def detect(self, path: Path) -> float:
        suffix = path.suffix.lower()
        if suffix in _HTML_EXTENSIONS:
            return 0.92
        if suffix == ".jsonld":
            return 0.9
        if suffix == ".json":
            return self._detect_schema_json(path)
        return 0.0

    def inspect(self, path: Path) -> WorkbookInspection:
        warnings: list[str] = []
        confidence = 0.75
        try:
            recipes = self._collect_schema_objects_for_path(path)
            if recipes:
                warnings.append(f"Detected {len(recipes)} schema recipe object(s).")
                confidence = 0.95
            else:
                warnings.append("No schema recipe objects detected in inspect pass.")
                confidence = 0.6
        except Exception as exc:  # noqa: BLE001
            warnings.append(f"Inspect failed to parse schema objects: {exc}")
            confidence = 0.3
        return WorkbookInspection(
            path=str(path),
            sheets=[
                SheetInspection(
                    name=path.name,
                    layout="webschema-local",
                    confidence=confidence,
                    warnings=warnings,
                )
            ],
            mappingStub=MappingConfig(),
        )

    def convert(
        self,
        path: Path,
        mapping: MappingConfig | None,
        progress_callback: Callable[[str], None] | None = None,
        run_settings: RunSettings | None = None,
    ) -> ConversionResult:
        _ = mapping
        report = ConversionReport(importer_name=self.name, source_file=path.name)
        raw_artifacts: list[RawArtifact] = []

        suffix = path.suffix.lower()
        source_hash = compute_file_hash(path)
        schema_policy = _run_setting_str(run_settings, "web_schema_policy", "prefer_schema")
        if schema_policy not in _SCHEMA_POLICY_CHOICES:
            schema_policy = "prefer_schema"
        schema_extractor = _run_setting_str(
            run_settings,
            "web_schema_extractor",
            "builtin_jsonld",
        )
        schema_normalizer = _run_setting_str(
            run_settings,
            "web_schema_normalizer",
            "simple",
        )
        text_extractor = _run_setting_str(
            run_settings,
            "web_html_text_extractor",
            "bs4",
        )
        schema_min_confidence = _run_setting_float(
            run_settings,
            "web_schema_min_confidence",
            0.75,
            low=0.0,
            high=1.0,
        )
        schema_min_ingredients = _run_setting_int(
            run_settings,
            "web_schema_min_ingredients",
            2,
            minimum=0,
        )
        schema_min_instruction_steps = _run_setting_int(
            run_settings,
            "web_schema_min_instruction_steps",
            1,
            minimum=0,
        )

        html_text: str | None = None
        html_title_hint: str | None = None
        source_url_hint: str | None = None
        extracted_source_text: str | None = None
        extracted_source_meta: dict[str, Any] | None = None
        schema_objects: list[dict[str, Any]] = []

        if suffix in _HTML_EXTENSIONS:
            html_text = path.read_text(encoding="utf-8", errors="replace")
            html_title_hint = _extract_title_from_html(html_text, fallback=path.stem)
            source_url_hint = _extract_source_url_from_html(html_text)
            raw_artifacts.append(
                RawArtifact(
                    importer=self.name,
                    sourceHash=source_hash,
                    locationId="source",
                    extension="html",
                    content=html_text,
                )
            )
            extracted_source_text, extracted_source_meta = extract_main_text_from_html(
                html_text,
                extractor=text_extractor,
            )
            raw_artifacts.append(
                RawArtifact(
                    importer=self.name,
                    sourceHash=source_hash,
                    locationId="full_text",
                    extension="json",
                    content={
                        "lines": [
                            {"index": line_index, "text": line}
                            for line_index, line in enumerate(
                                extracted_source_text.splitlines()
                            )
                        ],
                        "text": extracted_source_text,
                    },
                    metadata={"artifact_type": "extracted_text"},
                )
            )
            raw_artifacts.append(
                RawArtifact(
                    importer=self.name,
                    sourceHash=source_hash,
                    locationId="source_text_meta",
                    extension="json",
                    content=extracted_source_meta,
                )
            )
            if schema_policy != "heuristic_only":
                if progress_callback:
                    progress_callback("Extracting schema.org data from HTML...")
                schema_objects = extract_schema_recipes_from_html(
                    html_text,
                    extractor=schema_extractor,
                    normalizer=schema_normalizer,
                    source_url=source_url_hint,
                )
        elif suffix in _JSON_EXTENSIONS:
            if progress_callback:
                progress_callback("Loading JSON payload...")
            data = _load_json(path)
            source_url_hint = _source_url_from_json_payload(data)
            if suffix == ".json" and _is_recipesage_export_payload(data):
                raise RuntimeError(
                    "Detected RecipeSage export JSON; this should route to the recipesage importer."
                )
            if schema_policy != "heuristic_only":
                schema_objects = collect_schemaorg_recipe_objects(data)
        else:
            raise RuntimeError(
                f"webschema importer does not support file extension {suffix or '<none>'}."
            )

        schema_debug_rows: list[dict[str, Any]] = []
        for index, schema_obj in enumerate(schema_objects):
            confidence, reasons = schema_recipe_confidence(
                schema_obj,
                min_ingredients=schema_min_ingredients,
                min_instruction_steps=schema_min_instruction_steps,
            )
            schema_debug_rows.append(
                {
                    "index": index,
                    "name": schema_obj.get("name"),
                    "confidence": confidence,
                    "reasons": reasons,
                    "schema_threshold": schema_min_confidence,
                    "recipe": schema_obj,
                }
            )

        if schema_debug_rows:
            raw_artifacts.append(
                RawArtifact(
                    importer=self.name,
                    sourceHash=source_hash,
                    locationId="schema_extracted",
                    extension="json",
                    content={
                        "policy": schema_policy,
                        "extractor": schema_extractor,
                        "normalizer": schema_normalizer,
                        "items": schema_debug_rows,
                    },
                )
            )
        source_blocks: list[dict[str, Any]] = []
        if suffix in _HTML_EXTENSIONS:
            source_blocks = _source_blocks_from_text(
                extracted_source_text or "",
                source_kind="html_main_text",
                location_key="line_index",
            )
            if not source_blocks and html_text is not None:
                source_blocks = _source_blocks_from_text(
                    html_text,
                    source_kind="html_source",
                    location_key="line_index",
                )
        elif schema_objects:
            for index, schema_obj in enumerate(schema_objects):
                block_id = f"b{len(source_blocks)}"
                source_blocks.append(
                    {
                        "block_id": block_id,
                        "order_index": len(source_blocks),
                        "text": _schema_recipe_text(
                            schema_obj,
                            fallback_name=f"Recipe {index + 1}",
                        ),
                        "location": {"row_index": index},
                        "features": {"source_kind": "schema_recipe_object"},
                        "provenance": {"importer": self.name, "source_hash": source_hash},
                    }
                )
        else:
            source_blocks = _source_blocks_from_text(
                json.dumps(data, indent=2, sort_keys=True) if 'data' in locals() else "",
                source_kind="json_payload",
                location_key="line_index",
            )

        source_support = _schema_source_support(schema_objects)

        return ConversionResult(
            recipes=[],
            sourceBlocks=normalize_source_blocks(source_blocks),
            sourceSupport=source_support,
            nonRecipeBlocks=[],
            rawArtifacts=raw_artifacts,
            report=report,
            workbook=path.stem,
            workbookPath=str(path),
        )

    def _detect_schema_json(self, path: Path) -> float:
        try:
            payload = _load_json(path)
        except Exception:
            return 0.0
        if _is_recipesage_export_payload(payload):
            return 0.0
        recipes = collect_schemaorg_recipe_objects(payload)
        if recipes:
            return 0.86
        return 0.0

    def _collect_schema_objects_for_path(self, path: Path) -> list[dict[str, Any]]:
        suffix = path.suffix.lower()
        if suffix in _HTML_EXTENSIONS:
            html_text = path.read_text(encoding="utf-8", errors="replace")
            source_url = _extract_source_url_from_html(html_text)
            return extract_schema_recipes_from_html(
                html_text,
                extractor="builtin_jsonld",
                normalizer="simple",
                source_url=source_url,
            )
        if suffix in _JSON_EXTENSIONS:
            payload = _load_json(path)
            if suffix == ".json" and _is_recipesage_export_payload(payload):
                return []
            return collect_schemaorg_recipe_objects(payload)
        return []


def _run_setting_str(
    run_settings: RunSettings | None,
    field_name: str,
    fallback: str,
) -> str:
    if run_settings is None:
        return fallback
    value = getattr(run_settings, field_name, fallback)
    if hasattr(value, "value"):
        value = value.value
    normalized = str(value or fallback).strip().lower()
    return normalized or fallback


def _run_setting_float(
    run_settings: RunSettings | None,
    field_name: str,
    fallback: float,
    *,
    low: float,
    high: float,
) -> float:
    if run_settings is None:
        return fallback
    value = getattr(run_settings, field_name, fallback)
    try:
        parsed = float(value)
    except Exception:
        return fallback
    return max(low, min(high, parsed))


def _run_setting_int(
    run_settings: RunSettings | None,
    field_name: str,
    fallback: int,
    *,
    minimum: int,
) -> int:
    if run_settings is None:
        return fallback
    value = getattr(run_settings, field_name, fallback)
    try:
        parsed = int(value)
    except Exception:
        return fallback
    return max(minimum, parsed)


def _load_json(path: Path) -> object:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _is_recipesage_export_payload(payload: object) -> bool:
    if not isinstance(payload, dict):
        return False
    recipes = payload.get("recipes")
    if not isinstance(recipes, list) or not recipes:
        return False
    recipe_like_rows = 0
    for item in recipes:
        if not isinstance(item, dict):
            continue
        item_type = str(item.get("@type") or "").lower()
        if "recipe" in item_type:
            recipe_like_rows += 1
    return recipe_like_rows > 0


def _source_url_from_json_payload(payload: object) -> str | None:
    if not isinstance(payload, dict):
        return None
    for key in ("url", "@id", "mainEntityOfPage"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
        if isinstance(value, dict):
            nested_url = value.get("url") or value.get("@id")
            if isinstance(nested_url, str) and nested_url.strip():
                return nested_url.strip()
    return None


def _extract_source_url_from_html(html_text: str) -> str | None:
    try:
        soup = BeautifulSoup(html_text, "lxml")
    except Exception:
        return None
    canonical = soup.find("link", rel=lambda value: value and "canonical" in str(value).lower())
    if canonical and canonical.get("href"):
        href = str(canonical.get("href")).strip()
        if href:
            return href
    meta_og = soup.find("meta", attrs={"property": "og:url"})
    if meta_og and meta_og.get("content"):
        content = str(meta_og.get("content")).strip()
        if content:
            return content
    return None


def _extract_title_from_html(html_text: str, *, fallback: str) -> str:
    try:
        soup = BeautifulSoup(html_text, "lxml")
    except Exception:
        return fallback
    heading = soup.find("h1")
    if heading and heading.get_text(strip=True):
        return heading.get_text(strip=True)
    if soup.title and soup.title.get_text(strip=True):
        return soup.title.get_text(strip=True)
    return fallback


def _candidate_from_fallback_text(
    text: str,
    *,
    source_path: Path,
    source_hash: str,
    source_url_hint: str | None,
    title_hint: str | None,
) -> RecipeCandidate | None:
    normalized = cleaning.normalize_text(text)
    if not normalized:
        return None

    sections = extract_sections_from_text_blob(normalized)
    lines = [line.strip() for line in normalized.splitlines() if line.strip()]
    ingredients: list[str] = []
    instructions: list[str] = []
    notes_text: str | None = None
    if sections and (sections.get("ingredients") or sections.get("instructions")):
        ingredients = list(sections.get("ingredients", []))
        instructions = list(sections.get("instructions", []))
        notes = sections.get("notes", [])
        if notes:
            notes_text = "\n".join(notes)
    else:
        ingredients, instructions = _heuristic_split_ingredients_and_instructions(lines)

    if not ingredients and not instructions:
        return None

    title = _best_title_from_lines(lines, title_hint=title_hint or source_path.stem)
    candidate = RecipeCandidate(
        name=title,
        recipeIngredient=ingredients,
        recipeInstructions=instructions,
        description=notes_text,
        sourceUrl=source_url_hint,
        source=str(source_path),
        provenance={
            "source_hash": source_hash,
            "extraction_method": "webschema_fallback_text",
            "location": {"fallback": True},
        },
    )
    candidate.identifier = generate_recipe_id("webschema", source_hash, "fallback_0")
    return candidate


def _best_title_from_lines(lines: list[str], *, title_hint: str) -> str:
    header_tokens = {"ingredients", "ingredient", "instructions", "instruction", "directions", "method", "steps", "notes", "tips"}
    for line in lines[:20]:
        lower = line.strip().lower().rstrip(":")
        if lower in header_tokens:
            continue
        if len(line.split()) < 2:
            continue
        if len(line) > 100:
            continue
        feats = signals.classify_block(line)
        if feats.get("is_ingredient_likely"):
            continue
        return line.strip()
    return title_hint


def _heuristic_split_ingredients_and_instructions(
    lines: list[str],
) -> tuple[list[str], list[str]]:
    ingredients: list[str] = []
    instructions: list[str] = []
    section_mode: str | None = None

    for line in lines:
        normalized = line.strip()
        if not normalized:
            continue
        lower = normalized.lower().rstrip(":")
        if lower in {"ingredients", "ingredient"}:
            section_mode = "ingredients"
            continue
        if lower in {"instructions", "instruction", "directions", "method", "steps"}:
            section_mode = "instructions"
            continue
        if lower in {"notes", "tips", "note"}:
            section_mode = "notes"
            continue

        if section_mode == "ingredients":
            ingredient_line = _normalize_ingredient_line(normalized)
            if ingredient_line:
                ingredients.append(ingredient_line)
            continue
        if section_mode == "instructions":
            instruction_line = _normalize_instruction_line(normalized)
            if instruction_line:
                instructions.append(instruction_line)
            continue

        feats = signals.classify_block(normalized)
        if feats.get("is_ingredient_likely") or (
            feats.get("starts_with_quantity") and not feats.get("is_instruction_likely")
        ):
            ingredient_line = _normalize_ingredient_line(normalized)
            if ingredient_line:
                ingredients.append(ingredient_line)
            continue
        if feats.get("is_instruction_likely") or _INSTRUCTION_LEAD_RE.match(normalized):
            instruction_line = _normalize_instruction_line(normalized)
            if instruction_line:
                instructions.append(instruction_line)

    return ingredients, instructions


def _normalize_ingredient_line(line: str) -> str:
    return re.sub(r"^\s*[-*]+\s+", "", line).strip()


def _normalize_instruction_line(line: str) -> str:
    cleaned = re.sub(r"^\s*[-*]+\s+", "", line)
    cleaned = re.sub(r"^\s*\d+[.)]\s+", "", cleaned)
    return cleaned.strip()


def _rejected_candidate_block(
    candidate: RecipeCandidate,
    *,
    gate_action: str,
    score: float,
    tier: str,
    index_hint: int,
) -> dict[str, Any] | None:
    text = "\n".join(
        [
            candidate.name,
            "Ingredients:",
            *candidate.ingredients,
            "Instructions:",
            *[str(step) for step in candidate.instructions],
        ]
    ).strip()
    if not text:
        return None
    return {
        "index": index_hint,
        "text": text,
        "location": {"chunk_index": index_hint},
        "features": {
            "source": "rejected_recipe_candidate",
            "gate_action": gate_action,
            "score": score,
            "tier": tier,
        },
    }


registry.register(WebSchemaImporter())
