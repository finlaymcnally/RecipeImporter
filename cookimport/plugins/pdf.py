from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import fitz  # type: ignore

from cookimport.core.models import (
    ConversionReport,
    ConversionResult,
    MappingConfig,
    RecipeCandidate,
    WorkbookInspection,
    SheetInspection,
)
from cookimport.core.reporting import (
    ProvenanceBuilder,
    compute_file_hash,
    generate_recipe_id,
)
from cookimport.core.blocks import Block, BlockType
from cookimport.parsing import cleaning, signals
from cookimport.plugins import registry

logger = logging.getLogger(__name__)

class PdfImporter:
    name = "pdf"

    def detect(self, path: Path) -> float:
        if path.suffix.lower() == ".pdf":
            return 0.95
        return 0.0

    def inspect(self, path: Path) -> WorkbookInspection:
        try:
            doc = fitz.open(path)
            page_count = len(doc)
            title = doc.metadata.get("title") or path.stem
            
            # Simple layout check on first page
            layout = "unknown"
            if page_count > 0:
                page = doc[0]
                text = page.get_text()
                if text.strip():
                    layout = "text-pdf"
                else:
                    layout = "image-pdf" # OCR might be needed
            
            doc.close()
            
            return WorkbookInspection(
                path=str(path),
                sheets=[
                    SheetInspection(
                        name=title,
                        layout=layout,
                        confidence=0.8,
                        warnings=[f"Found {page_count} pages."],
                    )
                ],
                mappingStub=MappingConfig(),
            )
        except Exception as e:
            logger.warning(f"Failed to inspect PDF {path}: {e}")
            return WorkbookInspection(
                path=str(path),
                sheets=[],
                mappingStub=MappingConfig(),
            )

    def convert(self, path: Path, mapping: MappingConfig | None) -> ConversionResult:
        report = ConversionReport()
        recipes: List[RecipeCandidate] = []
        
        try:
            file_hash = compute_file_hash(path)
            doc = fitz.open(path)
            
            # 1. Extract Blocks (Linear Stream)
            all_blocks: List[Block] = []
            for page_num, page in enumerate(doc):
                page_blocks = self._extract_blocks_from_page(page, page_num)
                all_blocks.extend(page_blocks)
            
            doc.close()
            
            # 2. Segment into Candidates
            candidates_ranges = self._detect_candidates(all_blocks)
            
            # 3. Extract Fields
            for i, (start, end, score) in enumerate(candidates_ranges):
                try:
                    candidate_blocks = all_blocks[start:end]
                    candidate = self._extract_fields(candidate_blocks)
                    
                    # Provenance
                    provenance_builder = ProvenanceBuilder(
                        source_file=path.name,
                        source_hash=file_hash,
                        extraction_method="heuristic_pdf",
                    )
                    
                    # Determine page range
                    start_page = candidate_blocks[0].page if candidate_blocks else 0
                    end_page = candidate_blocks[-1].page if candidate_blocks else 0
                    
                    provenance = provenance_builder.build(
                        confidence_score=score / 10.0,
                        location={
                            "start_block": start,
                            "end_block": end,
                            "start_page": start_page,
                            "end_page": end_page,
                            "chunk_index": i
                        }
                    )
                    candidate.provenance = provenance
                    
                    if not candidate.identifier:
                        candidate.identifier = generate_recipe_id(
                            "pdf", file_hash, f"c{i}"
                        )
                    
                    recipes.append(candidate)
                    
                except Exception as e:
                    logger.warning(f"Failed to extract candidate {i} in {path}: {e}")
                    report.warnings.append(f"Failed to parse candidate {i}: {e}")

            report.total_recipes = len(recipes)
            if recipes:
                report.samples = [{"name": r.name} for r in recipes[:3]]

            return ConversionResult(
                recipes=recipes,
                report=report,
                workbook=path.stem,
                workbookPath=str(path),
            )

        except Exception as e:
            logger.error(f"Fatal error converting PDF {path}: {e}")
            report.errors.append(str(e))
            return ConversionResult(
                recipes=[],
                report=report,
                workbook=path.stem,
                workbookPath=str(path),
            )

    def _extract_blocks_from_page(self, page: fitz.Page, page_num: int) -> List[Block]:
        """
        Extracts blocks from a PDF page using PyMuPDF.
        Attempts to reconstruct reading order (columns).
        """
        blocks: List[Block] = []
        
        # Get blocks with layout info
        # sort=True attempts to sort by reading order (vertical then horizontal)
        raw_blocks = page.get_text("blocks", sort=True)
        
        for b in raw_blocks:
            # b is (x0, y0, x1, y1, text, block_no, block_type)
            x0, y0, x1, y1, text, block_no, block_type = b
            
            # Skip image blocks for now (block_type == 1)
            if block_type == 1:
                continue
                
            clean_text = cleaning.normalize_text(text)
            if not clean_text:
                continue
                
            # Create Block
            block = Block(
                text=clean_text,
                type=BlockType.TEXT,
                bbox=[x0, y0, x1, y1],
                page=page_num + 1,
            )
            
            # Calculate style info (simple approximation)
            # PyMuPDF "blocks" aggregates lines. We assume the block has uniform style roughly.
            # To get accurate style, we'd need "dict" or "rawdict" output.
            # For now, let's infer heading from font size logic if we had it, but "blocks" doesn't give font size directly.
            # We can use "dict" extraction if we want font sizes.
            # Let's stick to "blocks" for speed and simplicity in Phase 2 unless detailed font info is needed.
            # We can infer heading from text properties (short, few words, no end punctuation).
            
            signals.enrich_block(block)
            
            # Post-signal layout inference
            # If block is centered or very large (we don't have size), etc.
            
            blocks.append(block)
            
        return blocks

    def _detect_candidates(self, blocks: List[Block]) -> List[Tuple[int, int, float]]:
        """
        Segments blocks into recipes. 
        Reusing logic similar to EPUB but adapted for PDF flow.
        """
        candidates = []
        
        # Heuristics:
        # Title usually precedes Ingredients.
        # But in PDF, title might be "Pasta" and then "Ingredients" is much later due to headnote.
        
        i = 0
        while i < len(blocks):
            block = blocks[i]
            
            if block.features.get("is_ingredient_header"):
                # Backtrack for Title
                start_idx = self._backtrack_for_title(blocks, i)
                if start_idx == -1:
                    start_idx = i # Start at ingredients if no title found
                
                # Scan forward for end
                end_idx = self._find_recipe_end(blocks, i)
                
                score = 5.0
                candidates.append((start_idx, end_idx, score))
                
                i = end_idx
                continue
                
            i += 1
            
        return candidates

    def _backtrack_for_title(self, blocks: List[Block], ingredient_idx: int) -> int:
        limit = 20
        best_idx = -1
        
        for i in range(ingredient_idx - 1, max(-1, ingredient_idx - limit), -1):
            b = blocks[i]
            
            if b.features.get("is_ingredient_header"):
                break
            
            is_heading = b.features.get("is_heading") # Not reliably set yet for PDF without font info
            is_short = len(b.text) < 100
            
            # For PDF, without font size, we rely on shortness and casing
            # Titles usually don't end with a period.
            if is_short and not b.text.strip().endswith("."):
                return i

            if is_short and (b.text.istitle() or b.text.isupper()):
                return i
                
        return best_idx

    def _find_recipe_end(self, blocks: List[Block], ingredient_idx: int) -> int:
        # Similar to EPUB
        for i in range(ingredient_idx + 1, len(blocks)):
            b = blocks[i]
            
            if b.features.get("is_ingredient_header"):
                # Check if it's a new recipe or sub-header
                # Using same simplistic logic as EPUB for now
                if b.text.lower().rstrip(":") in ["ingredients", "ingredient"]:
                    # Likely new recipe, try to backtrack to its title
                    next_title = self._backtrack_for_title(blocks, i)
                    if next_title != -1 and next_title > ingredient_idx:
                        return next_title
                    return i
                    
        return len(blocks)

    def _extract_fields(self, blocks: List[Block]) -> RecipeCandidate:
        # Reuse EPUB logic mostly
        name = "Untitled Recipe"
        ingredients = []
        instructions = []
        description = []
        
        if blocks:
            name = blocks[0].text
            
        current_section = "description"
        content_blocks = blocks[1:] if blocks else []
        
        for b in content_blocks:
            if b.features.get("is_ingredient_header"):
                current_section = "ingredients"
                continue
            if b.features.get("is_instruction_header"):
                current_section = "instructions"
                continue
                
            if current_section == "ingredients":
                clean = re.sub(r"^\s*[-*•]\s*", "", b.text)
                ingredients.append(clean)
            elif current_section == "instructions":
                clean = re.sub(r"^\s*(?:\d+[.)]|\*|-)\s*", "", b.text)
                instructions.append(clean)
            elif current_section == "description":
                description.append(b.text)
                
        return RecipeCandidate(
            name=name,
            ingredients=ingredients,
            instructions=instructions,
            description="\n".join(description) if description else None
        )

registry.register(PdfImporter())
