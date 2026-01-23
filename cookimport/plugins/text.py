from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import yaml

from cookimport.core.models import (
    ConversionReport,
    ConversionResult,
    MappingConfig,
    RecipeCandidate,
    WorkbookInspection,
    SheetInspection,
    SheetMapping,
)
from cookimport.core.reporting import (
    ProvenanceBuilder,
    compute_file_hash,
    generate_recipe_id,
)
from cookimport.parsing import cleaning, signals
from cookimport.plugins import registry

logger = logging.getLogger(__name__)

# Constants for splitting
_SPLIT_DELIMITER_RE = re.compile(r"\n={3,}\s*(?:RECIPE)?\s*={3,}\n", re.IGNORECASE)
_MARKDOWN_HEADER_RE = re.compile(r"^#+\s+(.+)$", re.MULTILINE)


class TextImporter:
    name = "text"

    def detect(self, path: Path) -> float:
        """
        Returns confidence that this is a text file we can handle.
        """
        if path.suffix.lower() in {'.txt', '.md', '.markdown'}:
            return 0.9
        return 0.0

    def inspect(self, path: Path) -> WorkbookInspection:
        """
        Analyzes the text file to determine structure (single vs multi-recipe).
        Reuses WorkbookInspection for consistency, treating the file as one 'sheet'.
        """
        text = path.read_text(encoding="utf-8", errors="replace")
        normalized = cleaning.normalize_text(text)
        
        candidates = self._split_recipes(normalized)
        recipe_count = len(candidates)
        
        # We'll treat the file as having one "sheet" named after the file
        sheet_name = path.name
        
        # Heuristic layout detection
        layout = "single-recipe" if recipe_count == 1 else "multi-recipe"
        
        return WorkbookInspection(
            path=str(path),
            sheets=[
                SheetInspection(
                    name=sheet_name,
                    layout=layout,
                    headerRow=None,
                    confidence=0.8,  # Arbitrary high confidence
                    warnings=[f"Detected {recipe_count} recipe candidate(s)."],
                )
            ],
            mappingStub=MappingConfig(),
        )

    def convert(self, path: Path, mapping: MappingConfig | None) -> ConversionResult:
        """
        Converts the text file into RecipeCandidates.
        """
        report = ConversionReport()
        recipes: List[RecipeCandidate] = []
        
        try:
            raw_text = path.read_text(encoding="utf-8", errors="replace")
            file_hash = compute_file_hash(path)
            normalized = cleaning.normalize_text(raw_text)
            
            # 1. Split
            chunks = self._split_recipes(normalized)
            
            # 2. Parse each chunk
            for i, (chunk_text, line_range) in enumerate(chunks):
                try:
                    candidate = self._parse_chunk(chunk_text)
                    
                    # Add provenance
                    provenance_builder = ProvenanceBuilder(
                        source_file=path.name,
                        source_hash=file_hash,
                        extraction_method="heuristic_text",
                    )
                    
                    provenance = provenance_builder.build(
                        confidence_score=0.8, # TODO: Calculate based on signal strength
                        location={
                            "start_line": line_range[0],
                            "end_line": line_range[1],
                            "chunk_index": i
                        }
                    )
                    candidate.provenance = provenance
                    
                    # Add generic ID if none
                    if not candidate.identifier:
                        candidate.identifier = generate_recipe_id(
                            "text", file_hash, f"chunk_{i}"
                        )
                        
                    recipes.append(candidate)
                    
                except Exception as e:
                    logger.warning(f"Failed to parse chunk {i} in {path}: {e}")
                    report.warnings.append(f"Failed to parse chunk {i}: {e}")
            
            report.total_recipes = len(recipes)
            if recipes:
                report.samples = [{"name": r.name} for r in recipes[:3]]
                
            return ConversionResult(
                recipes=recipes,
                report=report,
                workbook=path.stem, # Using stem as "workbook" name
                workbookPath=str(path),
            )
            
        except Exception as e:
            logger.error(f"Fatal error converting {path}: {e}")
            report.errors.append(str(e))
            return ConversionResult(
                recipes=[],
                report=report,
                workbook=path.stem,
                workbookPath=str(path),
            )

    def _split_recipes(self, text: str) -> List[Tuple[str, Tuple[int, int]]]:
        """
        Splits text into recipe chunks.
        Returns list of (text_chunk, (start_line, end_line)).
        """
        # Strategy 1: Explicit delimiters
        if _SPLIT_DELIMITER_RE.search(text):
            return self._split_by_regex(text, _SPLIT_DELIMITER_RE)
            
        # Strategy 2: Markdown Headers (if multiple H1s are present)
        h1_matches = list(_MARKDOWN_HEADER_RE.finditer(text))
        if len(h1_matches) > 1:
            # Check if they look like recipe titles (not too long)
            # This is a simplification; we might assume top-level headers are recipes
            return self._split_by_positions(text, [m.start() for m in h1_matches])
            
        # Strategy 3: Default to single recipe
        return [(text, (1, len(text.splitlines())))]

    def _split_by_regex(self, text: str, pattern: re.Pattern) -> List[Tuple[str, Tuple[int, int]]]:
        chunks = []
        last_end = 0
        lines = text.splitlines(keepends=True)
        # Mapping char index to line number is expensive, so we'll approximate or do it if needed.
        # For now, let's just split string and estimate lines.
        
        # Actually, let's use re.split logic but keep offsets
        matches = list(pattern.finditer(text))
        if not matches:
             return [(text, (1, len(lines)))]
             
        current_start = 0
        for match in matches:
            chunk = text[current_start:match.start()].strip()
            if chunk:
                 # TODO: Calculate accurate line numbers
                 chunks.append((chunk, (0, 0))) 
            current_start = match.end()
            
        last_chunk = text[current_start:].strip()
        if last_chunk:
            chunks.append((last_chunk, (0, 0)))
            
        return chunks

    def _split_by_positions(self, text: str, positions: List[int]) -> List[Tuple[str, Tuple[int, int]]]:
        chunks = []
        for i in range(len(positions)):
            start = positions[i]
            end = positions[i+1] if i + 1 < len(positions) else len(text)
            chunk = text[start:end].strip()
            if chunk:
                chunks.append((chunk, (0, 0)))
        return chunks

    def _parse_chunk(self, text: str) -> RecipeCandidate:
        """
        Parses a single recipe chunk into a candidate.
        """
        lines = text.splitlines()
        
        # 1. Frontmatter
        frontmatter = {}
        content_lines = lines
        if text.startswith("---"):
            try:
                # Find end of frontmatter
                end_idx = -1
                for i in range(1, len(lines)):
                    if lines[i].strip() == "---":
                        end_idx = i
                        break
                if end_idx > 0:
                    fm_text = "\n".join(lines[1:end_idx])
                    frontmatter = yaml.safe_load(fm_text) or {}
                    content_lines = lines[end_idx+1:]
            except Exception as e:
                logger.warning(f"Failed to parse frontmatter: {e}")

        # 2. Identify Sections
        name = frontmatter.get("title")
        ingredients: List[str] = []
        instructions: List[str] = []
        description_lines: List[str] = []
        tags = frontmatter.get("tags", [])
        if isinstance(tags, str):
            tags = [t.strip() for t in tags.split(",")]
        
        current_section = "description" # Default start
        
        # Heuristic: First line is title if not in frontmatter
        start_idx = 0
        if not name:
            for i, line in enumerate(content_lines):
                stripped = line.strip()
                if stripped:
                    # Cleanup title candidates
                    name = re.sub(r"^#+\s*", "", stripped) # Remove markdown headers
                    name = re.sub(r"^Title:\s*", "", name, flags=re.IGNORECASE) # Remove "Title:" prefix
                    start_idx = i + 1
                    break
        
        for line in content_lines[start_idx:]:
            if not line.strip():
                continue
                
            block_feats = signals.classify_block(line)
            
            if block_feats["is_ingredient_header"]:
                current_section = "ingredients"
                continue
            elif block_feats["is_instruction_header"]:
                current_section = "instructions"
                continue
            elif block_feats["is_header_likely"] and "notes" in line.lower():
                current_section = "description" # Append notes to description
                continue
                
            # Classify content based on section
            if current_section == "ingredients":
                # Strip bullets
                clean_line = re.sub(r"^\s*[-*•]\s*", "", line.strip())
                ingredients.append(clean_line)
            elif current_section == "instructions":
                # Strip numbers and bullets
                clean_line = re.sub(r"^\s*(?:\d+[.)]|\*|-)\s*", "", line.strip())
                instructions.append(clean_line)
            else:
                description_lines.append(line.strip())

        return RecipeCandidate(
            name=name or "Untitled Recipe",
            ingredients=ingredients,
            instructions=instructions,
            description="\n".join(description_lines) if description_lines else None,
            recipeYield=str(frontmatter.get("servings") or frontmatter.get("yield") or ""),
            sourceUrl=frontmatter.get("source"),
            tags=tags
        )

registry.register(TextImporter())
