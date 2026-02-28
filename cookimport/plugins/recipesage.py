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
    generate_recipe_id,
)
from cookimport.core.scoring import (
    build_recipe_scoring_debug_row,
    recipe_gate_action,
    score_recipe_likeness,
    summarize_recipe_likeness,
)
from cookimport.plugins import registry

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from cookimport.config.run_settings import RunSettings

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
        """
        Converts RecipeSage export into RecipeCandidates.
        """
        report = ConversionReport(importer_name=self.name, source_file=path.name)
        recipes: List[RecipeCandidate] = []
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

            provenance_builder = ProvenanceBuilder(
                source_file=path.name,
                source_hash=file_hash,
                extraction_method="recipesage_import",
            )

            total_recipes = len(raw_recipes)
            for i, raw_recipe in enumerate(raw_recipes):
                if progress_callback and i % 10 == 0:
                    name = raw_recipe.get("name", "Untitled")
                    progress_callback(f"Processing recipe {i + 1}/{total_recipes}: {name}...")
                try:
                    # Basic validation
                    name = raw_recipe.get("name")
                    if not name:
                        report.warnings.append(f"Recipe at index {i} missing name, skipping.")
                        report.missing_field_counts["name"] = report.missing_field_counts.get("name", 0) + 1
                        continue

                    # Normalize fields
                    # RecipeCandidate handles most normalization via Pydantic validators
                    candidate = RecipeCandidate.model_validate(raw_recipe)
                    
                    # Ensure context
                    # (Pydantic model doesn't have @context by default in extra="forbid",
                    # but schema.org-style exports usually have it. We might need to pop it or allow it.)
                    
                    # Add provenance
                    candidate.provenance = provenance_builder.build(
                        confidence_score=1.0,
                        location={"index": i},
                        extra={"source_system": "recipesage"}
                    )
                    
                    # Ensure stable ID
                    source_uid = raw_recipe.get("identifier") or str(i)
                    if not candidate.identifier:
                        candidate.identifier = generate_recipe_id(
                            "recipesage", file_hash, f"recipe_{source_uid}"
                        )
                    
                    recipes.append(candidate)
                    
                except Exception as e:
                    logger.warning(f"Failed to normalize recipe {i}: {e}")
                    report.warnings.append(f"Failed to normalize recipe {i}: {e}")

            accepted_recipes: list[RecipeCandidate] = []
            non_recipe_blocks: list[dict[str, Any]] = []
            recipe_likeness_results = []
            recipe_scoring_debug_rows: list[dict[str, Any]] = []
            rejected_candidate_count = 0
            for index, recipe in enumerate(recipes):
                likeness = score_recipe_likeness(recipe, settings=run_settings)
                gate_action = recipe_gate_action(likeness, settings=run_settings)
                recipe.recipe_likeness = likeness
                recipe.confidence = likeness.score
                recipe_likeness_results.append(likeness)
                recipe_scoring_debug_rows.append(
                    build_recipe_scoring_debug_row(
                        candidate=recipe,
                        result=likeness,
                        gate_action=gate_action,
                        candidate_index=index,
                        importer=self.name,
                        source_hash=file_hash,
                    )
                )
                if gate_action == "reject":
                    rejected_candidate_count += 1
                    rejected_text = "\n".join(
                        [
                            recipe.name,
                            "Ingredients:",
                            *recipe.ingredients,
                            "Instructions:",
                            *[str(step) for step in recipe.instructions],
                        ]
                    ).strip()
                    if rejected_text:
                        non_recipe_blocks.append(
                            {
                                "index": len(non_recipe_blocks),
                                "text": rejected_text,
                                "location": {"chunk_index": index},
                                "features": {
                                    "source": "rejected_recipe_candidate",
                                    "gate_action": gate_action,
                                    "score": likeness.score,
                                    "tier": likeness.tier.value,
                                },
                            }
                        )
                    continue
                accepted_recipes.append(recipe)

            if recipe_scoring_debug_rows:
                raw_artifacts.append(
                    RawArtifact(
                        importer=self.name,
                        sourceHash=file_hash,
                        locationId="recipe_scoring_debug",
                        extension="jsonl",
                        content="\n".join(
                            json.dumps(row, sort_keys=True)
                            for row in recipe_scoring_debug_rows
                        ),
                        metadata={"artifact_type": "recipe_scoring_debug"},
                    )
                )

            recipes = accepted_recipes
            report.total_recipes = len(recipes)
            report.recipe_likeness = summarize_recipe_likeness(
                recipe_likeness_results,
                rejected_candidate_count,
                settings=run_settings,
            )
            if recipes:
                report.samples = [{"name": r.name} for r in recipes[:3]]

            return ConversionResult(
                recipes=recipes,
                nonRecipeBlocks=non_recipe_blocks,
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
