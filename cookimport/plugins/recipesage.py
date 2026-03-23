from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, List

from cookimport.core.models import (
    ConversionReport,
    ConversionResult,
    MappingConfig,
    RawArtifact,
    RecipeCandidate,
    WorkbookInspection,
    SheetInspection,
)
from cookimport.core.reporting import (
    ProvenanceBuilder,
    compute_file_hash,
)
from cookimport.core.source_model import normalize_source_blocks
from cookimport.plugins import registry

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from cookimport.config.run_settings import RunSettings


def _recipesage_recipe_text(raw_recipe: dict[str, Any]) -> str:
    name = str(raw_recipe.get("name") or "Untitled").strip()
    parts = [name]
    description = str(raw_recipe.get("description") or raw_recipe.get("notes") or "").strip()
    if description:
        parts.append(description)
    ingredients = raw_recipe.get("recipeIngredient") or raw_recipe.get("ingredients") or []
    if isinstance(ingredients, str):
        ingredients = [line.strip() for line in ingredients.splitlines() if line.strip()]
    if ingredients:
        parts.append("Ingredients:")
        parts.extend(f"- {item}" for item in ingredients if str(item).strip())
    instructions = raw_recipe.get("recipeInstructions") or raw_recipe.get("instructions") or []
    if isinstance(instructions, str):
        instructions = [line.strip() for line in instructions.splitlines() if line.strip()]
    if instructions:
        parts.append("Instructions:")
        for index, item in enumerate(instructions, start=1):
            if isinstance(item, dict):
                text = str(item.get("text") or "").strip()
            else:
                text = str(item).strip()
            if text:
                parts.append(f"{index}. {text}")
    recipe_yield = str(raw_recipe.get("recipeYield") or raw_recipe.get("yield") or "").strip()
    if recipe_yield:
        parts.append(f"Yield: {recipe_yield}")
    source_url = str(raw_recipe.get("sourceUrl") or raw_recipe.get("url") or "").strip()
    if source_url:
        parts.append(f"Source URL: {source_url}")
    return "\n".join(parts)

class RecipeSageImporter:
    name = "recipesage"

    def detect(self, path: Path) -> float:
        """
        Returns confidence that this is a RecipeSage export file.
        Expects a .json file with a 'recipes' array of objects with '@type': 'Recipe'.
        """
        if path.suffix.lower() != ".json":
            return 0.0
        
        try:
            with open(path, "r", encoding="utf-8") as f:
                # Read just enough to check structure
                head = f.read(1024)
                if '"recipes"' in head and '"@type"' in head and '"Recipe"' in head:
                    return 0.95
        except Exception:
            return 0.0
        return 0.0

    def inspect(self, path: Path) -> WorkbookInspection:
        """
        Analyzes the RecipeSage export file.
        """
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            
            recipes = data.get("recipes", [])
            recipe_count = len(recipes)
            
            return WorkbookInspection(
                path=str(path),
                sheets=[
                    SheetInspection(
                        name=path.name,
                        layout="recipesage-export",
                        confidence=1.0,
                        warnings=[f"Detected {recipe_count} recipe(s)."],
                    )
                ],
                mappingStub=MappingConfig(),
            )
        except Exception as e:
            return WorkbookInspection(
                path=str(path),
                sheets=[
                    SheetInspection(
                        name=path.name,
                        layout="recipesage-export",
                        confidence=0.0,
                        warnings=[f"Failed to read RecipeSage export: {e}"],
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
        report = ConversionReport(importer_name=self.name, source_file=path.name)
        raw_artifacts: List[RawArtifact] = []
        file_hash = compute_file_hash(path)

        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            
            raw_recipes = data.get("recipes", [])
            
            raw_artifacts.append(
                RawArtifact(
                    importer=self.name,
                    sourceHash=file_hash,
                    locationId="full_export",
                    extension="json",
                    content=data,
                )
            )
            source_blocks: list[dict[str, Any]] = []
            source_support: list[dict[str, Any]] = []
            total_recipes = len(raw_recipes)
            for i, raw_recipe in enumerate(raw_recipes):
                if progress_callback and i % 10 == 0:
                    name = raw_recipe.get("name", "Untitled")
                    progress_callback(f"Processing recipe {i + 1}/{total_recipes}: {name}...")
                if not isinstance(raw_recipe, dict):
                    report.warnings.append(f"Recipe at index {i} is not an object, skipping.")
                    continue
                name = str(raw_recipe.get("name") or "").strip()
                if not name:
                    report.warnings.append(f"Recipe at index {i} missing name, skipping.")
                    report.missing_field_counts["name"] = report.missing_field_counts.get("name", 0) + 1
                    continue
                block_id = f"b{len(source_blocks)}"
                source_blocks.append(
                    {
                        "block_id": block_id,
                        "order_index": len(source_blocks),
                        "text": _recipesage_recipe_text(raw_recipe),
                        "location": {"row_index": i},
                        "features": {"source_kind": "recipesage_recipe"},
                        "provenance": {"importer": self.name, "source_hash": file_hash},
                    }
                )
                source_support.append(
                    {
                        "hintClass": "evidence",
                        "kind": "recipesage_recipe_object",
                        "referencedBlockIds": [block_id],
                        "payload": {
                            "recipe_index": i,
                            "name": name,
                            "recipe": raw_recipe,
                        },
                        "provenance": {"importer": self.name, "source": "recipesage_export"},
                    }
                )

            report.total_recipes = 0
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

        except Exception as e:
            logger.error(f"Fatal error converting {path}: {e}")
            report.errors.append(str(e))
            return ConversionResult(
                recipes=[],
                rawArtifacts=[],
                report=report,
                workbook=path.stem,
                workbookPath=str(path),
            )

registry.register(RecipeSageImporter())
