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
    WorkbookInspection,
)
from cookimport.core.reporting import compute_file_hash, generate_recipe_id
from cookimport.core.scoring import (
    build_recipe_scoring_debug_row,
    recipe_gate_action,
    score_recipe_likeness,
    summarize_recipe_likeness,
)
from cookimport.parsing import cleaning, signals
from cookimport.parsing.html_schema_extract import extract_schema_recipes_from_html
from cookimport.parsing.html_text_extract import extract_main_text_from_html
from cookimport.parsing.schemaorg_ingest import (
    collect_schemaorg_recipe_objects,
    schema_recipe_confidence,
    schema_recipe_to_candidate,
)
from cookimport.parsing.text_section_extract import extract_sections_from_text_blob
from cookimport.parsing.tips import (
    extract_tip_candidates_from_candidate,
    partition_tip_candidates,
)
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
        non_recipe_blocks: list[dict[str, Any]] = []
        recipe_likeness_results = []
        recipe_scoring_debug_rows: list[dict[str, Any]] = []
        rejected_candidate_count = 0

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
        accepted_schema_recipes: list[RecipeCandidate] = []
        for index, schema_obj in enumerate(schema_objects):
            confidence, reasons = schema_recipe_confidence(
                schema_obj,
                min_ingredients=schema_min_ingredients,
                min_instruction_steps=schema_min_instruction_steps,
            )
            candidate = schema_recipe_to_candidate(
                schema_obj,
                source=str(path),
                source_url_hint=source_url_hint,
                confidence=confidence,
                provenance={
                    "source_hash": source_hash,
                    "extraction_method": "webschema_schema",
                    "location": {"schema_index": index},
                },
            )
            if not candidate.identifier:
                candidate.identifier = generate_recipe_id(
                    "webschema", source_hash, f"schema_{index}"
                )

            likeness = score_recipe_likeness(candidate, settings=run_settings)
            gate_action = recipe_gate_action(likeness, settings=run_settings)
            candidate.recipe_likeness = likeness
            candidate.confidence = likeness.score
            recipe_likeness_results.append(likeness)

            recipe_scoring_debug_rows.append(
                build_recipe_scoring_debug_row(
                    candidate=candidate,
                    result=likeness,
                    gate_action=gate_action,
                    candidate_index=index,
                    location={"schema_index": index},
                    importer=self.name,
                    source_hash=source_hash,
                )
            )

            accepted_by_schema_threshold = confidence >= schema_min_confidence
            accepted_by_gate = gate_action != "reject"
            schema_debug_rows.append(
                {
                    "index": index,
                    "name": candidate.name,
                    "confidence": confidence,
                    "reasons": reasons,
                    "schema_threshold": schema_min_confidence,
                    "accepted_schema_threshold": accepted_by_schema_threshold,
                    "accepted_gate": accepted_by_gate,
                    "gate_action": gate_action,
                    "recipe_likeness_score": likeness.score,
                    "recipe_likeness_tier": likeness.tier.value,
                    "recipe": schema_obj,
                }
            )

            if not accepted_by_schema_threshold:
                continue
            if gate_action == "reject":
                rejected_candidate_count += 1
                rejected_block = _rejected_candidate_block(
                    candidate,
                    gate_action=gate_action,
                    score=likeness.score,
                    tier=likeness.tier.value,
                    index_hint=index,
                )
                if rejected_block:
                    non_recipe_blocks.append(rejected_block)
                continue
            accepted_schema_recipes.append(candidate)

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
        if accepted_schema_recipes:
            raw_artifacts.append(
                RawArtifact(
                    importer=self.name,
                    sourceHash=source_hash,
                    locationId="schema_accepted",
                    extension="json",
                    content=[
                        recipe.model_dump(by_alias=True, exclude_none=True)
                        for recipe in accepted_schema_recipes
                    ],
                )
            )

        selected_recipes: list[RecipeCandidate]
        fallback_recipes: list[RecipeCandidate] = []
        if schema_policy == "heuristic_only":
            selected_recipes = []
        elif schema_policy == "schema_only":
            selected_recipes = list(accepted_schema_recipes)
            if not selected_recipes:
                report.warnings.append(
                    "web_schema_policy=schema_only and no schema recipes passed thresholds."
                )
        else:
            selected_recipes = list(accepted_schema_recipes)

        should_run_fallback = (
            schema_policy in {"heuristic_only", "prefer_schema"}
            and (schema_policy == "heuristic_only" or not accepted_schema_recipes)
        )
        if should_run_fallback:
            if suffix not in _HTML_EXTENSIONS:
                report.warnings.append(
                    "Fallback extraction requested but only HTML/HTM sources support fallback."
                )
            elif html_text is not None:
                if progress_callback:
                    progress_callback("Running deterministic HTML fallback extraction...")
                fallback_text, fallback_meta = extract_main_text_from_html(
                    html_text,
                    extractor=text_extractor,
                )
                raw_artifacts.append(
                    RawArtifact(
                        importer=self.name,
                        sourceHash=source_hash,
                        locationId="fallback_text",
                        extension="txt",
                        content=fallback_text,
                    )
                )
                raw_artifacts.append(
                    RawArtifact(
                        importer=self.name,
                        sourceHash=source_hash,
                        locationId="fallback_meta",
                        extension="json",
                        content=fallback_meta,
                    )
                )
                fallback_candidate = _candidate_from_fallback_text(
                    fallback_text,
                    source_path=path,
                    source_hash=source_hash,
                    source_url_hint=source_url_hint,
                    title_hint=html_title_hint,
                )
                if fallback_candidate is not None:
                    likeness = score_recipe_likeness(fallback_candidate, settings=run_settings)
                    gate_action = recipe_gate_action(likeness, settings=run_settings)
                    fallback_candidate.recipe_likeness = likeness
                    fallback_candidate.confidence = likeness.score
                    recipe_likeness_results.append(likeness)
                    recipe_scoring_debug_rows.append(
                        build_recipe_scoring_debug_row(
                            candidate=fallback_candidate,
                            result=likeness,
                            gate_action=gate_action,
                            candidate_index=len(schema_objects),
                            location={"fallback": True},
                            importer=self.name,
                            source_hash=source_hash,
                        )
                    )
                    if gate_action == "reject":
                        rejected_candidate_count += 1
                        rejected_block = _rejected_candidate_block(
                            fallback_candidate,
                            gate_action=gate_action,
                            score=likeness.score,
                            tier=likeness.tier.value,
                            index_hint=len(non_recipe_blocks),
                        )
                        if rejected_block:
                            non_recipe_blocks.append(rejected_block)
                    else:
                        fallback_recipes.append(fallback_candidate)
                else:
                    report.warnings.append("Fallback extraction produced no recipe candidate.")

        if schema_policy == "heuristic_only":
            selected_recipes = fallback_recipes
        elif schema_policy == "prefer_schema" and not selected_recipes:
            selected_recipes = fallback_recipes

        tip_candidates = []
        for recipe in selected_recipes:
            tip_candidates.extend(extract_tip_candidates_from_candidate(recipe))
        tips, recipe_specific, not_tips = partition_tip_candidates(tip_candidates)

        if recipe_scoring_debug_rows:
            raw_artifacts.append(
                RawArtifact(
                    importer=self.name,
                    sourceHash=source_hash,
                    locationId="recipe_scoring_debug",
                    extension="jsonl",
                    content="\n".join(
                        json.dumps(row, sort_keys=True)
                        for row in recipe_scoring_debug_rows
                    ),
                    metadata={"artifact_type": "recipe_scoring_debug"},
                )
            )

        report.total_recipes = len(selected_recipes)
        report.total_tips = len(tips)
        report.total_tip_candidates = len(tip_candidates)
        report.total_general_tips = len(tips)
        report.total_recipe_specific_tips = len(recipe_specific)
        report.total_not_tips = len(not_tips)
        report.recipe_likeness = summarize_recipe_likeness(
            recipe_likeness_results,
            rejected_candidate_count,
            settings=run_settings,
        )
        report.samples = [{"name": recipe.name} for recipe in selected_recipes[:3]]

        return ConversionResult(
            recipes=selected_recipes,
            tips=tips,
            tip_candidates=tip_candidates,
            nonRecipeBlocks=non_recipe_blocks,
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
