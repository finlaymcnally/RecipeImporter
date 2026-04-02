from __future__ import annotations

import gzip
import json
import logging
import re
import zipfile
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Optional

try:
    from bs4 import BeautifulSoup
except ImportError:
    BeautifulSoup = None

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
from cookimport.core.source_model import normalize_source_blocks
from cookimport.plugins import registry

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from cookimport.config.run_settings import RunSettings


def _paprika_recipe_text(raw_recipe: dict[str, Any]) -> str:
    name = str(raw_recipe.get("name") or "Untitled").strip()
    parts = [name]
    notes = str(raw_recipe.get("notes") or "").strip()
    if notes:
        parts.append(notes)
    prep_time = str(raw_recipe.get("prep_time") or raw_recipe.get("prepTime") or "").strip()
    if prep_time:
        parts.append(f"Prep Time: {prep_time}")
    cook_time = str(raw_recipe.get("cook_time") or raw_recipe.get("cookTime") or "").strip()
    if cook_time:
        parts.append(f"Cook Time: {cook_time}")
    ingredients = str(raw_recipe.get("ingredients") or "").splitlines()
    ingredients = [line.strip() for line in ingredients if line.strip()]
    if ingredients:
        parts.append("Ingredients:")
        parts.extend(f"- {item}" for item in ingredients)
    directions = str(raw_recipe.get("directions") or "").splitlines()
    directions = [line.strip() for line in directions if line.strip()]
    if directions:
        parts.append("Instructions:")
        parts.extend(f"{index}. {item}" for index, item in enumerate(directions, start=1))
    servings = str(raw_recipe.get("servings") or "").strip()
    if servings:
        parts.append(f"Yield: {servings}")
    source_url = str(raw_recipe.get("source_url") or "").strip()
    if source_url:
        parts.append(f"Source URL: {source_url}")
    return "\n".join(parts)


def _candidate_to_source_recipe(candidate: RecipeCandidate) -> dict[str, Any]:
    return {
        "name": candidate.name,
        "notes": candidate.description,
        "ingredients": "\n".join(item for item in candidate.ingredients if item),
        "directions": "\n".join(
            step if isinstance(step, str) else step.text
            for step in candidate.instructions
            if (step if isinstance(step, str) else step.text)
        ),
        "servings": candidate.recipe_yield,
        "source_url": candidate.source_url,
        "prep_time": candidate.prep_time,
        "cook_time": candidate.cook_time,
        "total_time": candidate.total_time,
    }

def _normalize_duration(text: str | None) -> str | None:
    if not text:
        return None
    
    text = text.lower().strip()
    if not text or text == "0":
        return None
    
    # Already ISO 8601
    if text.startswith("pt"):
        return text.upper()
    
    # Common Paprika formats: "5 mins", "1 hr 30 mins", "1 hour"
    total_minutes = 0
    
    # Matches "1 hr", "2 hours", "30 mins", "15 minutes"
    matches = re.findall(r"(\d+)\s*(hours?|hrs?|h|mins?|m)\b", text)
    if matches:
        for val, unit in matches:
            v = int(val)
            if unit.startswith("h"):
                total_minutes += v * 60
            else:
                total_minutes += v
    else:
        # Try just a number
        try:
            total_minutes = int(text)
        except ValueError:
            return None

    if total_minutes == 0:
        return None
    
    hours = total_minutes // 60
    minutes = total_minutes % 60
    
    res = "PT"
    if hours:
        res += f"{hours}H"
    if minutes:
        res += f"{minutes}M"
    return res

class PaprikaImporter:
    name = "paprika"

    def detect(self, path: Path) -> float:
        """
        Returns confidence that this is a Paprika export.
        """
        if path.suffix.lower() == ".paprikarecipes":
            return 0.95
        
        if path.is_dir():
            # Check for Paprika HTML export structure
            if (path / "index.html").exists() and (path / "images").is_dir():
                return 0.8
            # Check for .paprikarecipes files
            if list(path.glob("*.paprikarecipes")):
                return 0.7
        
        return 0.0

    def inspect(self, path: Path) -> WorkbookInspection:
        """
        Analyzes the Paprika export.
        """
        try:
            recipe_count = 0
            if path.suffix.lower() == ".paprikarecipes":
                with zipfile.ZipFile(path, "r") as z:
                    recipe_count = len([name for name in z.namelist() if not name.endswith("/")])
            elif path.is_dir():
                recipe_count = len(list(path.glob("*.html"))) - 1 # Subtract index.html
            
            return WorkbookInspection(
                path=str(path),
                sheets=[
                    SheetInspection(
                        name=path.name,
                        layout="paprika-export",
                        confidence=1.0,
                        warnings=[f"Detected {recipe_count} recipe candidate(s)."],
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
                        layout="paprika-export",
                        confidence=0.0,
                        warnings=[f"Failed to inspect Paprika export: {e}"],
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
        file_hash = compute_file_hash(path) if path.is_file() else "dir_hash"

        try:
            raw_recipe_rows: list[dict[str, Any]] = []
            if path.suffix.lower() == ".paprikarecipes":
                zip_recipes, raw_artifacts = self._convert_paprikarecipes(
                    path,
                    file_hash,
                    report,
                    progress_callback,
                )
                raw_recipe_rows.extend(
                    _candidate_to_source_recipe(candidate) for candidate in zip_recipes
                )
            elif path.is_dir():
                zip_files = list(path.glob("*.paprikarecipes"))
                has_html = (path / "index.html").exists()

                for zf in zip_files:
                    zf_hash = compute_file_hash(zf)
                    z_recipes, z_artifacts = self._convert_paprikarecipes(
                        zf,
                        zf_hash,
                        report,
                        progress_callback,
                    )
                    raw_artifacts.extend(z_artifacts)
                    raw_recipe_rows.extend(
                        _candidate_to_source_recipe(candidate) for candidate in z_recipes
                    )
                if has_html:
                    h_recipes, h_artifacts = self._convert_html_export(
                        path,
                        file_hash,
                        report,
                        progress_callback,
                    )
                    raw_artifacts.extend(h_artifacts)
                    raw_recipe_rows.extend(
                        _candidate_to_source_recipe(candidate) for candidate in h_recipes
                    )

            source_blocks: list[dict[str, Any]] = []
            source_support: list[dict[str, Any]] = []
            for index, raw_recipe in enumerate(raw_recipe_rows):
                if not isinstance(raw_recipe, dict):
                    continue
                block_id = f"b{len(source_blocks)}"
                source_blocks.append(
                    {
                        "block_id": block_id,
                        "order_index": len(source_blocks),
                        "text": _paprika_recipe_text(raw_recipe),
                        "location": {"row_index": index},
                        "features": {"source_kind": "paprika_recipe"},
                        "provenance": {"importer": self.name, "source_hash": file_hash},
                    }
                )
                source_support.append(
                    {
                        "hintClass": "evidence",
                        "kind": "paprika_recipe_object",
                        "referencedBlockIds": [block_id],
                        "payload": {
                            "recipe_index": index,
                            "name": raw_recipe.get("name"),
                            "recipe": raw_recipe,
                        },
                        "provenance": {"importer": self.name, "source": "paprika_export"},
                    }
                )

            report.total_recipes = 0
            return ConversionResult(
                recipes=[],
                sourceBlocks=normalize_source_blocks(source_blocks),
                sourceSupport=source_support,
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

    def _convert_paprikarecipes(
        self,
        path: Path,
        file_hash: str,
        report: ConversionReport,
        progress_callback: Callable[[str], None] | None = None,
    ) -> tuple[list[RecipeCandidate], list[RawArtifact]]:
        recipes: list[RecipeCandidate] = []
        raw_artifacts: list[RawArtifact] = []
        
        provenance_builder = ProvenanceBuilder(
            source_file=path.name,
            source_hash=file_hash,
            extraction_method="paprikarecipes_zip",
        )

        with zipfile.ZipFile(path, "r") as z:
            namelist = [n for n in z.namelist() if not n.endswith("/")]
            total = len(namelist)
            for i, name in enumerate(namelist):
                if progress_callback and i % 5 == 0:
                    progress_callback(f"Processing Paprika entry {i + 1}/{total}...")
                
                try:
                    with z.open(name) as f:
                        content = f.read()
                        # Paprika files are gzipped JSON
                        decompressed = gzip.decompress(content)
                        raw_recipe = json.loads(decompressed.decode("utf-8"))
                    
                    raw_artifacts.append(
                        RawArtifact(
                            importer=self.name,
                            sourceHash=file_hash,
                            locationId=name,
                            extension="json",
                            content=raw_recipe,
                        )
                    )

                    candidate = self._map_paprika_json(raw_recipe)
                    candidate.provenance = provenance_builder.build(
                        confidence_score=1.0,
                        location={"zip_entry": name},
                        extra={"source_system": "paprika"}
                    )
                    
                    if not candidate.identifier:
                        uid = raw_recipe.get("uid") or name
                        candidate.identifier = generate_recipe_id(
                            "paprika", file_hash, f"recipe_{uid}"
                        )
                    
                    recipes.append(candidate)
                    
                except Exception as e:
                    logger.warning(f"Failed to parse Paprika entry {name}: {e}")
                    report.warnings.append(f"Failed to parse entry {name}: {e}")
                    
        return recipes, raw_artifacts

    def _convert_html_export(
        self,
        path: Path,
        file_hash: str,
        report: ConversionReport,
        progress_callback: Callable[[str], None] | None = None,
    ) -> tuple[list[RecipeCandidate], list[RawArtifact]]:
        if BeautifulSoup is None:
            report.errors.append("BeautifulSoup4 is required for Paprika HTML exports.")
            return [], []
            
        recipes: list[RecipeCandidate] = []
        raw_artifacts: list[RawArtifact] = []
        
        provenance_builder = ProvenanceBuilder(
            source_file=path.name,
            source_hash=file_hash,
            extraction_method="paprika_html_folder",
        )

        html_files = list(path.glob("*.html"))
        total = len(html_files)
        for i, html_file in enumerate(html_files):
            if html_file.name == "index.html":
                continue
            
            if progress_callback and i % 5 == 0:
                progress_callback(f"Processing Paprika HTML {i + 1}/{total}...")
                
            try:
                content = html_file.read_text(encoding="utf-8")
                soup = BeautifulSoup(content, "lxml")
                
                # Paprika HTML exports often have JSON-LD
                json_ld_script = soup.find("script", type="application/ld+json")
                if json_ld_script:
                    raw_recipe = json.loads(json_ld_script.string)
                    # Handle if it's a list or single object
                    if isinstance(raw_recipe, list):
                        raw_recipe = raw_recipe[0]
                    
                    candidate = RecipeCandidate.model_validate(raw_recipe)
                else:
                    # Fallback to heuristic extraction if no JSON-LD
                    candidate = self._extract_from_html_fallback(soup)

                raw_artifacts.append(
                    RawArtifact(
                        importer=self.name,
                        sourceHash=file_hash,
                        locationId=html_file.name,
                        extension="html",
                        content=content,
                    )
                )

                candidate.provenance = provenance_builder.build(
                    confidence_score=0.9,
                    location={"file": html_file.name},
                    extra={"source_system": "paprika"}
                )
                
                if not candidate.identifier:
                    candidate.identifier = generate_recipe_id(
                        "paprika_html", file_hash, html_file.stem
                    )
                
                recipes.append(candidate)

            except Exception as e:
                logger.warning(f"Failed to parse Paprika HTML {html_file.name}: {e}")
                report.warnings.append(f"Failed to parse {html_file.name}: {e}")
                
        return recipes, raw_artifacts

    def _map_paprika_json(self, data: dict[str, Any]) -> RecipeCandidate:
        """
        Maps raw Paprika JSON fields to RecipeCandidate.
        """
        ingredients_raw = data.get("ingredients", "")
        ingredients = [line.strip() for line in ingredients_raw.splitlines() if line.strip()]
        
        directions_raw = data.get("directions", "")
        instructions = [line.strip() for line in directions_raw.splitlines() if line.strip()]
        
        return RecipeCandidate(
            name=data.get("name", "Untitled"),
            ingredients=ingredients,
            instructions=instructions,
            description=data.get("notes"),
            recipeYield=data.get("servings"),
            prep_time=_normalize_duration(data.get("prep_time")),
            cook_time=_normalize_duration(data.get("cook_time")),
            source_url=data.get("source_url"),
            publisher=data.get("source"),
            recipe_category=data.get("categories", []),
        )

    def _extract_from_html_fallback(self, soup: BeautifulSoup) -> RecipeCandidate:
        """
        Heuristic extraction from Paprika HTML if JSON-LD is missing.
        """
        name = soup.find("h1").get_text(strip=True) if soup.find("h1") else "Untitled"
        
        ingredients = []
        ing_div = soup.find("div", class_="ingredients")
        if ing_div:
            ingredients = [li.get_text(strip=True) for li in ing_div.find_all("li")]
            
        instructions = []
        dir_div = soup.find("div", class_="directions")
        if dir_div:
            instructions = [li.get_text(strip=True) for li in dir_div.find_all("li")]
            if not instructions:
                 # Sometimes it's just paragraphs
                 instructions = [p.get_text(strip=True) for p in dir_div.find_all("p") if p.get_text(strip=True)]

        return RecipeCandidate(
            name=name,
            ingredients=ingredients,
            instructions=instructions,
        )

registry.register(PaprikaImporter())
